# Dia-Run :syringe::running:

## Installation
```bash
uv sync
```

### Pre-Commit Hooks
This project uses [pre-commit](https://pre-commit.com/) to run ruff (linting + formatting) and mypy (type checking) automatically before each commit. After installing dependencies, set up the hooks:
```bash
uv run pre-commit install
```

To run all hooks manually against the entire codebase:
```bash
uv run pre-commit run --all-files
```

### Architecture Diagram
This project includes a living Mermaid class diagram that visualises the codebase structure. The diagram is stored in `docs/diagram.mmd`.

To render and view it:
```bash
# Install the Mermaid CLI if you don't have it
npm install -g @mermaid-js/mermaid-cli

# Generate SVG from the diagram
mmdc -i docs/diagram.mmd -o docs/diagram.svg

# Open in your browser
open docs/diagram.svg
```

Alternatively, open `docs/diagram.mmd` directly in VS Code — it has built-in Mermaid preview support.

### Prepare Strava
You need to set up [Strava API](https://developers.strava.com/docs/getting-started/) for you account and create an app.
After that create a `.env` file and fill out the variables `CLIENT_ID` and `CLIENT_SECRET` from your newly created app.
When fetching data for the first time, click on the Strava link provided in the terminal, log in and accept the authorization for downloading data from your account.

### Prepare Carelink
When using Dia-Run for the first time, run the setup for carelink `uv run src/dia_run/carelink_setup.py`.
This will require you to log in to your Carelink account and will automatically create a `logindata.json` file.
This file is valid for about a week.
If you are using Dia-Run regularly this file automatically gets updated. 
If you fail to use it within a week, you will need to recreate the file using the setup script.

## Usage
To get your latest data:
1. Run `uv run fetch` to download Strava and Carelink data
2. Afterwards you will be prompted to fill out the questionnaire about the run (basal setting, pre-run nutrition, fueling, and bolusing)

**Note**: Right now, it only pulls the most recent Strava workout and the last 24 hours of Carelink data.
This means that you should track your runs right after your workout.

### Web UI
Start the FastAPI app:
```bash
uv run uvicorn dia_run.web.app:app --reload
```

Open http://localhost:8000

Key pages:
- Dashboard: `/`
- Activities: `/activities`
- Questionnaire: `/questionnaire`

Use the "Download new data" button on the dashboard to trigger the fetch workflow.

In the questionnaire, each section starts with three blank entries. Use its **Add entry** button
(for example, **Add fueling entry**) for longer runs, and **Remove** to discard a row.
Saved questionnaires load their existing entries when reopened; validation errors retain the submitted values.

### Docker
```bash
docker compose up --build
```

Open http://localhost:8000

Ensure `.env` and `logindata.json` exist locally so the container can authenticate with Strava and CareLink.

### Production Deployment
Production deployment targets AWS Lightsail with Docker Compose, WireGuard-only access, and S3-backed `./data` sync.

- Use `docker-compose.prod.yml` for the production container.
- Keep production secrets in `.env.prod` on the server; do not commit it.
- Mount runtime secrets such as `logindata.json` and the Strava refresh token through `./secrets/` on the server.
- Follow the full provisioning, VPN, deploy, and recovery guide in `docs/lightsail_deployment.md`.

## AWS Backup
```
aws s3 sync ./data s3://dia-run-bucket/ --profile personal --exclude "*/.DS_Store"
```
