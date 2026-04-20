from __future__ import annotations

import logging

from briefing.logging_utils import configure_logging


def test_configure_logging_sends_info_to_stdout_and_errors_to_stderr(
    app_settings, capsys
) -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level

    try:
        configure_logging(app_settings)
        logger = logging.getLogger("briefing.test")

        logger.info("info message")
        logger.error("error message")

        captured = capsys.readouterr()
        assert "info message" in captured.out
        assert "error message" not in captured.out
        assert "error message" in captured.err
        assert "info message" not in captured.err

        last_run_text = (
            app_settings.paths.log_dir / app_settings.logging.last_run_file
        ).read_text(encoding="utf-8")
        history_text = (
            app_settings.paths.log_dir / app_settings.logging.history_file
        ).read_text(encoding="utf-8")
        assert "info message" in last_run_text
        assert "error message" in last_run_text
        assert "info message" in history_text
        assert "error message" in history_text
    finally:
        for handler in list(root.handlers):
            handler.close()
        root.handlers.clear()
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
