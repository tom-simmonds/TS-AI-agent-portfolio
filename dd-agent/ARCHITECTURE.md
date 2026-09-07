# Supplier Due-Diligence Agent — Architecture Mapping

A local agent that takes a company name, investigates it against the real
Companies House register, and returns a structured due-diligence report.
Built as a learning project to work through an agentic pattern (LLM
reasoning core + tool-calling harness + enforced output) against a real,
non-trivial business API — not as production compliance tooling.

**Stack:** Python, Ollama running `qwen3:8b` locally, the live Companies
House REST API (`api.company-information.service.gov.uk`).

**Run it:** `python dd_agent.py "<company name>"` from the project root
(Ollama must be running locally; `.env` needs a **Live**-environment
Companies House REST API key as `CH_API_KEY`).

**Files:** `agent_harness.py` (the loop), `companies_house.py` (the
tools), `prompts.py` (system prompt + output schema + validation),
`dd_agent.py` (entry point), `memory.py` (episodic log).

## Coverage at a glance

| Box | Status | In one line |
|---|---|---|
| 1. Business/User App | Partial | CLI only — `python dd_agent.py "<name>"`, no frontend or API |
| 2. Prompt Engineering | Built | Role, 6-step process, guardrails, output schema, one worked example |
| 3. Agent Harness | Built | Domain-agnostic loop, iteration cap + wall-clock timeout, clean error states |
| 4. Reasoning Core | Built | `qwen3:8b` via Ollama, genuinely decides tool order/necessity at runtime |
| 5a. Memory | Partial | Short-term (message window) + a simple episodic log; no semantic recall, not yet fed back to the agent |
| 5b. Tools | Built | 7 tools against the real, live Companies House API |
| 5c. MCP | Not built | Plain Python tool dict instead — reasoning below |
| 6. Response/Action | Built | Structured JSON report + human-review escalation flag |
| 7. Governance & Compliance | Partial | Two real deterministic checks (required-tool enforcement + a hard "dissolved can't be low risk" business rule); everything else documented, not built |
| 8. Observability | Minimal | Console trace + iteration/timing in the report; no persistent logs or metrics |
| 9. Token Usage & Cost | Not built | Explained below — one cheap first step identified, not taken |

---

## 1. Business/User App

There's no frontend or API. The "business request" is a company name
passed as a command-line argument — `python dd_agent.py "Tesco"` — and
the response is JSON printed to the console. Wiring this to an actual
interface (even a basic web form or a Slack command) is future work; the
CLI was enough to develop and test the agent itself.

## 2. Prompt Engineering

`prompts.py`'s `SYSTEM_PROMPT` assigns the role (a due-diligence
analyst), lays out a numbered process — search first and confirm the
match, then profile, PSC, and filing history as standard, charges and
insolvency only when the profile flags say there's something to check,
officers only if needed — and states guardrails: never invent a fact not
returned by a tool, say so plainly when a match is ambiguous rather than
guessing, and this produces a factual summary, not a recommendation. The
output shape is given as a literal JSON schema plus one fully worked
example.

Same principle as the scheduling agent's system prompt: it guides the
model, but nothing here is trusted to hold on its own. `validate_dd_report()`
deterministically re-checks every answer against the schema (required
fields, types, allowed enum values) *and*, new in this project, confirms
the tools the process actually requires were called before a claimed
company match is accepted — this is what caught the model shortcutting
straight to a verdict after only a search call, in a live run during
development (see box 7).

## 3. Agent Harness

`agent_harness.py` is intentionally domain-agnostic — it has no
Companies House logic in it at all, only `run_agent(user_request,
system_prompt, tools, available_tools, ...)`. It enforces a hard
iteration cap (`max_iterations`) and, beyond what the earlier scheduling
agent's harness did, a wall-clock timeout (`timeout`) so a hung model
call can't hang the process indefinitely. Every model call is wrapped so
a connection failure comes back as a clean `status: "error"` instead of
an unhandled crash — this isn't theoretical, it's what surfaced a real
GPU-memory error cleanly during testing instead of a raw traceback.

Same file also now supports an optional `validate_answer` callback: a
final answer only counts as `"complete"` once it passes validation,
otherwise the harness feeds the validator's error back to the model and
keeps looping within the same bounds. That's how box 2's schema and box
7's process check get enforced without either living inside this
generic file.

## 4. Reasoning Core

`qwen3:8b`, called through Ollama's `/api/chat`, same model as the
scheduling agent. The tool-call sequence isn't hardcoded — the model
decides, from the tool descriptions and the process rules in the system
prompt, what to call and in what order. This was directly observable in
testing: on a company where the profile showed `has_charges: false` and
`has_insolvency_history: false`, the model correctly skipped
`get_charges` and `get_insolvency` rather than calling them "just in
case." It's also where the model's limits showed up — on one run it
tried to finalise a verdict after a single search call, skipping the
profile/PSC/filing-history checks the prompt asked for. A small local
model doesn't reliably follow multi-step "always do X, Y, Z" instructions
end to end, which is exactly why box 7's enforcement exists rather than
relying on box 2 alone.

## 5a. Memory

Short-term memory is the message window inside `run_agent()`, same as
before — gone the moment the process exits. `memory.py` adds a real, if
deliberately small, long-term layer: `log_run()` appends every completed
or failed check to `runs.jsonl` (one JSON object per line), and
`recall(company_name)` looks past runs up by name. No database, no
embeddings, no semantic search — just "have we checked this company
before, and what did we find." It's also currently write-only in the
sense that matters most: the agent doesn't consult its own history when
running a fresh check, a person has to call `recall()` themselves.
Closing that loop — the agent noting "we checked this three weeks ago and
found X, here's what's changed" — is a concrete next step, not a vague
one. There's no user/customer-profile sub-box in use here; this tool has
no end-user identity to track, it's a stateless business query.

## 5b. Tools

Seven tools in `companies_house.py`, all against the real, live
Companies House REST API, not a sandbox or mock: `search_companies`,
`get_company_profile`, `get_officers`, `get_persons_with_significant_control`,
`get_filing_history`, `get_charges`, `get_insolvency`. Genuine HTTP,
genuine Basic-auth key handling (including the Live-vs-Test environment
mismatch that actually blocked development for a while), 404s treated as
data ("no PSCs on record") rather than errors where that's what they
mean, and 429 rate-limit handling. This is the project's largest single
piece of real integration work and its main point of contrast with the
scheduling agent — more endpoints, a real production-scale public API
rather than three small free ones.

## 5c. MCP

Not implemented here, and worth being specific about why rather than
leaving it as a gap: the scheduling agent proved the pattern works — an
MCP server exposing tools that any client can discover and call at
runtime, decoupling tool implementation from agent reasoning. For this
project, the tools are plain Python functions registered directly into
an `available_tools` dict that gets passed into the harness. With one
agent and one tool provider, MCP's actual payoff — multiple
agents/clients sharing the same tool server — doesn't have anywhere to
land yet; it would be protocol overhead with no second consumer. If a
second agent needed Companies House data, or these tools needed to be
reused outside this one script, wrapping `companies_house.py` as an MCP
server is the natural next step, and it's a known pattern rather than an
unknown one at this point.

## 6. Response/Action

The final JSON report *is* the response — `company_number`,
`match_confidence`, `status`, `filing_compliance`, `red_flags`, a
plain-English `summary`, `risk_rating`, and `escalate_for_human_review` /
`escalation_reason`. Unlike the scheduling agent's `record_decision`,
nothing here writes a state-changing action anywhere — no ticket, no
approval, no transaction. That's a deliberate choice for this domain: a
due-diligence check should inform a human decision, not make one. The
escalation flag is the human-in-the-loop equivalent of the diagram's
"human approval for high-risk actions," without an actual downstream
action to gate.

## 7. Governance & Compliance

Two real, deterministic, LLM-independent checks live in
`validate_dd_report()` in `prompts.py`, both sending the model back
around the loop with a specific error rather than letting a bad answer
through — the same shape of idea as `record_decision` refusing an
invalid decision in the scheduling agent:

- **Process enforcement**: rejects an answer that names a specific
  `company_number` without having actually called `get_company_profile`,
  `get_persons_with_significant_control`, and `get_filing_history` first.
  Caught a real case in testing where the model tried to conclude on a
  search result alone.
- **A hard business rule**: a company whose status is dissolved, in
  liquidation, administration, receivership, insolvency proceedings, or
  converted/closed can never be rated `risk_rating: "low"`, and must have
  `escalate_for_human_review: true` — checked directly against the
  company's actual status from `get_company_profile`, not left to the
  model's judgement. This is the direct counterpart to the scheduling
  agent's weekend/bank-holiday check in `record_decision`: a rule that
  was part of this project's original plan from the start, and the
  clearest point of comparison between the two projects' box 7.

Everything else in this box is deliberately not built: no RBAC or
least-privilege tooling (there's one API key with full read access), no
PII masking beyond what the Companies House API already does itself
(officer dates of birth only ever include month/year, not day — that's
their design, not this project's), no immutable audit trail, and no
sector-specific regulatory checklist (KYC/AML, PCI-DSS, SOX). Those are
platform-team-scale concerns for a real deployment, not something to
fake with a local script for a one-person learning project — building a
convincing-looking audit log here would be less honest than naming the
gap.

## 8. Observability

What exists: a console trace of every `CALLING:`/`RESULT:` step, the
iteration count, and elapsed seconds, all included in the final report's
`_meta` field. This was genuinely useful during development — it's how
two real bugs got diagnosed live (a GPU out-of-memory error, and the
model skipping required tool calls). What doesn't exist: persistent
structured logs, a metrics dashboard, latency percentiles, or any
drift/hallucination detection. Same honest assessment as the scheduling
agent: basic, console-only, not production level.

## 9. Token Usage & Cost

Not implemented. Worth noting precisely what "not implemented" means
here, though: Ollama's `/api/chat` response already includes real token
counts (`prompt_eval_count`, `eval_count`) and timing data that this
project isn't currently reading — that's a genuinely cheap first step
(a few lines, not a system), just not one that's been taken. Because
inference is local and free, the natural version of this box for now
would be a compute/time budget, not a £/$ dashboard — real cost tracking
only becomes a live concern if a hosted model replaces Ollama.

---

## Honest summary

Boxes 1 through 6 are real and working — tested live against Tesco PLC
and Waitrose Limited end to end, including catching and self-correcting
genuine failure modes mid-run. Box 7 has two real mechanisms — a process
check and a hard business rule — not a framework. Boxes 8 and 9 are
acknowledged, not built. That split is the point: a solo learning
project can legitimately go deep on the agent itself while being
straightforward about which parts of "production-ready" it was never
trying to be.
