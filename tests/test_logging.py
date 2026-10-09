import logging

from exitvector_agent.logging import setup_logging


def test_setup_logging_creates_json_formatter() -> None:
    logger = setup_logging(name="exitvector.tests", level="INFO")

    assert logger.name == "exitvector.tests"
    assert logger.level == logging.INFO
    assert any(
        isinstance(handler.formatter, logging.Formatter)
        for handler in logger.handlers
    )
