"""
Site Visit Planner - a single agent that decides whether a scheduled
engineer visit should go ahead.

Calls three real public APIs (no keys required):
  postcodes.io      - UK postcode -> coordinates and region
  gov.uk            - official bank holiday calendar
  open-meteo.com    - weather forecast

Plus one deterministic tool that enforces the business rules.

Run:  pip install ollama requests
      python visit_agent.py
"""

import json
import sys
from datetime import date, timedelta

import ollama
import requests

MODEL = "qwen3:8b"
MAX_ITERATIONS = 10
TIMEOUT = 15



# Mock scheduling system.
# Dates are relative to today


def _next_saturday() -> str:
    today = date.today()
    return (today + timedelta(days=(5 - today.weekday()) % 7 or 7)).isoformat()


VISITS = {
    "V-2001": {
        "visit_id": "V-2001",
        "customer": "Norton Manufacturing Ltd",
        "postcode": "CV1 2TT",
        "date": (date.today() + timedelta(days=4)).isoformat(),
        "job": "Rooftop aerial installation (work at height)",
    },
    "V-2002": {
        "visit_id": "V-2002",
        "customer": "Bexley Logistics",
        "postcode": "M1 3BE",
        "date": _next_saturday(),
        "job": "Loading bay door replacement",
    },
}


# TOOL 1: internal lookup

def get_visit(visit_id: str) -> dict:
    """Look up a scheduled visit by its ID."""
    visit = VISITS.get(visit_id.upper())
    if visit is None:
        return {"error": f"No visit '{visit_id}'", "available": list(VISITS)}
    return visit


# TOOL 2: postcodes.io (real API)

def lookup_postcode(postcode: str) -> dict:
    """Convert a UK postcode to coordinates and region."""
    try:
        r = requests.get(
            f"https://api.postcodes.io/postcodes/{postcode.replace(' ', '')}",
            timeout=TIMEOUT,
        )
        if r.status_code == 404:
            return {"error": f"Postcode '{postcode}' not found."}
        r.raise_for_status()
        result = r.json()["result"]
        return {
            "postcode": result["postcode"],
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "region": result.get("region"),
            "country": result.get("country"),
        }
    except requests.RequestException as exc:
        return {"error": f"Postcode lookup failed: {exc}"}


# TOOL 3: gov.uk bank holidays (real API)

def check_bank_holiday(check_date: str, country: str = "England") -> dict:
    """Check whether a date is an official UK bank holiday."""
    division = {
        "England": "england-and-wales",
        "Wales": "england-and-wales",
        "Scotland": "scotland",
        "Northern Ireland": "northern-ireland",
    }.get(country, "england-and-wales")

    try:
        r = requests.get("https://www.gov.uk/bank-holidays.json", timeout=TIMEOUT)
        r.raise_for_status()
        events = r.json()[division]["events"]
        for event in events:
            if event["date"] == check_date:
                return {"date": check_date, "is_bank_holiday": True, "name": event["title"]}
        return {"date": check_date, "is_bank_holiday": False}
    except requests.RequestException as exc:
        return {"error": f"Bank holiday lookup failed: {exc}"}


# TOOL 4: open-meteo (real API)

def get_forecast(latitude: float, longitude: float, forecast_date: str) -> dict:
    """Get the weather forecast for a location on a specific date."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": "temperature_2m_max,precipitation_sum,wind_speed_10m_max",
                "start_date": forecast_date,
                "end_date": forecast_date,
                "timezone": "Europe/London",
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        daily = r.json().get("daily", {})
        if not daily.get("time"):
            return {"error": f"No forecast available for {forecast_date} (max ~16 days ahead)."}
        return {
            "date": forecast_date,
            "max_temp_c": daily["temperature_2m_max"][0],
            "precipitation_mm": daily["precipitation_sum"][0],
            "max_wind_kmh": daily["wind_speed_10m_max"][0],
        }
    except requests.RequestException as exc:
        return {"error": f"Forecast lookup failed: {exc}"}


# TOOL 5: record the decision (deterministic gate)

def record_decision(visit_id: str, decision: str, reason: str) -> dict:
    """
    Record a GO or RESCHEDULE decision.

    This is the guardrail. It re-checks the business rules in plain Python
    before accepting anything, so the model cannot approve a visit that
    breaks policy - whatever it decided or claimed.
    """
    decision = decision.upper().strip()
    if decision not in {"GO", "RESCHEDULE"}:
        return {"recorded": False, "error": "decision must be 'GO' or 'RESCHEDULE'."}
    if len(reason.strip()) < 20:
        return {"recorded": False, "error": "reason must be at least 20 characters."}

    visit = VISITS.get(visit_id.upper())
    if visit is None:
        return {"recorded": False, "error": f"No visit '{visit_id}'."}

    violations = []
    visit_date = date.fromisoformat(visit["date"])

    if visit_date.weekday() >= 5:
        violations.append(f"{visit['date']} is a weekend. Policy: no non-emergency visits.")

    holiday = check_bank_holiday(visit["date"])
    if holiday.get("is_bank_holiday"):
        violations.append(f"{visit['date']} is a bank holiday ({holiday['name']}).")

    if violations and decision == "GO":
        return {
            "recorded": False,
            "error": "Policy prevents a GO decision for this visit.",
            "violations": violations,
            "required_decision": "RESCHEDULE",
        }

    with open("visit_decisions.json", "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "visit_id": visit_id.upper(),
            "decision": decision,
            "reason": reason,
            "recorded_at": date.today().isoformat(),
        }) + "\n")

    return {"recorded": True, "visit_id": visit_id.upper(), "decision": decision}


# ---------------------------------------------------------------------------

TOOLS = [
    {"type": "function", "function": {
        "name": "get_visit",
        "description": "Look up a scheduled site visit by ID. Call this first. Returns customer, postcode, date and job type.",
        "parameters": {"type": "object", "properties": {
            "visit_id": {"type": "string", "description": "Visit ID, e.g. V-2001"}},
            "required": ["visit_id"]}}},
    {"type": "function", "function": {
        "name": "lookup_postcode",
        "description": "Convert a UK postcode into latitude, longitude and region. You need the coordinates before you can get a weather forecast.",
        "parameters": {"type": "object", "properties": {
            "postcode": {"type": "string", "description": "UK postcode, e.g. CV1 2TT"}},
            "required": ["postcode"]}}},
    {"type": "function", "function": {
        "name": "check_bank_holiday",
        "description": "Check whether a date is an official UK bank holiday, using the gov.uk calendar.",
        "parameters": {"type": "object", "properties": {
            "check_date": {"type": "string", "description": "Date as YYYY-MM-DD"},
            "country": {"type": "string", "description": "England, Wales, Scotland or Northern Ireland"}},
            "required": ["check_date"]}}},
    {"type": "function", "function": {
        "name": "get_forecast",
        "description": "Get the weather forecast for a location on a date. Requires latitude and longitude from lookup_postcode.",
        "parameters": {"type": "object", "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "forecast_date": {"type": "string", "description": "Date as YYYY-MM-DD"}},
            "required": ["latitude", "longitude", "forecast_date"]}}},
    {"type": "function", "function": {
        "name": "record_decision",
        "description": "Record the final GO or RESCHEDULE decision. If this returns violations, you must change the decision to RESCHEDULE and call it again.",
        "parameters": {"type": "object", "properties": {
            "visit_id": {"type": "string"},
            "decision": {"type": "string", "description": "GO or RESCHEDULE"},
            "reason": {"type": "string", "description": "At least 20 characters explaining the decision"}},
            "required": ["visit_id", "decision", "reason"]}}},
]

DISPATCH = {
    "get_visit": get_visit,
    "lookup_postcode": lookup_postcode,
    "check_bank_holiday": check_bank_holiday,
    "get_forecast": get_forecast,
    "record_decision": record_decision,
}


SYSTEM_PROMPT = """You are a scheduling assistant for a field engineering team.
You decide whether a booked site visit should go ahead.

Work it out step by step using the tools:
1. get_visit - fetch the visit details.
2. lookup_postcode - get coordinates for the site.
3. check_bank_holiday - check the visit date.
4. get_forecast - get the weather using those coordinates.
5. record_decision - record GO or RESCHEDULE with a clear reason.

Guidance:
- Work at height is unsafe above 40 km/h wind.
- Heavy rain (over 10mm) makes outdoor work impractical.
- If record_decision returns violations, change your decision and call it again.
- Never guess a coordinate, a forecast or a holiday. Always use the tools.

Finish with a short plain-text summary for the scheduling team.

/no_think"""


def run_agent(request: str, max_iterations: int = MAX_ITERATIONS) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request},
    ]

    for step in range(1, max_iterations + 1):
        print(f"\n--- Iteration {step}/{max_iterations} " + "-" * 40)

        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
        message = response["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls")
        content = (message.get("content") or "").strip()

        if not tool_calls:
            if content:
                return content
            print("  (empty response - nudging)")
            messages.append({"role": "user",
                             "content": "Continue. Call the next tool, or give your final summary."})
            continue

        for call in tool_calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            if isinstance(args, str):
                args = json.loads(args)

            print(f"  TOOL CALL : {name}({', '.join(f'{k}={v}' for k, v in args.items())})")

            func = DISPATCH.get(name)
            if func is None:
                result = {"error": f"Unknown tool '{name}'"}
            else:
                try:
                    result = func(**args)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}

            summary = json.dumps(result)
            print(f"  RESULT    : {summary[:250]}{'...' if len(summary) > 250 else ''}")
            messages.append({"role": "tool", "name": name, "content": summary})

    return f"STOPPED: hit the {max_iterations}-iteration limit."


def main() -> None:
    visit_id = sys.argv[1] if len(sys.argv) > 1 else "V-2001"
    request = f"Should visit {visit_id} go ahead? Check everything and record the decision."

    print(f"MODEL   : {MODEL}")
    print(f"REQUEST : {request}")

    try:
        answer = run_agent(request)
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Is Ollama running? Try: ollama list", file=sys.stderr)
        raise SystemExit(1)

    print("\n" + "=" * 60)
    print("FINAL RESPONSE")
    print("=" * 60)
    print(answer)


if __name__ == "__main__":
    main()
