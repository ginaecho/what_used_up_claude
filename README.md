# what_used_up_claude

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
```

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
This is a keyword heuristic — tune the `CLASSIFY_RULES` list in the script, or
override any session with a tag file:

```bash
# tags.json  ->  { "6533afa3-915f-...": "refactor", "1a2b...": "research" }
python3 claude_usage_stats.py --tags tags.json
```

### Caveats

- **Dollar figures are approximate.** Prices live in the `PRICING` dict at the
  top of the script; update them if they drift. Token counts come straight from
  the logs and are exact.
- **Cache-read tokens dominate the raw token total** but are cheap in dollars —
  so the `~cost` column is a better planning signal than raw token count.
- Only sessions still present under `~/.claude/projects` are analyzed; Claude
  Code prunes old logs over time.

## Possible next steps

- LLM-based classification (send the first prompt to Claude) for better accuracy
  than keywords.
- A `--live` burn-rate view against the current 5-hour / weekly window.
- Weekly summary export (CSV) for tracking trends.
