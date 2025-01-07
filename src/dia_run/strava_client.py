"""
Copied from https://github.com/surendranb/runinsight-ai/tree/v2
"""

import os
import time
from datetime import timezone

import stravalib
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")
REDIRECT_URI = "http://localhost:8000/authorized"

# Rate limiting variables
STRAVA_REQUEST_DELAY = 10  # 10 seconds delay between requests


def authenticate_strava(code=None):
    """Authenticates with the Strava API using OAuth 2.0."""
    client = stravalib.Client()
    print("[Strava] Authenticating...")

    # Check if we have a refresh token
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")
    if refresh_token:
        try:
            refresh_response = client.refresh_access_token(
                client_id=STRAVA_CLIENT_ID,
                client_secret=STRAVA_CLIENT_SECRET,
                refresh_token=refresh_token,
            )
            client.access_token = refresh_response["access_token"]
            os.environ["STRAVA_ACCESS_TOKEN"] = client.access_token
            print("[Strava] Authentication successful")
            return client
        except Exception as e:
            print("[Strava] Token refresh failed")
            return None

    # If no refresh token or refresh failed, start the OAuth flow
    authorize_url = client.authorization_url(
        client_id=STRAVA_CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        scope=["read_all", "activity:read_all"],
    )

    print(f"\n[Strava] Please visit this URL to authorize: {authorize_url}")
    code = input("[Strava] Enter the authorization code from the URL: ")

    try:
        token_response = client.exchange_code_for_token(
            client_id=STRAVA_CLIENT_ID, client_secret=STRAVA_CLIENT_SECRET, code=code
        )
        client.access_token = token_response["access_token"]
        os.environ["STRAVA_ACCESS_TOKEN"] = client.access_token
        os.environ["STRAVA_REFRESH_TOKEN"] = token_response["refresh_token"]
        print("[Strava] New authentication successful")
        return client
    except Exception as e:
        print("[Strava] Authentication failed")
        return None


def stream_activities(client, after=None):
    """
    Streams activities one at a time from Strava API.
    Stops when an activity older than the cutoff date is encountered.
    """
    try:
        print("[Strava] Starting activity stream...")
        activity_count = 0
        for activity in client.get_activities():
            activity_count += 1
            activity_date = activity.start_date.replace(tzinfo=timezone.utc)
            if after and activity_date < after:
                print(f"[Strava] Reached cutoff date after {activity_count} activities")
                break
            print(f"[Strava] Processing activity {activity_count}: {activity.id}")
            yield activity
            time.sleep(10)  # 10 second delay between Strava API calls

    except Exception as e:
        print(f"[Strava] Error streaming activities: {e}")
        # st.error(f"Error streaming activities: {e}")


def stream_last_activity(client):
    """
    Streams the last activity from Strava API.
    """
    try:
        logger.info("Streaming last activity...")
        activity = next(client.get_activities(limit=1))
        return activity
    except Exception as e:
        logger.error(f"Error streaming last activity: {e}")
        return None


def process_activity(client, activity_id):
    """Process a single Strava activity."""
    try:
        print(f"[Strava] Fetching details for activity {activity_id}")
        activity = client.get_activity(activity_id)
        if activity:
            print(f"[Strava] Successfully fetched activity {activity_id}")
        return activity
    except Exception as e:
        print(f"[Strava] Error fetching activity {activity_id}: {e}")
        # st.error(f"Error fetching activity {activity_id}: {e}")
        return None
