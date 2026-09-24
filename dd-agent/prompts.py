"""
prompts.py - the prompt engineering layer : system prompt (role/rules/tone), the output schema the final
answer must match, a worked few-shot example, and safety/guardrail
instructions. All bundled into one SYSTEM_PROMPT because that's what a
single non-fine-tuned local model responds to reliably - splitting these
into separate "system prompt" vs "task prompt" strings the way the
diagram draws them wouldn't change what's actually sent to Ollama, since
they'd just get concatenated back together anyway.

The output schema is enforced, not just requested: validate_dd_report()
is passed into agent_harness.run_agent() as validate_answer, so a
response that doesn't match the schema gets bounced back to the model
instead of accepted as-is.
"""

import json

SYSTEM_PROMPT = """You are a supplier due-diligence analyst. You investigate a UK company using the real Companies House register and produce a factual, structured report. You do not give legal, financial, or compliance advice, and you never state anything as fact that isn't backed by what a tool actually returned.

## Process
1. Call search_companies with the name you were given. If there are multiple plausible matches, prefer an exact name match with company_status "active"; if it's genuinely ambiguous, say so in the report rather than guessing.
2. Once you have a company_number, call get_company_profile.
3. Call get_persons_with_significant_control and get_filing_history - these are standard for every check.
4. Only call get_charges if the profile showed has_charges: true.
5. Only call get_insolvency if the profile showed has_insolvency_history: true.
6. Call get_officers if you need to know who runs the company, or if the profile/PSC data doesn't already answer that.
Don't call a tool twice with the same arguments, and don't call get_charges or get_insolvency "just in case" when the profile flag says false - that wastes a call for no new information.

## Guardrails
- Never invent a company number, name, date, or fact. Everything in your report must trace back to a tool result.
- If search_companies finds no match, or you're not confident which result is the right one, say so plainly - do not pick one and pretend it's certain.
- If a tool returns "no data" for something (e.g. no PSCs, no charges), report that as a fact ("none on record"), not as an error or an unknown.
- This is a factual summary, not a decision. Never say a company is "safe to use" or "should be avoided" - describe what the data shows and let the reader decide.
- Flag anything a human should look at before proceeding: dissolved/liquidation/administration status, insolvency history, overdue filings, no confident name match, or anything else that doesn't look right.
- Hard rule, enforced in code, not just requested here: a company that is dissolved, in liquidation, administration, receivership, insolvency proceedings, or converted/closed can NEVER be given risk_rating "low", and must have escalate_for_human_review set to true.

## Final answer
When you've gathered what you need, respond with ONLY a single JSON object - no markdown fences, no other text before or after it - in exactly this shape:

{
  "company_queried": "<the name you were asked to check>",
  "company_number": "<CH company number, or null if no confident match>",
  "company_name_matched": "<the exact registered name, or null>",
  "match_confidence": "high | medium | low | no_match",
  "status": "<company_status from the profile, or 'unknown'>",
  "incorporated_on": "<YYYY-MM-DD, or null>",
  "filing_compliance": "up_to_date | overdue | unknown",
  "red_flags": ["<short factual flag>", "..."],
  "summary": "<2-4 plain-English sentences of what you found>",
  "risk_rating": "low | medium | high",
  "confidence": "high | medium | low",
  "escalate_for_human_review": true | false,
  "escalation_reason": "<why, or null if escalate_for_human_review is false>"
}

Example, for a company with no notable issues:
{
  "company_queried": "Acme Supplies",
  "company_number": "01234567",
  "company_name_matched": "ACME SUPPLIES LIMITED",
  "match_confidence": "high",
  "status": "active",
  "incorporated_on": "2011-03-14",
  "filing_compliance": "up_to_date",
  "red_flags": [],
  "summary": "Acme Supplies Limited (01234567) is an active company incorporated in 2011. Filings are up to date, one PSC holds 75-100% of shares, and there are no outstanding charges or insolvency history.",
  "risk_rating": "low",
  "confidence": "high",
  "escalate_for_human_review": false,
  "escalation_reason": null
}

Set escalate_for_human_review to true whenever risk_rating is "high", match_confidence is "low" or "no_match", or you found anything (insolvency, liquidation, dissolved status, significant overdue filings) that a person should look at before this supplier is used."""


# --- Output schema

REQUIRED_FIELDS = {
    "company_queried": str,
    "company_number": (str, type(None)),
    "company_name_matched": (str, type(None)),
    "match_confidence": str,
    "status": str,
    "incorporated_on": (str, type(None)),
    "filing_compliance": str,
    "red_flags": list,
    "summary": str,
    "risk_rating": str,
    "confidence": str,
    "escalate_for_human_review": bool,
    "escalation_reason": (str, type(None)),
}

ALLOWED_VALUES = {
    "match_confidence": {"high", "medium", "low", "no_match"},
    "filing_compliance": {"up_to_date", "overdue", "unknown"},
    "risk_rating": {"low", "medium", "high"},
    "confidence": {"high", "medium", "low"},
}

# Statuses that mean the company isn't a going concern - mirrors the
# scheduling agent's weekend/bank-holiday check: a hard rule enforced in
# code, not a prompt instruction the model could ignore or talk past.
NOT_LOW_RISK_STATUSES = {
    "dissolved",
    "liquidation",
    "administration",
    "receivership",
    "insolvency-proceedings",
    "converted-closed",
}


def parse_json_answer(content):
    """Strip accidental markdown code fences and parse as JSON.
    Raises json.JSONDecodeError on failure - callers decide what to do with that."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


# If the report names a specific company_number, these tools must have
# actually been called before the answer is accepted - a schema-valid
# report that skipped them (e.g. declared a match but never checked PSC
# or filing history) gets bounced back just like a malformed one.
REQUIRED_TOOLS_FOR_A_NAMED_COMPANY = {
    "get_company_profile",
    "get_persons_with_significant_control",
    "get_filing_history",
}


def validate_dd_report(content, tools_called=None):
    """validate_answer callback for agent_harness.run_agent(). Returns
    (True, None) if content is a JSON object matching REQUIRED_FIELDS and
    ALLOWED_VALUES *and* (when it names a company) the minimum tool calls
    were actually made, otherwise (False, <error message for the model>).

    tools_called is the list of tool names invoked so far this run, passed
    in by the harness - defaults to None/[] so this still works if called
    directly (e.g. in a quick test) without a real run behind it."""
    tools_called = tools_called or []

    try:
        data = parse_json_answer(content)
    except json.JSONDecodeError as exc:
        return False, f"Your response was not valid JSON ({exc}). Respond with ONLY the JSON object, no other text."

    if not isinstance(data, dict):
        return False, "Your response must be a single JSON object, not a list or a bare value."

    missing = [key for key in REQUIRED_FIELDS if key not in data]
    if missing:
        return False, f"Your JSON is missing required field(s): {', '.join(missing)}."

    wrong_type = [
        key for key, expected_type in REQUIRED_FIELDS.items()
        if key in data and not isinstance(data[key], expected_type)
    ]
    if wrong_type:
        return False, f"These fields have the wrong type: {', '.join(wrong_type)}."

    bad_values = [
        f'{key} must be one of {sorted(allowed)}, got {data.get(key)!r}'
        for key, allowed in ALLOWED_VALUES.items()
        if data.get(key) not in allowed
    ]
    if bad_values:
        return False, " ".join(bad_values)

    if data.get("company_number"):
        missing_calls = REQUIRED_TOOLS_FOR_A_NAMED_COMPANY - set(tools_called)
        if missing_calls:
            return False, (
                f"You named company_number {data['company_number']!r} but haven't called "
                f"{', '.join(sorted(missing_calls))} yet. Call them for this company before "
                f"giving your final answer - don't conclude on a search result alone."
            )

    # Hard business rule, same shape as the scheduling agent's record_decision
    # policy gate: this is not a request in the prompt, it's a check the model
    # cannot talk its way past. A company that isn't a going concern can never
    # be rated low risk, whatever the summary says.
    if data.get("status") in NOT_LOW_RISK_STATUSES:
        if data.get("risk_rating") == "low":
            return False, (
                f"status is {data['status']!r} but risk_rating is 'low' - a company that "
                f"isn't a going concern can never be rated low risk. Set risk_rating to "
                f"'medium' or 'high', set escalate_for_human_review to true, and try again."
            )
        if not data.get("escalate_for_human_review"):
            return False, (
                f"status is {data['status']!r} - this must be escalated for human review "
                f"(escalate_for_human_review: true), whatever the risk_rating. Try again."
            )

    return True, None
