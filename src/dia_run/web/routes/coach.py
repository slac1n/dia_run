"""Personal coach UI with CSRF protection."""

import json
import re
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from dia_run.coach.agent import respond
from dia_run.coach.history import ChatStore
from dia_run.coach.models import CoachAnswer
from dia_run.coach.rendering import render_reply
from dia_run.coach.tools import CoachTools
from dia_run.data_processing.data_processing import DataProcessor
from dia_run.llm.openrouter_client import OpenRouterError
from dia_run.settings import settings
from dia_run.web.dependencies import get_data_paths, get_data_processor
from dia_run.web.templates import templates

COOKIE = "dia_run_coach"
PERSONAL_OWNER = "personal"


def require_coach_enabled() -> None:
    if not settings.coach_enabled:
        raise HTTPException(status_code=404, detail="The coach is disabled")


router = APIRouter(dependencies=[Depends(require_coach_enabled)])


def _store() -> ChatStore:
    path = settings.coach_history_path
    # Mock mode must not allow the real sync root to be used either.
    if path.resolve().is_relative_to(settings.data_root.resolve()):
        raise ValueError("History must be outside the synced data root")
    return ChatStore(path=path, data_root=get_data_paths().data_root)


def _owner(request: Request) -> str:
    value = request.cookies.get(COOKIE, "")
    return value if re.fullmatch(r"[a-f0-9]{64}", value) else secrets.token_hex(32)


def _check_csrf(request: Request, *, token: str) -> str:
    owner = _owner(request)
    if not secrets.compare_digest(owner, token):
        raise HTTPException(status_code=403, detail="Reload the page before submitting")
    return owner


@router.get("/coach", response_class=HTMLResponse)
def coach_page(request: Request, *, chat_id: str | None = None, error: str | None = None) -> HTMLResponse:
    owner = PERSONAL_OWNER
    csrf_token = _owner(request)
    store = _store()
    messages: list[dict[str, Any]] = []
    draft = ""
    if chat_id:
        try:
            messages, _ = store.load(chat_id=chat_id, owner=owner)
            draft, saved_error = store.get_attempt(chat_id=chat_id, owner=owner)
            error = error or saved_error
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Conversation not found") from exc
    turns = []
    evidence: list[dict[str, Any]] = []
    for message in messages:
        if message["role"] == "user":
            turns.append({"question": message["content"]})
        elif message["role"] == "assistant" and not message.get("tool_calls"):
            raw = json.loads(message["content"])
            answer = CoachAnswer.model_validate(raw)
            turns.append(
                {
                    "coach_html": render_reply(answer.message),
                    "memory_updates": answer.memory_updates,
                    "forgotten": len(answer.forget_memories),
                }
            )
            evidence.extend(message.get("memory_context", []))
        elif message["role"] == "tool":
            result = json.loads(message["content"])
            if "id" in result:
                evidence.append(result)
    response = templates.TemplateResponse(
        request,
        "pages/coach.html",
        {
            "title": "Running coach",
            "memories": store.list_memories(owner=owner),
            "chats": store.list_chats(owner=owner),
            "chat_id": chat_id,
            "turns": turns,
            "evidence": evidence,
            "csrf_token": csrf_token,
            "error": error,
            "draft": draft,
            "model": settings.openrouter_model,
        },
    )
    response.set_cookie(
        COOKIE,
        csrf_token,
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 365,
        secure=request.url.scheme == "https",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@router.post("/coach/message", response_model=None)
def coach_message(
    request: Request,
    *,
    data_processor: Annotated[DataProcessor, Depends(get_data_processor)],
    question: Annotated[str, Form(min_length=1, max_length=4000)],
    csrf_token: Annotated[str, Form()],
    chat_id: Annotated[str, Form()] = "",
    consent: Annotated[bool, Form()] = False,
) -> HTMLResponse | RedirectResponse:
    _check_csrf(request, token=csrf_token)
    owner = PERSONAL_OWNER
    if not consent:
        raise HTTPException(status_code=400, detail="Confirm sharing selected health data with OpenRouter")
    store = _store()
    if not chat_id:
        chat_id = store.create(owner=owner)
    try:
        messages, revision = store.load(chat_id=chat_id, owner=owner)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    try:
        revision = store.record_attempt(chat_id=chat_id, owner=owner, question=question, error="", revision=revision)
        messages = respond(
            messages=messages,
            question=question,
            tools=CoachTools(processor=data_processor, store=store, owner=owner),
        )
        store.save(
            chat_id=chat_id,
            owner=owner,
            messages=messages,
            revision=revision,
            answer=CoachAnswer.model_validate_json(messages[-1]["content"]),
        )
    except (OpenRouterError, ValueError) as exc:
        try:
            store.record_attempt(chat_id=chat_id, owner=owner, question=question, error=str(exc), revision=revision)
        except ValueError:
            return coach_page(request, chat_id=chat_id, error=str(exc))
        return RedirectResponse(f"/coach?chat_id={chat_id}", status_code=303)
    return RedirectResponse(f"/coach?chat_id={chat_id}", status_code=303)


@router.post("/coach/delete")
def delete_coach(
    request: Request, *, chat_id: Annotated[str, Form()], csrf_token: Annotated[str, Form()]
) -> RedirectResponse:
    _check_csrf(request, token=csrf_token)
    owner = PERSONAL_OWNER
    _store().delete(chat_id=chat_id, owner=owner)
    return RedirectResponse("/coach", status_code=303)


@router.post("/coach/forget")
def forget_coach_memory(
    request: Request, *, memory_id: Annotated[str, Form()], csrf_token: Annotated[str, Form()]
) -> RedirectResponse:
    _check_csrf(request, token=csrf_token)
    _store().forget_memory(memory_id=memory_id, owner=PERSONAL_OWNER)
    return RedirectResponse("/coach", status_code=303)
