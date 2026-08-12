#!/usr/bin/env python3
"""Fail if tracked files contain internal deployment or credential material."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]

DENIED_PATHS = {
    "df.csv",
    "examples/df.csv",
    "examples/table_ddl.csv",
    "success_case.yml",
    "span.log",
    "docs/opensource-application.md",
    "docs/patent-disclosure.md",
    "deploy/tce/cluster-info.default.json",
}

DENIED_PREFIXES = (
    ".bytefaas_home/",
    ".opensource-audit/",
    ".tools/",
    "deploy/tce/",
    "docs/superpowers/",
)

TEXT_DENYLIST = (
    (
        "internal domain",
        re.compile(
            r"code\.byted|byted\.org|bytedance\.net|tiktok-row\.org|"
            r"sg-fn\.tiktok-row\.net|tosv\.byted|adseek-code\.tiktok-row\.org",
            re.IGNORECASE,
        ),
    ),
    (
        "internal deployment",
        re.compile(
            r"\b(bytefaas|bytedcli|bytedtos|bytedpypi|BytePaaS|TCE|TOS_|"
            r"toutiao\.tos|tiktok\.ad_data|tiktok/ad_data|plpysn)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "credential marker",
        re.compile(
            r"service_account_token\s*=|client_secret\s*=|X-Jwt-Token|"
            r"Authorization\s*[:=]\s*['\"]?Bearer|TOS_(AK|SK|ACCESS_KEY|SECRET_KEY)|"
            r"\btos_(ak|sk)\b",
            re.IGNORECASE,
        ),
    ),
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [item for item in result.stdout.decode("utf-8").split("\0") if item]


def _is_binary(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return True
    return b"\0" in sample


def _line_allowed(rel: str, line: str) -> bool:
    # Public copyright headers are expected even after internal deployment
    # adapters have been removed.
    if "Copyright (c) 2026 ByteDance Ltd. and/or its affiliates" in line:
        return True
    if rel == ".gitignore":
        stripped = line.strip()
        if stripped in DENIED_PATHS or any(
            stripped == prefix or stripped == prefix.rstrip("/")
            for prefix in DENIED_PREFIXES
        ):
            return True
    return False


def main() -> int:
    failures: list[str] = []
    for rel in _tracked_files():
        if rel == "scripts/opensource_guard.py":
            continue
        path = ROOT / rel
        if not path.exists():
            continue
        if rel in DENIED_PATHS or any(rel.startswith(prefix) for prefix in DENIED_PREFIXES):
            failures.append(f"{rel}: denied tracked path")
            continue

        if not path.exists() or _is_binary(path):
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _line_allowed(rel, line):
                continue
            for label, pattern in TEXT_DENYLIST:
                if pattern.search(line):
                    failures.append(f"{rel}:{line_number}: {label}: {line.strip()[:160]}")

    if failures:
        print("Open-source guard failed. Remove or privatize these tracked items:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("Open-source guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
