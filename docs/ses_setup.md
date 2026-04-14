# AWS SES Setup (Heartbeat Email Alerts)

One-time setup so the nightly CareLink heartbeat can send failure emails.

## 1. Verify your sender address

In [SES → Verified identities](https://console.aws.amazon.com/ses/home#/verified-identities):

1. **Create identity → Email address** — enter the address you want as the `FROM` sender
2. AWS sends a confirmation email — click the link
3. Status turns **Verified** ✓

> You can use any email you control (e.g. your personal iCloud/Gmail address).

## 2. Grant `ses:SendEmail` to the IAM user

The IAM user whose keys are in `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` needs one extra permission.

1. [IAM → Users](https://console.aws.amazon.com/iam/home#/users) → click the user (e.g. `dia-run-lightsail-s3`)
2. **Permissions → Add permissions → Create inline policy**
3. Paste the JSON below, replacing the ARN with your own region, account ID, and verified address:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "arn:aws:ses:<region>:<account-id>:identity/<your-verified-address>"
    }
  ]
}
```

The exact ARN to use is shown in the AccessDenied error if you run the heartbeat before adding the policy.

## 3. Set env vars on the server

Add to `.env.prod` on the Lightsail instance:

```env
HEARTBEAT_EMAIL_FROM=<your verified sender address>
HEARTBEAT_EMAIL_TO=<where you want alerts>
```

`AWS_REGION`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` are already present — no changes needed there.

## 4. Sandbox vs. production mode

SES starts in **sandbox mode**: you can only send to verified addresses.
Since the heartbeat sends to yourself, sandbox is fine as long as `HEARTBEAT_EMAIL_TO` is the same verified address (or also verified separately).

If you ever need to send to a different address, request production access in [SES → Account dashboard → Request production access](https://console.aws.amazon.com/ses/home#/account).

## 5. Smoke test

```bash
docker compose -f docker-compose.prod.yml exec cron \
  bash -c "CARELINK_TOKEN_FILE=/nonexistent /app/.venv/bin/python /app/scripts/carelink_heartbeat.py"
```

You should receive a failure alert email within a few seconds.
