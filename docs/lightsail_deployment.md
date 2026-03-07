# AWS Lightsail Deployment

This guide describes the production deployment for Dia-Run on an Amazon Lightsail Linux instance.

## Target Design

- Single Lightsail instance running Docker and Docker Compose
- WireGuard VPN controls all app access
- FastAPI binds only to the server's WireGuard interface IP
- `./data` stays on the instance disk and syncs with the shared S3 bucket
- Only one runtime may write to the shared data at a time: local or production, never both

## 1. Provision the Server

1. Create an Ubuntu 24.04 Lightsail instance.
2. Attach a static IP.
3. Add only these public firewall rules in Lightsail:
   - TCP `22` for SSH
   - UDP `51820` for WireGuard
4. Do not expose port `8000` publicly.

## 2. Harden SSH

If you uploaded your admin SSH public key during Lightsail instance creation and already logged in successfully, you do not need to copy that same key again. Only add a key manually if you are adding another admin device or rotating keys.

Then update `/etc/ssh/sshd_config`:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
```

Restart SSH:

```bash
sudo systemctl restart ssh
```

## 3. Install Docker and Compose

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git wireguard
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version
```

## 4. Clone the Private Repository

Create a read-only GitHub deploy key and add it to the repository.

```bash
mkdir -p ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/dia-run-deploy -C "dia-run-lightsail" -N ""
cat ~/.ssh/dia-run-deploy.pub
```

Add the public key as a GitHub deploy key with read-only access, then create `~/.ssh/config`:

```text
Host github.com
  IdentityFile ~/.ssh/dia-run-deploy
  IdentitiesOnly yes
```

Clone the repo:

```bash
git clone git@github.com:slac1n/dia_run.git
cd dia_run
```

## 5. Configure WireGuard

Install WireGuard peers for the server, one laptop, and one mobile device.

Example server config at `/etc/wireguard/wg0.conf`:

```ini
[Interface]
Address = 10.44.0.1/24
ListenPort = 51820
PrivateKey = <server-private-key>

[Peer]
PublicKey = <laptop-public-key>
AllowedIPs = 10.44.0.2/32

[Peer]
PublicKey = <mobile-public-key>
AllowedIPs = 10.44.0.3/32
```

Do not use `SaveConfig = true` for this setup. It can rewrite `wg0.conf` on restart and persist transient client `Endpoint` values learned at runtime. The server should usually keep only each peer's `PublicKey` and private WireGuard IP in `AllowedIPs`.

Start WireGuard:

```bash
sudo systemctl enable --now wg-quick@wg0
sudo wg
ip addr show wg0
```

Record the server WireGuard IP. Use that IP as `UVICORN_HOST` in `.env.prod`.

## 6. Configure Production Secrets and Runtime Files

Create the runtime secrets directory:

```bash
mkdir -p secrets data
chmod 700 secrets
```

Place these files on the server:

- `secrets/logindata.json`
- `secrets/strava-refresh-token.txt`

Create `.env.prod` in the repository root. You can copy `.env.prod.example` and fill in the secrets:

```bash
cp .env.prod.example .env.prod
```

Example `.env.prod`:

```dotenv
APP_ENV=production
USE_MOCK_DATA=false
DATA_ROOT=data
CARELINK_TOKEN_FILE=/app/secrets/logindata.json
STRAVA_REFRESH_TOKEN_FILE=/app/secrets/strava-refresh-token.txt

CLIENT_ID=<strava-client-id>
CLIENT_SECRET=<strava-client-secret>

S3_SYNC_ENABLED=true
S3_BUCKET=<shared-bucket-name>
S3_PREFIX=
S3_SYNC_ON_STARTUP=true
S3_SYNC_AFTER_FETCH=true
S3_SYNC_AFTER_QUESTIONNAIRE=true
AWS_REGION=<bucket-region>
AWS_ACCESS_KEY_ID=<iam-access-key-id>
AWS_SECRET_ACCESS_KEY=<iam-secret-access-key>
AWS_PAGER=

UVICORN_HOST=10.44.0.1
UVICORN_PORT=8000
```

Leave `S3_PREFIX` empty if you want to sync against the bucket root.

`.env.prod` must never be committed.

## 7. Configure AWS Credentials

Standard Lightsail instances do not provide EC2-style instance-profile credentials for normal Amazon S3 access. Use a dedicated IAM user with least-privilege access to the target bucket and provide its access key to the production container via `.env.prod`.

Recommended IAM policy for bucket-root sync:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListDiaRunBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<shared-bucket-name>"
    },
    {
      "Sid": "ReadWriteDiaRunBucketObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::<shared-bucket-name>/*"
    }
  ]
}
```

The host AWS CLI can also be configured for troubleshooting, but the application itself needs credentials inside the container. The easiest path is to set these in `.env.prod`:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `AWS_PAGER=`

Verify on the server:

```bash
aws sts get-caller-identity
aws s3 ls "s3://<shared-bucket-name>/"
docker compose -f docker-compose.prod.yml run --rm web aws sts get-caller-identity
docker compose -f docker-compose.prod.yml run --rm web aws s3 ls "s3://<shared-bucket-name>/"
```

## 8. Deploy the Application

Initial deploy:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f web
```

The production compose file uses:

- `restart: always`
- `network_mode: host`
- `UVICORN_HOST` bound to the WireGuard IP only
- runtime-mounted `./data` and `./secrets`
- healthcheck against `/health`

## 9. Manual Deployment Workflow

For each new version:

```bash
ssh <lightsail-host>
cd ~/dia_run
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

This is the documented manual process that can later be automated.

## 10. VPN Access Validation

### Laptop

1. Import the laptop peer config into WireGuard.
2. Connect the tunnel.
3. Visit `http://<wireguard-server-ip>:8000/health`.
4. Confirm the dashboard is reachable only while the tunnel is active.

### Mobile

1. Create a mobile peer in `wg0.conf`.
2. Generate a QR code for the mobile peer config:

```bash
qrencode -t ansiutf8 < mobile.conf
```

3. Import the profile into the WireGuard mobile app.
4. Confirm `http://<wireguard-server-ip>:8000/health` opens only when connected.

## 11. S3 Sync Behavior

- On app startup, the service runs `aws s3 sync s3://... ./data` before serving traffic.
- After a successful fetch, the service runs `aws s3 sync ./data s3://...`.
- After a questionnaire save, the service runs the same upload sync.
- Delta Lake metadata under `_delta_log/` is included because the whole `data` root is synced.

## 12. Single-Instance Rule

The S3 bucket is the shared source of truth, but writes are not coordinated across multiple live app instances.

- Run either local or production against the shared bucket, not both.
- Before switching environments, stop the currently active instance.
- Let the active environment finish its upload sync before starting the other one.

## 13. Recovery Procedure

To rebuild from scratch on a replacement server:

1. Provision a new Lightsail instance and static IP.
2. Reapply SSH hardening and firewall rules.
3. Reinstall Docker, Compose, Git, and WireGuard.
4. Re-add the GitHub deploy key.
5. Restore `.env.prod` and `secrets/`.
6. Recreate the WireGuard server config.
7. Run `docker compose -f docker-compose.prod.yml up -d --build`.
8. Confirm startup sync restores `./data` from S3.

## 14. Operational Checks

Use these commands during support:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 web
curl "http://<wireguard-server-ip>:8000/health"
aws s3 ls "s3://<shared-bucket-name>/<prefix>/"
```
