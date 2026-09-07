"""
companies_house.py - tool functions for the real Companies House public
data API (box 5b "Tools -> Business APIs" in the architecture diagram).

Docs: https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference

Auth: HTTP Basic, the API key as the username, blank password. Rate limit
is 600 requests / 5 minutes per key - fine for interactive lookups on one
supplier at a time, but don't loop this over a big supplier list without
a delay between companies.

Design note: these functions raise on genuine failures (bad key, network
error, rate limit) and let agent_harness.execute_tool_call() catch and
report them - that's already the harness's job, no need to duplicate it
here. The one thing each function DOES handle itself is a 404 that means
"this company legitimately has none of this data" (e.g. no PSCs, no
charges, no insolvency history) - that's not an error, it's a fact worth
reporting to the agent.
"""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.company-information.service.gov.uk"
REQUEST_TIMEOUT = 15.0

_api_key = os.getenv("CH_API_KEY")
if not _api_key or _api_key == "your_key_here":
    raise RuntimeError(
        "CH_API_KEY is not set in .env (or is still the placeholder). "
        "Get a key at https://developer.company-information.service.gov.uk/ "
        "and put it in dd-agent/.env as CH_API_KEY=<your key>."
    )

_session = requests.Session()
_session.auth = (_api_key, "")


class CompaniesHouseRateLimited(Exception):
    """Raised on HTTP 429 - the 600-requests-per-5-minutes cap was hit."""


def _normalise_company_number(company_number):
    """Companies House numbers are 8 characters, zero-padded
    (e.g. "445790" -> "00445790"). LLP/other prefixed numbers pass through
    unchanged."""
    company_number = str(company_number).strip().upper()
    if company_number.isdigit():
        company_number = company_number.zfill(8)
    return company_number


def _get(path, params=None):
    """GET one Companies House endpoint. Returns the parsed JSON body, or
    None if the endpoint 404s (which for several of these endpoints means
    "no data of this kind exists" rather than "not found")."""
    response = _session.get(f"{BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT)

    if response.status_code == 404:
        return None
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        raise CompaniesHouseRateLimited(
            f"Companies House rate limit hit (600 req/5 min). Retry-After: {retry_after}s"
        )
    response.raise_for_status()
    return response.json()


# --- Tools -------------------------------------------------------------------

def search_companies(company_name, max_results=5):
    """Search Companies House by name. Returns candidate companies so the
    agent can confirm which one it means before pulling any detail."""
    data = _get("/search/companies", params={"q": company_name, "items_per_page": max_results})

    if not data or not data.get("items"):
        return json.dumps({"query": company_name, "matches": []})

    matches = [
        {
            "company_number": item.get("company_number"),
            "name": item.get("title"),
            "status": item.get("company_status"),
            "type": item.get("company_type"),
            "incorporated_on": item.get("date_of_creation"),
            "address": item.get("address_snippet"),
        }
        for item in data["items"][:max_results]
    ]
    return json.dumps({"query": company_name, "matches": matches}, indent=2)


def get_company_profile(company_number):
    """Core facts about one company: status, incorporation date, type,
    registered address, SIC codes, and filing-compliance flags."""
    company_number = _normalise_company_number(company_number)
    data = _get(f"/company/{company_number}")

    if data is None:
        return json.dumps({"company_number": company_number, "error": "No company found with this number."})

    accounts = data.get("accounts", {})
    confirmation = data.get("confirmation_statement", {})

    profile = {
        "company_number": company_number,
        "name": data.get("company_name"),
        "status": data.get("company_status"),
        "type": data.get("type"),
        "incorporated_on": data.get("date_of_creation"),
        "dissolved_on": data.get("date_of_cessation"),
        "sic_codes": data.get("sic_codes", []),
        "registered_office_address": data.get("registered_office_address", {}),
        "accounts_overdue": accounts.get("overdue"),
        "accounts_next_due": accounts.get("next_due"),
        "confirmation_statement_overdue": confirmation.get("overdue"),
        "confirmation_statement_next_due": confirmation.get("next_due"),
        "has_charges": data.get("has_charges", False),
        "has_insolvency_history": data.get("has_insolvency_history", False),
    }
    return json.dumps(profile, indent=2, default=str)


def get_officers(company_number, include_resigned=False):
    """Directors and secretaries. Companies House only ever exposes
    month/year of birth (never the day) - that's the API's own privacy
    protection, nothing this tool adds."""
    company_number = _normalise_company_number(company_number)
    data = _get(f"/company/{company_number}/officers", params={"items_per_page": 50})

    if data is None or not data.get("items"):
        return json.dumps({"company_number": company_number, "officers": []})

    officers = []
    for item in data["items"]:
        if not include_resigned and item.get("resigned_on"):
            continue
        officers.append({
            "name": item.get("name"),
            "role": item.get("officer_role"),
            "appointed_on": item.get("appointed_on"),
            "resigned_on": item.get("resigned_on"),
            "nationality": item.get("nationality"),
            "country_of_residence": item.get("country_of_residence"),
            "date_of_birth": item.get("date_of_birth"),  # {"month": .., "year": ..} or absent
        })

    return json.dumps({
        "company_number": company_number,
        "active_count": data.get("active_count"),
        "resigned_count": data.get("resigned_count"),
        "officers": officers,
    }, indent=2, default=str)


def get_persons_with_significant_control(company_number):
    """Who actually owns/controls the company - the real target of most
    supplier due diligence (beneficial ownership, not just directors)."""
    company_number = _normalise_company_number(company_number)
    data = _get(f"/company/{company_number}/persons-with-significant-control")

    if data is None or not data.get("items"):
        return json.dumps({
            "company_number": company_number,
            "persons_with_significant_control": [],
            "note": "No PSC data - either none on record, or this company type is exempt from PSC reporting.",
        })

    pscs = [
        {
            "name": item.get("name"),
            "kind": item.get("kind"),
            "natures_of_control": item.get("natures_of_control", []),
            "notified_on": item.get("notified_on"),
            "ceased_on": item.get("ceased_on"),
            "nationality": item.get("nationality"),
            "country_of_residence": item.get("country_of_residence"),
        }
        for item in data["items"]
    ]
    return json.dumps({"company_number": company_number, "persons_with_significant_control": pscs}, indent=2, default=str)


def get_filing_history(company_number, category=None, max_results=10):
    """Recent filings - the fastest way to see whether a company is
    keeping up its statutory obligations (accounts, confirmation
    statements) or has recently changed officers, address, or charges."""
    company_number = _normalise_company_number(company_number)
    params = {"items_per_page": max_results}
    if category:
        params["category"] = category
    data = _get(f"/company/{company_number}/filing-history", params=params)

    if data is None or not data.get("items"):
        return json.dumps({"company_number": company_number, "filings": []})

    filings = [
        {
            "date": item.get("date"),
            "type": item.get("type"),
            "category": item.get("category"),
            "description": item.get("description"),
        }
        for item in data["items"][:max_results]
    ]
    return json.dumps({
        "company_number": company_number,
        "total_filings": data.get("total_count"),
        "filings": filings,
    }, indent=2, default=str)


def get_charges(company_number):
    """Outstanding mortgages/charges over company assets - a lender's
    claim, relevant to assessing financial exposure."""
    company_number = _normalise_company_number(company_number)
    data = _get(f"/company/{company_number}/charges")

    if data is None or not data.get("items"):
        return json.dumps({"company_number": company_number, "charges": [], "outstanding_count": 0})

    charges = [
        {
            "status": item.get("status"),
            "created_on": item.get("created_on"),
            "delivered_on": item.get("delivered_on"),
            "classification": (item.get("classification") or {}).get("description"),
            "persons_entitled": [p.get("name") for p in item.get("persons_entitled", [])],
        }
        for item in data["items"]
    ]
    outstanding = sum(1 for c in charges if c["status"] == "outstanding")
    return json.dumps({
        "company_number": company_number,
        "outstanding_count": outstanding,
        "charges": charges,
    }, indent=2, default=str)


def get_insolvency(company_number):
    """Insolvency proceedings, if any - administration, liquidation, etc.
    A 404 here (returned as no cases) is the good outcome."""
    company_number = _normalise_company_number(company_number)
    data = _get(f"/company/{company_number}/insolvency")

    if data is None or not data.get("cases"):
        return json.dumps({"company_number": company_number, "insolvency_cases": []})

    cases = [
        {"type": case.get("type"), "dates": case.get("dates", []), "number": case.get("number")}
        for case in data["cases"]
    ]
    return json.dumps({"company_number": company_number, "insolvency_cases": cases}, indent=2, default=str)


# --- Tool specs (Ollama / OpenAI function-calling format) --------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "search_companies",
            "description": (
                "Search Companies House by company name to find its company number. "
                "ALWAYS call this first and confirm the match before calling any other "
                "tool - company names are not unique, and every other tool needs the "
                "exact company_number, not the name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string", "description": "The company name to search for."},
                },
                "required": ["company_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_profile",
            "description": "Get core facts about a company: status (active/dissolved/liquidation/etc), incorporation date, registered address, SIC codes, and whether its accounts or confirmation statement are overdue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_number": {"type": "string", "description": "The 8-character Companies House company number, e.g. 00445790."},
                },
                "required": ["company_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_officers",
            "description": "Get the company's current directors and secretaries (excludes resigned officers).",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_number": {"type": "string", "description": "The 8-character Companies House company number."},
                },
                "required": ["company_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_persons_with_significant_control",
            "description": "Get the people or entities who actually own or control the company (beneficial ownership) - the core of most due-diligence checks, distinct from the directors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_number": {"type": "string", "description": "The 8-character Companies House company number."},
                },
                "required": ["company_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_filing_history",
            "description": "Get the company's recent statutory filings (accounts, confirmation statements, officer/address changes). Useful for checking it's keeping up its obligations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_number": {"type": "string", "description": "The 8-character Companies House company number."},
                },
                "required": ["company_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_charges",
            "description": "Get outstanding mortgages/charges registered against the company's assets - relevant to financial exposure and lender claims.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_number": {"type": "string", "description": "The 8-character Companies House company number."},
                },
                "required": ["company_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_insolvency",
            "description": "Check for insolvency proceedings (administration, liquidation, receivership, etc). Only call this if get_company_profile showed has_insolvency_history: true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company_number": {"type": "string", "description": "The 8-character Companies House company number."},
                },
                "required": ["company_number"],
            },
        },
    },
]

available_tools = {
    "search_companies": search_companies,
    "get_company_profile": get_company_profile,
    "get_officers": get_officers,
    "get_persons_with_significant_control": get_persons_with_significant_control,
    "get_filing_history": get_filing_history,
    "get_charges": get_charges,
    "get_insolvency": get_insolvency,
}


if __name__ == "__main__":
    # Quick manual smoke test against the REAL API - run this yourself, e.g.:
    #   python companies_house.py Tesco
    import sys
    name = " ".join(sys.argv[1:]) or "Tesco"
    print(f"Searching for: {name}\n")
    print(search_companies(name))
