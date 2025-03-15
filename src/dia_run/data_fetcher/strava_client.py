import os
import urllib.parse
import webbrowser

from dotenv import find_dotenv, load_dotenv, set_key
from loguru import logger
from stravalib.client import Client
from stravalib.model import SummaryActivity


def setup_strava_auth() -> bool:
    dotenv_path = find_dotenv()
    load_dotenv(dotenv_path)
    CLIENT_ID = os.getenv("CLIENT_ID")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET")

    if not CLIENT_ID or not CLIENT_SECRET:
        logger.error("CLIENT_ID and CLIENT_SECRET must be in your .env file.")
        return False

    # Initialize client
    client = Client()

    # Get the authorization URL
    auth_url = client.authorization_url(
        client_id=int(CLIENT_ID), redirect_uri="http://localhost", scope=["read_all", "activity:read_all"]
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
            client_id=int(CLIENT_ID), client_secret=CLIENT_SECRET, code=code
        )

        # Update the .env file with the refresh token
        set_key(dotenv_path, "REFRESH_TOKEN", token_response["refresh_token"])
        logger.info("Success! REFRESH_TOKEN has been added to your .env file.")
        return True

    except Exception as e:
        logger.error(f"Error during authorization: {str(e)}")
        return False


def get_strava_client() -> Client | None:
    dotenv_path = find_dotenv()
    load_dotenv(dotenv_path)
    CLIENT_ID = os.getenv("CLIENT_ID")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET")
    REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

    if not REFRESH_TOKEN:
        logger.info("No refresh token found. Running setup...")
        if not setup_strava_auth():
            return None
        # Reload environment variables after setup
        load_dotenv(dotenv_path)
        REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

    if not REFRESH_TOKEN or not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN must be in your .env file.")

    client = Client()

    # Exchange refresh token for fresh access token
    refresh_response = client.refresh_access_token(
        client_id=int(CLIENT_ID), client_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN
    )

    # Set the access token on the client
    client.access_token = refresh_response["access_token"]

    # Update the refresh token in .env if it changed
    if refresh_response["refresh_token"] != REFRESH_TOKEN:
        set_key(dotenv_path, "REFRESH_TOKEN", refresh_response["refresh_token"])
        logger.info("Your refresh token has been updated in the .env file.")

    return client


def stream_last_activity(client: Client) -> SummaryActivity | None:
    try:
        logger.info("Streaming last activity...")
        activity = next(client.get_activities(limit=1))
        return activity
    except Exception as e:
        logger.error(f"Error streaming last activity: {e}")
        return None
