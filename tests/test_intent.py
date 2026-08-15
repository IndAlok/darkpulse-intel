from __future__ import annotations

from darkpulse.models import IntentLabel
from darkpulse.nlp.intent import IntentClassifier, _rule_based_classify


class TestRuleBasedClassification:
    def test_sale_patterns(self, sample_listing: str):
        label, confidence = _rule_based_classify(sample_listing)
        assert label == IntentLabel.SALE
        assert confidence > 0.5

    def test_solicitation_patterns(self, sample_solicitation: str):
        label, confidence = _rule_based_classify(sample_solicitation)
        assert label == IntentLabel.SOLICITATION
        assert confidence > 0.5

    def test_discussion_patterns(self, sample_discussion: str):
        label, confidence = _rule_based_classify(sample_discussion)
        assert label in (IntentLabel.DISCUSSION, IntentLabel.UNRELATED, IntentLabel.SOLICITATION)

    def test_review_patterns(self, sample_review: str):
        label, confidence = _rule_based_classify(sample_review)
        assert label in (IntentLabel.REVIEW, IntentLabel.SALE)

    def test_unrelated_text(self):
        text = "The weather is nice today. Going for a walk in the park."
        label, confidence = _rule_based_classify(text)
        assert label == IntentLabel.UNRELATED


class TestIntentClassifier:
    def test_classify_returns_intent(self, sample_listing: str):
        classifier = IntentClassifier()
        intent = classifier.classify(sample_listing)
        assert hasattr(intent, "label")
        assert hasattr(intent, "score")
        assert isinstance(intent.label, IntentLabel)
        assert 0 <= intent.score <= 1

    def test_classify_batch(self, slang_dict):
        classifier = IntentClassifier()
        texts = [
            "MDMA for sale. $50.",
            "Looking for cocaine vendor.",
            "Great vendor! Fast shipping.",
        ]
        results = classifier.classify_batch(texts)
        assert len(results) == 3
        for intent in results:
            assert hasattr(intent, "label")

    def test_train_and_classify(self, tmp_path):
        classifier = IntentClassifier()

        texts = [
            "MDMA for sale",
            "Cocaine available now",
            "Weed for sale cheap",
            "LSD tabs available",
            "Meth for sale",
            "Heroin available",
            "Xanax bars for sale",
            "Ketamine available",
            "Looking for vendor",
            "Need drugs",
            "Where to buy MDMA",
            "Need cocaine connect",
            "Looking for weed",
            "Need LSD source",
            "Where to find vendor",
            "Need reliable plug",
            "Great experience",
            "Excellent quality product",
            "Fast shipping good vendor",
            "Best MDMA ever",
            "Amazing service",
            "Highly recommended",
            "Perfect transaction",
            "Will buy again",
            "Nice weather today",
            "Going to the park",
            "Watched a movie",
            "Cooking dinner",
            "School homework",
            "Work meeting",
            "Family dinner",
            "Gym workout",
        ]
        labels = ["sale"] * 8 + ["solicitation"] * 8 + ["review"] * 8 + ["unrelated"] * 8

        model_path = tmp_path / "intent_model.joblib"
        metrics = classifier.train(texts, labels, model_path=model_path)

        assert "cv_f1_macro_mean" in metrics
        assert model_path.exists()

        intent = classifier.classify("MDMA pills available")
        assert intent.label in (IntentLabel.SALE, IntentLabel.SOLICITATION)
