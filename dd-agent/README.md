# dd-agent — Supplier Due-Diligence Agent

A local agent that takes a company name, checks it against the real, live
Companies House public data API, and returns a structured due-diligence
report a human can act on. Built against `qwen3:8b` running locally via
Ollama, no agent framework — the harness, tool-calling loop, and output
validation are all hand-written.

## Run it

```
pip install -r requirements.txt
cp .env.example .env      # fill in CH_API_KEY — see below
python dd_agent.py "Tesco"
python dd_agent.py "Waitrose"
```

Get a free Companies House API key at
https://developer.company-information.service.gov.uk/ (HTTP Basic auth,
the key as the username, blank password).

## What it does

Given a company name, the agent decides for itself which of 7 real tools to
call and in what order (`search_companies`, `get_company_profile`,
`get_persons_with_significant_control`, `get_filing_history`,
`get_charges`, `get_insolvency_history`, plus a name-disambiguation step) —
the sequence isn't hardcoded. It returns one JSON report:
`company_number`, `match_confidence`, `status`, `filing_compliance`,
`red_flags`, a plain-English `summary`, `risk_rating`, and
`escalate_for_human_review` / `escalation_reason`.

Deliberately, the agent never writes a state-changing action anywhere — no
approval, no ticket, no transaction. A due-diligence check should inform a
human decision, not make one.

## Files

| File                 | Role                                                                                            |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| `dd_agent.py`        | Entry point — wires the harness, tools, and prompts together                                    |
| `agent_harness.py`   | Domain-agnostic agent loop: iteration cap + wall-clock timeout, reusable by any agent           |
| `companies_house.py` | The 7 real tool functions against the live Companies House API                                  |
| `prompts.py`         | System prompt + `validate_dd_report()`, the one deterministic, LLM-independent governance check |
| `memory.py`          | Episodic run log (`log_run` / `recall`) — write-only, not yet fed back into the agent           |

## Governance: `validate_dd_report()`

Not a tool the agent calls — a plain Python check on the model's _final
answer_, in `prompts.py`. It rejects the response if the JSON doesn't match
the required schema, and separately rejects it if the model names a
specific `company_number` without having actually called
`get_company_profile`, `get_persons_with_significant_control`, and
`get_filing_history` first. Either failure sends the model back around the
loop with a specific error instead of letting a bad or unverified answer
through.
