---
name: taiga-workflow
description: Workflow for starting work on a Taiga user story - fetches details, sets status, creates branch, and drafts an implementation plan
---

## Purpose

This skill drives the workflow for starting work on a Taiga user story. It is triggered by the `/taiga` command which provides the story details and branch name as context.

## Workflow

When this skill is loaded, the command prompt already contains:
- The full user story detail (from `uv run taiga <tag>`)
- The suggested branch name (from `uv run taiga <tag> --branch-name`)

Execute these steps in order:

### 1. Review the user story

Read the story detail provided in the prompt. Summarise it back to the user:
- Ticket ref and subject
- Current status
- Description / acceptance criteria

### 2. Set the story to "In progress"

Run the following command to move the story to "In progress" on Taiga:

```
uv run taiga <tag> --set-in-progress
```

Replace `<tag>` with the ticket tag from the prompt (e.g. `TG-23`).

Confirm to the user that the status was updated.

### 3. Create the feature branch

The branch name is already provided in the prompt. First, ensure you are on the latest `develop` branch:

```
git checkout develop && git pull origin develop
```

Then create and checkout the feature branch from `develop`:

```
git checkout -b <branch-name>
```

Use the exact branch name from the prompt output (e.g. `feat/TG-23-add-glucose-overlay`).

If the branch already exists, check it out instead of creating it.

### 4. Draft an implementation plan

Based on the user story description and the project structure in `AGENTS.md`:

- Use the **TodoWrite** tool to create a structured implementation plan
- Break the work into concrete, actionable tasks
- Reference specific files and modules from the project structure where relevant
- Do **not** commit the plan to a file — it stays in the TodoWrite tool only

### 5. Summarise

Print a summary for the user:
- Ticket ref, subject, and link
- Branch name (now checked out)
- Number of planned tasks
- Ask if the user wants to start on the first task

## Important notes

- The Taiga CLI (`uv run taiga`) is defined in `src/dia_run/taiga/taiga_client.py`
- Auth tokens are read from `.env` as `TAIGA_AUTH_TOKEN` and `TAIGA_REFRESH_TOKEN`
- Use `uv run taiga --login` to authenticate interactively and set up these tokens
- Project slug is read from `.env` as `TAIGA_PROJECT_SLUG` (default: `slac1n-dia-run`)
- Branch naming convention: `feat/TG-{number}-{slugified-subject}`
- Only user stories are supported (not issues, tasks, or epics)
