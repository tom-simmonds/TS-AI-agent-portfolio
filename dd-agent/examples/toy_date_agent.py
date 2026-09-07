"""
toy_date_agent.py - the same date-scheduling demo from the old stage4.py,
now as a plain caller of agent_harness.run_agent(). If this still works
after the harness was generalised to take tools as arguments instead of
module-level globals, that proves the harness has no domain logic baked in.

Run directly:
    python examples/toy_date_agent.py

Or import SYSTEM_PROMPT / tools / available_tools elsewhere - eval.py uses
this to regression-test the harness itself, independent of the real
Companies House agent.
"""

import sys
from pathlib import Path
from datetime import datetime, date

# Let this run both as `python examples/toy_date_agent.py` and via imports
# from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_harness import run_agent

SYSTEM_PROMPT = """You are a scheduling assistant.

You have tools available. Use them rather than guessing.
You do not know today's date until you look it up.
When you have the answer, state it plainly in one sentence."""


# --- Tools -----------------------------------------------------------------

def get_current_time():
    return datetime.now().strftime("%A %d %B %Y, %H:%M")


def days_until(date_string):
    target = datetime.strptime(date_string, "%Y-%m-%d").date()
    delta = target - date.today()
    return f"{delta.days} days until {date_string}"


available_tools = {
    "get_current_time": get_current_time,
    "days_until": days_until,
}

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time. Use this whenever you need to know today's date.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "days_until",
            "description": (
                "Calculate how many days remain until a given date. "
                "The date must be in YYYY-MM-DD format. "
                "You need to know today's date before this is meaningful."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_string": {
                        "type": "string",
                        "description": "Target date in YYYY-MM-DD format, e.g. 2026-12-25",
                    }
                },
                "required": ["date_string"],
            },
        },
    },
]


if __name__ == "__main__":
    outcome = run_agent("How many days until Christmas?", SYSTEM_PROMPT, tools, available_tools)

    print("\n" + "=" * 50)
    print("STATUS:", outcome["status"])
    if outcome["status"] == "complete":
        print("ANSWER:", outcome["answer"])
    else:
        print("FAILED:", outcome.get("reason"))
    print(f"({outcome['iterations']} iterations, {outcome['elapsed_seconds']:.1f}s)")
