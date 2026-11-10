"""Initial local records, evidence and SQLite FTS5 index."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE users (
	name VARCHAR NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
)""")
    op.execute("""CREATE TABLE vector_changes (
	memory_id VARCHAR NOT NULL, 
	layer VARCHAR NOT NULL, 
	action VARCHAR NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (memory_id)
)""")
    op.execute("""CREATE TABLE conversations (
	title VARCHAR NOT NULL, 
	synthetic BOOLEAN NOT NULL, 
	closed BOOLEAN NOT NULL, 
	updated_at DATETIME NOT NULL, 
	cleared_at DATETIME, 
	reflected_through DATETIME, 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_conversations_updated_at ON conversations (updated_at)""")
    op.execute("""CREATE INDEX ix_conversations_user_id ON conversations (user_id)""")
    op.execute("""CREATE TABLE memories (
	layer VARCHAR NOT NULL, 
	content TEXT NOT NULL, 
	status VARCHAR NOT NULL, 
	confidence FLOAT NOT NULL, 
	origin VARCHAR NOT NULL, 
	importance FLOAT NOT NULL, 
	manual BOOLEAN NOT NULL, 
	synthetic BOOLEAN NOT NULL, 
	valid_from DATETIME NOT NULL, 
	valid_until DATETIME, 
	updated_at DATETIME NOT NULL, 
	superseded_by VARCHAR(36), 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(superseded_by) REFERENCES memories (id) ON DELETE SET NULL, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_memories_user_id ON memories (user_id)""")
    op.execute("""CREATE INDEX ix_memory_current ON memories (user_id, layer, status)""")
    op.execute("""CREATE TABLE user_settings (
	"values" JSON NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_user_settings_user_id ON user_settings (user_id)""")
    op.execute("""CREATE TABLE episodes (
	id VARCHAR(36) NOT NULL, 
	conversation_id VARCHAR(36) NOT NULL, 
	start_time DATETIME NOT NULL, 
	end_time DATETIME NOT NULL, 
	event_type VARCHAR NOT NULL, 
	topics JSON NOT NULL, 
	details JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE, 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_episodes_conversation_id ON episodes (conversation_id)""")
    op.execute("""CREATE TABLE messages (
	conversation_id VARCHAR(36) NOT NULL, 
	role VARCHAR NOT NULL, 
	content TEXT NOT NULL, 
	details JSON NOT NULL, 
	status VARCHAR NOT NULL, 
	request_key VARCHAR, 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (conversation_id, request_key, role), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_message_thread_time ON messages (conversation_id, created_at)""")
    op.execute("""CREATE INDEX ix_messages_user_id ON messages (user_id)""")
    op.execute("""CREATE TABLE semantic_memories (
	id VARCHAR(36) NOT NULL, 
	subject VARCHAR NOT NULL, 
	predicate VARCHAR NOT NULL, 
	value VARCHAR NOT NULL, 
	scope VARCHAR NOT NULL, 
	category VARCHAR NOT NULL, 
	observed_at DATETIME NOT NULL, 
	last_confirmed_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_semantic_memories_predicate ON semantic_memories (predicate)""")
    op.execute("""CREATE TABLE calendar_events (
	status VARCHAR NOT NULL, 
	source_type VARCHAR NOT NULL, 
	source_id VARCHAR(36), 
	user_confirmed BOOLEAN NOT NULL, 
	cancelled_at DATETIME, 
	sequence INTEGER NOT NULL, 
	title VARCHAR NOT NULL, 
	category VARCHAR NOT NULL, 
	description VARCHAR NOT NULL, 
	local_date VARCHAR, 
	start_utc DATETIME, 
	end_utc DATETIME, 
	all_day BOOLEAN NOT NULL, 
	timezone VARCHAR NOT NULL, 
	importance FLOAT NOT NULL, 
	reason VARCHAR NOT NULL, 
	original_date_text VARCHAR NOT NULL, 
	parsed JSON NOT NULL, 
	confidence FLOAT NOT NULL, 
	synthetic BOOLEAN NOT NULL, 
	updated_at DATETIME NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES messages (id) ON DELETE SET NULL, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_calendar_events_status ON calendar_events (status)""")
    op.execute("""CREATE INDEX ix_calendar_events_user_id ON calendar_events (user_id)""")
    op.execute("""CREATE INDEX ix_event_date ON calendar_events (user_id, local_date)""")
    op.execute("""CREATE TABLE memory_evidence (
	memory_id VARCHAR(36) NOT NULL, 
	message_id VARCHAR(36) NOT NULL, 
	span VARCHAR NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (memory_id, message_id), 
	FOREIGN KEY(memory_id) REFERENCES memories (id) ON DELETE CASCADE, 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_memory_evidence_memory_id ON memory_evidence (memory_id)""")
    op.execute("""CREATE INDEX ix_memory_evidence_message_id ON memory_evidence (message_id)""")
    op.execute("""CREATE TABLE memory_processing_jobs (
	conversation_id VARCHAR(36) NOT NULL, 
	message_id VARCHAR(36), 
	"key" VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	attempts INTEGER NOT NULL, 
	error VARCHAR, 
	available_at DATETIME NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	UNIQUE ("key"), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute(
        """CREATE INDEX ix_memory_processing_jobs_conversation_id ON memory_processing_jobs (conversation_id)"""
    )
    op.execute("""CREATE INDEX ix_memory_processing_jobs_status ON memory_processing_jobs (status)""")
    op.execute("""CREATE INDEX ix_memory_processing_jobs_user_id ON memory_processing_jobs (user_id)""")
    op.execute("""CREATE TABLE persona_assertions (
	id VARCHAR(36) NOT NULL, 
	path VARCHAR NOT NULL, 
	value VARCHAR NOT NULL, 
	scope VARCHAR NOT NULL, 
	semantic_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(id) REFERENCES memories (id) ON DELETE CASCADE, 
	FOREIGN KEY(semantic_id) REFERENCES semantic_memories (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_persona_assertions_path ON persona_assertions (path)""")
    op.execute("""CREATE TABLE calendar_candidates (
	source_id VARCHAR(36) NOT NULL, 
	status VARCHAR NOT NULL, 
	target_id VARCHAR(36), 
	event_id VARCHAR(36), 
	source_key VARCHAR NOT NULL, 
	needs_review BOOLEAN NOT NULL, 
	title VARCHAR NOT NULL, 
	category VARCHAR NOT NULL, 
	description VARCHAR NOT NULL, 
	local_date VARCHAR, 
	start_utc DATETIME, 
	end_utc DATETIME, 
	all_day BOOLEAN NOT NULL, 
	timezone VARCHAR NOT NULL, 
	importance FLOAT NOT NULL, 
	reason VARCHAR NOT NULL, 
	original_date_text VARCHAR NOT NULL, 
	parsed JSON NOT NULL, 
	confidence FLOAT NOT NULL, 
	synthetic BOOLEAN NOT NULL, 
	updated_at DATETIME NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES messages (id) ON DELETE CASCADE, 
	FOREIGN KEY(target_id) REFERENCES calendar_events (id) ON DELETE SET NULL, 
	FOREIGN KEY(event_id) REFERENCES calendar_events (id) ON DELETE SET NULL, 
	UNIQUE (source_key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_calendar_candidates_source_id ON calendar_candidates (source_id)""")
    op.execute("""CREATE INDEX ix_calendar_candidates_user_id ON calendar_candidates (user_id)""")
    op.execute("""CREATE TABLE calendar_event_revisions (
	event_id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(36), 
	operation VARCHAR NOT NULL, 
	snapshot JSON NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(event_id) REFERENCES calendar_events (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_id) REFERENCES messages (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute(
        """CREATE INDEX ix_calendar_event_revisions_event_id ON calendar_event_revisions (event_id)"""
    )
    op.execute(
        """CREATE INDEX ix_calendar_event_revisions_user_id ON calendar_event_revisions (user_id)"""
    )
    op.execute("""CREATE TABLE persona_revisions (
	assertion_id VARCHAR(36) NOT NULL, 
	operation VARCHAR NOT NULL, 
	detail JSON NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(assertion_id) REFERENCES persona_assertions (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)""")
    op.execute("""CREATE INDEX ix_persona_revisions_assertion_id ON persona_revisions (assertion_id)""")
    op.execute("""CREATE INDEX ix_persona_revisions_user_id ON persona_revisions (user_id)""")
    op.execute(
        """CREATE VIRTUAL TABLE memory_search USING fts5(id UNINDEXED, content, tokenize='porter unicode61')"""
    )
    op.execute(
        """CREATE TRIGGER fts_insert AFTER INSERT ON memories BEGIN INSERT INTO memory_search(id,content) VALUES(new.id,new.content); END"""
    )
    op.execute(
        """CREATE TRIGGER fts_update AFTER UPDATE OF content ON memories BEGIN DELETE FROM memory_search WHERE id=old.id; INSERT INTO memory_search(id,content) VALUES(new.id,new.content); END"""
    )
    op.execute(
        """CREATE TRIGGER fts_delete AFTER DELETE ON memories BEGIN DELETE FROM memory_search WHERE id=old.id; END"""
    )


def downgrade():
    op.execute("DROP TABLE memory_search")
    op.drop_table("persona_revisions")
    op.drop_table("calendar_event_revisions")
    op.drop_table("calendar_candidates")
    op.drop_table("persona_assertions")
    op.drop_table("memory_processing_jobs")
    op.drop_table("memory_evidence")
    op.drop_table("calendar_events")
    op.drop_table("semantic_memories")
    op.drop_table("messages")
    op.drop_table("episodes")
    op.drop_table("user_settings")
    op.drop_table("memories")
    op.drop_table("conversations")
    op.drop_table("vector_changes")
    op.drop_table("users")
