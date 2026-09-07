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

messages = [
    {"role": "user", "content": "What day is it today?"}
]

def call_model():
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen3:8b",
            "messages": messages,
            "tools": tools,
            "stream": False,
        },
    )
    return response.json()["message"]

# 1. First call — model asks for a tool
assistant_message = call_model()
messages.append(assistant_message)
print("MODEL WANTS:", assistant_message.get("tool_calls"))

# 2. Execute what it asked for
# YOUR CODE HERE:
#   for each entry in assistant_message["tool_calls"]:
#       get the name from call["function"]["name"]
#       look the function up in available_tools
#       call it
#       messages.append({"role": "tool", "content": <result as a string>})

# 2. Execute what it asked for

for call in assistant_message["tool_calls"]:

    function_name = call["function"]["name"]
    arguments = call["function"]["arguments"]

    print("CALLING:", function_name)
    print("ARGUMENTS:", arguments)

    function = available_tools[function_name]

    result = function(**arguments)

    print("RESULT:", result)

    messages.append({
        "role": "tool",
        "content": str(result)
    })

# 3. Second call — now it can see the result
final_message = call_model()
messages.append(final_message)
print("ANSWER:", final_message["content"])
