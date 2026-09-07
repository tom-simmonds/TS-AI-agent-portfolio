import requests

response = requests.post(
    "http://localhost:11434/api/chat",
    json={
        "model": "qwen3:8b",
        "messages": [
            {"role": "user", "content": "Say hello in exactly five words."}
        ],
        "stream": False,
    },
)

data = response.json()
print(data["message"]["content"])
