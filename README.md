# Agent Portfolio — Two Agents, so far

Two local agents built
both against `qwen3:8b` running locally via Ollama, written with no
agent framework, and mapped side by side against the same nine-box
single-agent architecture diagram.

## The agents

- **[`visit-agent/`](visit-agent/)** — decides whether a field engineer's
  booked site visit should go ahead, against three real public APIs
  (postcodes.io, gov.uk bank holidays, open-meteo). Built first. Two
  implementations included: tools hardcoded, and tools served over MCP.
- **[`dd-agent/`](dd-agent/)** — takes a company name and returns a
  structured supplier due-diligence report, against the real, live
  Companies House public data API. Built second, after `visit-agent`'s
  gaps were known.

## Quick start

Each agent is self-contained — see its own README for exact run
instructions and dependencies:

```
cd dd-agent && pip install -r requirements.txt && cp .env.example .env
cd visit-agent && pip install -r requirements.txt
```

Both need Ollama running locally with `qwen3:8b` pulled
(`ollama pull qwen3:8b`).
