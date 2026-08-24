from __future__ import annotations

from pathlib import Path

from tools.check_capabilities import check_capabilities


def test_implemented_capabilities_reference_existing_assets():
    root = Path(__file__).parents[2]

    assert check_capabilities(root) == []
