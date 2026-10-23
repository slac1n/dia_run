# Running coach

The coach uses one tool-calling OpenRouter model to discuss running, fueling and glucose,
review activities, and help plan training. The default model is `anthropic/claude-sonnet-5.5`;
`OPENROUTER_MODEL` overrides it. Numerical analysis runs in Python.

## Configuration

```dotenv
COACH_ENABLED=true
OPENROUTER_MODEL=anthropic/claude-sonnet-5.5
COACH_HISTORY_PATH=.local-state/coach/chats.sqlite3
```

Set `OPENROUTER_API_KEY` in the runtime environment, never in tracked files.
Start the app with `uv run uvicorn dia_run.web.app:app --host 127.0.0.1 --reload`
and open `/coach`. `COACH_ENABLED` controls availability in both development and production.
The coach uses the same deployment-level access protection as the rest of the app: WireGuard,
binding to the VPN interface, and keeping port 8000 closed publicly.
The consent checkbox covers sending the current conversation, selected records and relevant
saved notes to OpenRouter and its model provider. Requests require parameter support,
disallow provider data collection, and request zero-data-retention routing; unavailable
compatible endpoints cause an error rather than relaxing these settings.

## Tools and answers

Read-only tools expose:

- `find_activities`: runs filtered by distance, type and dates.
- `get_activity_context`: run details and recorded insulin context.
- `get_glucose_analysis`: CGM samples and Python-calculated statistics.
- `get_fueling_events`: carbohydrate entries, totals and grams per elapsed hour.
- `find_comparable_runs`: candidate runs matched by type, distance and duration.
- `compare_activities`: direct comparison of two to five selected runs.
- `get_training_overview`: a period of up to 90 days and the preceding equal-length period.
- `search_memory`: keyword search over contextual notes, with sources and expiry.

Successfully loaded event logs are treated as complete. Absent fueling or insulin entries
mean no such event; empty fueling entries yield zero intake. Data-access failures remain
errors. Actual CGM gaps remain gaps, never zero-valued glucose readings. The coach should
mention a limitation only when it materially affects the question.

Duration labels use hours and minutes, or minutes below an hour. Values rounded to minute
precision are marked “about.” Glucose percentages describe samples, not elapsed time;
measurements are not interpolated. Tool results include coverage and units. Comparisons
show associations rather than establishing causes. Insulin estimates use linear decay
and are not measured insulin-on-board or dosing calculations.

The model chooses whether to request tools or return an answer on each round. The loop
continues after tool calls and stops when the model returns a final answer that passes
schema, citation and memory-source validation. There is no separate model judging whether
the answer is complete or correct. Evidence references link to the underlying tool results;
valid references alone do not prove that a claim is supported.

Limits default to eight rounds, sixteen tool calls and 180,000 context characters, configured
by `COACH_MAX_ROUNDS`, `COACH_MAX_TOOL_CALLS` and `COACH_MAX_CONTEXT_CHARS`.
Questions have a 4,000-character limit; model outputs have a 4,000-token limit.
`OPENROUTER_TIMEOUT_SECONDS` bounds each request. One extra tool-free call can repair an
invalid answer format within the context limit. Exhausted limits or invalid answers display
an error and preserve the question for retry. Only successful replies are committed.

## Memory

The model may propose up to three useful notes per reply without a separate extraction call.
Each note contains a self-contained text, category, stable key, original user quote, relevant
conversation quote, source conversation and expiry. For example, in a conversation about a
past marathon, “my goal was 3:45h” can become “The user's goal for that marathon was 3:45h,”
with an event name or date included only if the conversation establishes it. A past goal
must not silently become a future target. Ambiguous context calls for clarification.

The text is a model-written summary. Code checks that source quotes occur in the relevant
conversation, but cannot prove that the summary interprets them correctly. Notes remain
user-reported context. The prompt excludes one-off questions, model hypotheses, credentials
and treatment instructions from memory.

Notes expire after 1–180 days (default 90); at most 100 active notes are retained. Matching
keys replace notes, and identical texts are deduplicated. At most five notes enter a new turn,
ranked by keyword overlap with recent goals, schedules and preferences as fallback. Explicit
search returns up to eight notes. Search uses the contextual text and key, not full historical
conversations. Source links allow inspection; there is no automatic full-chat lookup.

The memory panel shows the note and its supporting quotes. Ask the coach to forget a note
or use Forget. Deleting a conversation removes notes sourced from it. Forgetting a note
does not rewrite original conversation messages or evidence snapshots in previous replies.
Memory changes and completed conversation history are committed in one SQLite transaction.

## Storage and access

SQLite stores conversations and memory at `COACH_HISTORY_PATH`, outside the S3-synced
`DATA_ROOT`. The directory is private (0700), and the database is 0600. Storage is plaintext;
filesystem permissions do not provide encryption. There is no automatic database backup
or S3 synchronization. No local database is included in Git or the Docker build context.

This is a single-person application. The deployment network controls access; the cookie is for
CSRF protection, not user authentication. All browsers with app access see the same conversations.
Responses are not cacheable. Logs omit model responses and sensitive validation inputs.
The model cannot execute arbitrary code, SQL, filesystem paths or network requests.
Insulin dosing and individualized diabetes treatment are outside the coach's role.

Production Compose mounts the Docker-managed `coach_state` volume at `/app/state` and
sets `COACH_HISTORY_PATH=/app/state/coach/chats.sqlite3`. Docker creates an empty volume
on the server; nothing is copied from the local computer. Container replacement preserves
the volume. Do not use `docker compose down -v` unless deleting stored conversations is
intentional. Losing the volume or server disk without a backup loses chats and memory.

The server binds to its WireGuard IP, with port 8000 closed to public access.
HTTP traffic to the private server address is carried inside the encrypted WireGuard tunnel.
See [Lightsail deployment](lightsail_deployment.md).

Replies render a small Markdown subset: bold text, paragraphs, bullet/numbered lists and
local evidence links. Raw HTML is escaped; remote links and images are not activated.
This rendering applies to stored replies as well as new replies.

## Tests

`uv run pytest tests/test_coach.py tests/test_coach_integration.py tests/test_coach_access_and_rendering.py` uses synthetic records
and mocked model responses. It covers analysis, tool limits, answer formatting, evidence
references, memory sources, persistence, CSRF protection and failures without external calls.
