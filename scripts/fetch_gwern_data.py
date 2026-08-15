from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATASET_URLS = {
    "grams_archive_1": {
        "url": "https://archive.org/download/dnmarchives/grams.tar.xz",
        "description": "Grams search engine CSV exports (2014-2015)",
        "size_mb": 500,
        "format": "tar.xz",
    },
    "kilos_reviews": {
        "url": "https://gwern.net/doc/darknet-market/2020-01-13-kilos-6dnms-reviews.csv.xz",
        "description": "Kilos reviews CSV (235K reviews, 6 markets)",
        "size_mb": 23,
        "format": "csv.xz",
    },
    "agora_kaggle": {
        "url": "https://www.kaggle.com/datasets/philipjames11/dark-net-marketplace-drug-data-agora-20142015",
        "description": "Agora marketplace listings (100K+ items)",
        "size_mb": 100,
        "format": "csv",
        "note": "Requires Kaggle CLI: kaggle datasets download -d "
        "philipjames11/dark-net-marketplace-drug-data-agora-20142015",
    },
    "drug_listings": {
        "url": "https://www.kaggle.com/datasets/mhwong2007/drug-listing-dataset",
        "description": "Drug listings from multiple DNMs",
        "size_mb": 50,
        "format": "csv",
        "note": "Requires Kaggle CLI: kaggle datasets download -d mhwong2007/drug-listing-dataset",
    },
}


def download_file(url: str, dest_path: Path, chunk_size: int = 8192) -> bool:
    import requests

    try:
        logger.info("Downloading %s to %s", url, dest_path)
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0 and downloaded % (1024 * 1024) < chunk_size:
                        progress = (downloaded / total_size) * 100
                        logger.info("Download progress: %.1f%%", progress)

        logger.info("Download complete: %s (%d bytes)", dest_path, downloaded)
        return True

    except Exception:
        logger.exception("Failed to download %s", url)
        return False


def extract_tar_xz(archive_path: Path, dest_dir: Path) -> bool:
    import tarfile

    try:
        logger.info("Extracting %s to %s", archive_path, dest_dir)
        with tarfile.open(archive_path, "r:xz") as tar:
            tar.extractall(path=dest_dir)
        logger.info("Extraction complete")
        return True
    except Exception:
        logger.exception("Failed to extract %s", archive_path)
        return False


def extract_xz(file_path: Path, dest_path: Path) -> bool:
    import lzma

    try:
        logger.info("Extracting %s to %s", file_path, dest_path)
        with lzma.open(file_path, "rb") as f_in, open(dest_path, "wb") as f_out:
            while True:
                chunk = f_in.read(8192)
                if not chunk:
                    break
                f_out.write(chunk)
        logger.info("Extraction complete")
        return True
    except Exception:
        logger.exception("Failed to extract %s", file_path)
        return False


def fetch_grams_data(data_dir: Path) -> Path | None:
    grams_dir = data_dir / "grams"
    if grams_dir.exists() and any(grams_dir.glob("*.csv")):
        logger.info("Grams data already exists at %s", grams_dir)
        return grams_dir

    archive_path = data_dir / "grams.tar.xz"

    url = DATASET_URLS["grams_archive_1"]["url"]
    if not download_file(url, archive_path):
        return None

    if not extract_tar_xz(archive_path, data_dir):
        return None

    archive_path.unlink(missing_ok=True)

    return grams_dir if grams_dir.exists() else None


def fetch_kilos_reviews(data_dir: Path) -> Path | None:
    csv_path = data_dir / "kilos_reviews.csv"
    if csv_path.exists():
        logger.info("Kilos reviews already exists at %s", csv_path)
        return csv_path

    xz_path = data_dir / "kilos_reviews.csv.xz"

    url = DATASET_URLS["kilos_reviews"]["url"]
    if not download_file(url, xz_path):
        return None

    if not extract_xz(xz_path, csv_path):
        return None

    xz_path.unlink(missing_ok=True)

    return csv_path if csv_path.exists() else None


def load_grams_listings(grams_dir: Path, max_files: int = 100) -> list[dict[str, str]]:
    listings: list[dict[str, str]] = []
    csv_files = list(grams_dir.rglob("*.csv"))[:max_files]

    for csv_file in csv_files:
        try:
            with open(csv_file, encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    listing = {
                        "name": row.get("name", ""),
                        "description": row.get("description", ""),
                        "price": row.get("price", ""),
                        "vendor": row.get("vendor_name", row.get("vendor", "")),
                        "market": row.get("market_name", row.get("market", "")),
                        "ship_from": row.get("ship_from", ""),
                        "category": row.get("category", ""),
                    }
                    if listing["name"] or listing["description"]:
                        listings.append(listing)
        except Exception:
            logger.warning("Failed to read %s", csv_file)
            continue

    logger.info("Loaded %d listings from %d Grams CSV files", len(listings), len(csv_files))
    return listings


def load_kilos_reviews(csv_path: Path, max_rows: int = 50000) -> list[dict[str, str]]:
    reviews: list[dict[str, str]] = []

    try:
        with open(csv_path, encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break

                review = {
                    "site": row.get("site", ""),
                    "vendor": row.get("vendor", ""),
                    "score": row.get("score", ""),
                    "value_btc": row.get("value_btc", ""),
                    "comment": row.get("comment", ""),
                    "timestamp": row.get("timestamp", ""),
                }
                if review["comment"]:
                    reviews.append(review)
    except Exception:
        logger.exception("Failed to read Kilos reviews from %s", csv_path)

    logger.info("Loaded %d reviews from Kilos CSV", len(reviews))
    return reviews


def prepare_intent_training_data(
    listings: list[dict[str, str]],
    reviews: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []

    for listing in listings:
        name = listing.get("name", "")
        desc = listing.get("description", "")
        price = listing.get("price", "")

        text = f"{name} {desc}".strip()
        if not text:
            continue

        text_lower = text.lower()

        if any(kw in text_lower for kw in ["fe only", "finalized early", "finalize early"]):
            label = "solicitation"
        elif (
            price
            and any(c in price for c in ["$", "€", "£", "btc"])
            or any(
                kw in text_lower for kw in ["for sale", "available", "in stock", "ship", "order"]
            )
        ):
            label = "sale"
        elif any(kw in text_lower for kw in ["review", "rating", "feedback", "recommended"]):
            label = "review"
        else:
            label = "sale"

        texts.append(text[:1000])
        labels.append(label)

    for review in reviews:
        comment = review.get("comment", "").strip()
        if not comment:
            continue

        texts.append(comment[:1000])
        labels.append("review")

    logger.info(
        "Prepared %d training samples: %s",
        len(texts),
        {label: labels.count(label) for label in set(labels)},
    )

    return texts, labels


def generate_training_data(data_dir: Path) -> tuple[list[str], list[str]]:
    data_dir.mkdir(parents=True, exist_ok=True)

    grams_dir = fetch_grams_data(data_dir)
    listings = load_grams_listings(grams_dir) if grams_dir else []

    kilos_path = fetch_kilos_reviews(data_dir)
    reviews = load_kilos_reviews(kilos_path) if kilos_path else []

    if not listings and not reviews:
        logger.warning("No training data available — using synthetic examples")
        return _get_synthetic_training_data()

    return prepare_intent_training_data(listings, reviews)


def _get_synthetic_training_data() -> tuple[list[str], list[str]]:
    texts = [
        "MDMA pills available. 10 for $50. Discrete packaging. Ship worldwide.",
        "High quality cocaine. $80/gram. FE only for trusted buyers.",
        "Weed for sale. OG Kush. $200/oz. Fast shipping.",
        "LSD tabs. 100ug. $10 each. Bulk discounts available.",
        "Crystal meth. Pure. $50/gram. Stealth shipping.",
        "Heroin. #4. $150/gram. Discrete packaging.",
        "Xanax bars. 2mg. $5 each. Minimum order 10.",
        "Ketamine. Medical grade. $60/gram.",
        "Fentanyl patches. 25mcg. $30 each.",
        "Cocaine. Fish scale. $100/gram. Pure.",
        "Looking for MDMA in bulk. Need reliable vendor.",
        "Anyone have good cocaine connect? DM me.",
        "Where can I find quality LSD? Need plug.",
        "Need weed vendor that ships to my area.",
        "Searching for reliable heroin supplier.",
        "Anyone selling Xanax? Need bulk.",
        "Looking for ketamine vendor. DM for details.",
        "Need fentanyl patches. Where to buy?",
        "Want to buy meth. Need connect.",
        "Looking for quality pills. Any vendors?",
        "Tried MDMA last night. Amazing experience. 10/10.",
        "What's a safe dose of LSD for first time?",
        "Cocaine purity testing. How to check quality?",
        "Weed vs hash. Which is better for anxiety?",
        "Meth addiction recovery. Day 30 clean.",
        "Heroin withdrawal timeline. When does it end?",
        "Xanax tolerance. How to reduce dosage?",
        "Ketamine therapy. Legal in my country.",
        "Drug testing. How long to pass urine test?",
        "Psychedelic therapy. Psilocybin research.",
        "Great vendor. Fast shipping. Product was fire.",
        "Excellent quality. 10/10 would recommend.",
        "Scammed. Don't buy from this vendor.",
        "Best MDMA I've ever had. Pure and strong.",
        "Quick delivery. Product exactly as described.",
        "Terrible quality. Bunk product. Avoid.",
        "Reliable vendor. Always comes through.",
        "Amazing service. Discrete packaging.",
        "Product was cut. Not pure as advertised.",
        "Trustworthy seller. Will order again.",
        "Weather is nice today. Going for a walk.",
        "Watched a great movie last night.",
        "School homework is so boring.",
        "Work meeting at 3pm. Can't wait.",
        "Family dinner tonight. Excited.",
        "Playing video games all weekend.",
        "Cooking dinner. Making pasta.",
        "Birthday party tomorrow. So excited.",
        "Going to the gym. Leg day.",
        "Reading a book. Almost finished.",
    ]

    labels = (
        ["sale"] * 10
        + ["solicitation"] * 10
        + ["discussion"] * 10
        + ["review"] * 10
        + ["unrelated"] * 10
    )

    return texts, labels


if __name__ == "__main__":
    import sys

    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/training")
    texts, labels = generate_training_data(data_dir)

    output_path = data_dir / "intent_training_data.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "label"])
        for text, label in zip(texts, labels, strict=False):
            writer.writerow([text, label])

    print(f"Saved {len(texts)} training samples to {output_path}")
