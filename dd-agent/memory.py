"""
memory.py - episodic memory (box 5a "Memory -> Episodic: past actions &
outcomes" in the architecture diagram). Short-term memory already exists
as the message window inside agent_harness.run_agent() - this is the
long-term half: an append-only log of past due-diligence runs, so a
report doesn't vanish the moment the process exits.

Deliberately simple: one JSON object per line in runs.jsonl, no database,
no embeddings, no semantic recall - just "what did we find last time we
checked this company," which is what due diligence actually needs day to
day. A real vector-DB/knowledge-base layer (the diagram's "long-term:
vector DB, knowledge base" sub-box) is future work, not this.

Note this is a write-only history right now: dd_agent.py logs every run,
but doesn't read its own past runs back into a fresh check - an analyst
can call recall() themselves, but the agent doesn't yet. Closing that
loop (the agent noting "we checked this 3 weeks ago and found X") is a
named future improvement, not done here.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "runs.jsonl"


def log_run(report):
    """Append one completed (or failed) due-diligence run to the episodic
    log. report is whatever run_due_diligence() returned - success and
    agent_failed reports both have a company_queried field, so recall()
    works on either."""
    entry = {"logged_at": datetime.now(timezone.utc).isoformat(), **report}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def recall(company_query, limit=5):
    """Return past runs whose company_queried or company_name_matched
    contains company_query (case-insensitive), most recent first."""
    if not LOG_PATH.exists():
        return []

    query = company_query.strip().lower()
    matches = []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            haystack = " ".join(
                str(entry.get(key, "")) for key in ("company_queried", "company_name_matched")
            ).lower()
            if query in haystack:
                matches.append(entry)

    matches.reverse()
    return matches[:limit]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python memory.py \"<company name or partial name>\"")
        sys.exit(1)

    results = recall(" ".join(sys.argv[1:]))
    if not results:
        print("No past runs found for that query.")
    else:
        for entry in results:
            print(f"{entry.get('logged_at', '?')}  {entry.get('company_queried', '?')!r} "
                  f"-> {entry.get('company_name_matched') or entry.get('status', '?')}, "
                  f"risk={entry.get('risk_rating', '?')}")
