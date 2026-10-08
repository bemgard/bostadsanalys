"""
Steg 1: Testa att kopplingen till Claude-API:t fungerar.
Kör: python test_api.py
"""

import os
import sys

from dotenv import load_dotenv
import anthropic

load_dotenv()

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    sys.exit("Hittar ingen ANTHROPIC_API_KEY. Har du skapat .env-filen?")

client = anthropic.Anthropic(api_key=api_key)

MODEL = "claude-sonnet-5-5"

try:
    response = client.messages.create(
        model=MODEL,
        max_tokens=100,
        messages=[
            {"role": "user", "content": "Svara med exakt en mening: vad är en bostadsrättsförening?"}
        ],
    )
except anthropic.AuthenticationError:
    sys.exit("API-nyckeln är ogiltig. Kontrollera den i .env.")
except anthropic.APIError as e:
    sys.exit(f"API-fel: {e}")

print("✅ Kopplingen fungerar!\n")
print("Claude svarade:", response.content[0].text)
print(f"\nTokens: {response.usage.input_tokens} in, {response.usage.output_tokens} ut")
