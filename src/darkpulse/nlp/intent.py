from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from darkpulse.models import Intent, IntentLabel

logger = logging.getLogger(__name__)


_SALE_PATTERNS = [
    re.compile(r"\b(?:for\s+sale|selling|available|in\s+stock|ready\s+to\s+ship)\b", re.I),
    re.compile(r"\b(?:FE\s+only|finalized?\s+early|escrow)\b", re.I),
    re.compile(r"\b(?:bulk\s+discount|sample\s+available|wholesale)\b", re.I),
    re.compile(r"\b(?:ship\s+worldwide|discrete\s+packaging|stealth\s+shipping)\b", re.I),
    re.compile(r"\b(?:DM\s+for\s+price|PM\s+for\s+details|contact\s+for)\b", re.I),
    re.compile(r"\b(?:limited\s+stock|last\s+few|get\s+yours)\b", re.I),
    re.compile(r"\b(?:menu|price\s+list|catalogue|catalog)\b", re.I),
    re.compile(r"\$\d+(?:\.\d{2})?(?:\s*(?:per|/)\s*(?:g|gram|oz|ounce|pill|tab))?", re.I),
]

_SOLICITATION_PATTERNS = [
    re.compile(r"\b(?:looking\s+for|need|want|searching\s+for|where\s+can\s+I)\b", re.I),
    re.compile(r"\b(?:anyone\s+have|any\s+vendors|connect\s+me|hook\s+me\s+up)\b", re.I),
    re.compile(r"\b(?:DM\s+me|PM\s+me|contact\s+me|reach\s+out)\b", re.I),
    re.compile(r"\b(?:how\s+much|what's\s+the\s+price|pricing)\b", re.I),
    re.compile(r"\b(?:plug|connect|source|supplier)\b", re.I),
]

_DISCUSSION_PATTERNS = [
    re.compile(r"\b(?:tried|experience|trip\s+report|high\s+was)\b", re.I),
    re.compile(r"\b(?:dosage|dose|how\s+much\s+to)\b", re.I),
    re.compile(r"\b(?:safe|test|reagent|purity|quality)\b", re.I),
    re.compile(r"\b(?:addiction|recovery|withdrawal|clean)\b", re.I),
    re.compile(r"\b(?:legal|law|arrested|busted|police)\b", re.I),
]

_REVIEW_PATTERNS = [
    re.compile(r"\b(?:review|rating|score|feedback|10/10|5/5)\b", re.I),
    re.compile(r"\b(?:fast\s+shipping|quick\s+delivery|great\s+vendor)\b", re.I),
    re.compile(r"\b(?:fire|loud|dank|bomb|good\s+shit|best\s+vendor)\b", re.I),
    re.compile(r"\b(?:scam|ripped\s+off|fake|bunk|trash)\b", re.I),
    re.compile(r"\b(?:recommended|trust|reliable|legit)\b", re.I),
]

_UNRELATED_PATTERNS = [
    re.compile(r"\b(?:weather|sports?|movie|music|game|cooking|recipe)\b", re.I),
    re.compile(r"\b(?:school|homework|exam|college|university)\b", re.I),
    re.compile(r"\b(?:job|work|office|meeting|salary)\b", re.I),
    re.compile(r"\b(?:family|kids?|children|wedding|birthday)\b", re.I),
]


def _rule_based_classify(text: str) -> tuple[IntentLabel, float]:
    text_lower = text.lower()

    scores: dict[IntentLabel, int] = {
        IntentLabel.SALE: 0,
        IntentLabel.SOLICITATION: 0,
        IntentLabel.DISCUSSION: 0,
        IntentLabel.REVIEW: 0,
        IntentLabel.UNRELATED: 0,
    }

    for pattern in _SALE_PATTERNS:
        if pattern.search(text_lower):
            scores[IntentLabel.SALE] += 1

    for pattern in _SOLICITATION_PATTERNS:
        if pattern.search(text_lower):
            scores[IntentLabel.SOLICITATION] += 1

    for pattern in _DISCUSSION_PATTERNS:
        if pattern.search(text_lower):
            scores[IntentLabel.DISCUSSION] += 1

    for pattern in _REVIEW_PATTERNS:
        if pattern.search(text_lower):
            scores[IntentLabel.REVIEW] += 1

    for pattern in _UNRELATED_PATTERNS:
        if pattern.search(text_lower):
            scores[IntentLabel.UNRELATED] += 1

    max_score = max(scores.values())
    if max_score == 0:
        return (IntentLabel.UNRELATED, 0.1)

    winner = max(scores, key=lambda k: scores[k])

    total = sum(scores.values())
    confidence = min(0.95, 0.5 + (max_score / total) * 0.5)

    return (winner, confidence)


class IntentClassifier:
    def __init__(self) -> None:
        self._model: Any = None
        self._vectorizer: Any = None
        self._is_trained = False
        self._model_path: Path | None = None

    def load_model(self, model_path: Path | str) -> bool:
        import joblib

        path = Path(model_path)
        if not path.exists():
            logger.warning("Intent model not found at %s — using rule-based only", path)
            return False

        try:
            model_data = joblib.load(path)
            self._model = model_data.get("model")
            self._vectorizer = model_data.get("vectorizer")
            self._is_trained = self._model is not None and self._vectorizer is not None
            self._model_path = path
            logger.info("Loaded intent classifier from %s", path)
            return self._is_trained
        except Exception:
            logger.exception("Failed to load intent model from %s", path)
            return False

    def train(
        self,
        texts: list[str],
        labels: list[str],
        model_path: Path | str | None = None,
    ) -> dict[str, float]:
        import joblib
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import classification_report, f1_score
        from sklearn.model_selection import cross_val_score

        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=50000,
            sublinear_tf=True,
            min_df=2,
        )
        x_train = self._vectorizer.fit_transform(texts)

        self._model = LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            C=1.0,
            solver="lbfgs",
        )
        self._model.fit(x_train, labels)
        self._is_trained = True

        cv_scores = cross_val_score(self._model, x_train, labels, cv=5, scoring="f1_macro")

        predictions = self._model.predict(x_train)
        classification_report(labels, predictions, output_dict=True)

        metrics = {
            "cv_f1_macro_mean": float(cv_scores.mean()),
            "cv_f1_macro_std": float(cv_scores.std()),
            "train_f1_macro": float(f1_score(labels, predictions, average="macro")),
            "train_f1_weighted": float(f1_score(labels, predictions, average="weighted")),
        }

        logger.info(
            "Intent classifier trained: CV F1=%.3f (±%.3f), Train F1=%.3f",
            metrics["cv_f1_macro_mean"],
            metrics["cv_f1_macro_std"],
            metrics["train_f1_macro"],
        )

        if model_path:
            path = Path(model_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(
                {"model": self._model, "vectorizer": self._vectorizer},
                path,
            )
            logger.info("Saved intent classifier to %s", path)

        return metrics

    def classify(self, text: str) -> Intent:
        rule_label, rule_confidence = _rule_based_classify(text)

        if self._is_trained and self._model is not None and self._vectorizer is not None:
            try:
                x_test = self._vectorizer.transform([text])
                ml_label_str = self._model.predict(x_test)[0]
                ml_proba = self._model.predict_proba(x_test)[0]
                ml_confidence = float(max(ml_proba))

                ml_label = IntentLabel(ml_label_str)

                if rule_confidence >= 0.8:
                    final_label = rule_label
                    final_confidence = rule_confidence
                elif ml_confidence >= 0.7:
                    final_label = ml_label
                    final_confidence = ml_confidence
                else:
                    final_label = rule_label
                    final_confidence = rule_confidence * 0.8

                return Intent(label=final_label, score=final_confidence)

            except Exception:
                logger.debug("ML classification failed, using rule-based only")

        return Intent(label=rule_label, score=rule_confidence)

    def classify_batch(self, texts: list[str]) -> list[Intent]:
        return [self.classify(text) for text in texts]
