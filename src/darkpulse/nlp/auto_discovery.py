from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CandidateTerm:
    term: str
    similar_to: list[str]
    similarity_score: float
    occurrences: int
    context_snippets: list[str] = field(default_factory=list)
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "similar_to": self.similar_to,
            "similarity_score": round(self.similarity_score, 3),
            "occurrences": self.occurrences,
            "context_snippets": self.context_snippets[:5],
            "status": self.status,
        }


class SlangAutoDiscovery:
    def __init__(
        self,
        similarity_threshold: float = 0.7,
        min_occurrences: int = 3,
        max_candidates: int = 100,
        fasttext_model_path: str | None = None,
    ) -> None:
        self._similarity_threshold = similarity_threshold
        self._min_occurrences = min_occurrences
        self._max_candidates = max_candidates
        self._fasttext_model_path = fasttext_model_path

        self._term_counts: dict[str, int] = {}
        self._term_contexts: dict[str, list[str]] = {}

        self._known_terms: set[str] = set()

        self._embeddings: dict[str, np.ndarray[Any, Any]] = {}

        self._candidates: dict[str, CandidateTerm] = {}

        self._model = None
        self._tokenizer = None

    def _load_model(self) -> None:
        if self._model is not None:
            return

        if self._fasttext_model_path is None:
            logger.info("fastText path not configured; auto-discovery embeddings unavailable")
            return

        try:
            import fasttext

            self._model = fasttext.load_model(self._fasttext_model_path)
            logger.info("Loaded fastText model for auto-discovery")
        except Exception:
            logger.warning("fastText not available for auto-discovery")
            self._model = None

    def _get_embedding(self, term: str) -> np.ndarray[Any, Any] | None:
        if term in self._embeddings:
            return self._embeddings[term]

        if self._model is None:
            self._load_model()

        if self._model is None:
            return None

        try:
            embedding = self._model.get_word_vector(term)

            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            self._embeddings[term] = embedding
            return embedding

        except Exception:
            logger.debug("Failed to get embedding for '%s'", term)
            return None

    def _cosine_similarity(self, a: np.ndarray[Any, Any], b: np.ndarray[Any, Any]) -> float:
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

    def set_known_terms(self, terms: set[str]) -> None:
        self._known_terms = terms.copy()

    def observe_term(self, term: str, context: str = "") -> None:
        term_lower = term.lower().strip()

        if len(term_lower) < 3 or len(term_lower) > 30:
            return

        if term_lower in self._known_terms:
            return

        if term_lower in _STOP_WORDS:
            return

        self._term_counts[term_lower] = self._term_counts.get(term_lower, 0) + 1

        if context:
            if term_lower not in self._term_contexts:
                self._term_contexts[term_lower] = []
            if len(self._term_contexts[term_lower]) < 10:
                self._term_contexts[term_lower].append(context[:200])

    def discover_candidates(self) -> list[CandidateTerm]:
        candidate_terms = {
            term: count
            for term, count in self._term_counts.items()
            if count >= self._min_occurrences
        }

        if not candidate_terms:
            return []

        known_embeddings: list[tuple[str, np.ndarray[Any, Any]]] = []
        for term in self._known_terms:
            emb = self._get_embedding(term)
            if emb is not None:
                known_embeddings.append((term, emb))

        if not known_embeddings:
            logger.warning("No known term embeddings available for comparison")
            return []

        new_candidates: list[CandidateTerm] = []

        for term, count in candidate_terms.items():
            term_emb = self._get_embedding(term)
            if term_emb is None:
                continue

            similarities: list[tuple[str, float]] = []
            for known_term, known_emb in known_embeddings:
                sim = self._cosine_similarity(term_emb, known_emb)
                similarities.append((known_term, sim))

            similarities.sort(key=lambda x: x[1], reverse=True)

            top_similarities = similarities[:5]
            max_sim = top_similarities[0][1] if top_similarities else 0.0

            if max_sim >= self._similarity_threshold:
                similar_to = [t for t, _ in top_similarities if _ >= self._similarity_threshold]

                candidate = CandidateTerm(
                    term=term,
                    similar_to=similar_to[:5],
                    similarity_score=max_sim,
                    occurrences=count,
                    context_snippets=self._term_contexts.get(term, []),
                )

                new_candidates.append(candidate)

        new_candidates.sort(
            key=lambda c: c.similarity_score * c.occurrences,
            reverse=True,
        )

        new_candidates = new_candidates[: self._max_candidates]

        for candidate in new_candidates:
            if candidate.term not in self._candidates:
                self._candidates[candidate.term] = candidate
            else:
                existing = self._candidates[candidate.term]
                existing.occurrences = candidate.occurrences
                existing.similarity_score = max(
                    existing.similarity_score,
                    candidate.similarity_score,
                )

        return new_candidates

    def get_all_candidates(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self._candidates.values()]

    def approve_candidate(self, term: str) -> bool:
        if term in self._candidates:
            self._candidates[term].status = "approved"
            return True
        return False

    def reject_candidate(self, term: str) -> bool:
        if term in self._candidates:
            self._candidates[term].status = "rejected"
            return True
        return False

    @property
    def candidate_count(self) -> int:
        return len(self._candidates)

    @property
    def pending_candidates(self) -> int:
        return sum(1 for c in self._candidates.values() if c.status == "pending")


_STOP_WORDS = {
    "the",
    "be",
    "to",
    "of",
    "and",
    "a",
    "in",
    "that",
    "have",
    "i",
    "it",
    "for",
    "not",
    "on",
    "with",
    "he",
    "as",
    "you",
    "do",
    "at",
    "this",
    "but",
    "his",
    "by",
    "from",
    "they",
    "we",
    "say",
    "her",
    "she",
    "or",
    "an",
    "will",
    "my",
    "one",
    "all",
    "would",
    "there",
    "their",
    "what",
    "so",
    "up",
    "out",
    "if",
    "about",
    "who",
    "get",
    "which",
    "go",
    "me",
    "when",
    "make",
    "can",
    "like",
    "time",
    "no",
    "just",
    "him",
    "know",
    "take",
    "people",
    "into",
    "year",
    "your",
    "good",
    "some",
    "could",
    "them",
    "see",
    "other",
    "than",
    "then",
    "now",
    "look",
    "only",
    "come",
    "its",
    "over",
    "think",
    "also",
    "back",
    "after",
    "use",
    "two",
    "how",
    "our",
    "work",
    "first",
    "well",
    "way",
    "even",
    "new",
    "want",
    "because",
    "any",
    "these",
    "give",
    "day",
    "most",
    "us",
    "is",
    "was",
    "are",
    "been",
    "has",
    "had",
    "were",
    "did",
    "being",
    "am",
    "does",
    "done",
    "going",
    "got",
    "hasn",
    "haven",
    "isn",
    "wasn",
    "weren",
    "won",
    "wouldn",
    "shouldn",
    "mustn",
    "needn",
    "mightn",
    "shan",
    "let",
    "here",
    "where",
    "why",
    "much",
    "many",
    "more",
    "very",
    "too",
    "really",
    "still",
    "already",
    "always",
    "never",
    "often",
    "sometimes",
    "usually",
    "actually",
    "probably",
    "maybe",
    "perhaps",
    "sure",
    "right",
    "okay",
    "yes",
    "don",
    "doesn",
    "didn",
    "aren",
    "hadn",
    "couldn",
}
