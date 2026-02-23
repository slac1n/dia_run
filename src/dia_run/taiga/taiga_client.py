import getpass
import os
import re
import sys
from typing import Any

import requests
from dotenv import find_dotenv, load_dotenv, set_key
from loguru import logger

TAIGA_API_BASE = "https://api.taiga.io/api/v1"
DEFAULT_PROJECT_SLUG = "slac1n-dia-run"
TICKET_PREFIX = "TG"
IN_PROGRESS_SLUG = "in-progress"
MAX_BRANCH_SLUG_LENGTH = 50


def _login() -> None:
    """Interactively log in to Taiga and save tokens to .env."""
    print("Please enter your Taiga credentials.")
    username = input("Username or email: ")
    password = getpass.getpass("Password: ")

    url = f"{TAIGA_API_BASE}/auth"
    payload = {
        "type": "normal",
        "username": username,
        "password": password,
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.error(f"Login failed: {e}")
        if e.response is not None and e.response.status_code == 401:
            logger.error("Invalid credentials.")
        sys.exit(1)
    except requests.RequestException as e:
        logger.error(f"Network error: {e}")
        sys.exit(1)

    data = response.json()
    auth_token = data.get("auth_token")
    refresh_token = data.get("refresh")

    if not auth_token:
        logger.error("No auth_token received from Taiga.")
        sys.exit(1)

    dotenv_path = find_dotenv()
    if not dotenv_path:
        # If no .env exists, create one in the current directory
        dotenv_path = os.path.join(os.getcwd(), ".env")
        with open(dotenv_path, "w") as f:
            f.write("")

    set_key(dotenv_path, "TAIGA_AUTH_TOKEN", auth_token)
    if refresh_token:
        set_key(dotenv_path, "TAIGA_REFRESH_TOKEN", refresh_token)
        logger.info(f"Successfully logged in! Tokens saved to {dotenv_path}")
    else:
        logger.warning(f"Logged in, but no refresh token received. saved auth token to {dotenv_path}")


def _refresh_token(*, refresh_token: str, dotenv_path: str) -> str | None:
    """Attempt to refresh the auth token using the refresh token.

    If successful, updates the .env file with the new tokens and returns the new auth token.
    If failing, returns None.
    """
    url = f"{TAIGA_API_BASE}/auth/refresh"
    payload = {"refresh": refresh_token}

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"Token refresh failed: {e}")
        return None

    data = response.json()
    new_auth_token = data.get("auth_token")
    new_refresh_token = data.get("refresh")

    if new_auth_token and new_refresh_token:
        set_key(dotenv_path, "TAIGA_AUTH_TOKEN", new_auth_token)
        set_key(dotenv_path, "TAIGA_REFRESH_TOKEN", new_refresh_token)
        logger.debug("Token refreshed and updated in .env")
        return new_auth_token

    return None


def _get_config() -> tuple[str, str]:
    """Load Taiga auth token and project slug from environment.

    Proactively refreshes the token if a refresh token is present.
    """
    dotenv_path = find_dotenv()
    load_dotenv(dotenv_path)

    auth_token = os.getenv("TAIGA_AUTH_TOKEN")
    refresh_token = os.getenv("TAIGA_REFRESH_TOKEN")

    if refresh_token and dotenv_path:
        # Proactive refresh
        new_token = _refresh_token(refresh_token=refresh_token, dotenv_path=dotenv_path)
        if new_token:
            auth_token = new_token

    if not auth_token:
        logger.error("TAIGA_AUTH_TOKEN is not set in your .env file.")
        logger.info("Run 'uv run taiga --login' to authenticate.")
        sys.exit(1)

    project_slug = os.getenv("TAIGA_PROJECT_SLUG", DEFAULT_PROJECT_SLUG)
    return auth_token, project_slug


def _auth_headers(*, token: str) -> dict[str, str]:
    """Build authorization headers for Taiga API requests."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def parse_ticket_tag(*, tag: str) -> int:
    """Parse a ticket tag like 'TG-23' and return the numeric ref.

    Raises:
        ValueError: If the tag does not match the expected format.

    """
    tag = tag.strip().upper()
    prefix = f"{TICKET_PREFIX}-"

    if not tag.startswith(prefix):
        msg = f"Invalid ticket tag '{tag}'. Expected format: {TICKET_PREFIX}-<number> (e.g. TG-23)"
        raise ValueError(msg)

    ref_str = tag[len(prefix) :]
    if not ref_str.isdigit():
        msg = f"Invalid ticket tag '{tag}'. The part after '{prefix}' must be a number."
        raise ValueError(msg)

    return int(ref_str)


def _slugify(*, text: str, max_length: int = MAX_BRANCH_SLUG_LENGTH) -> str:
    """Convert text to a lowercase hyphenated slug suitable for branch names."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


def _resolve_user_story(*, token: str, project_slug: str, ref: int) -> int:
    """Resolve a user story ref number to its internal Taiga ID."""
    url = f"{TAIGA_API_BASE}/resolver"
    params: dict[str, str | int] = {"project": project_slug, "us": ref}
    headers = _auth_headers(token=token)

    response = requests.get(url, params=params, headers=headers, timeout=15)
    response.raise_for_status()

    data: dict[str, Any] = response.json()
    us_id: int | None = data.get("us")

    if us_id is None:
        msg = f"User story #{ref} not found in project '{project_slug}'."
        raise ValueError(msg)

    return us_id


def get_user_story(*, token: str, project_slug: str, ref: int) -> dict[str, Any]:
    """Fetch a full user story by its ref number.

    Args:
        token: Taiga API auth token.
        project_slug: Taiga project slug (e.g. 'slac1n-dia-run').
        ref: User story reference number.

    Returns:
        The user story detail as a dictionary.

    """
    us_id = _resolve_user_story(token=token, project_slug=project_slug, ref=ref)

    url = f"{TAIGA_API_BASE}/userstories/{us_id}"
    headers = _auth_headers(token=token)

    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    result: dict[str, Any] = response.json()
    return result


def _get_project_id(*, token: str, project_slug: str) -> int:
    """Resolve a project slug to its numeric ID."""
    url = f"{TAIGA_API_BASE}/projects/by_slug"
    params: dict[str, str] = {"slug": project_slug}
    headers = _auth_headers(token=token)

    response = requests.get(url, params=params, headers=headers, timeout=15)
    response.raise_for_status()

    data: dict[str, Any] = response.json()
    project_id: int = data["id"]
    return project_id


def _get_in_progress_status_id(*, token: str, project_id: int) -> int:
    """Find the 'In progress' status ID for user stories in a project."""
    url = f"{TAIGA_API_BASE}/userstory-statuses"
    params: dict[str, str | int] = {"project": project_id}
    headers = _auth_headers(token=token)

    response = requests.get(url, params=params, headers=headers, timeout=15)
    response.raise_for_status()

    statuses: list[dict[str, Any]] = response.json()
    for status in statuses:
        if status.get("slug") == IN_PROGRESS_SLUG:
            result: int = status["id"]
            return result

    available = [s.get("slug", "?") for s in statuses]
    msg = f"Status '{IN_PROGRESS_SLUG}' not found. Available: {', '.join(available)}"
    raise ValueError(msg)


def set_user_story_in_progress(*, token: str, project_slug: str, ref: int) -> dict[str, Any]:
    """Move a user story to 'In progress' status.

    Args:
        token: Taiga API auth token.
        project_slug: Taiga project slug.
        ref: User story reference number.

    Returns:
        The updated user story detail.

    """
    story = get_user_story(token=token, project_slug=project_slug, ref=ref)
    us_id: int = story["id"]
    version: int = story["version"]

    project_id = _get_project_id(token=token, project_slug=project_slug)
    status_id = _get_in_progress_status_id(token=token, project_id=project_id)

    url = f"{TAIGA_API_BASE}/userstories/{us_id}"
    headers = _auth_headers(token=token)
    payload: dict[str, int] = {"status": status_id, "version": version}

    response = requests.patch(url, json=payload, headers=headers, timeout=15)
    response.raise_for_status()

    result: dict[str, Any] = response.json()
    return result


def get_branch_name(*, ref: int, subject: str) -> str:
    """Generate a git branch name from a ticket ref and subject.

    Args:
        ref: User story reference number.
        subject: User story subject line.

    Returns:
        A branch name like 'feat/TG-23-add-glucose-overlay'.

    """
    slug = _slugify(text=subject)
    return f"feat/{TICKET_PREFIX}-{ref}-{slug}"


def _format_user_story(*, story: dict[str, Any]) -> str:
    """Format a user story dict into a readable summary."""
    lines: list[str] = []

    lines.append(f"[TG-{story.get('ref', '?')}] {story.get('subject', 'No subject')}")
    lines.append(f"URL: https://tree.taiga.io/project/{DEFAULT_PROJECT_SLUG}/us/{story.get('ref', '')}")
    lines.append("")

    status_info: dict[str, Any] | None = story.get("status_extra_info")
    status_name = status_info.get("name", "Unknown") if status_info else "Unknown"
    lines.append(f"Status:      {status_name}")

    assigned_info: dict[str, Any] | None = story.get("assigned_to_extra_info")
    assigned_name = assigned_info.get("full_name_display", "Unassigned") if assigned_info else "Unassigned"
    lines.append(f"Assigned to: {assigned_name}")

    tags: list[list[str]] | None = story.get("tags")
    if tags:
        tag_names = [t[0] for t in tags]
        lines.append(f"Tags:        {', '.join(tag_names)}")

    due_date = story.get("due_date")
    if due_date:
        lines.append(f"Due date:    {due_date}")

    milestone: dict[str, Any] | None = story.get("milestone_extra_info")
    if milestone:
        lines.append(f"Sprint:      {milestone.get('name', '')}")

    lines.append("")

    description = story.get("description")
    if description:
        lines.append("--- Description ---")
        lines.append(description.strip())
        lines.append("")

    return "\n".join(lines)


def _parse_args() -> tuple[str, bool, bool, bool]:
    """Parse CLI arguments.

    Returns:
        A tuple of (tag, set_in_progress, branch_name_only, login).

    """
    args = sys.argv[1:]
    set_in_progress = False
    branch_name_only = False
    login = False
    tag = ""

    for arg in args:
        if arg == "--set-in-progress":
            set_in_progress = True
        elif arg == "--branch-name":
            branch_name_only = True
        elif arg == "--login":
            login = True
        elif not arg.startswith("--"):
            tag = arg

    if login:
        return tag, set_in_progress, branch_name_only, login

    if not tag:
        logger.error(f"Usage: taiga {TICKET_PREFIX}-<number> [--set-in-progress] [--branch-name] | --login")
        sys.exit(1)

    return tag, set_in_progress, branch_name_only, login


def main() -> None:
    """CLI entry point: fetch and display a Taiga user story by tag."""
    tag, set_in_progress, branch_name_only, login = _parse_args()

    if login:
        _login()
        return

    try:
        ref = parse_ticket_tag(tag=tag)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    token, project_slug = _get_config()

    try:
        if set_in_progress:
            story = set_user_story_in_progress(token=token, project_slug=project_slug, ref=ref)
            logger.info(f"TG-{ref} status set to 'In progress'")
        else:
            story = get_user_story(token=token, project_slug=project_slug, ref=ref)

        if branch_name_only:
            branch = get_branch_name(ref=ref, subject=story.get("subject", ""))
            print(branch)  # noqa: T201
        else:
            print(_format_user_story(story=story))  # noqa: T201

    except requests.HTTPError as e:
        logger.error(f"Taiga API error: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
