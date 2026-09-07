# visit-agent — Site Visit Scheduling Agent

A local agent that decides whether a field engineer's booked site visit
should go ahead, or be rescheduled. Built against `qwen3:8b` running
locally via Ollama, no framework. Two implementations of the same agent are
included, to compare hardcoded tools against tools served over MCP.

## Run it

```
pip install -r requirements.txt

# hardcoded tools
python visit_agent.py V-2001

# same agent, tools discovered at runtime over MCP
python mcp_agent.py V-2001
```

## What it does

Calls three real, free public APIs, forcing genuine tool chaining (it needs
coordinates before it can request a forecast):

- **postcodes.io** — UK postcode -> coordinates and region
- **gov.uk** — official bank holiday calendar
- **open-meteo.com** — weather forecast

Plus one deterministic tool, `record_decision`, that enforces the actual
business rules in plain Python (no visits on weekends/bank holidays,
reschedule above 40km/h wind or 10mm rain) — the model cannot approve a
visit that breaks policy, whatever it reasons its way into. The final
decision (`visit_id`, `decision`, `reason`, `recorded_at`) is written to
`visit_decisions.json` — this agent does take a real, state-changing
action, unlike the due-diligence agent in `../dd-agent/`.

## Files

| File | Role |
|---|---|
| `visit_agent.py` | The agent with tools hardcoded directly into the loop |
| `mcp_agent.py` | Identical reasoning loop — tools instead discovered at runtime from an MCP server via `client.list_tools()` |
| `visit_tools_server.py` | The MCP tool server `mcp_agent.py` talks to (FastMCP over stdio) |
| `visit_decisions.json` | Example output — decisions recorded across test runs |

## A known, unfixed bug

The "weather rules apply only to outdoor work" fix exists in
`mcp_agent.py` but was never backported to `visit_agent.py` — found once,
fixed in one implementation, left in the other. Left as-is deliberately, as
an honest artifact of iterative development rather than tidied away. See
`../docs/two-agents-nine-boxes.pptx` for the full comparison against the
due-diligence agent, box by box.
