from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dia_run.coach.rendering import render_reply
from dia_run.settings import settings
from dia_run.web.app import create_app


@pytest.mark.parametrize("client_ip,host", [("10.44.0.2", "10.44.0.1"), ("10.44.0.3", "dia-run.internal")])
def test_production_access(*, client_ip: str, host: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "coach_enabled", True)
    monkeypatch.setattr(settings, "coach_history_path", tmp_path / "private" / "chats.sqlite3")
    client = TestClient(create_app(), base_url=f"http://{host}", client=(client_ip, 50000))
    response = client.get("/coach", headers={"X-Forwarded-For": "10.44.0.2", "X-Forwarded-Host": "10.44.0.1"})
    assert response.status_code == 200
    assert 'href="/coach">Running coach' in response.text
    assert response.headers["cache-control"] == "no-store"
    for path in ("/coach/message", "/coach/forget", "/coach/delete"):
        # Allowed peers still require a valid cookie/form CSRF token.
        assert (
            client.post(
                path,
                data={"question": "Hi", "memory_id": "x", "chat_id": "x", "csrf_token": "invalid", "consent": "true"},
            ).status_code
            == 403
        )


def test_reply_formats_bold_lists_and_citations() -> None:
    result = str(
        render_reply(
            "Your run [E2].\n\n- **Keep it easy.** Run gently. - **Skip speed work.** Rest.\n\n1. First\n2. Second"
        )
    )
    assert "<strong>Keep it easy.</strong>" in result
    assert "<strong>Skip speed work.</strong>" in result
    assert result.count("<li>") == 4
    assert '<a href="#E2">[E2]</a>' in result
    assert '<ol start="1">' in result
    assert "**" not in result


def test_reply_escapes_html_and_does_not_load_images_or_remote_links() -> None:
    result = str(
        render_reply(
            "**<img src=x onerror=alert(1)>**\n\n<script>alert(1)</script>\n"
            "[click](javascript:alert(1)) ![tracking](https://example.com/pixel) [E1]"
        )
    )
    assert "<script" not in result
    assert "<img" not in result
    assert "&lt;script&gt;" in result
    assert '<a href="javascript:' not in result
    assert '<a href="https:' not in result
    assert '<a href="#E1">[E1]</a>' in result
