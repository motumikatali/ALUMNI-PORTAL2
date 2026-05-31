import json
import logging
import sqlite3
from collections import Counter

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    cosine_similarity = None


class SemanticSearch:
    def __init__(self, db_path="database.db", model_name="all-MiniLM-L6-v2"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.model_name = model_name
        self.encoder = None
        if SentenceTransformer is None:
            self.logger.warning("sentence-transformers is not available; falling back to lexical cosine matching.")
        else:
            try:
                self.encoder = SentenceTransformer(self.model_name)
                self.logger.info("Loaded sentence transformer model: %s", self.model_name)
            except Exception as exc:
                self.logger.warning("Sentence transformer failed to load: %s", exc)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _decode_embedding(self, embedding_blob):
        if not embedding_blob:
            return None
        try:
            values = json.loads(embedding_blob)
            return np.array(values, dtype=float)
        except Exception:
            return None

    def _text_to_vector(self, text):
        tokens = [token.lower() for token in (text or "").split() if token.strip()]
        counts = Counter(tokens)
        vocab = sorted(set(tokens))
        vector = np.array([counts[token] for token in vocab], dtype=float)
        if vector.size == 0:
            return np.zeros(1, dtype=float)
        return vector

    def _encode_text(self, text):
        if self.encoder is not None:
            return self.encoder.encode(text, convert_to_numpy=True)
        return self._text_to_vector(text)

    def _cosine_similarity(self, left, right):
        left_array = np.asarray(left, dtype=float).reshape(1, -1)
        right_array = np.asarray(right, dtype=float).reshape(1, -1)
        if cosine_similarity is not None:
            return float(cosine_similarity(left_array, right_array)[0][0])
        denom = float(np.linalg.norm(left_array) * np.linalg.norm(right_array))
        if denom == 0:
            return 0.0
        return float(np.dot(left_array, right_array)[0][0] / denom)

    def search(self, query, documents=None, top_k=5, min_similarity=0.35):
        if not query:
            return []

        if documents is None:
            documents = self._fetch_documents()

        query_embedding = self._encode_text(query)
        if query_embedding is None:
            return []

        scored = []

        for document in documents:
            embedding_blob = document.get("embedding")
            embedding = self._decode_embedding(embedding_blob)
            if embedding is None:
                combined_text = f"{document.get('question', '')} {document.get('answer', '')}".strip()
                if self.encoder is not None:
                    embedding = self._encode_text(combined_text)
                    if embedding is not None:
                        self._store_embedding(document["id"], embedding)
                else:
                    embedding = self._text_to_vector(combined_text)
            if embedding is None:
                continue

            similarity = self._cosine_similarity(query_embedding, embedding)
            if similarity >= min_similarity:
                scored.append({
                    "id": document["id"],
                    "question": document["question"],
                    "answer": document["answer"],
                    "category": document["category"],
                    "source": document["source"],
                    "similarity": similarity,
                })

        scored.sort(key=lambda item: item["similarity"], reverse=True)
        return scored[:top_k]

    def _fetch_documents(self):
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, question, answer, category, source, embedding FROM chatbot_knowledge ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def _store_embedding(self, knowledge_id, embedding):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE chatbot_knowledge SET embedding = ? WHERE id = ?",
                (json.dumps(embedding.tolist()), knowledge_id)
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            self.logger.warning("Failed to store semantic embedding: %s", exc)
