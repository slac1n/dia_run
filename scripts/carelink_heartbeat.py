"""Nightly CareLink heartbeat script.

Keeps the CareLink access token alive (auto-refreshed on every call) and
validates that the API response still matches the expected schema.

Runs once a day via supercronic inside the ``cron`` Docker service.
Sends an email via AWS SES on any failure. Silent on success.

Usage:
    uv run python scripts/carelink_heartbeat.py
"""

import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
from loguru import logger

from dia_run.data_fetcher.carelink_client import CareLinkClient
from dia_run.data_models.api_responses import CareLinkResponse
from dia_run.settings import settings


def _send_failure_email(*, subject: str, body: str) -> None:
    if settings.heartbeat_email_from is None or settings.heartbeat_email_to is None:
        logger.warning("HEARTBEAT_EMAIL_FROM or HEARTBEAT_EMAIL_TO not set — skipping email notification.")
        return
    if settings.aws_region is None:
        logger.warning("AWS_REGION not set — skipping email notification.")
        return

    try:
        client = boto3.client("ses", region_name=settings.aws_region)
        client.send_email(
            Source=settings.heartbeat_email_from,
            Destination={"ToAddresses": [settings.heartbeat_email_to]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        )
        logger.info("Failure email sent to {}", settings.heartbeat_email_to)
    except Exception as email_exc:
        logger.error("SES send_email failed: {}", email_exc)


def _parse_timestamp(raw: str) -> datetime:
    tz = ZoneInfo(settings.server_timezone)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(tz).replace(tzinfo=None)


def main() -> int:
    tz = ZoneInfo(settings.server_timezone)
    now = datetime.now(tz=tz).replace(tzinfo=None)
    logger.info("carelink-heartbeat starting at {} ({})", now.isoformat(), settings.server_timezone)

    try:
        client = CareLinkClient(tokenFile=str(settings.carelink_token_file))
        if not client.init():
            raise RuntimeError("CareLinkClient.init() returned False — authentication failed")

        raw = client.getRecentData()
        if raw is None:
            raise RuntimeError("CareLinkClient.getRecentData() returned None")

        try:
            resp = CareLinkResponse(**raw)
        except Exception as exc:
            raise RuntimeError(f"CareLinkResponse schema validation failed: {exc}") from exc

        # Summary stats for the logs
        sgs = resp.patientData.sgs
        timestamps = [_parse_timestamp(r.timestamp) for r in sgs if r.timestamp is not None]
        valid_glucose = [r.sg for r in sgs if r.sg is not None]
        newest = max(timestamps) if timestamps else None
        age_min = round((now - newest).total_seconds() / 60, 1) if newest else None

        logger.info(
            "carelink-heartbeat OK — sgs={} readings, valid_glucose={}, markers={}, newest_cgm={}, age={}min",
            len(sgs),
            len(valid_glucose),
            len(resp.patientData.markers),
            newest.isoformat() if newest else "n/a",
            age_min,
        )
        return 0

    except Exception:
        error_detail = traceback.format_exc()
        logger.error("carelink-heartbeat FAILED:\n{}", error_detail)
        _send_failure_email(
            subject="[dia-run] CareLink heartbeat failed",
            body=(
                f"The nightly CareLink heartbeat failed at {now.isoformat()}.\n\n"
                f"Error:\n{error_detail}\n\n"
                "Check the container logs: docker-compose -f docker-compose.prod.yml logs cron"
            ),
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
