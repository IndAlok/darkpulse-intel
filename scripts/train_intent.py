from __future__ import annotations

import argparse
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train intent classifier")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/training"),
        help="Directory for training data",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/intent_classifier.joblib"),
        help="Output path for trained model",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Intent Classifier Training")
    logger.info("=" * 60)

    from darkpulse.nlp.intent import IntentClassifier
    from scripts.fetch_gwern_data import generate_training_data

    logger.info("\n[1/3] Generating training data...")
    texts, labels = generate_training_data(args.data_dir)
    logger.info("Generated %d training samples", len(texts))
    logger.info("Label distribution: %s", {label: labels.count(label) for label in set(labels)})

    logger.info("\n[2/3] Training classifier...")
    classifier = IntentClassifier()
    metrics = classifier.train(texts, labels, model_path=args.output)

    logger.info("\n[3/3] Training complete!")
    logger.info(
        "Cross-validation F1 (macro): %.3f (±%.3f)",
        metrics["cv_f1_macro_mean"],
        metrics["cv_f1_macro_std"],
    )
    logger.info("Training F1 (macro): %.3f", metrics["train_f1_macro"])
    logger.info("Model saved to: %s", args.output)

    logger.info("\nSample predictions:")
    test_texts = [
        "MDMA pills available. $50 for 10.",
        "Looking for cocaine vendor in Surat.",
        "Great vendor! Fast shipping.",
        "What's a safe dose of LSD?",
        "Nice weather today.",
    ]
    for text in test_texts:
        intent = classifier.classify(text)
        logger.info("  '%s' -> %s (%.2f)", text[:50], intent.label.value, intent.score)

    logger.info("\n" + "=" * 60)


if __name__ == "__main__":
    main()
