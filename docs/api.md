# HTTP API

All product routes use `/api/v1`. The running workspace exposes its generated [OpenAPI schema](http://127.0.0.1:8010/openapi.json) and [interactive documentation](http://127.0.0.1:8010/docs). Use the port printed by your server for other installations. IDs below stand for UUIDs returned by the service. Use JSON request bodies. Successful deletes return HTTP 204. An unknown record returns 404, conflicting operations return 409, and invalid inputs return 422.

## Route inventory

Document routes also use `/api/v1`. Upload multipart form fields `file` and `kind` at `POST /sources/upload`. A 202 response includes an ID and a durable processing status. Poll `GET /sources/{id}` for parsing outcomes, extracted evidence, conflicts and indexing counts.

| Method | Additional routes | Purpose |
| --- | --- | --- |
| GET | `/sources`, `/sources/{id}`, `/sources/{id}/original` | List, review and download private local sources |
| POST | `/sources/{id}/reprocess`, `/sources/{id}/confirm`, `/sources/{id}/rows/{iid}/review` | Reclassify, confirm selected survey fields, or review document extractions |
| DELETE | `/sources/{id}` | Erase the file and its derived evidence |
| GET | `/survey/schema`, `/academic/profile`, `/academic/semesters`, `/academic/courses`, `/curriculum/programmes`, `/curriculum/courses` | Inspect field definitions, academic evidence, and programme requirements |
| POST | `/retrieval/query`, `/retrieval/debug` | Query grounded answers and inspect independent retrieval paths |
| GET | `/graph/status`, `/graph/entities/{entity}/relations` | Check graph availability and bounded neighboring relations |
| POST | `/graph/reindex` | Queue graph reconciliation against SQLite |

For example, confirm a single survey field with `{"version":1,"fields":[{"pointer":"/institution","value":"Example Institute"}]}`. A stale version returns 409. Inspect retrieval with `{"query":"Which college do I attend?"}`. The trace includes `direct`, `semantic`, `lexical`, `graph`, `expansion`, `rrf`, `selected`, `answer` and service states.

| Method | Path | Operation |
| --- | --- | --- |
| GET | `/health`, `/health/details` | Liveness, inference mode, vector status and pending index changes |
| GET, PATCH | `/settings` | Read or update local settings |
| POST, GET | `/conversations` | Create or list conversations. Optional `q` searches titles and message bodies |
| GET, PATCH, DELETE | `/conversations/{cid}` | Read, rename, close, reopen, or erase a conversation |
| POST, GET | `/conversations/{cid}/messages` | Ingest a user-only turn or read persisted messages, optionally matching `q` |
| GET | `/conversations/{cid}/context` | Read recent turns, older excerpts, topics and state |
| POST | `/conversations/{cid}/reflect`, `/conversations/{cid}/reprocess` | Queue reflection or replay original evidence |
| POST | `/chat` | Persist a turn, retrieve context, and return both user and assistant messages |
| GET | `/memory/short-term` | Read the working window, optionally by `conversation_id` |
| DELETE | `/memory/short-term/{cid}` | Advance the working-memory cutoff |
| GET | `/memory/episodes`, `/memory/semantic` | List memories with optional `q` and `status` |
| POST | `/memory/search` | Inspect bounded retrieval, optionally by layer, date range, budget, and conversation |
| POST | `/memory/reflect`, `/persona/reflect` | Queue reflection across conversations |
| POST | `/memory/rebuild` | Repair vector indexing, optionally replay history |
| PATCH, DELETE | `/memory/semantic/{mid}` | Correct, confirm, reject, archive or forget a fact |
| GET | `/memory/{mid}/evidence` | Read source message IDs, timestamps, conversation IDs, and spans |
| GET, PATCH | `/persona` | Read the nested profile and assertions or apply one field operation |
| GET | `/persona/history` | Read revisions, optionally filtered by `assertion_id` |
| POST | `/persona/assertions/{aid}/confirm`, `/persona/assertions/{aid}/reject` | Record a human decision |
| GET, POST | `/calendar/events` | List confirmed events or explicitly create one |
| GET, PATCH, DELETE | `/calendar/events/{eid}` | Read details and revision history, edit, or delete |
| GET | `/calendar/candidates` | List suggestions, defaulting to proposed status |
| POST | `/calendar/candidates/{id}/confirm`, `/calendar/candidates/{id}/reject` | Review a suggestion |
| GET | `/calendar/upcoming` | Confirmed future calendar items |
| GET | `/calendar/export.ics` | Download local events as iCalendar |
| POST | `/calendar/import/csv` | Import CSV text and receive errors per row |
| GET | `/jobs`, `/jobs/{jid}` | Read persisted processing status |
| POST | `/jobs/{jid}/retry` | Retry a failed job with a fresh attempt budget |
| GET | `/debug/retrieval` | Inspect retrieval using `query` and optional `conversation_id` |
| GET | `/data/export` | Download the workspace as JSON |
| DELETE | `/data?confirm=DELETE` | Purge learner data from this workspace |

## Conversation and evidence example

These PowerShell commands exercise the offline write/read path against a running instance. They create a real conversation in the selected workspace.

```powershell
$apiRoot = 'http://127.0.0.1:8010/api/v1'
$thread = Invoke-RestMethod -Method Post -Uri "$apiRoot/conversations" -ContentType 'application/json' -Body '{"title":"Mechanics"}'
$turn = @{ conversation_id=$thread.id; content='I prefer detailed explanations.'; request_key='example-pref-1' } | ConvertTo-Json
$reply = Invoke-RestMethod -Method Post -Uri "$apiRoot/chat" -ContentType 'application/json' -Body $turn
$reply.assistant.details
Invoke-RestMethod -Uri "$apiRoot/persona"
```

`POST /chat` returns `{"user": {...}, "assistant": {...}}`. Both records contain IDs, role, content, status, timestamp and conversation ID. The assistant's `details` object records its mode and selected sources. A selected source includes the memory ID, layer, score, rationale and evidence array. The message's `request_key` is optional and scoped to its conversation. A retry using identical content returns the original response.

A semantic search request can use `{"query":"study preferences","layer":"semantic","budget":1000}`. The response includes `selected`, `excluded`, `tokens` and `budget`. For historical queries, send ISO `start` and `end` civil dates. Manual changes accept a field operation such as `{"operation":"ADD","path":"goals.short_term","value":"Review vector calculus"}`. REPLACE, SUPERSEDE, and REMOVE require a target assertion ID.

## Calendar example

Post a chat turn containing “My physics quiz is on November 19, 2030.” Read `GET /calendar/candidates` and use the returned candidate ID. An unambiguous candidate accepts an empty JSON object at its confirm route. The response is the confirmed event with its revision history. Repeating confirmation returns that event's existing ID. A clarification request accepts the following shape.

```json
{
  "event": {
    "title": "Physics quiz",
    "date": "2030-11-19",
    "time": "09:00",
    "timezone": "Asia/Kolkata",
    "category": "quiz"
  }
}
```

A reschedule with multiple matching confirmed events requires `target_id` from `parsed.possible_targets`. An event's `local_date` is the original civil date, and `start_utc` and `end_utc` are timezone-aware timestamps for timed events. All-day records have no UTC start time. Calendar list filters include `start`, `end`, `category`, `q` and `overdue=true`.

CSV import accepts `{"content":"title,date,category\nStudy session,2030-11-19,milestone\n"}`. Its response includes an `accepted` array of event IDs and an `errors` array of line numbers and explanations. JSON export and ICS export set download headers.
