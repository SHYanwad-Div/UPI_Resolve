"""Thin wrapper around Sarvam's chat API. Changing LLM provider means replacing this one file."""
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

URL = "https://api.sarvam.ai/v1/chat/completions"
# Chosen by testing 19 real complaints in English, Hindi and Kannada: this model got 19 right
# at about 3 seconds each, against 18 right at about 8 seconds for sarvam-105b.
MODEL = "sarvam-105b-conversations"
TIMEOUT_SECONDS = 20
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class LLMError(Exception):
    """The model could not answer. Callers must treat this as 'send it to a human'."""


def chat(messages: list[dict], tools: list[dict]) -> dict:
    """Returns the assistant message: {"content": ..., "tool_calls": [...]}."""
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        raise LLMError("SARVAM_API_KEY is not set")

    body = {"model": MODEL, "messages": messages, "tools": tools, "tool_choice": "auto", "reasoning_effort": "low", "max_tokens": 1500}
    headers = {"api-subscription-key": key, "Authorization": f"Bearer {key}"}

    error = "No attempt made"
    for _ in range(2):  # One retry only: a customer is waiting, and a human can take over.
        try:
            response = httpx.post(URL, headers=headers, json=body, timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            error = f"Could not reach Sarvam: {type(exc).__name__}"
            continue
        if response.status_code == 200:
            try:
                return response.json()["choices"][0]["message"]
            except (ValueError, KeyError, IndexError) as exc:
                raise LLMError("Sarvam returned an unexpected response") from exc
        error = f"Sarvam returned HTTP {response.status_code}"
        if response.status_code not in RETRYABLE_STATUSES:
            break
    raise LLMError(error)
