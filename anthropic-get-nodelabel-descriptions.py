#pip install anthropic python-dotenv
import os
# Load env variables
from dotenv import load_dotenv

load_dotenv()

# Create an API Client
from anthropic import Anthropic


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

prompt_text = read_file("./setup/node_label_text_prompt.txt")
csv_text = read_file("./setup/node_label_example_prop_value.csv")

combined = f"{prompt_text}\n\n<csv>\n{csv_text}\n</csv>\n\nReturn ONLY valid Cypher statements. No explanation, no markdown fences, no commentary."

client = Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
)
model = "claude-sonnet-4-6"

messages=[
    {
        "role": "user",
        "content": combined
    }
]
result_parts = []

# stream request
with client.messages.stream(
        model=model,
        max_tokens=100000,
        messages=messages
) as stream:
    for text in stream.text_stream:
        result_parts.append(text)
        print(text, end="", flush=True)  # optional live preview

result = "".join(result_parts)

#message
#print(message.content[0].text)
#print(f"Stop reason: {message.stop_reason}")
#result = message.content[0].text

output_path = "./setup/node_label_description.cypher"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(result)

print(f"Done. Cypher written to {output_path}")
