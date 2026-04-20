# 🗣️ Git Gossip — Your Repo's Secret Diary

**Deep behavioral analysis of any Git repository.** Not what was coded — but *how, when, and by whom.*

Every Git repo has stories hiding in its log that no tool surfaces. Who works at 3 AM? Who writes code that gets deleted within a week? Which files are so fragile that touching them is a team sport? What does the team's frustration look like in data?

Git Gossip answers all of that. Point it at any repo — yours, your team's, or any open-source project — and get a deep behavioral forensics report in seconds.

## What it reveals

| Analysis | What it tells you |
|---|---|
| 🦉 **Developer personas** | Night owl or early bird? Heatmap of when each person actually commits |
| 😤 **Frustration index** | Detects rage-commits — rapid successive commits with messages like "fix", "try again", "ugh" |
| 💀 **Zombie code** | Code that was written and deleted within 7 days — wasted effort, quantified |
| 🔥 **File hotspots** | Most frequently modified files — high churn = high bug probability |
| 🚌 **Bus factor** | How many developers could leave before critical files have no one who understands them |
| 🤝 **Implicit collaborators** | People who constantly edit the same files but may never directly communicate |
| 📝 **Commit message quality** | Grades your team's commit messages from A to D with best/worst examples |
| 🏃 **Velocity trends** | Is the project speeding up or slowing down? Monthly commit/churn chart |
| 🧬 **Code churn ratio** | New code vs deleted code per developer — who rewrites the most? |

## Demo

### Terminal output
```
🗣️ GIT GOSSIP  —  my-project
Your repo's secret diary

📊 2,847 commits  •  👥 12 contributors  •  📅 Jan 2023 → Apr 2026

👤 DEVELOPER PROFILES

 Jane Doe — 🦉 Night Owl
 ┌──────────────────┬────────────────────────────────────┐
 │ Commits          │                                847 │
 │ Lines added      │                           +124,832 │
 │ Lines deleted    │                            -87,291 │
 │ Churn ratio      │                       41% deleted  │
 │ Peak hour        │                             11 PM  │
 │ Activity (0→23h) │  ·░░·····░░▓██▓▓░░░░░▓▓██         │
 │ Frustration rate │                    😤 18.2% (154)  │
 │ Rage bursts      │                       🔥 7 detected│
 └──────────────────┴────────────────────────────────────┘
```

### HTML report

Run with `--html report.html` to generate a beautiful standalone dark-themed report with interactive heatmaps, velocity charts, and full analysis — perfect for sharing with your team.

## Install

```bash
git clone https://github.com/adithyakiranhere/git-gossip.git
cd git-gossip
pip install -r requirements.txt
```

Only dependency is `rich` (for terminal output). The HTML report has zero dependencies.

## Usage

Analyze the current repo:

```bash
python git_gossip.py
```

Analyze any repo by path:

```bash
python git_gossip.py /path/to/any/repo
```

Generate an HTML report:

```bash
python git_gossip.py /path/to/repo --html report.html
```

Limit commits analyzed (for huge repos):

```bash
python git_gossip.py --max-commits 10000
```

## Try it on famous repos

```bash
git clone --depth=5000 https://github.com/torvalds/linux.git
python git_gossip.py linux/ --html linux-gossip.html

git clone https://github.com/facebook/react.git
python git_gossip.py react/ --html react-gossip.html

git clone https://github.com/microsoft/vscode.git
python git_gossip.py vscode/ --html vscode-gossip.html
```

## How the metrics work

### Frustration Index
Scans commit messages for patterns like "fix", "try again", "ugh", "please work", "broken", "revert", profanity, and similar signals. Then detects **rage bursts** — 3+ commits within 5 minutes by the same author, which typically indicates someone fighting a stubborn bug.

### Zombie Code
Tracks files where code was inserted in one commit and deleted in a subsequent commit within 7 days. High zombie counts suggest unclear requirements, premature implementation, or architectural churn.

### Bus Factor
Examines the top 50 most-changed files. For each, calculates what percentage of changes came from a single author. Files where one person owns >80% of changes are "at risk." The bus factor is the count of unique developers who solely own critical files.

### Commit Message Quality
Scores each message 0–1 based on: length (>10 chars), capitalization, use of conventional commit format (`feat:`, `fix:`, etc.), presence of action verbs, and penalties for lazy single-word messages like "fix" or "wip".

### Collaboration Graph
For every file in the repo, tracks which developers have modified it. Developers who share many files are "implicit collaborators" — they're coupled through code even if they never directly communicate. High coupling between two developers who don't talk is a project management risk worth knowing about.

## Who this is for

- **Engineering managers** — understand team dynamics from data, not guesswork
- **Tech leads** — identify hotspot files before they become bug factories
- **Open source maintainers** — spot contributor patterns, bus factor risks, and velocity trends
- **Individual developers** — understand your own working patterns (and your teammates')
- **Anyone curious** — run it on Linux, React, or VS Code and see what falls out

## Ideas for contributions

- **Export to JSON** for integration with dashboards
- **GitHub Action** that posts a gossip summary on every PR
- **Compare two time periods** — "how did our patterns change after the reorg?"
- **Slack/Discord bot** — weekly gossip digest posted to a channel
- **Language-specific analysis** — detect test file ratios, doc coverage
- **Interactive HTML** — clickable heatmaps, filterable author cards
- **Git blame integration** — deeper per-line ownership analysis

## What this is NOT

This tool analyzes **patterns**, not **performance**. Commit frequency, work hours, and churn ratios are behavioral signals, not productivity scores. A developer who commits rarely but ships critical architecture is just as valuable as one with 1,000 small commits. Use this for understanding, not judging.

## License

MIT

---

*Generated by [git-gossip](https://github.com/adithyakiranhere/git-gossip) — because every repo has stories worth telling.* 🗣️
