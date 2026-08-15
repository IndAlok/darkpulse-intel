from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MODELS = {
    "fasttext_lid": {
        "url": "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin",
        "path": "/app/models/lid.176.bin",
        "size_mb": 130,
        "description": "fastText Language Identification model",
    },
}


def download_file(url: str, dest: Path, chunk_size: int = 8192) -> bool:
    import requests

    try:
        logger.info("Downloading %s", url)
        response = requests.get(url, stream=True, timeout=600)
        response.raise_for_status()

        dest.parent.mkdir(parents=True, exist_ok=True)

        total = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0 and downloaded % (10 * 1024 * 1024) < chunk_size:
                        pct = (downloaded / total) * 100
                        logger.info(
                            "Progress: %.1f%% (%d MB / %d MB)",
                            pct,
                            downloaded // (1024 * 1024),
                            total // (1024 * 1024),
                        )

        logger.info("Downloaded %s (%d bytes)", dest.name, downloaded)
        return True

    except Exception:
        logger.exception("Failed to download %s", url)
        return False


def download_fasttext_model() -> bool:
    config = MODELS["fasttext_lid"]
    dest = Path(config["path"])

    if dest.exists():
        logger.info("fastText model already exists at %s", dest)
        return True

    return download_file(config["url"], dest)


def download_hf_model(model_name: str, cache_dir: str | None = None) -> bool:
    try:
        from transformers import AutoModel, AutoTokenizer

        logger.info("Downloading HuggingFace model: %s", model_name)

        AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
        logger.info("Tokenizer downloaded: %s", model_name)

        AutoModel.from_pretrained(model_name, cache_dir=cache_dir)
        logger.info("Model downloaded: %s", model_name)

        return True

    except Exception:
        logger.exception("Failed to download HuggingFace model: %s", model_name)
        return False


def download_spacy_model() -> bool:
    try:
        import spacy

        try:
            spacy.load("xx_ent_wiki_sm")
            logger.info("spaCy xx_ent_wiki_sm already installed")
            return True
        except OSError:
            pass

        logger.info("Downloading spaCy xx_ent_wiki_sm...")
        os.system(f"{sys.executable} -m spacy download xx_ent_wiki_sm")
        return True

    except Exception:
        logger.exception("Failed to download spaCy model")
        return False


def main() -> None:
    logger.info("=" * 60)
    logger.info("DarkPulse NLP — Model Download Script")
    logger.info("=" * 60)

    results = {}

    logger.info("\n[1/3] Downloading fastText LID model...")
    results["fasttext"] = download_fasttext_model()

    muril_enabled = os.environ.get("DOWNLOAD_MURIL", "false").lower() == "true"
    if muril_enabled:
        logger.info("\n[2/3] Downloading MuRIL model...")
        results["muril"] = download_hf_model("google/muril-base-cased")
    else:
        logger.info("\n[2/3] Skipping MuRIL (set DOWNLOAD_MURIL=true to enable)")
        results["muril"] = True

    logger.info("\n[3/3] Downloading spaCy model...")
    results["spacy"] = download_spacy_model()

    logger.info("\n" + "=" * 60)
    logger.info("Download Summary:")
    for name, success in results.items():
        status = "OK" if success else "FAILED"
        logger.info("  %s: %s", name, status)

    failed = [name for name, success in results.items() if not success]
    if failed:
        logger.warning("Some models failed to download: %s", ", ".join(failed))
        logger.warning("The service will use fallback implementations")
    else:
        logger.info("All models downloaded successfully!")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()
