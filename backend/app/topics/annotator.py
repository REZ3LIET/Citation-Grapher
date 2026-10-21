from __future__ import annotations

import hashlib
import math
import re


TOKEN_RE = re.compile(r"[a-z0-9]+")


class TopicAnnotator:
    """Sentence-transformer annotator with a deterministic offline fallback."""

    def __init__(self, model_name: str, threshold: float):
        self.model_name = model_name
        self.threshold = threshold
        self.backend = "sentence-transformers"
        self._model = None
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name)
        except (ImportError, OSError, RuntimeError):
            self.backend = "local-hash-embedding-fallback-v1"

    @staticmethod
    def _hash_embedding(text: str, dimensions: int = 384) -> list[float]:
        vector = [0.0] * dimensions
        for token in TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if self._model is not None:
            encoded = self._model.encode(texts, normalize_embeddings=True)
            return [list(map(float, row)) for row in encoded]
        return [self._hash_embedding(text) for text in texts]

    def annotate(self, papers: list[dict], topics: list[str]) -> tuple[list[dict], dict]:
        topic_vectors = self._encode(topics)
        eligible: list[tuple[int, str]] = []
        results = [
            {"topics": [], "scores": {}, "status": "unclassified"} for _ in papers
        ]
        for index, paper in enumerate(papers):
            title = (paper.get("title") or "").strip()
            abstract = (paper.get("abstract") or "").strip()
            text = f"{title}. {abstract}".strip()
            if len(TOKEN_RE.findall(text)) >= 3:
                eligible.append((index, text))
        vectors = self._encode([text for _, text in eligible])
        for (paper_index, _), vector in zip(eligible, vectors):
            scores = {
                topic: round(sum(a * b for a, b in zip(vector, topic_vector)), 6)
                for topic, topic_vector in zip(topics, topic_vectors)
            }
            labels = [topic for topic, score in scores.items() if score >= self.threshold]
            results[paper_index] = {"topics": labels, "scores": scores, "status": "classified"}
        metadata = {
            "model": self.model_name if self._model is not None else self.backend,
            "requested_model": self.model_name,
            "backend": self.backend,
            "threshold": self.threshold,
            "similarity": "cosine",
            "interpretation": "heuristic_not_probability",
            "classified": len(eligible),
            "unclassified": len(papers) - len(eligible),
        }
        return results, metadata

