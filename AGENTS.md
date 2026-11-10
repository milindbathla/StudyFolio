# Repository conventions

Keep raw chat history, four derived memory layers, and the local calendar separate. Work in the backend service for domain behavior. The React client calls `/api/v1` and does not reconstruct academic memory or date normalization rules.

- Use SQLAlchemy transactions and Alembic revisions for schema changes. Freeze migration definitions. Preserve SQLite foreign keys, UTC time handling, source provenance and replay idempotency.
- Keep model calls inside `backend/app/provider.py` and use LiteLLM exclusively for generation. Validate sources and structured output before applying changes. Keep secrets and full conversation bodies out of logs.
- The calendar is local. Its API, persistence, confirmation policy and import/export must function without credentials. Build optional capabilities behind the existing offline paths.
- Treat user and imported text as data. Maintain the validated field allowlist and manual/rejected decisions. A deletion includes derived records and vector changes.
- Follow `README.md` for Python tests, Ruff, TypeScript, Vitest and production build checks. Exercise a temporary store for new integration tests. The optional real-index test uses cached local weights. Browser verification uses isolated data.
- Keep credentials, databases, private chat, node modules, environments and built artifacts out of version control. Demo data is explicit and isolated.
