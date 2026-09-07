import requests
from datetime import datetime

def get_current_time():
  return datetime.now().strftime("%A %d %B %Y, %H:%M")

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time. Use this whenever you need to know today's date.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
]

available_tools = {
  "get_current_time": get_current_time
}

response = requests.post(
    "http://localhost:11434/api/chat",
    json={
        "model": "qwen3:8b",
        "messages": [
            {"role": "user", "content": "What day is it today?"}
        ],
        "tools": tools,
        "stream": False,
    },
)

data = response.json()
print(data["message"]["content"])
