import requests
from datetime import datetime, date

def get_current_time():
    return datetime.now().strftime("%A %d %B %Y, %H:%M")


def days_until(date_string):
    target = datetime.strptime(date_string, "%Y-%m-%d").date()
    delta = target - date.today()
    return f"{delta.days} days until {date_string}"

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time. Use this whenever you need to know today's date.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "days_until",
            "description": (
                "Calculate how many days remain until a given date. "
                "The date must be in YYYY-MM-DD format. "
                "You need to know today's date before this is meaningful."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_string": {
                        "type": "string",
                        "description": "Target date in YYYY-MM-DD format, e.g. 2026-12-25",
                    }
                },
                "required": ["date_string"],
            },
        },
    },
]
