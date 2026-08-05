"""Jarvis_60 brain — the only module that talks to the LLM."""
import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

client = Anthropic()  # reads ANTHROPIC_API_KEY automatically

def think(prompt: str, system: str = "You are Jarvis_60, a precise assistant.") -> str:
    """Send a prompt to the brain, return its reply as text."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text

if __name__ == "__main__":
    print(think("Say exactly: Jarvis_60 online. All systems nominal."))
