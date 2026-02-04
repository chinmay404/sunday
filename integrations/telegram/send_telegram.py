#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def load_env():
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")


def send_message(token: str, chat_id: str, message: str, parse_mode: str | None, disable_preview: bool) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": disable_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    response = requests.post(url, json=payload, timeout=10)
    if response.status_code != 200:
        raise RuntimeError(f"Telegram API error {response.status_code}: {response.text}")

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API returned ok=false: {data}")
    return data


def main():
    parser = argparse.ArgumentParser(description="Send a Telegram message using TELEGRAM_API_TOKEN.")
    parser.add_argument("chat_id", help="Target chat ID (user, group, or channel ID).")
    parser.add_argument("message", help="Message text to send.")
    parser.add_argument(
        "--parse-mode",
        choices=["Markdown", "MarkdownV2", "HTML"],
        default=None,
        help="Optional parse mode for the message.",
    )
    parser.add_argument(
        "--disable-preview",
        action="store_true",
        help="Disable link previews in the message.",
    )
    args = parser.parse_args()

    load_env()
    token = os.getenv("TELEGRAM_API_TOKEN")
    if not token:
        print("Missing TELEGRAM_API_TOKEN in .env or environment.", file=sys.stderr)
        sys.exit(1)

    try:
        result = send_message(
            token=token,
            chat_id=args.chat_id,
            message=args.message,
            parse_mode=args.parse_mode,
            disable_preview=args.disable_preview,
        )
    except Exception as exc:
        print(f"Failed to send message: {exc}", file=sys.stderr)
        sys.exit(1)

    message_id = result.get("result", {}).get("message_id")
    print(f"Message sent successfully. message_id={message_id}")


if __name__ == "__main__":
    main()
