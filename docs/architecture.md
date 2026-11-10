# Architecture

The source ingestion worker, document vector collection, local Neo4j projection, SQLite fallback and adapted CDF-RAG paths extend the original architecture below. Migrations 0004 and 0005 preserve the original data model. [Upgrade architecture and verification](multi_source_audit.md)

The React application calls a versioned FastAPI API. TanStack Query caches and invalidates server data. The Vite development proxy and production static-file mount both support relative `/api/v1` URLs. All screens read the same single-user workspace.

## Ownership and writes

SQLite owns raw messages, derived memory, evidence relationships, persona history, calendar records, settings, processing jobs and vector mutations. UUIDs identify records. A unique per-conversation position orders messages with identical timestamps. The ORM restricts owned queries to the local user. Foreign keys, WAL, a busy timeout and serialized write transactions keep revisions and evidence consistent. Alembic upgrades run before the server accepts requests. Revision 0001 creates the relational and FTS schema, 0002 adds replay suppression, and 0003 backfills turn order and the reflection cursor for existing conversations.

The orchestrator validates the conversation and request key, appends a timestamped user turn, runs bounded local extraction in a savepoint, and persists a processing job. Local extraction failures leave a queued job and the original turn. Chat commits ingestion before optional model generation. A client request key can be safely retried, including when the user turn committed but the assistant response did not. Reusing a key with different content returns a conflict.

Episodes, semantic facts and persona assertions share indexed lifecycle fields in `memories`. Their joined tables hold layer-specific data. `memory_evidence` links many messages to many memories and stores quoted spans. Persona revisions snapshot individual operations. Calendar proposals link to source messages and target events. Confirmed event revisions store title, date, UTC times, operation and source. Each confirm or correction runs in one transaction.

## Background processing

One persisted job worker claims jobs under a short SQL transaction. Provider calls run outside the write transaction. On restart, running jobs return to the queue. Failures use bounded backoff and stop after three job attempts. The provider makes at most two bounded calls per structured-output request. A manual retry resets attempts. Job status and safe error summaries appear in Settings.

Reflection triggers on a configurable message count, conversation close, explicit request, or hourly local consolidation while the server is running. Each batch includes up to 16 new messages, bounded active assertions and relevant grounded facts. A per-conversation watermark advances when its patch transaction commits. Large backlogs continue in later job iterations. Source reprocessing uses original timestamps and respects rejection, supersession, and deletion decisions.

A separate local indexing worker drains durable SQLite changes. It loads the encoder on demand, upserts vectors by relational ID, and reopens persistent Chroma collections after restart. SQL and Chroma each commit independently. Pending work survives a failure between commits, and retries use the same vector ID. Query results are validated against current SQL records. A model or index failure leaves FTS5 available.

## Read pipeline

Chat and the inspector share the context builder. It checks the current thread's working window, runs FTS5 and optional local vector similarity, and applies date, status, scope and validity rules. Scores combine lexical relevance, vector similarity, source strength, importance and recency. Stable facts receive no recency penalty. Episode queries can use the previous calendar week or last matching conversation. Context budgets include source metadata. The selection and exclusions explain the result. Chat also resolves confirmed calendar dates through the calendar service.

## Privacy and deletion

Deleting a conversation removes its raw history, jobs, and whole derived memories citing it. A multi-source memory is removed conservatively. Surviving raw source turns can be explicitly reprocessed. Linked events, revisions and dependent proposals are purged. Generated replies in other threads that cite removed material are removed. Independently authored user turns remain authoritative.

Forgetting a semantic memory deletes its paired assertion, revision records, evidence and vector. A source-bound digest suppresses recreation of that fact by replaying the same evidence. Rejecting an assertion retains a visible historical decision. The source conversation itself can still be read or explicitly deleted. Erasing the workspace removes conversations and calendar data while preserving user settings. Local exports and OS-level backups are separate copies.

The single-process, single-user design uses localhost and OS file access. It supplies no account login or multi-tenant security boundary. Messages, retrieved content and imports are untrusted. Provider prompts accept data only and expose no executable tools. Validation and error reporting avoid printing secret values or chat text. Remote inference is opt-in.
