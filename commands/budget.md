---
description: Show token usage by task type and recommend what fits your remaining limit
allowed-tools: Bash(python3:*)
---

You are helping the user decide what to work on given their remaining Claude
usage. Two data dumps follow. The script counts ALL LLM turns in the logs,
including subagents (sidechain turns), so these numbers already include any
Task/subagent work.

The script ships inside this plugin; ${CLAUDE_PLUGIN_ROOT} points at the plugin
directory. Fallbacks cover a manual (~/.claude) or in-repo install too.

Historical cost per task type and model:
!`python3 "${CLAUDE_PLUGIN_ROOT}/claude_usage_stats.py" --by task 2>/dev/null || python3 "$HOME/.claude/claude_usage_stats.py" --by task 2>/dev/null || python3 claude_usage_stats.py --by task`

Live burn-rate against the current 5-hour and 7-day windows (limits, if any,
come from usage_limits.json — see the "What fits" section for recommendations):
!`python3 "${CLAUDE_PLUGIN_ROOT}/claude_usage_stats.py" --live 2>/dev/null || python3 "$HOME/.claude/claude_usage_stats.py" --live 2>/dev/null || python3 claude_usage_stats.py --live`

Now, using ONLY the numbers above, give me a short briefing:

1. **Where my tokens go** — the 2-3 task types that cost the most per session,
   and whether a cheaper model (Sonnet/Haiku) would do for any of them.
2. **Right now** — how much of my 5-hour window is left, and my burn rate.
3. **What to do next** — concrete recommendation: which task types are safe to
   start now, which to avoid until the window resets, and roughly how many of
   each I can still fit. Lean on the "What fits in your remaining 5-hour budget"
   table if it's present.

Keep it to a tight briefing, not a wall of text. If no limits are configured,
say so and tell me to set my caps in `~/.claude/usage_limits.json` (run `/usage`
once to find the real numbers, or `python3 claude_usage_stats.py --calibrate`)
so you can give headroom instead of just consumption.
