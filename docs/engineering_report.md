# Studyfolio implementation audit

This report records the original four-layer application baseline. The later ingestion and retrieval upgrade has its own verification results and current schema information. [Multi-source upgrade audit](multi_source_audit.md)

Verified on Windows, November 10, 2026. The production app is running on [127.0.0.1:8010](http://127.0.0.1:8010). The [Vite frontend](http://127.0.0.1:5173) proxies to the same backend. Port 8000 was unavailable on this host, so the ignored local `.env` selects 8010. The source template retains the configurable default of 8000.

## Executed verification

| Check | Result | Evidence |
| --- | --- | --- |
| Full backend suite | **45 passed, 0 failed, 0 skipped** in 80.16 s | Real Chroma and LiteLLM integration flags enabled. Five dependency deprecation warnings from LiteLLM, native bindings and tqdm. |
| Clean base installation | **43 passed, 0 failed, 2 skipped** in 11.68 s | Fresh venv with LiteLLM, Chroma and sentence-transformers absent. Both optional integration cases were skipped. Offline chat also ran directly from the editable install. |
| SQLite | **Passed** | Upgraded a populated 0001 database to 0003, then reran migration on the current schema. Compared ORM columns with migrated tables. Verified order for tied historical messages. The running database reported WAL, `integrity_check = ok`, and zero foreign-key violations. |
| Python quality | **Passed** | Ruff lint and format checks on the backend. |
| React component tests | **7 passed, 0 failed** | Conversation creation, history, empty states, persona evidence, event confirmation, inspector, settings and API errors. |
| TypeScript and build | **Passed** | Strict type checking. Vite emitted a production bundle, with a 108.97 kB gzip JavaScript asset and bundled local fonts. A separate `npm ci` installation also built successfully. |
| Chromium end-to-end | **Passed** | Built UI, real HTTP requests, temporary SQLite database, offline inference, process termination/restart, desktop and 390-pixel mobile layouts. |
| Live services | **Passed** | Both port 8010 and the port 5173 proxy returned Studyfolio health and settings. Chromium opened chat and calendar through both interfaces. The generated API contains 48 operations across 38 paths. |

The verification host ran Python 3.12.10, Node 24.18.0 and npm 11.16.0. The optional integration runs used LiteLLM 1.108.3, ChromaDB 1.5.9 and sentence-transformers 6.0.0.

Git remains on the original `main` branch with no commits. Application files are present in the working tree. Git ignores the virtual environment, local configuration, built assets and browser verification captures.

## Requirements and implementation

| Area | Implemented and exercised |
| --- | --- |
| Chat and raw history | Create, rename, close, reopen, search, revisit, reprocess and delete conversations. Stable IDs, per-thread positions, timestamps, request-key retries, source references and persistent assistant replies. |
| Working memory | Session-scoped selection by age, count and token budget. Clearing or compacting context preserves history. Restart restores the eligible window. |
| Episodic memory | Significant interactions are grouped by topic, event type and time gap. The system stores self-reported descriptions, occurrence times, topics, importance and message evidence. |
| Semantic memory | Normalized facts, subject/predicate/value, scope, evidence, validity, duplicate detection and lifecycle status. Explicit corrections preserve old versions. Rejected evidence is suppressed during replay. |
| Learner persona | Seven structured sections, individual evidence scores, manual corrections, confirmation, rejection, restoration and revision history. Explicit facts, hypotheses and repeatedly supported observations are distinguished. |
| Orchestration and reflection | The source turn, lightweight extraction and durable processing state share an ingestion transaction. Jobs retry after failures and recover after restart. Reflection batches use a timestamp and position cursor. Model output is bounded and validated before changes commit. |
| Retrieval | Persistent semantic and episodic Chroma collections, real local embeddings, SQL-authoritative filtering, FTS5 fallback, configurable ranking weights, source deduplication and a context-budget inspector. |
| Academic calendar | Local date extraction, timezone normalization, ambiguity review, manual CRUD, candidate confirmation/rejection, duplicate prevention, target-specific rescheduling, revisions, month grid, agenda, upcoming/overdue lists, CSV validation and ICS export. |
| User controls | Settings, index repair, history replay, JSON export, calendar export, actual privacy deletion, source navigation and an explicitly seeded synthetic demo workspace. |

### Browser workflow

Chromium created a conversation and sent a learning preference and a physics quiz date. It confirmed the suggestion, rescheduled the quiz through a second chat message, and found exactly one event on the new date. It edited the date again through the calendar dialog. It then corrected the learner preference through the persona screen, opened its history, and followed the semantic memory's source link to the highlighted manual-edit message. A settings change produced a saved-state confirmation.

The test terminated the backend process and started another against the same database. The browser recovered the original chat, corrected persona, and revised calendar event. It also exercised mobile navigation and checked for horizontal overflow. All browser write tests used a temporary workspace.

### Issues fixed during verification

- Assistant source timestamps are encoded before serialization into SQLite JSON. Reloaded reply metadata is checked against the stored JSON.
- Migration 0003 backfills message positions using original insertion order within timestamp ties. History, working context, and multi-batch reflection now handle identical clock values.
- An explicit return to a previously superseded preference creates a new valid interval. Reprocessing older turns preserves the correction and its history.
- Duplicate mentions retain their own evidence links. Replaying a conversation cannot recreate an obsolete proposal after the deadline moves.
- Date-only reschedules preserve existing event time, duration and description. Date interpretation records the source message's timezone.
- Chat drafts are scoped to their conversation. Source links highlight their exact destination after client-side navigation. The Vite proxy follows the configured backend port.

## Architecture and schema

The React client calls FastAPI. The orchestrator uses SQLite as its system of record, a durable job worker for optional extraction/reflection, and an outbox for incremental Chroma updates. Chat retrieves a bounded, provenance-bearing context before responding. Offline replies quote matching saved evidence or report confirmed calendar dates. Configured generation and structured extraction go through LiteLLM. [Architecture and data flow](architecture.md)

| SQLite ownership | Tables |
| --- | --- |
| Workspace and source history | `users`, `user_settings`, `conversations`, `messages` |
| Four-layer memory and provenance | `memories`, `episodes`, `semantic_memories`, `persona_assertions`, `persona_revisions`, `memory_evidence` |
| Durable work and privacy decisions | `memory_processing_jobs`, `vector_changes`, `suppressed_evidence` |
| Calendar | `calendar_candidates`, `calendar_events`, `calendar_event_revisions` |

Working memory is computed from raw messages. The SQLite FTS5 virtual table, its triggers, and Alembic's version table supplement the 16 application tables. The persistent Chroma collections use the relational memory IDs as vector keys. The real-index test wrote both collections, reopened a new application instance, searched existing vectors and verified deletion from Chroma. [Memory design](memory_design.md)

The calendar holds timed events in UTC and all-day events as civil dates. Original expressions, sources and revisions remain inspectable. Calendar management never calls a hosted calendar service. [Calendar design](calendar_design.md)

The J.A.R.V.I.S. review informed bounded working context, selective persona reflection, incremental patches and relevant supplemental retrieval. The inspected revision and its MIT notice are recorded in the repository. [Reference attribution](reference_attribution.md)

## Directory summary

```text
adobe-persona-calendar/
  backend/
    app/
      calendar/       Date interpretation, review, revisions, CSV and ICS
      memory/         Four layers, orchestration, ranking and provenance
      main.py         HTTP API, local origin checks and built-UI serving
      models.py       SQLAlchemy relational schema
      contracts.py    Validated inputs, structured extraction and patches
      responses.py    Public response shapes
      db.py           SQLite sessions, migration entry point and user scope
      provider.py     LiteLLM adapter and deterministic test provider
      vectors.py      Local embeddings, Chroma and vector outbox
      config.py       Environment and defaults
      cli.py          Serve, migrate, demo and cache-model commands
    alembic/versions/ Frozen migrations 0001–0003
    tests/            Unit, integration, replay, migration and transport tests
    pyproject.toml
  frontend/
    src/              React pages, API hooks, styles and Vitest tests
    package.json
    package-lock.json
    vite.config.ts
  scripts/
    start.ps1         Windows launcher
    browser_smoke.py  Real browser and process-restart verification
  docs/               Architecture, memory, calendar, API, attribution and audit
  .env.example
  .gitignore
  AGENTS.md
  README.md
```

The endpoint inventory includes all system, conversation, chat, memory, persona, calendar, job, retrieval-debug and data-management operations. It also includes PowerShell requests and example bodies. [API inventory and examples](api.md)

## Windows PowerShell commands

The current workspace is installed and running. To start it again after stopping the active server:

```powershell
Set-Location "$env:USERPROFILE\OneDrive\Desktop\adobe-persona-calendar"
.\.venv\Scripts\python.exe -m app.cli serve
```

For a fresh installation from these sources:

```powershell
Set-Location "$env:USERPROFILE\OneDrive\Desktop\adobe-persona-calendar"
python --version
node --version
if (!(Test-Path .\.venv\Scripts\python.exe)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -e "./backend[dev]"
if (!(Test-Path .env)) { Copy-Item .env.example .env }
$env:APP_PORT = '8010'
Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location
.\.venv\Scripts\python.exe -m app.cli migrate
.\.venv\Scripts\python.exe -m app.cli serve
```

The compiled frontend is served by this single process. For development, open a second PowerShell window:

```powershell
Set-Location "$env:USERPROFILE\OneDrive\Desktop\adobe-persona-calendar\frontend"
$env:APP_PORT = '8010'
npm.cmd run dev
```

For a repeat of the complete verification with optional packages:

```powershell
Set-Location "$env:USERPROFILE\OneDrive\Desktop\adobe-persona-calendar"
.\.venv\Scripts\python.exe -m pip install -e "./backend[dev,ai,vectors]"
.\.venv\Scripts\python.exe -m app.cli cache-model
$env:TEST_LOCAL_VECTORS = '1'
$env:TEST_LOCAL_LITELLM = '1'
$env:HF_HUB_OFFLINE = '1'
Push-Location backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m ruff format --check .
Pop-Location
Push-Location frontend
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
Pop-Location
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe scripts\browser_smoke.py
```

To enable remote inference, set `LLM_ENABLED=true`, `LLM_MODEL` to a provider/model identifier your account can use, and that provider's credential in the local environment. Restart the server. Selected conversation content and relevant context are sent to that provider. [Setup and configuration](../README.md)

## Limitations and unverified components

- Hosted-provider authentication, model availability, answer quality and real-provider extraction quality were not tested. The real LiteLLM transport was exercised against a deterministic loopback HTTP endpoint for chat, structured extraction and reflection.
- The embedding weights were already cached on this host. The cold model download and an unattended hour-long consolidation interval were not exercised.
- Offline chat retrieves evidence and parses common English academic statements. Open-ended tutoring and general natural-language interpretation require a configured model.
- The optional week grid is unimplemented. Calendar views include month, agenda, upcoming and overdue. The editor supports individual events and same-day timed intervals. In-app notifications require the application to be open.
- The intended deployment is one learner and one application process on localhost. Confidence is a heuristic, the context budget uses a token estimate, and the ranked candidate pool is bounded.
- Windows desktop and emulated mobile Chromium were verified. Native mobile clients, other browsers and other operating systems were not exercised.
