"""SQLAlchemy Core table definitions - the diagram's band-3 schema.

Core rather than the ORM so the SQL stays visible and the user_id filter that FR-12
makes load-bearing cannot be hidden behind a relationship. Postgres is a URL change.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

conversation = Table(
    "conversation",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("title", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("archived_at", String, nullable=True),
    Column("deleted_at", String, nullable=True),
    Column("dataset_version", String, nullable=False),
    Index("idx_conversation_user_updated", "user_id", "updated_at"),
)

message = Table(
    "message",
    metadata,
    Column("id", String, primary_key=True),
    Column("conversation_id", String, ForeignKey("conversation.id"), nullable=False),
    Column("role", String, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("turn_id", String, nullable=True),
    Column("created_at", String, nullable=False),
    UniqueConstraint("conversation_id", "seq", name="uq_message_conversation_seq"),
    Index("idx_message_conversation_seq", "conversation_id", "seq"),
)

# `seq` here is a per-CONVERSATION monotonic event id, not a per-message counter: it is
# the number the SSE `id:` field carries and the number `?after=` takes, which is what
# makes stream resume exact instead of replay-the-whole-message.
message_part = Table(
    "message_part",
    metadata,
    Column("id", String, primary_key=True),
    Column("message_id", String, ForeignKey("message.id"), nullable=False),
    Column("conversation_id", String, ForeignKey("conversation.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("text", Text, nullable=True),
    Column("card_json", JSON, nullable=True),
    Column("chips_json", JSON, nullable=True),
    Column("row_id", String, nullable=True),
    Column("citation_json", JSON, nullable=True),
    UniqueConstraint("conversation_id", "seq", name="uq_part_conversation_seq"),
    Index("idx_part_message_seq", "message_id", "seq"),
)

taste_profile = Table(
    "taste_profile",
    metadata,
    Column("conversation_id", String, ForeignKey("conversation.id"), primary_key=True),
    Column("style", String, nullable=True),
    Column("sweetness", String, nullable=True),
    Column("body", String, nullable=True),
    Column("oak", String, nullable=True),
    Column("tannin", String, nullable=True),
    Column("acidity", String, nullable=True),
    Column("fruit_savoury", String, nullable=True),
    Column("confidence_json", JSON, nullable=False, default=dict),
)

feedback = Table(
    "feedback",
    metadata,
    Column("id", String, primary_key=True),
    Column("message_id", String, ForeignKey("message.id"), nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("row_id", String, nullable=False),
    Column("vote", String, nullable=False),
    Column("created_at", String, nullable=False),
    UniqueConstraint("message_id", "row_id", name="uq_feedback_message_row"),
    Index("idx_feedback_row", "row_id"),
)

transaction_log = Table(
    "transaction_log",
    metadata,
    Column("id", String, primary_key=True),
    Column("conversation_id", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("turn_id", String, nullable=False),
    Column("intent", String, nullable=True),
    Column("intent_confidence", Float, nullable=True),
    Column("model", String, nullable=False),
    Column("engine", String, nullable=False),
    Column("tokens_in", Integer, nullable=False, default=0),
    Column("tokens_out", Integer, nullable=False, default=0),
    Column("cost_usd", Float, nullable=False, default=0.0),
    Column("latency_ms", Integer, nullable=False, default=0),
    Column("status", String, nullable=False),
    Column("error_code", String, nullable=True),
    Column("cache_hit", Boolean, nullable=False, default=False),
    Column("created_at", String, nullable=False),
    Index("idx_transaction_turn", "turn_id"),
    Index("idx_transaction_user_created", "user_id", "created_at"),
)

retrieval_log = Table(
    "retrieval_log",
    metadata,
    Column("id", String, primary_key=True),
    Column("turn_id", String, nullable=False),
    Column("stage", String, nullable=False),
    Column("query_text", Text, nullable=True),
    Column("candidate_row_ids", JSON, nullable=True),
    Column("ranks", JSON, nullable=True),
    Column("scores", JSON, nullable=True),
    Column("created_at", String, nullable=False),
    Index("idx_retrieval_turn", "turn_id"),
)

graph_checkpoint = Table(
    "graph_checkpoint",
    metadata,
    Column("turn_id", String, primary_key=True),
    Column("node", String, primary_key=True),
    Column("state_json", JSON, nullable=False),
    Column("created_at", String, nullable=False),
)

idempotency_key = Table(
    "idempotency_key",
    metadata,
    Column("key", String, primary_key=True),
    Column("endpoint", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("request_hash", String, nullable=False),
    Column("response_json", JSON, nullable=True),
    Column("turn_id", String, nullable=True),
    Column("created_at", String, nullable=False),
    Column("expires_at", String, nullable=False),
)

# Band 3's eval store. Created now so band 2 has somewhere to write; only `feedback`
# above has a writer in this phase.
gold_set = Table(
    "gold_set",
    metadata,
    Column("row_id", String, primary_key=True),
    Column("axis", String, primary_key=True),
    Column("true_value", String, nullable=False),
    Column("labeller", String, nullable=False),
)

retrieval_eval = Table(
    "retrieval_eval",
    metadata,
    Column("id", String, primary_key=True),
    Column("query", Text, nullable=False),
    Column("relevant_row_ids", JSON, nullable=False),
    Column("recall_at_k", Float, nullable=True),
    Column("ndcg_at_10", Float, nullable=True),
)

intent_eval = Table(
    "intent_eval",
    metadata,
    Column("id", String, primary_key=True),
    Column("utterance", Text, nullable=False),
    Column("true_intent", String, nullable=True),
    Column("predicted", String, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("created_at", String, nullable=False),
)
