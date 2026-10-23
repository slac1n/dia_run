"""Thin wrapper around OpenRouter's chat completions endpoint."""

from __future__ import annotations

from typing import Any

import requests
from loguru import logger

from dia_run.settings import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

RECOMMENDATION_PROMPT = (
    "I just completed a run and want to improve my glucose management. "
    "My run data is attached at the end of this. Give me the changes I should "
    "make next run, ranked from highest to lowest expected impact. Provide up "
    "to 3 items, but fewer is fine — only include an item if the data clearly "
    "supports it. If the data does not support any actionable change, say so "
    "in one short sentence and stop.\n\n"
    "For each item: one sentence on what to change (with specific timing and "
    "quantity), one sentence on the data point that supports it. No intro, no "
    "summary, no general advice.\n\n"
    "Output format — strict:\n"
    "- Plain text only. No markdown, no bold, no italics, no asterisks, no "
    "headers, no bullet characters, no code fences.\n"
    "- No leading whitespace or indentation on any line. Every line must start "
    "at column 1.\n"
    '- Number the items "1.", "2.", "3." in impact order (highest first). Skip '
    "numbers you do not use.\n"
    "- Put exactly one blank line between items.\n\n"
    "=== RUN DATA ===\n"
)


class OpenRouterError(RuntimeError):
    """Raised when the OpenRouter API call fails or returns an unusable payload."""


def request_recommendation(*, run_context: str) -> str:
    """Call OpenRouter and return the model's plain-text recommendation."""
    if not settings.openrouter_api_key:
        raise OpenRouterError("OPENROUTER_API_KEY is not configured.")

    payload: dict[str, Any] = {
        "model": settings.openrouter_model,
        "messages": [{"role": "user", "content": RECOMMENDATION_PROMPT + run_context}],
    }
    if settings.openrouter_reasoning_effort:
        # OpenRouter passes this through to models that support reasoning
        # (e.g. OpenAI o-series, Anthropic extended thinking, Gemini thinking).
        # Models without reasoning support ignore the field.
        payload["reasoning"] = {"effort": settings.openrouter_reasoning_effort}

    message = _request_message(payload=payload)
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise OpenRouterError("OpenRouter response did not contain a completion.")
    return content.strip()


def request_tool_completion(*, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Request one tool-capable completion without logging health data."""
    payload: dict[str, Any] = {
        "model": settings.openrouter_model,
        "messages": messages,
        "max_tokens": 4000,
        "provider": {"require_parameters": True, "data_collection": "deny", "zdr": True},
    }
    if tools:
        payload.update(tools=tools, tool_choice="auto")
    if settings.openrouter_reasoning_effort:
        payload["reasoning"] = {"effort": settings.openrouter_reasoning_effort}
    return _request_message(payload=payload)


def _request_message(*, payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.openrouter_api_key:
        raise OpenRouterError("OPENROUTER_API_KEY is not configured.")
    try:
        response = requests.post(
            OPENROUTER_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json"},
            timeout=settings.openrouter_timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.error("OpenRouter transport request failed")
        raise OpenRouterError("OpenRouter request failed. Please retry.") from exc
    if response.status_code != 200:
        logger.error("OpenRouter returned HTTP {status}", status=response.status_code)
        raise OpenRouterError(f"OpenRouter returned HTTP {response.status_code}.")
    try:
        data = response.json()
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise OpenRouterError(
                "The model reached its output limit before completing the answer. "
                "Try a narrower question or lower OPENROUTER_REASONING_EFFORT."
            )
        message = choice["message"]
        if not isinstance(message, dict):
            raise TypeError("Invalid message")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError("OpenRouter response did not contain a valid completion.") from exc
    return message
