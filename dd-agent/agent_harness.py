"""
agent_harness.py - the reusable agent loop (the "Agent Harness" box in the
architecture diagram): hosts an agent, wires a prompt + a tool set together,
and enforces the two limits a harness is responsible for - a hard iteration
cap and a wall-clock timeout.

This file is intentionally domain-agnostic: it knows nothing about dates,
companies, or anything else. Callers supply:
  - a system prompt
  - a JSON tool spec list (what the model is told about the tools)
  - an available_tools dict (name -> callable) the harness actually invokes
  - a user request

See examples/toy_date_agent.py for the smallest possible caller, and
dd_agent.py (coming next) for the real due-diligence agent.
"""

import time
import requests

MODEL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434/api/chat"

MAX_ITERATIONS = 6          # hard cap on plan/act/observe cycles
RUN_TIMEOUT = 60.0          # wall-clock budget for the whole run, in seconds
REQUEST_TIMEOUT = 30.0      # per-HTTP-call timeout, so a hung model can't hang the process


# --- Model call --------------------------------------------------------------

def call_model(messages, tools, model=MODEL, request_timeout=REQUEST_TIMEOUT):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
        },
        timeout=request_timeout,
    )
    response.raise_for_status()
    return response.json()["message"]


# --- Tool dispatch -------------------------------------------------------------

def execute_tool_call(call, available_tools, verbose=True):
    """Run one tool call. Never raises - errors come back as strings."""
    function_name = call["function"]["name"]
    arguments = call["function"]["arguments"]
    if verbose:
        print(f"  CALLING: {function_name}({arguments})")

    function = available_tools.get(function_name)
    if function is None:
        return f"Error: no tool named '{function_name}'. Available tools: {list(available_tools)}"

    try:
        return function(**arguments)
    except Exception as exc:
        return f"Error running {function_name}: {type(exc).__name__}: {exc}"


# --- Harness ------------------------------------------------------------------

def run_agent(
    user_request,
    system_prompt,
    tools,
    available_tools,
    *,
    model=MODEL,
    max_iterations=MAX_ITERATIONS,
    timeout=RUN_TIMEOUT,
    validate_answer=None,
    verbose=True,
):
    """Run the plan/act/observe loop until the model gives a final answer,
    or one of the harness's limits kicks in.

    Returns a dict with a "status" of one of:
      - "complete"   - the model gave a final answer
      - "incomplete" - hit max_iterations without a final answer
      - "timeout"    - hit the wall-clock budget without a final answer
      - "error"      - the model call itself failed (e.g. Ollama unreachable)

    validate_answer, if given, is called as validate_answer(content, tools_called) -> (is_valid, error_message)
    on every non-tool-call response, where tools_called is the list of tool names invoked so
    far this run (in order, duplicates included). Only a response that passes is accepted as
    "complete" - otherwise the harness nudges the model with error_message and keeps looping,
    bounded by the same max_iterations/timeout as everything else. This is how the harness
    enforces an output schema AND a minimum "did you actually check" bar (box 2) without either
    living in this domain-agnostic file - a schema-valid answer that skipped required tool calls
    is still rejected, which a prompt instruction alone can't guarantee with a small local model.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_request},
    ]

    start = time.monotonic()
    tools_called = []

    for iteration in range(1, max_iterations + 1):
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            return {
                "status": "timeout",
                "answer": None,
                "reason": f"Exceeded run timeout of {timeout}s after {iteration - 1} iteration(s)",
                "iterations": iteration - 1,
                "elapsed_seconds": elapsed,
                "messages": messages,
            }

        if verbose:
            print(f"\n--- Iteration {iteration} ---")

        try:
            assistant_message = call_model(messages, tools, model=model)
        except requests.exceptions.RequestException as exc:
            return {
                "status": "error",
                "answer": None,
                "reason": f"Model call failed: {type(exc).__name__}: {exc}",
                "iterations": iteration,
                "elapsed_seconds": time.monotonic() - start,
                "messages": messages,
            }

        messages.append(assistant_message)

        tool_calls = assistant_message.get("tool_calls")
        content = (assistant_message.get("content") or "").strip()

        if not tool_calls:
            if content:
                if validate_answer is not None:
                    is_valid, error = validate_answer(content, tools_called)
                    if not is_valid:
                        if verbose:
                            print(f"  Answer failed validation: {error}")
                        messages.append({
                            "role": "user",
                            "content": f"Your answer didn't pass validation: {error} Correct it and respond again with ONLY the corrected answer.",
                        })
                        continue

                return {
                    "status": "complete",
                    "answer": content,
                    "iterations": iteration,
                    "elapsed_seconds": time.monotonic() - start,
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
            result = execute_tool_call(call, available_tools, verbose)
            tools_called.append(call["function"]["name"])
            if verbose:
                print(f"  RESULT: {result}")
            messages.append({"role": "tool", "content": str(result)})

    # DECISION: iterations exhausted. This must NOT look like success.
    return {
        "status": "incomplete",
        "answer": None,
        "reason": f"Hit iteration cap of {max_iterations} without a final answer",
        "iterations": max_iterations,
        "elapsed_seconds": time.monotonic() - start,
        "messages": messages,
    }


if __name__ == "__main__":
    print(
        "agent_harness.py is the generic loop only - it has no tools of its own.\n"
        "Run `python examples/toy_date_agent.py` for a minimal runnable example, "
        "or `python dd_agent.py \"<company name>\"` for the real due-diligence agent "
    )
