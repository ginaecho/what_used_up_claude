# claude-usage-statics

Understand **what kinds of task burn how many tokens**, per model, so that when
your Claude usage limit is approaching you can pick a task that fits the budget
you have left.

## Short answer to "is this possible / does it already exist?"

Yes, and most of the plumbing already exists:

- **The data is already on your disk.** Claude Code logs every session to
  `~/.claude/projects/<project>/<session-id>.jsonl`. Each assistant turn records
  `input_tokens`, `output_tokens`, cache read/write tokens, **and the model**
  (`claude-opus-4-8`, `claude-sonnet-5`, …). No API needed.
- **Built-in commands:** `/cost` (current session cost) and `/usage` (your plan's
  usage against its limits).
- **`ccusage`** (`npx ccusage@latest`) — a third-party tool that aggregates those
  same logs by day / week / month / session / project / model, with a live
  burn-rate view (`ccusage blocks --live`).

**What none of them do** is group by *what kind of task* it was — "debug" vs
"big refactor" vs "research". That task-type breakdown is the one number that
actually answers *"the limit's close, what's cheap enough to still do?"* — and
it's what this repo adds.

## Quickest path: the `/budget` slash command

Install once, then type **`/budget`** in any Claude Code session:

```bash
./install.sh --limit-5h 2M --limit-weekly '$150'
# (run /usage in Claude Code once to find your real caps)
```

This copies the analyzer and a `/budget` command into `~/.claude/`. When you run
`/budget`, Claude runs the analyzer and gives you a short briefing:

1. **Where your tokens go** — the costliest task types per model, and whether a
   cheaper model would do.
2. **Right now** — how much of your 5-hour window is left and your burn rate.
3. **What to do next** — which task types are safe to start now, which to hold
   until the window resets, and roughly how many of each you can still fit.

That last part is exactly *"with the usage I have left, what task is proper to
do?"* — computed from your own historical per-task averages.

### Does it count subagents / "all LLM usage"?

**Yes.** Claude Code logs subagent (Task tool) turns into the same session file
as `isSidechain: true` entries, each with its own `usage` and `model`. The
analyzer sums **every** assistant turn, so subagent tokens are already included
in every total, average, and burn-rate figure.

The one boundary: this reads **Claude Code** logs only. If you also chat in the
**claude.ai web app** (a separate product that shares your subscription's
limit), those conversations aren't in these logs and can't be counted here.
Everything you do *in Claude Code* — main agent + all subagents — is covered.

## The tool: `claude_usage_stats.py`

Pure Python standard library, no network. It reads your local logs, classifies
each session into a task type from its opening prompt, and prints per-task /
per-model token and (approximate) dollar stats.

```bash
python3 claude_usage_stats.py                 # summary by task type × model
python3 claude_usage_stats.py --by project    # group by project folder
python3 claude_usage_stats.py --by session    # one row per session
python3 claude_usage_stats.py --since 2026-06-01
python3 claude_usage_stats.py --json          # machine-readable
python3 claude_usage_stats.py --logs /path/to/projects
python3 claude_usage_stats.py --live          # burn-rate vs. current windows
python3 claude_usage_stats.py --classify llm  # accurate task labels via claude CLI
python3 claude_usage_stats.py --calibrate     # infer caps from /usage
python3 claude_usage_stats.py --csv weekly.csv # weekly trend export
```

### `--live` burn-rate view

Reconstructs your **current rolling 5-hour session window** and **trailing
7-day window** from the logs and shows what you've spent, your burn rate, and a
straight-line projection to the end of the 5-hour window:

```bash
python3 claude_usage_stats.py --live
python3 claude_usage_stats.py --live --limit-5h 2M --limit-weekly '$150'
```

```
=== 5-hour session window ===
  window   2026-07-13 10:00 -> 15:00 UTC   (1h22m elapsed, 3h37m left)
  used     3.3M tokens   ~$14.18
  burn     2.4M/hr   ~$10.30/hr
  project  11.8M tokens   ~$51.51  at end of window (current pace)
  limit    [################--------]   65%  (3.3M / 5.0M tok)
  ETA      ~44m to limit (12:06 UTC, within this window)
  WARNING  projected to EXCEED the limit before the window ends
```

When limits are set, `--live` also prints a recommendation table — which task
types still fit in the remaining 5-hour budget, at their historical average
size:

```
=== What fits in your remaining 5-hour budget (14.7M tokens) ===
task      typical cost  history  verdict
--------  ------------  -------  ---------------
docs           avg 24k      n=8  OK    ~600 more
tests         avg 120k      n=5  OK    ~120 more
refactor      avg 1.2M      n=4  OK    ~12 more
research      avg 5.3M      n=2  OK    ~2 more
```

Claude Code doesn't record your plan's actual caps, so the gauge, ETA,
warning, and recommendations only appear when limits are known. Provide them
via `--limit-5h` / `--limit-weekly` (tokens like `1.5M`/`500k`, or dollars like
`$20`), or set them once in a config file so you never pass flags:

```bash
# usage_limits.json (searched in ./ then ~/.claude/), or pass --limits FILE
{ "limit_5h": "2M", "limit_weekly": "$150" }
```

Copy `usage_limits.example.json` to get started. Without limits you still get
consumption + burn rate. If you've been idle more than 5 hours the session
window reports as clear.

Example output:

```
Analyzed 1 sessions   1.4M tokens   ~$8.97 (rough)

=== Per-task averages (plan with these) ===
task      sessions  avg tok  avg $  total tok  total $
--------  --------  -------  -----  ---------  -------
research         1     1.4M  $8.97       1.4M    $8.97
```

The **"avg tok / avg $" per task** columns are the ones to plan with: once you
have a few weeks of history, they tell you a typical refactor on Opus costs
~N tokens while a doc edit on Sonnet costs a fraction of that.

### Task classification

Sessions are auto-classified from the first user prompt into: `debug`,
`feature`, `refactor`, `tests`, `docs`, `research`, `review`, `ops`, `other`.
The default is a fast keyword heuristic — tune the `CLASSIFY_RULES` list in the
script, or override any session with a tag file:

```bash
# tags.json  ->  { "6533afa3-915f-...": "refactor", "1a2b...": "research" }
python3 claude_usage_stats.py --tags tags.json
```

**LLM classification (more accurate).** For better labels than keywords, use the
local `claude` CLI — no API key needed, it reuses your existing Claude Code auth:

```bash
python3 claude_usage_stats.py --classify llm            # default model: haiku
python3 claude_usage_stats.py --classify llm --classify-model sonnet
```

Each session is classified once and cached in `~/.claude/usage_classify_cache.json`,
so repeated runs cost **zero** extra tokens. Prompts are batched (40 per call) and
sent to a cheap model (Haiku) by default. If the CLI is missing or errors, it
falls back to keyword classification automatically.

### Auto-detect your plan caps from `/usage`

Instead of guessing your limits, infer them. `/usage` tells you what *percent* of
each window you've used; the tool knows how many *tokens* you've used from the
logs, so it back-computes the cap (`cap = used ÷ percent`):

```bash
# 1. run /usage in Claude Code, read the two percentages, then:
python3 claude_usage_stats.py --calibrate --pct-5h 58 --pct-weekly 24

# ...or just paste the whole /usage output in and let it scrape the numbers:
python3 claude_usage_stats.py --calibrate   # then paste, Ctrl-D
```

It writes `~/.claude/usage_limits.json` (merging, not clobbering), so every later
`--live` / `/budget` run has real limits. Caps are approximate — inferred from
local logs — so re-run occasionally to refine.

### Weekly CSV export

For tracking trends over weeks, export a summary grouped by ISO week × task × model:

```bash
python3 claude_usage_stats.py --csv weekly.csv
python3 claude_usage_stats.py --csv weekly.csv --classify llm   # with LLM labels
```

Columns: `week_start, task, model, sessions, input_tokens, output_tokens,
cache_write_tokens, cache_read_tokens, total_tokens, est_cost_usd` — ready to drop
into a spreadsheet or plot.

### Caveats

- **Dollar figures are approximate.** Prices live in the `PRICING` dict at the
  top of the script; update them if they drift. Token counts come straight from
  the logs and are exact.
- **Cache-read tokens dominate the raw token total** but are cheap in dollars —
  so the `~cost` column is a better planning signal than raw token count.
- Only sessions still present under `~/.claude/projects` are analyzed; Claude
  Code prunes old logs over time.

## Possible next steps

- A `--watch` auto-refreshing live dashboard (re-render every N seconds).
- Trend charts rendered straight from the weekly CSV.
- Per-project budgets, not just global windows.
