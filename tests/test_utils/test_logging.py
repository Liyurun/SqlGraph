# tests/test_utils/test_logging.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.utils.logging import log_info, log_warn, log_error, log_progress, reset_progress


def test_log_info(capsys):
    log_info("test message")
    captured = capsys.readouterr()
    assert "test message" in captured.out
    assert "[INFO]" in captured.out


def test_log_warn(capsys):
    log_warn("warning message")
    captured = capsys.readouterr()
    assert "warning message" in captured.out
    assert "[WARN]" in captured.out


def test_log_error(capsys):
    log_error("error message")
    captured = capsys.readouterr()
    assert "error message" in captured.out
    assert "[ERROR]" in captured.out


def test_log_progress(capsys):
    reset_progress()
    log_progress(3, 10, prefix="Parsing")
    captured = capsys.readouterr()
    assert "Parsing" in captured.out
    assert "3/10" in captured.out
