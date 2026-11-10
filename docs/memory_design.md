# Memory design

## Working context

Every message has an immutable ID, conversation, author, UTC timestamp, per-thread position and body. Position breaks timestamp ties in chat, recent context and reflection batches. The recent context builder scans newest first within one conversation, up to the configured age and message count. It stops when another turn would exceed the byte-based estimate of one token per three UTF-8 bytes. It returns the selected turns chronologically. Clearing working context advances a cutoff. The optional compact view returns excerpts from up to four older turns. The persisted conversation stays available after expiry or restart.

## Learning episodes

Significant self-reported difficulty, practice, achievement, goals, study sessions and deadlines can form episodes. The rules identify topics and classify the interaction. Same-type interactions in a conversation can merge within 45 minutes when topics overlap. Replaying a source preserves episode identity. Each episode includes its time bounds, summary, topics, confidence, importance, source spans and extraction metadata. A “yesterday” self-report shifts the occurrence date relative to the source timestamp. A valid model summary can refine a single-source episode when its terms are grounded. Episodes present self-reports with dated provenance, including when the learner later changes a preference.

## Semantic facts and retention

Each semantic fact identifies the learner, a validated academic predicate, a normalized value, optional topical scope, category, explicit/inferred origin, evidence score and validity. Repeated exact values consolidate source evidence. Near-duplicate consolidation combines token overlap and a high embedding similarity threshold inside the same field and scope. Opposing terms and differing numeric values prevent consolidation. The local rules recognize explicit identity, study history, self-reported difficulties, goals, preferences, interests and routines. General questions do not create durable interests.

Active facts can be stable, time-sensitive, or provisional. Academic year and courses have a one-year horizon, short-term goals, reported difficulties and time constraints have a 90-day horizon, and inferred values have a 30-day horizon. Each reconfirmation advances the appropriate horizon. Stable identity fields remain valid until updated. Stale facts are filtered at query time. Superseded facts retain successor links. Rejected and archived facts stay available for inspection. User-directed deletion purges their stored content and index records.

## Persona reflection and conflicts

The persona presents identity, academic profile, goals, learning preferences, behavioral patterns, constraints, and interests. Each field value is a separate assertion. Its semantic fact, message spans, origin, scope, human decisions and revision events are inspectable. General scalar values appear in the nested profile. Scoped values are available in the assertion list for context-specific use.

The optional model returns Pydantic-validated proposals. The server checks the evidence ID, verbatim quote, educational field, quoted value, scope, confidence floor and permitted operation. Sensitive inferred characteristics and unsupported performance labels are excluded. New uncertain observations remain pending. Repeated behavioral observations can become active after three distinct sources across at least two conversations. A confidence number is a heuristic evidence score. It has no probabilistic calibration.

ADD, REPLACE, SUPERSEDE, REMOVE and NO_CHANGE operate on specific assertions. A learner's correction supersedes earlier automatic scalar values in the same scope. An unrelated scope remains independent. Conflicts without a clear correction are pending for review. Manual confirmation or correction protects a value from automatic replacement. Rejection changes both the assertion and its semantic fact. Replaying its evidence preserves the rejection. Confirming a historical value can restore it and records a new decision.

## Selection

SQLite FTS5 uses a Porter tokenizer. Two Chroma collections hold semantic and episodic vectors with opaque memory/user IDs. Chroma stores no raw documents. Local encoders are loaded lazily. The lexical path also normalizes common question words such as “struggled” and “difficulty”. Default ranking weights in `Config.ranking` are lexical 0.50, vector 0.27, confidence 0.09, explicit or manually confirmed 0.06, importance 0.05 and episodic recency 0.03. Session-reference and historical intents adjust the appropriate layer. Style preferences are included selectively. The inspector reports selected IDs, per-factor scores, source messages and exclusions for the bounded candidate pool.
