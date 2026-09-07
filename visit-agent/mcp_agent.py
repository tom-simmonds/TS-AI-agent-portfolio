"""
Site visit agent - tools served over MCP.

Identical reasoning loop to visit_agent.py. The only difference is where the
tools come from: instead of being hardcoded, they are discovered at runtime
from an MCP server.

Run:  pip install ollama fastmcp requests
      python mcp_agent.py V-2001
      python mcp_agent.py V-2002
"""

import asyncio
import json
import sys
from pathlib import Path

import ollama
from fastmcp import Client

MODEL = "qwen3:8b"
MAX_ITERATIONS = 12
SERVER = "visit_tools_server.py"


SYSTEM_PROMPT = """You are a scheduling assistant for a field engineering team.
You decide whether a booked site visit should go ahead.

Work through it using the tools available to you:
1. Fetch the visit details.
2. Get coordinates for the site postcode.
3. Check whether the visit date is a bank holiday.
4. Get the weather forecast using those coordinates.
5. Record a GO or RESCHEDULE decision with a clear reason.

Guidance:
- Work at height is unsafe above 40 km/h wind.
- Heavy rain (over 10mm) makes outdoor work impractical.
- If recording the decision returns violations, change the decision and call it again.
- Never guess a coordinate, a forecast or a holiday. Always use the tools.
- If a tool returns an error, the action did NOT happen. Never state or imply that
  a decision was recorded unless the tool returned recorded=true. If you cannot
  record it, say so plainly and explain what failed.
- Weather rules apply only to ourdoors work; check the job description.

Finish with a short plain-text summary for the scheduling team.

/no_think"""


def mcp_tools_to_ollama(mcp_tools) -> list:
    """Translate MCP tool definitions into the schema Ollama expects.

    This is the whole adapter. MCP already gives us a name, a description and
    a JSON Schema for the arguments, which is exactly what Ollama wants.
    """
    tools = []
    for tool in mcp_tools:
        # MCP SDK v2 renamed inputSchema -> input_schema. Support both.
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schema,
            },
        })
    return tools


def extract_text(result) -> str:
    """Pull plain text out of an MCP tool result, across fastmcp versions."""
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = [getattr(block, "text", None) for block in content]
        parts = [p for p in parts if p]
        if parts:
            return "\n".join(parts)
    data = getattr(result, "data", None)
    if data is not None:
        return json.dumps(data)
    return str(result)


async def run_agent(request: str) -> str:
    client = Client(Path(SERVER))

    async with client:
        mcp_tools = await client.list_tools()

        print(f"\nDiscovered {len(mcp_tools)} tools from the MCP server:")
        for tool in mcp_tools:
            first_line = (tool.description or "").strip().split("\n")[0]
            print(f"  - {tool.name}: {first_line}")

        tools = mcp_tools_to_ollama(mcp_tools)
        tool_names = {t.name for t in mcp_tools}

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request},
        ]

        for step in range(1, MAX_ITERATIONS + 1):
            print(f"\n--- Iteration {step}/{MAX_ITERATIONS} " + "-" * 40)

            response = ollama.chat(model=MODEL, messages=messages, tools=tools)
            message = response["message"]
            messages.append(message)

            tool_calls = message.get("tool_calls")
            content = (message.get("content") or "").strip()

            if not tool_calls:
                if content:
                    return content
                print("  (empty response - nudging)")
                messages.append({
                    "role": "user",
                    "content": "Continue. Call the next tool, or give your final summary.",
                })
                continue

            for call in tool_calls:
                name = call["function"]["name"]
                args = call["function"]["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)

                print(f"  MCP CALL : {name}({', '.join(f'{k}={v}' for k, v in args.items())})")

                if name not in tool_names:
                    output = json.dumps({"error": f"Unknown tool '{name}'"})
                else:
                    try:
                        result = await client.call_tool(name, args)
                        output = extract_text(result)
                    except Exception as exc:
                        output = json.dumps({"error": f"{type(exc).__name__}: {exc}"})

                print(f"  RESULT   : {output[:250]}{'...' if len(output) > 250 else ''}")
                messages.append({"role": "tool", "name": name, "content": output})

        return f"STOPPED: hit the {MAX_ITERATIONS}-iteration limit."


def main() -> None:
    visit_id = sys.argv[1] if len(sys.argv) > 1 else "V-2001"
    request = f"Should visit {visit_id} go ahead? Check everything and record the decision."

    print(f"MODEL   : {MODEL}")
    print(f"SERVER  : {SERVER} (MCP over stdio)")
    print(f"REQUEST : {request}")

    try:
        answer = asyncio.run(run_agent(request))
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Check: is Ollama running, and is visit_tools_server.py in this folder?",
              file=sys.stderr)
        raise SystemExit(1)

    print("\n" + "=" * 60)
    print("FINAL RESPONSE")
    print("=" * 60)
    print(answer)


if __name__ == "__main__":
    main()
