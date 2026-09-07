"""
eval.py - a scored regression suite.

Two independent things are under test here:
  1. agent_harness.py - the generic loop (via examples/toy_date_agent.py's
     tools, the same demo stage4.py used to use).
  2. Later, dd_agent.py's Companies House tools get their own eval file -
     this one stays fast and network-free (aside from Ollama itself).

The oracle is computed with plain date arithmetic: no model, no tools,
no agent loop. If the agent disagrees with it, the agent is wrong.
"""

from datetime import date

from agent_harness import run_agent
from examples.toy_date_agent import SYSTEM_PROMPT, tools, available_tools


# --- Oracle ----------------------------------------------------------------

def days_from_today(year, month, day):
    return (date(year, month, day) - date.today()).days


# --- Cases -----------------------------------------------------------------

CASES = [
    {
        "name": "christmas",
        "request": "How many days until Christmas?",
        "expect": str(days_from_today(2026, 12, 25)),
    },
    {
        "name": "halloween",
        "request": "How many days until Halloween?",
        "expect": str(days_from_today(2026, 10, 31)),
    },
    {
        "name": "explicit_date",
        "request": "How many days until 2026-09-30?",
        "expect": str(days_from_today(2026, 9, 30)),
    },
    {
        "name": "new_year",
        "request": "How many days until New Year's Day?",
        "expect": str(days_from_today(2027, 1, 1)),
    },
    {
        "name": "weekday",
        "request": "What day of the week is it today?",
        "expect": date.today().strftime("%A"),
    },
    {
        "name": "past_date",
        "request": "How many days until 1 January 2026?",
        "expect": str(days_from_today(2026, 1, 1)),
    },
]


# --- Scoring ---------------------------------------------------------------

def check(answer, expected):
    """Assert on the fact, not the wording."""
    return expected.lower() in answer.replace(",", "").lower()


def run_suite():
    results = []

    for case in CASES:
        print(f"Running: {case['name']}...")
        outcome = run_agent(case["request"], SYSTEM_PROMPT, tools, available_tools, verbose=False)

        if outcome["status"] != "complete":
            passed = False
            actual = f"<{outcome['status']}: {outcome.get('reason')}>"
        else:
            actual = outcome["answer"]
            passed = check(actual, case["expect"])

        results.append({
            "name": case["name"],
            "expect": case["expect"],
            "actual": actual,
            "passed": passed,
            "iterations": outcome["iterations"],
        })

    return results


def report(results):
    print("\n" + "=" * 70)
    print("EVAL RESULTS")
    print("=" * 70)

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        answer = r["actual"].replace("\n", " ")[:60]
        print(f"{status}  {r['name']:<15} expect {r['expect']:<10} | {answer}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    iterations = sum(r["iterations"] for r in results)

    print("=" * 70)
    print(f"SCORE: {passed}/{total} ({passed / total:.0%})")
    print(f"Total LLM calls: {iterations}")


if __name__ == "__main__":
    report(run_suite())
