import os
from dotenv import load_dotenv
from anthropic import Anthropic

# Load your API key
load_dotenv()

# Test connection
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

message = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=100,
    messages=[{"role": "user", "content": "Say 'Setup successful!' if you can read this"}]
)

print(message.content[0].text)