# sqlgraph/utils/logging.py
import sys
from datetime import datetime


def _print(level: str, message: str) -> None:
    """带时间戳和级别的实时日志输出"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}", file=sys.stdout, flush=True)


def log_info(message: str) -> None:
    """输出 INFO 级别日志"""
    _print("INFO", message)


def log_warn(message: str) -> None:
    """输出 WARN 级别日志"""
    _print("WARN", message)


def log_error(message: str) -> None:
    """输出 ERROR 级别日志"""
    _print("ERROR", message)


def log_progress(current: int, total: int, prefix: str = "Processing") -> None:
    """输出进度日志（覆盖当前行）"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    pct = (current / total * 100) if total > 0 else 0
    bar_len = 30
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    line = f"[{timestamp}] [{prefix}] |{bar}| {current}/{total} ({pct:.1f}%)"
    print(f"\r{line}", end="", file=sys.stdout, flush=True)
    if current >= total:
        print(file=sys.stdout, flush=True)


def reset_progress() -> None:
    """重置进度条状态"""
    pass


def log_stats(stats: dict) -> None:
    """输出统计信息"""
    _print("STATS", "=" * 50)
    for key, value in stats.items():
        _print("STATS", f"  {key}: {value}")
    _print("STATS", "=" * 50)
