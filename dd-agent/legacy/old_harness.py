"""
Stage 4 - the agent loop.

Two chained tools, an iteration cap, and explicit handling for the three
ways this loop can go wrong.
"""

import requests
from datetime import datetime, date

MODEL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434/api/chat"
MAX_ITERATIONS = 6

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


# --- Harness ---------------------------------------------------------------

def call_model(messages):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": messages,
            "tools": tools,
            "stream": False,
        },
    )
    return response.json()["message"]


def execute_tool_call(call, verbose=True):
    """Run one tool call. Never raises - errors come back as strings."""
    function_name = call["function"]["name"]
    arguments = call["function"]["arguments"]
    print(f"  CALLING: {function_name}({arguments})")

    function = available_tools.get(function_name)
    if function is None:
        return f"Error: no tool named '{function_name}'. Available tools: {list(available_tools)}"

    try:
        return function(**arguments)
    except Exception as exc:
        return f"Error running {function_name}: {type(exc).__name__}: {exc}"


def run_agent(user_request, verbose=True):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_request},
    ]

    for iteration in range(1, MAX_ITERATIONS + 1):
        if verbose:
            print(f"\n--- Iteration {iteration} ---")

        assistant_message = call_model(messages)
        messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls")
        content = (assistant_message.get("content") or "").strip()

        if not tool_calls:
            if content:
                return {
                    "status": "complete",
                    "answer": content,
                    "iterations": iteration,
                    "messages": messages,
                }

            if verbose:
                print("  Empty response with no tool call - nudging.")
            messages.append({
                "role": "user",
                "content": "You returned an empty response. Either call a tool or give your final answer.",
            })
            continue

        for call in tool_calls:
            result = execute_tool_call(call, verbose)
            if verbose:
                print(f"  RESULT: {result}")
            messages.append({"role": "tool", "content": str(result)})

    # DECISION 4: iterations exhausted. This must NOT look like success.
    return {
        "status": "incomplete",
        "answer": None,
        "reason": f"Hit iteration cap of {MAX_ITERATIONS} without a final answer",
        "iterations": MAX_ITERATIONS,
        "messages": messages,
    }


if __name__ == "__main__":
    outcome = run_agent("How many days until Christmas?")

    print("\n" + "=" * 50)
    print("STATUS:", outcome["status"])
    if outcome["status"] == "complete":
        print("ANSWER:", outcome["answer"])
    else:
        print("FAILED:", outcome["reason"])
    print(f"({outcome['iterations']} iterations)")
