"""
MCP tool server for the site visit agent.

Exposes the same tools as visit_agent.py, but over the Model Context Protocol
instead of being hardcoded into the agent.

Run directly to test:   python visit_tools_server.py
Normally it is launched automatically by mcp_agent.py over stdio.
"""

import json
from datetime import date, timedelta

import requests
from fastmcp import FastMCP

mcp = FastMCP("visit-tools")

TIMEOUT = 15


def _next_saturday() -> str:
    today = date.today()
    return (today + timedelta(days=(5 - today.weekday()) % 7 or 7)).isoformat()

def _next_weekday(days_ahead: int = 3) -> str:
    d = date.today() + timedelta(days=days_ahead)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


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
        "date": _next_weekday(),
        "job": "Loading bay door replacement",
    },

        "V-2003": {
        "visit_id": "V-2003",
        "customer": "Ashfield Data Centre",
        "postcode": "B4 7DA",
        "date": _next_weekday(),
        "job": "Server room UPS replacement (indoor)",
    },
}


@mcp.tool
def get_visit(visit_id: str) -> dict:
    """Look up a scheduled site visit by ID. Call this first.
    Returns the customer, postcode, date and job type."""
    visit = VISITS.get(visit_id.upper())
    if visit is None:
        return {"error": f"No visit '{visit_id}'", "available": list(VISITS)}
    return visit


@mcp.tool
def lookup_postcode(postcode: str) -> dict:
    """Convert a UK postcode into latitude, longitude and region.
    You need the coordinates before you can request a weather forecast."""
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
        }
    except requests.RequestException as exc:
        return {"error": f"Postcode lookup failed: {exc}"}


def _lookup_bank_holiday(check_date: str, country: str = "England") -> dict:
    """Plain helper. Called both by the tool below and by record_decision.

    Tools registered with @mcp.tool should not be called directly from other
    Python code - the decorator's return value differs between FastMCP
    versions. Keeping the logic in an ordinary function avoids that entirely.
    """
    division = {
        "England": "england-and-wales",
        "Wales": "england-and-wales",
        "Scotland": "scotland",
        "Northern Ireland": "northern-ireland",
    }.get(country, "england-and-wales")
    try:
        r = requests.get("https://www.gov.uk/bank-holidays.json", timeout=TIMEOUT)
        r.raise_for_status()
        for event in r.json()[division]["events"]:
            if event["date"] == check_date:
                return {"date": check_date, "is_bank_holiday": True, "name": event["title"]}
        return {"date": check_date, "is_bank_holiday": False}
    except requests.RequestException as exc:
        return {"error": f"Bank holiday lookup failed: {exc}"}


@mcp.tool
def check_bank_holiday(check_date: str, country: str = "England") -> dict:
    """Check whether a date (YYYY-MM-DD) is an official UK bank holiday,
    using the gov.uk calendar. Country must be England, Wales, Scotland or
    Northern Ireland."""
    return _lookup_bank_holiday(check_date, country)


@mcp.tool
def get_forecast(latitude: float, longitude: float, forecast_date: str) -> dict:
    """Get the weather forecast for a location on a date (YYYY-MM-DD).
    Requires latitude and longitude from lookup_postcode."""
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
            return {"error": f"No forecast for {forecast_date} (max ~16 days ahead)."}
        return {
            "date": forecast_date,
            "max_temp_c": daily["temperature_2m_max"][0],
            "precipitation_mm": daily["precipitation_sum"][0],
            "max_wind_kmh": daily["wind_speed_10m_max"][0],
        }
    except requests.RequestException as exc:
        return {"error": f"Forecast lookup failed: {exc}"}


@mcp.tool
def record_decision(visit_id: str, decision: str, reason: str) -> dict:
    """Record the final GO or RESCHEDULE decision, with a reason of at least
    20 characters. If this returns violations, change the decision to
    RESCHEDULE and call it again."""
    decision = decision.upper().strip()
    if decision not in {"GO", "RESCHEDULE"}:
        return {"recorded": False, "error": "decision must be 'GO' or 'RESCHEDULE'."}
    if len(reason.strip()) < 20:
        return {"recorded": False, "error": "reason must be at least 20 characters."}

    visit = VISITS.get(visit_id.upper())
    if visit is None:
        return {"recorded": False, "error": f"No visit '{visit_id}'."}

    violations = []
    if date.fromisoformat(visit["date"]).weekday() >= 5:
        violations.append(f"{visit['date']} is a weekend. Policy: no non-emergency visits.")

    holiday = _lookup_bank_holiday(visit["date"])
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


if __name__ == "__main__":
    mcp.run()
