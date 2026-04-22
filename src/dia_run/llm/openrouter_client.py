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

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            OPENROUTER_URL,
            json=payload,
            headers=headers,
            timeout=settings.openrouter_timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.error("OpenRouter request failed: {error}", error=str(exc))
        raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc

    if response.status_code != 200:
        logger.error(
            "OpenRouter returned {status}: {body}",
            status=response.status_code,
            body=response.text[:500],
        )
        raise OpenRouterError(f"OpenRouter returned HTTP {response.status_code}.")

    data = response.json()
    try:
        content: str = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("OpenRouter response missing content: {body}", body=str(data)[:500])
        raise OpenRouterError("OpenRouter response did not contain a completion.") from exc

    return content.strip()
