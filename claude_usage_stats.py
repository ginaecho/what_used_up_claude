#!/usr/bin/env python3
"""
claude_usage_stats.py — "what used up Claude?"

Analyze local Claude Code session logs to show how many tokens (and roughly how
many dollars) different kinds of task cost, broken down by model. The goal is
practical: when your usage limit is approaching, you can glance at the averages
and pick a task that fits the budget you have left.

No API calls, no network. It only reads the JSONL session logs that Claude Code
already writes to  ~/.claude/projects/<project>/<session-id>.jsonl .

Each session is classified into a task type (debug, feature, refactor, tests,
docs, research, review, ops, other) using keyword rules on the *first* user
prompt. Classification is a heuristic — override it any time with a sidecar
tag file (see --tags below).

Usage:
    python3 claude_usage_stats.py                 # summary by task type x model
    python3 claude_usage_stats.py --by session    # one row per session
    python3 claude_usage_stats.py --by project    # group by project folder
    python3 claude_usage_stats.py --since 2026-06-01
    python3 claude_usage_stats.py --json          # machine-readable output
    python3 claude_usage_stats.py --logs /path/to/projects

Tagging (optional, for accurate task types):
    Create a JSON file mapping session id -> task type and pass --tags tags.json
        { "6533afa3-915f-...": "refactor", "1a2b...": "research" }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Pricing.  Approximate USD per 1,000,000 tokens. Prices change over time and
# vary by exact model version, so treat the dollar column as a rough guide.
# Update these if they drift. Keys are matched as substrings of the model id.
# ---------------------------------------------------------------------------
PRICING = {
    # model-id substring : (input, output, cache_write, cache_read)  per 1M tokens
    "opus":   (15.00, 75.00, 18.75, 1.50),
    "sonnet": (3.00,  15.00,  3.75, 0.30),
    "haiku":  (0.80,   4.00,  1.00, 0.08),
    "fable":  (3.00,  15.00,  3.75, 0.30),  # placeholder; adjust when known
}
DEFAULT_PRICE = (3.00, 15.00, 3.75, 0.30)  # fallback if model unrecognised

# ---------------------------------------------------------------------------
# Task classification. First matching rule wins, so order matters (most
# specific first). Each rule: (task_type, [keywords]). Matched against a
# lowercased copy of the session's first user prompt.
# ---------------------------------------------------------------------------
CLASSIFY_RULES = [
    ("debug",    ["bug", "error", "traceback", "exception", "crash", "fix ",
                  "failing", "broken", "doesn't work", "not working", "stack trace"]),
    ("tests",    ["unit test", "write test", "add test", "test coverage",
                  "pytest", "jest", "spec file"]),
    ("refactor", ["refactor", "clean up", "cleanup", "rename", "restructure",
                  "extract ", "simplify", "deduplicate", "tidy"]),
    ("review",   ["review", "code review", "audit", "security review", "critique"]),
    ("docs",     ["readme", "documentation", "docstring", "document ",
                  "changelog", "comment the", "write docs"]),
    ("research", ["research", "compare", "investigate", "explain", "how does",
                  "what is", "is it possible", "should i", "pros and cons",
                  "understand", "look into", "find out"]),
    ("ops",      ["deploy", "ci ", "pipeline", "docker", "kubernetes", "github action",
                  "workflow", "release", "migrate", "migration", "infra"]),
    ("feature",  ["add ", "implement", "create ", "build ", "new feature",
                  "support for", "write a", "make a", "develop"]),
]
DEFAULT_TASK = "other"


def classify(prompt: str) -> str:
    if not prompt:
        return DEFAULT_TASK
    p = prompt.lower()
    for task, keywords in CLASSIFY_RULES:
        if any(k in p for k in keywords):
            return task
    return DEFAULT_TASK


def price_for(model: str):
    if model:
        for key, price in PRICING.items():
            if key in model:
                return price
    return DEFAULT_PRICE


def cost_usd(model, inp, out, cw, cr):
    pi, po, pcw, pcr = price_for(model)
    return (inp * pi + out * po + cw * pcw + cr * pcr) / 1_000_000


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
class Session:
    __slots__ = ("sid", "project", "first_prompt", "start", "models",
                 "input", "output", "cache_write", "cache_read", "task",
                 "_per_model")

    def __init__(self, sid):
        self.sid = sid
        self.project = ""
        self.first_prompt = ""
        self.start = None
        self.models = set()
        self.input = 0
        self.output = 0
        self.cache_write = 0
        self.cache_read = 0
        self.task = DEFAULT_TASK

    @property
    def total_tokens(self):
        # All tokens that count against usage. Cache reads are cheap in $ but
        # still real tokens, so include them; the dollar figure weights them.
        return self.input + self.output + self.cache_write + self.cache_read

    @property
    def primary_model(self):
        # The model that did the most work is a fine label when a session
        # mixes models; here we just join, since token totals are per-session.
        return ", ".join(sorted(self.models)) if self.models else "unknown"

    def cost(self):
        # Cost is summed per-model in the aggregator; for a single-model
        # session this is exact, for mixed sessions it's an approximation
        # using the session's model set is avoided — see aggregate().
        return None


def parse_first_prompt(content):
    """User content may be a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
            if isinstance(block, str):
                return block
    return ""


def parse_file(path: Path):
    """Return a Session, accumulating per-model token sums separately so cost
    is exact even when a session switches models."""
    sid = path.stem
    sess = Session(sid)
    # per-model accumulation for exact cost
    per_model = defaultdict(lambda: [0, 0, 0, 0])  # inp,out,cw,cr
    got_prompt = False

    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue

            typ = o.get("type")

            if typ == "user" and not got_prompt:
                msg = o.get("message", {})
                # skip tool_result-only user turns; we want the human's ask
                text = parse_first_prompt(msg.get("content"))
                if text and o.get("origin", {}).get("kind", "human") != "tool":
                    sess.first_prompt = text
                    got_prompt = True
                if not sess.project:
                    sess.project = o.get("cwd", "")
                if not sess.start:
                    sess.start = o.get("timestamp")

            elif typ == "assistant":
                msg = o.get("message", {})
                model = msg.get("model", "") or ""
                if model and model != "<synthetic>":
                    sess.models.add(model)
                u = msg.get("usage") or {}
                inp = u.get("input_tokens", 0) or 0
                out = u.get("output_tokens", 0) or 0
                cw = u.get("cache_creation_input_tokens", 0) or 0
                cr = u.get("cache_read_input_tokens", 0) or 0
                sess.input += inp
                sess.output += out
                sess.cache_write += cw
                sess.cache_read += cr
                acc = per_model[model]
                acc[0] += inp; acc[1] += out; acc[2] += cw; acc[3] += cr

    sess.task = classify(sess.first_prompt)
    sess._per_model = per_model  # type: ignore[attr-defined]
    return sess


def session_cost(sess):
    total = 0.0
    for model, (inp, out, cw, cr) in getattr(sess, "_per_model", {}).items():
        total += cost_usd(model, inp, out, cw, cr)
    return total


# ---------------------------------------------------------------------------
# Aggregation & reporting
# ---------------------------------------------------------------------------
def load_sessions(logs_dir: Path, since=None, tags=None):
    sessions = []
    for path in sorted(logs_dir.glob("**/*.jsonl")):
        try:
            sess = parse_file(path)
        except Exception as e:  # keep going on a bad file
            print(f"warn: skipped {path.name}: {e}", file=sys.stderr)
            continue
        if sess.total_tokens == 0:
            continue
        if tags and sess.sid in tags:
            sess.task = tags[sess.sid]
        if since and sess.start:
            try:
                ts = datetime.fromisoformat(sess.start.replace("Z", "+00:00"))
                if ts < since:
                    continue
            except ValueError:
                pass
        sessions.append(sess)
    return sessions


def fmt_int(n):
    return f"{n:,}"


def human_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}k"
    return str(n)


def print_table(rows, headers, aligns=None):
    cols = len(headers)
    aligns = aligns or ["<"] * cols
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    sep = "  "
    line = sep.join(f"{h:{aligns[i]}{widths[i]}}" for i, h in enumerate(headers))
    print(line)
    print(sep.join("-" * widths[i] for i in range(cols)))
    for r in rows:
        print(sep.join(f"{str(c):{aligns[i]}{widths[i]}}" for i, c in enumerate(r)))


def report_grouped(sessions, group_key, label):
    # group_key(sess) -> (task_or_group, model-ish). We build task x model grid.
    buckets = defaultdict(lambda: {"n": 0, "tok": 0, "usd": 0.0})
    for s in sessions:
        for model, (inp, out, cw, cr) in getattr(s, "_per_model", {}).items():
            key = (group_key(s), model or "unknown")
            b = buckets[key]
            b["n"] += 0  # session counted once below
            b["tok"] += inp + out + cw + cr
            b["usd"] += cost_usd(model, inp, out, cw, cr)
    # session counts per group (not per model) tracked separately
    group_sessions = defaultdict(set)
    for s in sessions:
        group_sessions[group_key(s)].add(s.sid)

    rows = []
    for (grp, model), b in sorted(buckets.items(),
                                  key=lambda kv: (-kv[1]["tok"],)):
        rows.append([
            grp, short_model(model),
            human_tokens(b["tok"]),
            f"${b['usd']:.2f}",
        ])
    print(f"\n=== Tokens by {label} × model ===")
    print_table(rows, [label, "model", "tokens", "~cost"],
                aligns=["<", "<", ">", ">"])

    # per-group averages — the number you actually use for planning
    per_group = defaultdict(lambda: {"tok": 0, "usd": 0.0})
    for s in sessions:
        per_group[group_key(s)]["tok"] += s.total_tokens
        per_group[group_key(s)]["usd"] += session_cost(s)
    avg_rows = []
    for grp, agg in sorted(per_group.items(), key=lambda kv: -kv[1]["tok"]):
        n = len(group_sessions[grp])
        avg_rows.append([
            grp, str(n),
            human_tokens(agg["tok"] // max(n, 1)),
            f"${agg['usd']/max(n,1):.2f}",
            human_tokens(agg["tok"]),
            f"${agg['usd']:.2f}",
        ])
    print(f"\n=== Per-{label} averages (plan with these) ===")
    print_table(avg_rows,
                [label, "sessions", "avg tok", "avg $", "total tok", "total $"],
                aligns=["<", ">", ">", ">", ">", ">"])


def short_model(m):
    m = m or ""
    for k in ("opus", "sonnet", "haiku", "fable"):
        if k in m:
            return k
    return m or "unknown"


def report_sessions(sessions):
    rows = []
    for s in sorted(sessions, key=lambda x: -x.total_tokens):
        prompt = (s.first_prompt or "").replace("\n", " ")[:50]
        rows.append([
            s.sid[:8], s.task, short_model(s.primary_model),
            human_tokens(s.total_tokens), f"${session_cost(s):.2f}", prompt,
        ])
    print_table(rows,
                ["session", "task", "model", "tokens", "~cost", "first prompt"],
                aligns=["<", "<", "<", ">", ">", "<"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Analyze Claude Code token usage by task type and model.")
    default_logs = Path(os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--logs", type=Path, default=default_logs,
                    help=f"Claude Code projects log dir (default: {default_logs})")
    ap.add_argument("--by", choices=["task", "project", "session"], default="task",
                    help="grouping for the report (default: task)")
    ap.add_argument("--since", help="only sessions on/after this date (YYYY-MM-DD)")
    ap.add_argument("--tags", type=Path, help="JSON file mapping session id -> task type")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    if not args.logs.exists():
        print(f"No log directory at {args.logs}. Is Claude Code installed / has it run?",
              file=sys.stderr)
        return 1

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"bad --since date: {args.since} (use YYYY-MM-DD)", file=sys.stderr)
            return 1

    tags = None
    if args.tags and args.tags.exists():
        tags = json.loads(args.tags.read_text())

    sessions = load_sessions(args.logs, since=since, tags=tags)
    if not sessions:
        print("No sessions with token usage found.", file=sys.stderr)
        return 0

    if args.json:
        out = []
        for s in sessions:
            out.append({
                "session": s.sid,
                "task": s.task,
                "project": s.project,
                "models": sorted(s.models),
                "first_prompt": s.first_prompt[:200],
                "input_tokens": s.input,
                "output_tokens": s.output,
                "cache_write_tokens": s.cache_write,
                "cache_read_tokens": s.cache_read,
                "total_tokens": s.total_tokens,
                "est_cost_usd": round(session_cost(s), 4),
            })
        print(json.dumps(out, indent=2))
        return 0

    total_tok = sum(s.total_tokens for s in sessions)
    total_usd = sum(session_cost(s) for s in sessions)
    print(f"Analyzed {len(sessions)} sessions   "
          f"{human_tokens(total_tok)} tokens   ~${total_usd:.2f} (rough)")

    if args.by == "session":
        report_sessions(sessions)
    elif args.by == "project":
        report_grouped(sessions, lambda s: os.path.basename(s.project.rstrip("/")) or "?", "project")
    else:
        report_grouped(sessions, lambda s: s.task, "task")

    print("\nNote: dollar figures are approximate (see PRICING in this script); "
          "token counts come straight from the logs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
