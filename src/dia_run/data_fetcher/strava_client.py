import os
import urllib.parse
import webbrowser
from pathlib import Path

from dotenv import find_dotenv, load_dotenv, set_key
from loguru import logger
from stravalib.client import Client
from stravalib.model import SummaryActivity

from dia_run.settings import settings


def _load_runtime_env() -> str:
    dotenv_path = find_dotenv()
    load_dotenv(dotenv_path)
    return dotenv_path


def _get_refresh_token_file() -> Path | None:
    return settings.strava_refresh_token_file


def _read_refresh_token() -> str | None:
    refresh_token_file = _get_refresh_token_file()
    if refresh_token_file and refresh_token_file.exists():
        refresh_token = refresh_token_file.read_text(encoding="utf-8").strip()
        return refresh_token or None
    return os.getenv("REFRESH_TOKEN")


def _persist_refresh_token(*, refresh_token: str) -> None:
    refresh_token_file = _get_refresh_token_file()
    if refresh_token_file is not None:
        refresh_token_file.parent.mkdir(parents=True, exist_ok=True)
        refresh_token_file.write_text(f"{refresh_token}\n", encoding="utf-8")
        logger.info("Stored Strava refresh token at {}", refresh_token_file)
        return

    dotenv_path = _load_runtime_env()
    if dotenv_path:
        set_key(dotenv_path, "REFRESH_TOKEN", refresh_token)
        logger.info("Stored Strava refresh token in {}", dotenv_path)
        return

    logger.warning("REFRESH_TOKEN changed but no persistence target is configured")


def setup_strava_auth() -> bool:
    _load_runtime_env()
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.error("CLIENT_ID and CLIENT_SECRET must be in your .env file.")
        return False

    # Initialize client
    client = Client()

    # Get the authorization URL
    auth_url = client.authorization_url(
        client_id=int(client_id), redirect_uri="http://localhost", scope=["read_all", "activity:read_all"]
    )

    # Open browser for the user to authorize
    logger.info("Opening browser for Strava authorization...")
    webbrowser.open(auth_url)

    # After authorization, Strava will redirect to your redirect_uri with a code parameter
    # Copy the entire URL from your browser
    callback_url = input("Paste the URL you were redirected to: ")

    try:
        # Extract the code from the URL
        code = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query)["code"][0]

        # Exchange the code for tokens
        token_response = client.exchange_code_for_token(
            client_id=int(client_id), client_secret=client_secret, code=code
        )

        _persist_refresh_token(refresh_token=token_response["refresh_token"])
        return True

    except Exception as e:
        logger.error(f"Error during authorization: {str(e)}")
        return False


def get_strava_client() -> Client | None:
    _load_runtime_env()
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    refresh_token = _read_refresh_token()

    if not refresh_token:
        logger.info("No refresh token found. Running setup...")
        if not setup_strava_auth():
            return None
        # Reload environment variables after setup
        _load_runtime_env()
        refresh_token = _read_refresh_token()

    if not refresh_token or not client_id or not client_secret:
        raise ValueError("CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN must be in your .env file.")

    client = Client()

    # Exchange refresh token for fresh access token
    refresh_response = client.refresh_access_token(
        client_id=int(client_id), client_secret=client_secret, refresh_token=refresh_token
    )

    # Set the access token on the client
    client.access_token = refresh_response["access_token"]

    # Update the refresh token in .env if it changed
    if refresh_response["refresh_token"] != refresh_token:
        _persist_refresh_token(refresh_token=refresh_response["refresh_token"])

    return client


def stream_last_activity(client: Client) -> SummaryActivity | None:
    try:
        logger.info("Streaming last activity...")
        activity = next(client.get_activities(limit=1))
        return activity
    except Exception as e:
        logger.error(f"Error streaming last activity: {e}")
        return None
