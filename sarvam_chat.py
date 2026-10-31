"""Run with .venv/bin/python sarvam_chat.py after setting SARVAM_API_KEY in .env."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sarvamai import SarvamAI


def main():
    load_dotenv(Path(__file__).with_name(".env"))
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not key:
        raise SystemExit("Paste your Sarvam key into .env as SARVAM_API_KEY first.")

    client = SarvamAI(api_subscription_key=key)
    try:
        response = client.chat.completions(
            model="sarvam-105b-conversations",
            messages=[{"role": "user", "content": "Say hello in one short sentence."}],
            reasoning_effort=None,
            max_tokens=128,
            request_options={"max_retries": 0},
        )
    except Exception:
        raise SystemExit("Sarvam request failed; check your key, access and connection.") from None
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
