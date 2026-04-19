"""
Git Gossip — Your Repo's Secret Diary
Deep behavioral analysis of any Git repository.
"""

import argparse
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


# ─── Frustration detection ───────────────────────────────────────────
FRUSTRATION_PATTERNS = [
    r"\bfix\b", r"\bfixed\b", r"\bhotfix\b", r"\bbug\b",
    r"\btry\b", r"\btrying\b", r"\bagain\b", r"\bretry\b",
    r"\bugh\b", r"\bwip\b", r"\bwhy\b", r"\bhack\b",
    r"\btemp\b", r"\btmp\b", r"\bplease\b", r"\bwork\b",
    r"\bbroken\b", r"\brevert\b", r"\boops\b", r"\bfuck\b",
    r"\bshit\b", r"\bdamn\b", r"\bhelp\b", r"\bnope\b",
]
FRUSTRATION_RE = re.compile("|".join(FRUSTRATION_PATTERNS), re.IGNORECASE)

# How close commits must be to count as a "rage burst" (seconds)
RAGE_WINDOW = 300  # 5 minutes


@dataclass
class Commit:
    hash: str
    author: str
    email: str
    timestamp: datetime
    message: str
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    files: list[str] = field(default_factory=list)


@dataclass
class AuthorProfile:
    name: str
    email: str
    commits: list[Commit] = field(default_factory=list)
    hour_distribution: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    day_distribution: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    frustration_commits: list[Commit] = field(default_factory=list)
    rage_bursts: int = 0
    zombie_lines: int = 0
    total_insertions: int = 0
    total_deletions: int = 0

    @property
    def total_commits(self) -> int:
        return len(self.commits)

    @property
    def frustration_rate(self) -> float:
        if not self.commits:
            return 0.0
        return (len(self.frustration_commits) / len(self.commits)) * 100

    @property
    def peak_hour(self) -> int:
        if not self.hour_distribution:
            return 12
        return max(self.hour_distribution, key=self.hour_distribution.get)

    @property
    def is_night_owl(self) -> bool:
        late = sum(self.hour_distribution.get(h, 0) for h in range(22, 24))
        late += sum(self.hour_distribution.get(h, 0) for h in range(0, 5))
        return late > self.total_commits * 0.3

    @property
    def is_early_bird(self) -> bool:
        early = sum(self.hour_distribution.get(h, 0) for h in range(5, 9))
        return early > self.total_commits * 0.3

    @property
    def persona(self) -> str:
        if self.is_night_owl:
            return "🦉 Night Owl"
        if self.is_early_bird:
            return "🐦 Early Bird"
        return "☀️ Regular Hours"

    @property
    def churn_ratio(self) -> float:
        total = self.total_insertions + self.total_deletions
        if total == 0:
            return 0.0
        return self.total_deletions / total


def run_git(args: list[str], repo: Path) -> str:
    """Run a git command and return stdout."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"❌ Git error: {e}")
        sys.exit(1)


def parse_log(repo: Path, max_commits: int = 5000) -> list[Commit]:
    """Parse git log into structured Commit objects."""
    # Custom format: hash, author, email, timestamp, message
    separator = "---GIT_GOSSIP_SEP---"
    fmt = f"%H{separator}%aN{separator}%aE{separator}%aI{separator}%s"

    raw = run_git(
        ["log", f"--pretty=format:{fmt}", "--numstat", f"-{max_commits}"],
        repo,
    )

    commits = []
    current = None

    for line in raw.split("\n"):
        if separator in line:
            if current:
                commits.append(current)
            parts = line.split(separator)
            if len(parts) >= 5:
                try:
                    ts = datetime.fromisoformat(parts[3])
                except ValueError:
                    continue
                current = Commit(
                    hash=parts[0],
                    author=parts[1],
                    email=parts[2],
                    timestamp=ts,
                    message=parts[4],
                )
        elif current and line.strip():
            # numstat line: insertions\tdeletions\tfilename
            stat_parts = line.split("\t")
            if len(stat_parts) == 3:
                try:
                    ins = int(stat_parts[0]) if stat_parts[0] != "-" else 0
                    dels = int(stat_parts[1]) if stat_parts[1] != "-" else 0
                    current.insertions += ins
                    current.deletions += dels
                    current.files_changed += 1
                    current.files.append(stat_parts[2])
                except ValueError:
                    pass

    if current:
        commits.append(current)

    return commits


def build_author_profiles(commits: list[Commit]) -> dict[str, AuthorProfile]:
    """Build rich profiles for each author."""
    profiles: dict[str, AuthorProfile] = {}

    for commit in commits:
        key = commit.email.lower()
        if key not in profiles:
            profiles[key] = AuthorProfile(name=commit.author, email=commit.email)
        p = profiles[key]
        p.commits.append(commit)
        p.hour_distribution[commit.timestamp.hour] += 1
        p.day_distribution[commit.timestamp.weekday()] += 1
        p.total_insertions += commit.insertions
        p.total_deletions += commit.deletions

        if FRUSTRATION_RE.search(commit.message):
            p.frustration_commits.append(commit)

    # Detect rage bursts (rapid successive commits by same author)
    for p in profiles.values():
        sorted_commits = sorted(p.commits, key=lambda c: c.timestamp)
        burst = 0
        for i in range(1, len(sorted_commits)):
            diff = (sorted_commits[i].timestamp - sorted_commits[i - 1].timestamp).total_seconds()
            if 0 < diff < RAGE_WINDOW:
                burst += 1
            else:
                if burst >= 3:
                    p.rage_bursts += 1
                burst = 0
        if burst >= 3:
            p.rage_bursts += 1

    return profiles


def calculate_file_hotspots(commits: list[Commit], top_n: int = 15) -> list[tuple[str, int, int]]:
    """Find the most frequently changed files. Returns (file, change_count, unique_authors)."""
    file_changes: Counter = Counter()
    file_authors: dict[str, set] = defaultdict(set)

    for commit in commits:
        for f in commit.files:
            file_changes[f] += 1
            file_authors[f].add(commit.email.lower())

    return [
        (f, count, len(file_authors[f]))
        for f, count in file_changes.most_common(top_n)
    ]


def calculate_bus_factor(commits: list[Commit], top_files: int = 50) -> dict:
    """Estimate bus factor — how many devs need to leave before key files are orphaned."""
    file_owners: dict[str, Counter] = defaultdict(Counter)
    file_changes: Counter = Counter()

    for commit in commits:
        for f in commit.files:
            file_owners[f][commit.email.lower()] += 1
            file_changes[f] += 1

    critical_files = [f for f, _ in file_changes.most_common(top_files)]
    sole_owner_files = []
    for f in critical_files:
        owners = file_owners[f]
        total = sum(owners.values())
        top_owner_share = max(owners.values()) / total if total else 0
        if top_owner_share > 0.8:
            top_author = max(owners, key=owners.get)
            sole_owner_files.append((f, top_author, top_owner_share))

    # Bus factor = minimum devs who own >80% of critical files
    critical_owners = set(author for _, author, _ in sole_owner_files)
    return {
        "bus_factor": max(1, len(critical_owners)),
        "critical_files": len(critical_files),
        "sole_owner_files": sole_owner_files[:10],
        "at_risk": len(sole_owner_files),
    }


def calculate_collaboration_graph(commits: list[Commit]) -> list[tuple[str, str, int]]:
    """Find implicit collaborators — people who edit the same files but may never talk."""
    file_authors: dict[str, set] = defaultdict(set)
    for commit in commits:
        for f in commit.files:
            file_authors[f].add(commit.author)

    pair_count: Counter = Counter()
    for f, authors in file_authors.items():
        authors_list = sorted(authors)
        for i in range(len(authors_list)):
            for j in range(i + 1, len(authors_list)):
                pair_count[(authors_list[i], authors_list[j])] += 1

    return [
        (a, b, count)
        for (a, b), count in pair_count.most_common(10)
        if count >= 3
    ]


def score_commit_message(message: str) -> float:
    """Score a commit message from 0 to 1 based on quality heuristics."""
    score = 0.0
    msg = message.strip()

    # Length check
    if len(msg) >= 10:
        score += 0.25
    if len(msg) >= 30:
        score += 0.15

    # Starts with capital letter
    if msg and msg[0].isupper():
        score += 0.1

    # Uses conventional commit style (feat:, fix:, chore:, etc.)
    if re.match(r"^(feat|fix|chore|docs|style|refactor|test|build|ci|perf|revert)(\(.+\))?:", msg):
        score += 0.2

    # Contains a verb early on
    if re.match(r"^(add|fix|update|remove|refactor|implement|create|delete|improve|merge|bump|release|change|move|rename|set|enable|disable)\b", msg, re.I):
        score += 0.15

    # Penalty for lazy messages
    lazy = {"fix", "update", "changes", "wip", "test", ".", "asdf", "tmp", "temp", "stuff", "misc"}
    if msg.lower().strip(". ") in lazy:
        score = max(0, score - 0.4)

    # Penalty for single word
    if len(msg.split()) <= 1:
        score = max(0, score - 0.2)

    return min(1.0, score)


def calculate_message_quality(commits: list[Commit]) -> dict:
    """Analyze commit message quality across the project."""
    scores = [score_commit_message(c.message) for c in commits]
    avg = sum(scores) / len(scores) if scores else 0

    worst = sorted(
        [(c.message, score_commit_message(c.message), c.author) for c in commits],
        key=lambda x: x[1],
    )[:5]

    best = sorted(
        [(c.message, score_commit_message(c.message), c.author) for c in commits],
        key=lambda x: x[1],
        reverse=True,
    )[:5]

    return {
        "average_score": avg,
        "worst_messages": worst,
        "best_messages": best,
        "total_scored": len(scores),
    }


def calculate_velocity(commits: list[Commit], window_days: int = 30) -> list[dict]:
    """Calculate commits-per-window over time to show velocity trends."""
    if not commits:
        return []

    sorted_commits = sorted(commits, key=lambda c: c.timestamp)
    start = sorted_commits[0].timestamp
    end = sorted_commits[-1].timestamp

    windows = []
    current = start
    while current < end:
        window_end = current + timedelta(days=window_days)
        window_commits = [c for c in sorted_commits if current <= c.timestamp < window_end]
        windows.append({
            "period": current.strftime("%Y-%m"),
            "commits": len(window_commits),
            "authors": len(set(c.email for c in window_commits)),
            "insertions": sum(c.insertions for c in window_commits),
            "deletions": sum(c.deletions for c in window_commits),
        })
        current = window_end

    return windows


def calculate_zombie_code(commits: list[Commit], days_threshold: int = 7) -> dict:
    """Find code that was added and deleted within a short timeframe."""
    file_events: dict[str, list] = defaultdict(list)
    for commit in commits:
        for f in commit.files:
            file_events[f].append({
                "timestamp": commit.timestamp,
                "author": commit.author,
                "insertions": commit.insertions,
                "deletions": commit.deletions,
            })

    zombie_authors: Counter = Counter()
    zombie_files: Counter = Counter()

    for f, events in file_events.items():
        sorted_events = sorted(events, key=lambda e: e["timestamp"])
        for i in range(len(sorted_events) - 1):
            for j in range(i + 1, min(i + 5, len(sorted_events))):
                diff = (sorted_events[j]["timestamp"] - sorted_events[i]["timestamp"]).days
                if diff <= days_threshold and sorted_events[j]["deletions"] > 0 and sorted_events[i]["insertions"] > 0:
                    zombie_authors[sorted_events[i]["author"]] += 1
                    zombie_files[f] += 1
                    break

    return {
        "zombie_authors": zombie_authors.most_common(5),
        "zombie_files": zombie_files.most_common(5),
        "total_zombie_events": sum(zombie_authors.values()),
    }


def format_hour(h: int) -> str:
    """Format hour as 12-hour time."""
    if h == 0:
        return "12 AM"
    if h < 12:
        return f"{h} AM"
    if h == 12:
        return "12 PM"
    return f"{h - 12} PM"


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def generate_report(repo: Path, commits: list[Commit]) -> dict:
    """Run all analyses and return structured results."""
    profiles = build_author_profiles(commits)
    hotspots = calculate_file_hotspots(commits)
    bus = calculate_bus_factor(commits)
    collab = calculate_collaboration_graph(commits)
    msg_quality = calculate_message_quality(commits)
    velocity = calculate_velocity(commits)
    zombies = calculate_zombie_code(commits)

    sorted_authors = sorted(profiles.values(), key=lambda p: p.total_commits, reverse=True)

    return {
        "repo_name": repo.resolve().name,
        "total_commits": len(commits),
        "total_authors": len(profiles),
        "first_commit": min(c.timestamp for c in commits).isoformat() if commits else None,
        "last_commit": max(c.timestamp for c in commits).isoformat() if commits else None,
        "authors": sorted_authors,
        "hotspots": hotspots,
        "bus_factor": bus,
        "collaboration": collab,
        "message_quality": msg_quality,
        "velocity": velocity,
        "zombies": zombies,
    }


def print_terminal_report(report: dict) -> None:
    """Print a beautiful terminal report using Rich."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()

    # ── Header ──
    title = Text()
    title.append("🗣️ GIT GOSSIP", style="bold magenta")
    title.append(f"  —  {report['repo_name']}\n", style="dim")
    title.append(f"Your repo's secret diary\n\n", style="italic dim")
    title.append(f"📊 {report['total_commits']:,} commits", style="cyan")
    title.append(f"  •  ", style="dim")
    title.append(f"👥 {report['total_authors']} contributors", style="cyan")
    if report["first_commit"]:
        first = datetime.fromisoformat(report["first_commit"]).strftime("%b %Y")
        last = datetime.fromisoformat(report["last_commit"]).strftime("%b %Y")
        title.append(f"  •  ", style="dim")
        title.append(f"📅 {first} → {last}", style="cyan")
    console.print(Panel(title, border_style="magenta", expand=False))

    # ── Author Profiles ──
    console.print("\n[bold magenta]👤 DEVELOPER PROFILES[/]\n")
    for author in report["authors"][:8]:
        auth_table = Table(show_header=False, border_style="cyan", expand=False,
                           title=f"[bold]{author.name}[/] — {author.persona}")
        auth_table.add_column("Metric", style="bold", width=22)
        auth_table.add_column("Value", style="cyan", width=40)

        auth_table.add_row("Commits", f"{author.total_commits:,}")
        auth_table.add_row("Lines added", f"+{author.total_insertions:,}")
        auth_table.add_row("Lines deleted", f"-{author.total_deletions:,}")
        auth_table.add_row("Churn ratio", f"{author.churn_ratio:.0%} deleted vs total")
        auth_table.add_row("Peak hour", format_hour(author.peak_hour))

        # Mini hour heatmap
        max_h = max(author.hour_distribution.values()) if author.hour_distribution else 1
        heatmap = ""
        for h in range(24):
            count = author.hour_distribution.get(h, 0)
            intensity = count / max_h if max_h else 0
            if intensity > 0.7:
                heatmap += "█"
            elif intensity > 0.4:
                heatmap += "▓"
            elif intensity > 0.1:
                heatmap += "░"
            else:
                heatmap += "·"
        auth_table.add_row("Activity (0h→23h)", heatmap)

        if author.frustration_commits:
            auth_table.add_row(
                "Frustration rate",
                f"😤 {author.frustration_rate:.1f}% ({len(author.frustration_commits)} commits)"
            )
        if author.rage_bursts:
            auth_table.add_row("Rage bursts", f"🔥 {author.rage_bursts} detected")

        console.print(auth_table)
        console.print()

    # ── Frustration Leaderboard ──
    frustrated = sorted(report["authors"], key=lambda a: a.frustration_rate, reverse=True)
    frustrated = [a for a in frustrated if a.frustration_commits and a.total_commits >= 5]
    if frustrated:
        console.print("[bold magenta]😤 FRUSTRATION LEADERBOARD[/]\n")
        f_table = Table(border_style="red")
        f_table.add_column("Rank", style="bold", width=6)
        f_table.add_column("Developer", style="bold cyan")
        f_table.add_column("Rate", justify="right")
        f_table.add_column("Rage Bursts", justify="right")
        f_table.add_column("Worst Message", style="dim")
        for i, a in enumerate(frustrated[:5]):
            worst = min(a.frustration_commits, key=lambda c: len(c.message))
            f_table.add_row(
                f"#{i + 1}",
                a.name,
                f"{a.frustration_rate:.1f}%",
                f"🔥 {a.rage_bursts}" if a.rage_bursts else "—",
                f'"{worst.message[:40]}"',
            )
        console.print(f_table)
        console.print()

    # ── File Hotspots ──
    console.print("[bold magenta]🔥 FILE HOTSPOTS (most frequently changed)[/]\n")
    h_table = Table(border_style="yellow")
    h_table.add_column("File", style="bold")
    h_table.add_column("Changes", justify="right", style="yellow")
    h_table.add_column("Authors", justify="right", style="cyan")
    h_table.add_column("Risk", justify="center")
    for f, count, authors in report["hotspots"][:10]:
        risk = "🔴" if count > 50 else "🟡" if count > 20 else "🟢"
        display_name = f if len(f) <= 50 else "…" + f[-49:]
        h_table.add_row(display_name, str(count), str(authors), risk)
    console.print(h_table)
    console.print()

    # ── Bus Factor ──
    bus = report["bus_factor"]
    console.print("[bold magenta]🚌 BUS FACTOR[/]\n")
    bus_color = "red" if bus["bus_factor"] <= 2 else "yellow" if bus["bus_factor"] <= 4 else "green"
    console.print(f"  Bus factor: [bold {bus_color}]{bus['bus_factor']}[/] (developers who'd take critical knowledge with them)")
    console.print(f"  Files at risk: [bold]{bus['at_risk']}[/] out of top {bus['critical_files']} most-changed files have a single dominant owner (>80%)\n")
    if bus["sole_owner_files"]:
        b_table = Table(border_style="red", title="Files with single dominant owner")
        b_table.add_column("File", style="bold")
        b_table.add_column("Owner", style="cyan")
        b_table.add_column("Ownership", justify="right")
        for f, owner, share in bus["sole_owner_files"][:7]:
            display_name = f if len(f) <= 45 else "…" + f[-44:]
            # Look up author name from email
            b_table.add_row(display_name, owner, f"{share:.0%}")
        console.print(b_table)
        console.print()

    # ── Collaboration Graph ──
    if report["collaboration"]:
        console.print("[bold magenta]🤝 IMPLICIT COLLABORATORS (shared file edits)[/]\n")
        c_table = Table(border_style="green")
        c_table.add_column("Developer A", style="bold cyan")
        c_table.add_column("Developer B", style="bold cyan")
        c_table.add_column("Shared Files", justify="right", style="green")
        for a, b, count in report["collaboration"][:8]:
            c_table.add_row(a, b, str(count))
        console.print(c_table)
        console.print()

    # ── Commit Message Quality ──
    mq = report["message_quality"]
    console.print("[bold magenta]📝 COMMIT MESSAGE QUALITY[/]\n")
    avg = mq["average_score"]
    grade = "A" if avg >= 0.7 else "B" if avg >= 0.5 else "C" if avg >= 0.3 else "D"
    grade_color = "green" if avg >= 0.7 else "yellow" if avg >= 0.5 else "red"
    console.print(f"  Overall grade: [bold {grade_color}]{grade}[/] ({avg:.0%} average quality across {mq['total_scored']:,} commits)\n")

    if mq["worst_messages"]:
        console.print("  [dim]Worst messages:[/]")
        for msg, score, author in mq["worst_messages"][:3]:
            console.print(f'    [red]✗[/] "{msg[:50]}" [dim]— {author}[/]')
    console.print()
    if mq["best_messages"]:
        console.print("  [dim]Best messages:[/]")
        for msg, score, author in mq["best_messages"][:3]:
            console.print(f'    [green]✓[/] "{msg[:60]}" [dim]— {author}[/]')
    console.print()

    # ── Zombie Code ──
    zombies = report["zombies"]
    if zombies["total_zombie_events"] > 0:
        console.print("[bold magenta]💀 ZOMBIE CODE (written and deleted within 7 days)[/]\n")
        console.print(f"  Total zombie events detected: [bold]{zombies['total_zombie_events']}[/]\n")
        if zombies["zombie_authors"]:
            z_table = Table(border_style="dim", title="Top zombie code authors")
            z_table.add_column("Developer", style="bold")
            z_table.add_column("Zombie Events", justify="right", style="red")
            for author, count in zombies["zombie_authors"]:
                z_table.add_row(author, str(count))
            console.print(z_table)
        console.print()

    # ── Velocity ──
    if report["velocity"]:
        console.print("[bold magenta]🏃 VELOCITY TREND[/]\n")
        recent = report["velocity"][-6:]
        v_table = Table(border_style="blue")
        v_table.add_column("Period", style="bold")
        v_table.add_column("Commits", justify="right", style="cyan")
        v_table.add_column("Authors", justify="right")
        v_table.add_column("Lines +/-", justify="right")
        v_table.add_column("Trend", justify="center")
        for i, window in enumerate(recent):
            trend = ""
            if i > 0:
                prev = recent[i - 1]["commits"]
                curr = window["commits"]
                if curr > prev * 1.2:
                    trend = "📈"
                elif curr < prev * 0.8:
                    trend = "📉"
                else:
                    trend = "➡️"
            v_table.add_row(
                window["period"],
                str(window["commits"]),
                str(window["authors"]),
                f"+{window['insertions']:,} / -{window['deletions']:,}",
                trend,
            )
        console.print(v_table)
        console.print()

    # ── Summary ──
    console.print(Panel(
        "[dim]Generated by[/] [bold magenta]git-gossip[/] [dim]— your repo's secret diary[/]",
        border_style="dim",
        expand=False,
    ))


def generate_html_report(report: dict, output: Path) -> None:
    """Generate a beautiful standalone HTML report."""
    authors_html = ""
    for author in report["authors"][:10]:
        max_h = max(author.hour_distribution.values()) if author.hour_distribution else 1
        heatmap_cells = ""
        for h in range(24):
            count = author.hour_distribution.get(h, 0)
            intensity = count / max_h if max_h else 0
            opacity = max(0.08, intensity)
            heatmap_cells += f'<div class="heat-cell" style="opacity:{opacity}" title="{format_hour(h)}: {count} commits"></div>'

        day_cells = ""
        max_d = max(author.day_distribution.values()) if author.day_distribution else 1
        for d in range(7):
            count = author.day_distribution.get(d, 0)
            intensity = count / max_d if max_d else 0
            opacity = max(0.08, intensity)
            day_cells += f'<div class="day-cell" style="opacity:{opacity}" title="{DAY_NAMES[d]}: {count} commits">{DAY_NAMES[d]}</div>'

        frust_html = ""
        if author.frustration_commits:
            frust_html = f"""
            <div class="stat-row frust">
                <span class="stat-label">Frustration rate</span>
                <span class="stat-value">😤 {author.frustration_rate:.1f}%</span>
            </div>"""

        rage_html = ""
        if author.rage_bursts:
            rage_html = f"""
            <div class="stat-row rage">
                <span class="stat-label">Rage bursts</span>
                <span class="stat-value">🔥 {author.rage_bursts}</span>
            </div>"""

        authors_html += f"""
        <div class="author-card">
            <div class="author-header">
                <h3>{author.name}</h3>
                <span class="persona">{author.persona}</span>
            </div>
            <div class="stats-grid">
                <div class="stat-row">
                    <span class="stat-label">Commits</span>
                    <span class="stat-value">{author.total_commits:,}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Lines added</span>
                    <span class="stat-value add">+{author.total_insertions:,}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Lines deleted</span>
                    <span class="stat-value del">-{author.total_deletions:,}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Churn ratio</span>
                    <span class="stat-value">{author.churn_ratio:.0%}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">Peak hour</span>
                    <span class="stat-value">{format_hour(author.peak_hour)}</span>
                </div>
                {frust_html}
                {rage_html}
            </div>
            <div class="heatmap-section">
                <div class="heatmap-label">Activity by hour (0h → 23h)</div>
                <div class="heatmap">{heatmap_cells}</div>
            </div>
            <div class="heatmap-section">
                <div class="heatmap-label">Activity by day</div>
                <div class="day-map">{day_cells}</div>
            </div>
        </div>"""

    # Hotspots
    hotspots_rows = ""
    for f, count, auth_count in report["hotspots"][:12]:
        risk = "high" if count > 50 else "mid" if count > 20 else "low"
        risk_dot = "🔴" if risk == "high" else "🟡" if risk == "mid" else "🟢"
        display_name = f if len(f) <= 55 else "…" + f[-54:]
        hotspots_rows += f"""
        <tr class="risk-{risk}">
            <td class="file-name">{display_name}</td>
            <td>{count}</td>
            <td>{auth_count}</td>
            <td>{risk_dot}</td>
        </tr>"""

    # Bus factor
    bus = report["bus_factor"]
    bus_class = "danger" if bus["bus_factor"] <= 2 else "warn" if bus["bus_factor"] <= 4 else "safe"
    bus_files_html = ""
    for f, owner, share in bus["sole_owner_files"][:7]:
        display_name = f if len(f) <= 45 else "…" + f[-44:]
        bus_files_html += f"<tr><td>{display_name}</td><td>{owner}</td><td>{share:.0%}</td></tr>"

    # Collaboration
    collab_rows = ""
    for a, b, count in report["collaboration"][:8]:
        collab_rows += f"<tr><td>{a}</td><td>{b}</td><td>{count}</td></tr>"

    # Message quality
    mq = report["message_quality"]
    avg = mq["average_score"]
    grade = "A" if avg >= 0.7 else "B" if avg >= 0.5 else "C" if avg >= 0.3 else "D"
    grade_class = "good" if avg >= 0.7 else "ok" if avg >= 0.5 else "bad"

    worst_msgs = ""
    for msg, score, author in mq["worst_messages"][:5]:
        worst_msgs += f'<div class="msg bad-msg">✗ "{msg[:55]}" <span class="msg-author">— {author}</span></div>'
    best_msgs = ""
    for msg, score, author in mq["best_messages"][:5]:
        best_msgs += f'<div class="msg good-msg">✓ "{msg[:60]}" <span class="msg-author">— {author}</span></div>'

    # Velocity chart data
    vel_data = report["velocity"][-12:]
    vel_labels = [v["period"] for v in vel_data]
    vel_values = [v["commits"] for v in vel_data]
    max_vel = max(vel_values) if vel_values else 1
    vel_bars = ""
    for v in vel_data:
        height = (v["commits"] / max_vel) * 100 if max_vel else 0
        vel_bars += f"""
        <div class="vel-bar-wrap">
            <div class="vel-bar" style="height:{height}%">
                <span class="vel-count">{v['commits']}</span>
            </div>
            <div class="vel-label">{v['period'][-5:]}</div>
        </div>"""

    # Zombie code
    zombies = report["zombies"]
    zombie_html = ""
    if zombies["total_zombie_events"] > 0:
        zombie_rows = ""
        for author, count in zombies["zombie_authors"]:
            zombie_rows += f"<tr><td>{author}</td><td>{count}</td></tr>"
        zombie_html = f"""
        <section class="section">
            <h2>💀 Zombie Code</h2>
            <p class="subtitle">Code written and deleted within 7 days — {zombies['total_zombie_events']} events detected</p>
            <table>
                <thead><tr><th>Developer</th><th>Zombie Events</th></tr></thead>
                <tbody>{zombie_rows}</tbody>
            </table>
        </section>"""

    first_date = datetime.fromisoformat(report["first_commit"]).strftime("%B %Y") if report["first_commit"] else "—"
    last_date = datetime.fromisoformat(report["last_commit"]).strftime("%B %Y") if report["last_commit"] else "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Git Gossip — {report['repo_name']}</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Outfit:wght@300;400;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a26;
    --border: #2a2a3a;
    --text: #e0e0ec;
    --text-dim: #6a6a80;
    --accent: #c084fc;
    --accent2: #818cf8;
    --green: #4ade80;
    --red: #f87171;
    --yellow: #fbbf24;
    --cyan: #22d3ee;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Outfit', sans-serif;
    line-height: 1.6;
    padding: 2rem;
    max-width: 1100px;
    margin: 0 auto;
}}
.hero {{
    text-align: center;
    padding: 3rem 1rem;
    margin-bottom: 2rem;
    border-bottom: 1px solid var(--border);
}}
.hero h1 {{
    font-size: 2.8rem;
    font-weight: 800;
    background: linear-gradient(135deg, var(--accent), var(--accent2), var(--cyan));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.5rem;
}}
.hero .repo-name {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.3rem;
    color: var(--accent);
    margin-bottom: 1rem;
}}
.hero .meta {{
    color: var(--text-dim);
    font-size: 0.95rem;
}}
.meta span {{ margin: 0 0.8rem; }}

.section {{
    margin-bottom: 2.5rem;
}}
.section h2 {{
    font-size: 1.4rem;
    font-weight: 700;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
}}
.subtitle {{
    color: var(--text-dim);
    font-size: 0.9rem;
    margin-bottom: 1rem;
}}

.author-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}}
.author-card:hover {{ border-color: var(--accent); }}
.author-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
}}
.author-header h3 {{ font-size: 1.15rem; font-weight: 700; }}
.persona {{
    font-size: 0.85rem;
    padding: 0.2rem 0.7rem;
    background: var(--surface2);
    border-radius: 20px;
    color: var(--accent);
}}

.stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 0.5rem;
    margin-bottom: 1rem;
}}
.stat-row {{
    display: flex;
    justify-content: space-between;
    padding: 0.3rem 0.6rem;
    background: var(--surface2);
    border-radius: 6px;
    font-size: 0.9rem;
}}
.stat-label {{ color: var(--text-dim); }}
.stat-value {{ font-family: 'JetBrains Mono', monospace; font-weight: 600; }}
.stat-value.add {{ color: var(--green); }}
.stat-value.del {{ color: var(--red); }}
.stat-row.frust {{ border-left: 3px solid var(--yellow); }}
.stat-row.rage {{ border-left: 3px solid var(--red); }}

.heatmap-section {{ margin-top: 0.8rem; }}
.heatmap-label {{ font-size: 0.75rem; color: var(--text-dim); margin-bottom: 0.3rem; }}
.heatmap {{
    display: grid;
    grid-template-columns: repeat(24, 1fr);
    gap: 2px;
}}
.heat-cell {{
    height: 18px;
    background: var(--accent);
    border-radius: 3px;
    min-width: 0;
}}
.day-map {{
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 3px;
}}
.day-cell {{
    height: 28px;
    background: var(--accent2);
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
    font-weight: 600;
    color: var(--text);
}}

table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
}}
thead th {{
    text-align: left;
    padding: 0.6rem 0.8rem;
    background: var(--surface);
    border-bottom: 2px solid var(--border);
    color: var(--text-dim);
    font-weight: 600;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
tbody td {{
    padding: 0.5rem 0.8rem;
    border-bottom: 1px solid var(--border);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
}}
tbody tr:hover {{ background: var(--surface); }}
.file-name {{ color: var(--cyan); }}
.risk-high td:first-child {{ border-left: 3px solid var(--red); }}
.risk-mid td:first-child {{ border-left: 3px solid var(--yellow); }}
.risk-low td:first-child {{ border-left: 3px solid var(--green); }}

.bus-number {{
    font-size: 3rem;
    font-weight: 800;
    font-family: 'JetBrains Mono', monospace;
    display: inline-block;
    padding: 0.5rem 1.5rem;
    border-radius: 12px;
    margin: 0.5rem 0 1rem;
}}
.bus-number.danger {{ color: var(--red); background: rgba(248,113,113,0.1); }}
.bus-number.warn {{ color: var(--yellow); background: rgba(251,191,36,0.1); }}
.bus-number.safe {{ color: var(--green); background: rgba(74,222,128,0.1); }}

.grade-badge {{
    font-size: 2.5rem;
    font-weight: 800;
    font-family: 'JetBrains Mono', monospace;
    display: inline-block;
    padding: 0.3rem 1.2rem;
    border-radius: 10px;
    margin: 0.5rem 0;
}}
.grade-badge.good {{ color: var(--green); background: rgba(74,222,128,0.1); }}
.grade-badge.ok {{ color: var(--yellow); background: rgba(251,191,36,0.1); }}
.grade-badge.bad {{ color: var(--red); background: rgba(248,113,113,0.1); }}

.msg {{
    padding: 0.4rem 0.6rem;
    margin: 0.3rem 0;
    border-radius: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
}}
.bad-msg {{ background: rgba(248,113,113,0.08); color: var(--red); }}
.good-msg {{ background: rgba(74,222,128,0.08); color: var(--green); }}
.msg-author {{ color: var(--text-dim); font-family: 'Outfit', sans-serif; }}

.vel-chart {{
    display: flex;
    align-items: flex-end;
    gap: 4px;
    height: 160px;
    padding: 1rem 0;
    border-bottom: 1px solid var(--border);
}}
.vel-bar-wrap {{
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
}}
.vel-bar {{
    width: 100%;
    background: linear-gradient(to top, var(--accent2), var(--accent));
    border-radius: 4px 4px 0 0;
    min-height: 4px;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    position: relative;
}}
.vel-count {{
    font-size: 0.65rem;
    font-family: 'JetBrains Mono', monospace;
    color: var(--text);
    position: absolute;
    top: -18px;
    white-space: nowrap;
}}
.vel-label {{
    font-size: 0.65rem;
    color: var(--text-dim);
    margin-top: 0.4rem;
    font-family: 'JetBrains Mono', monospace;
}}

footer {{
    text-align: center;
    padding: 2rem;
    color: var(--text-dim);
    font-size: 0.85rem;
    border-top: 1px solid var(--border);
    margin-top: 2rem;
}}
footer a {{ color: var(--accent); text-decoration: none; }}

@media (max-width: 700px) {{
    body {{ padding: 1rem; }}
    .hero h1 {{ font-size: 1.8rem; }}
    .stats-grid {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div class="hero">
    <h1>🗣️ Git Gossip</h1>
    <div class="repo-name">{report['repo_name']}</div>
    <div class="meta">
        <span>📊 {report['total_commits']:,} commits</span>
        <span>👥 {report['total_authors']} contributors</span>
        <span>📅 {first_date} → {last_date}</span>
    </div>
</div>

<section class="section">
    <h2>👤 Developer Profiles</h2>
    {authors_html}
</section>

<section class="section">
    <h2>🔥 File Hotspots</h2>
    <p class="subtitle">Most frequently modified files — high churn often correlates with bugs</p>
    <table>
        <thead><tr><th>File</th><th>Changes</th><th>Authors</th><th>Risk</th></tr></thead>
        <tbody>{hotspots_rows}</tbody>
    </table>
</section>

<section class="section">
    <h2>🚌 Bus Factor</h2>
    <p class="subtitle">How many developers could leave before critical files are orphaned?</p>
    <div class="bus-number {bus_class}">{bus['bus_factor']}</div>
    <p>{bus['at_risk']} of top {bus['critical_files']} files have a single dominant owner (>80%)</p>
    {"<table><thead><tr><th>File</th><th>Owner</th><th>Ownership</th></tr></thead><tbody>" + bus_files_html + "</tbody></table>" if bus_files_html else ""}
</section>

{"<section class='section'><h2>🤝 Implicit Collaborators</h2><p class='subtitle'>Developers who frequently edit the same files</p><table><thead><tr><th>Developer A</th><th>Developer B</th><th>Shared Files</th></tr></thead><tbody>" + collab_rows + "</tbody></table></section>" if collab_rows else ""}

<section class="section">
    <h2>📝 Commit Message Quality</h2>
    <div class="grade-badge {grade_class}">{grade}</div>
    <p class="subtitle">{avg:.0%} average quality across {mq['total_scored']:,} commits</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem;">
        <div>
            <h4 style="color:var(--red);margin-bottom:0.5rem;">Worst messages</h4>
            {worst_msgs}
        </div>
        <div>
            <h4 style="color:var(--green);margin-bottom:0.5rem;">Best messages</h4>
            {best_msgs}
        </div>
    </div>
</section>

{zombie_html}

<section class="section">
    <h2>🏃 Velocity Trend</h2>
    <p class="subtitle">Commits per month — is the project speeding up or slowing down?</p>
    <div class="vel-chart">{vel_bars}</div>
</section>

<footer>
    Generated by <a href="https://github.com/YOUR_USERNAME/git-gossip">git-gossip</a> — your repo's secret diary
</footer>
</body>
</html>"""

    output.write_text(html)
    print(f"📄 HTML report saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Git Gossip — Deep behavioral analysis of any Git repository.",
    )
    parser.add_argument(
        "repo",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to a Git repository (defaults to current directory)",
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=None,
        help="Also generate a standalone HTML report (e.g., --html report.html)",
    )
    parser.add_argument(
        "--max-commits",
        type=int,
        default=5000,
        help="Maximum commits to analyze (default: 5000)",
    )
    args = parser.parse_args()

    repo = args.repo.resolve()
    git_dir = repo / ".git"
    if not git_dir.exists():
        print(f"❌ Not a Git repository: {repo}")
        print("   Run this inside a Git repo, or pass the path as an argument.")
        sys.exit(1)

    print(f"🗣️  Git Gossip — scanning {repo.name}...")
    print(f"   Parsing up to {args.max_commits:,} commits...\n")

    commits = parse_log(repo, max_commits=args.max_commits)
    if not commits:
        print("❌ No commits found.")
        sys.exit(1)

    report = generate_report(repo, commits)
    print_terminal_report(report)

    if args.html:
        generate_html_report(report, args.html)


if __name__ == "__main__":
    main()
