from __future__ import annotations

import uuid
from datetime import UTC, datetime

from darkpulse.models import (
    SanitizationStatus,
)
from darkpulse.nlp.pipeline import NLPPipeline
from darkpulse.nlp.slang import SlangDictionary


class MockRawIngest:
    def __init__(self, raw_content: str, source_class: str = "dnm_dataset"):
        self.ingest_id = str(uuid.uuid4())
        self.trace_id = str(uuid.uuid4())
        self.source_class = source_class
        self.source_ref = "test://source"
        self.content_type = "text"
        self.raw_content = raw_content
        self.captured_at = datetime.now(UTC)
        self.lang_hint = "en"
        self.geo_hints = ["Surat"]
        self.source_metadata = {}


class TestNLPPipeline:
    def test_process_clean_content(self):
        slang_dict = SlangDictionary()
        pipeline = NLPPipeline(slang_dictionary=slang_dict)

        record = MockRawIngest("MDMA pills available. $50 for 10.")
        result = pipeline.process(record)

        assert result is not None
        assert result.ingest_id == record.ingest_id
        assert result.sanitization.status != SanitizationStatus.DROPPED

    def test_process_drops_illegal_content(self):
        slang_dict = SlangDictionary()
        pipeline = NLPPipeline(slang_dictionary=slang_dict)

        record = MockRawIngest("child porn available. DM for links.")
        result = pipeline.process(record)

        assert result is None
        assert pipeline.metrics["dropped"] == 1

    def test_process_with_slang(self, slang_dict: SlangDictionary):
        pipeline = NLPPipeline(slang_dictionary=slang_dict)

        record = MockRawIngest("Snow and molly available. Maal bhi hai.")
        result = pipeline.process(record)

        assert result is not None

    def test_process_returns_trafficking_intel(self):
        slang_dict = SlangDictionary()
        pipeline = NLPPipeline(slang_dictionary=slang_dict)

        record = MockRawIngest("Test content")
        result = pipeline.process(record)

        assert result is not None
        assert hasattr(result, "intel_id")
        assert hasattr(result, "severity")
        assert hasattr(result, "intent")
        assert hasattr(result, "sanitization")

    def test_pipeline_metrics(self):
        slang_dict = SlangDictionary()
        pipeline = NLPPipeline(slang_dictionary=slang_dict)

        record = MockRawIngest("Test content")
        pipeline.process(record)

        metrics = pipeline.metrics
        assert "processed" in metrics
        assert "dropped" in metrics
        assert "errors" in metrics
        assert metrics["processed"] >= 1

    def test_trace_id_propagation(self):
        slang_dict = SlangDictionary()
        pipeline = NLPPipeline(slang_dictionary=slang_dict)

        record = MockRawIngest("Test content")
        result = pipeline.process(record)

        assert result.trace_id == record.trace_id
