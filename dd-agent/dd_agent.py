"""
dd_agent.py - the real supplier due-diligence agent (box 4 "Agent" in the
architecture diagram): wires the generic harness (agent_harness.py) up to
the real Companies House tools (companies_house.py) and the prompt layer
(prompts.py), and returns a structured due-diligence report.

Run:
    python dd_agent.py "Tesco"
    python dd_agent.py Tesco PLC
"""

import json
import sys

from agent_harness import run_agent
from companies_house import tools, available_tools
from prompts import SYSTEM_PROMPT, validate_dd_report, parse_json_answer
from memory import log_run

# A real check is search + profile + PSC + filings + maybe charges + maybe
# insolvency + maybe officers + the final answer - that's 6-8 iterations
# before success, well past the toy agent's default of 6. Local qwen3:8b
# also isn't fast: the toy agent took ~37s for 3 iterations in testing, so
# budget generously rather than have a real check hit "incomplete"/"timeout"
# purely because the limits were sized for a 2-tool demo.
MAX_ITERATIONS = 15
RUN_TIMEOUT = 300.0


def run_due_diligence(company_name, verbose=True):
    """Run a due-diligence check and return the parsed report dict.

    On anything other than a clean "complete" outcome (incomplete, timeout,
    error), returns a dict with status: "agent_failed" and a reason instead
    of raising - callers can check for that key rather than wrapping this
    in a try/except.
    """
    outcome = run_agent(
        f"Run a supplier due-diligence check on: {company_name}",
        SYSTEM_PROMPT,
        tools,
        available_tools,
        max_iterations=MAX_ITERATIONS,
        timeout=RUN_TIMEOUT,
        validate_answer=validate_dd_report,
        verbose=verbose,
    )

    if outcome["status"] != "complete":
        report = {
            "company_queried": company_name,
            "status": "agent_failed",
            "reason": outcome.get("reason", outcome["status"]),
            "iterations": outcome["iterations"],
            "elapsed_seconds": outcome.get("elapsed_seconds"),
        }
        log_run(report)
        return report

    # validate_dd_report already confirmed outcome["answer"] parses and matches
    # the schema before the harness would ever return "complete" - this can't fail.
    report = parse_json_answer(outcome["answer"])
    report["_meta"] = {
        "iterations": outcome["iterations"],
        "elapsed_seconds": round(outcome.get("elapsed_seconds", 0), 1),
    }
    log_run(report)
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python dd_agent.py "<company name>"')
        sys.exit(1)

    company_name = " ".join(sys.argv[1:])
    report = run_due_diligence(company_name)

    print("\n" + "=" * 70)
    print(json.dumps(report, indent=2))
