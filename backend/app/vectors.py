import os
import time
from threading import RLock

from sqlalchemy import select

from .config import USER
from .models import Memory, VectorChange
from .source_models import Document, SourceItem


def changed(s, mem, action="upsert"):
    if mem.layer not in ("semantic", "episodic"):
        return
    s.flush()
    change = s.scalar(select(VectorChange).where(VectorChange.memory_id == mem.id))
    if change:
        change.action = action
    else:
        s.add(VectorChange(memory_id=mem.id, layer=mem.layer, action=action))
    s.flush()


class VectorIndex:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = "waiting for first index update" if cfg.vector_enabled else "disabled"
        self.model = None
        self.client = None
        self.collections = {}
        self.lock = RLock()
        self.error_kind=None
        self.retry_at=0.0

    def unavailable(self,exc):
        self.state='unavailable; using SQLite lexical search'
        self.error_kind=type(exc).__name__ + (f' (Windows {exc.winerror})' if getattr(exc,'winerror',None) else '')
        self.retry_at=time.monotonic()+45

    def _open(self, embeddings=True):
        if not self.cfg.vector_enabled and not self.cfg.chroma_dir.exists():
            return False
        try:
            if self.client is None:
                import chromadb
                from chromadb.config import Settings

                self.client = chromadb.PersistentClient(
                    path=str(self.cfg.chroma_dir), settings=Settings(anonymized_telemetry=False)
                )
                for name in ("semantic", "episodic", "document_chunks"):
                    self.collections[name] = self.client.get_or_create_collection(
                        name, metadata={"hnsw:space": "cosine"}, embedding_function=None
                    )
            if embeddings and self.model is None and self.cfg.vector_enabled:
                from sentence_transformers import SentenceTransformer

                os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
                self.model = SentenceTransformer(
                    self.cfg.embedding_model, device=self.cfg.embedding_device, local_files_only=True
                )
                self.state = "ready"
            return not embeddings or self.model is not None
        except Exception as exc:
            self.unavailable(exc)
            return False

    def similarity(self, a, b):
        if self.model is None:
            return 0.0
        try:
            vectors = self.model.encode([a, b], normalize_embeddings=True)
            return float(vectors[0] @ vectors[1])
        except Exception:
            return 0.0

    def drain(self, db, limit=32, repair=False):
        with self.lock:
            if repair or self.cfg.vector_enabled and self.state.startswith("unavailable") and time.monotonic()>=self.retry_at:
                self.error_kind=None
                self.state = (
                    ("ready" if self.model is not None else "waiting for first index update")
                    if self.cfg.vector_enabled
                    else "disabled"
                )
            with db.sessions() as s:
                changes = [
                    (v.id, v.memory_id, v.layer, v.action)
                    for v in s.scalars(
                        select(VectorChange)
                        .order_by(VectorChange.action, VectorChange.created_at)
                        .limit(limit)
                    )
                ]
            if (
                not changes
                and self.cfg.vector_enabled
                and self.cfg.chroma_dir.is_dir()
                and self.state.startswith("waiting")
            ):
                self._open()
            batch = {}
            if (
                self.cfg.vector_enabled
                and not self.state.startswith("unavailable")
                and any(c[3] == "upsert" for c in changes)
                and self._open()
            ):
                with db.sessions() as s:
                    for _, rid, layer, action in changes:
                        if action != "upsert":
                            continue
                        record = s.get(SourceItem if layer == "document_chunks" else Memory, rid)
                        if record and record.status == "active":
                            batch[rid] = record.excerpt if layer == "document_chunks" else record.content
                if batch:
                    try:
                        encoded = self.model.encode(
                            list(batch.values()), batch_size=24, normalize_embeddings=True
                        )
                        batch = {
                            rid: (content, vector.tolist())
                            for (rid, content), vector in zip(batch.items(), encoded, strict=True)
                        }
                    except Exception as exc:
                        self.unavailable(exc)
                        batch.clear()
            for change_id, mem_id, layer, action in changes:
                if action == "delete" and not self.cfg.chroma_dir.exists():
                    pass
                elif action != "delete" and (
                    not self.cfg.vector_enabled or self.state.startswith("unavailable")
                ):
                    continue
                elif not self._open(embeddings=action != "delete"):
                    continue
                try:
                    content, vector = batch.get(mem_id, (None, None))
                    # Serialize final index mutation with SQL writes. A deletion racing an embedding always wins.
                    with db.write() as s:
                        current = s.get(VectorChange, change_id)
                        if not current or current.action != action:
                            continue
                        mem = s.get(SourceItem if layer == "document_chunks" else Memory, mem_id)
                        if action == "delete" or not mem or mem.status != "active":
                            if self.client:
                                self.collections[layer].delete(ids=[mem_id])
                        elif (
                            mem.excerpt if layer == "document_chunks" else mem.content
                        ) == content and vector is not None:
                            metadata = {
                                "user_id": USER,
                                "memory_id": mem_id,
                                "memory_type": layer,
                                "status": "active",
                            }
                            if isinstance(mem, SourceItem):
                                source = s.get(Document, mem.document_id)
                                metadata.update(
                                    document_id=mem.document_id,
                                    document_type=source.kind,
                                    programme=str(mem.value.get("programme", "")),
                                    course_code=str(
                                        mem.value.get("course")
                                        or (
                                            mem.value.get("raw")
                                            if mem.relation
                                            in (
                                                "HAS_COMPLETED_COURSE",
                                                "HAS_CURRICULUM_COURSE",
                                                "CURRENT_COURSE",
                                            )
                                            else ""
                                        )
                                    ),
                                    verification=mem.provenance,
                                )
                            self.collections[layer].upsert(
                                ids=[mem_id],
                                embeddings=[vector],
                                metadatas=[metadata],
                            )
                        else:
                            continue
                        s.delete(current)
                except Exception as exc:
                    self.unavailable(exc)
                    return

    def close(self):
        if self.client and hasattr(self.client, "close"):
            self.client.close()

    def search(self, query, limit=20, filters=None):
        if self.model is None or self.state != "ready":
            return {}
        try:
            vec = self.model.encode(query, normalize_embeddings=True).tolist()
            scores = {}
            clauses = [{"user_id": USER}, *[{k: v} for k, v in (filters or {}).items() if v]]
            where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
            for collection in self.collections.values():
                count = collection.count()
                if count:
                    hits = collection.query(
                        query_embeddings=[vec], n_results=min(count, limit), where=where
                    )
                    scores.update(
                        {
                            key: max(0.0, 1 - distance)
                            for key, distance in zip(hits["ids"][0], hits["distances"][0], strict=True)
                        }
                    )
            return scores
        except Exception as exc:
            self.unavailable(exc)
            return {}
