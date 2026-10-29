import json
import logging

from enterprise_knowledge.observability.logging import JsonFormatter


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord("eka.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formats_message_level_and_request_id() -> None:
    line = json.loads(JsonFormatter().format(_record(request_id="abc")))

    assert line["message"] == "hello world"
    assert line["level"] == "INFO"
    assert line["logger"] == "eka.test"
    assert line["request_id"] == "abc"


def test_includes_extra_fields_once() -> None:
    line = json.loads(JsonFormatter().format(_record(request_id=None, document_id="doc-1")))

    assert line["document_id"] == "doc-1"
    assert list(line).count("request_id") == 1
