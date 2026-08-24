from __future__ import annotations

from sqlgraph.api import build_graph
from sqlgraph.evidence import EvidenceEngine, EvidenceRequest


def test_unresolved_column_forces_escalation():
    graph = build_graph(
        "INSERT INTO dst SELECT id FROM left_table l "
        "JOIN right_table r ON l.key = r.key",
        dialect="spark",
    )
    request = EvidenceRequest(
        task_id="ambiguous",
        baseline_id="base_ambiguous",
        intent="caliber_repair",
        anchors=("left_table", "dst"),
        direction="both",
        max_depth=2,
        coverage_obligations=(
            "anchors_resolved",
            "lineage_path",
            "counterevidence_checked",
            "no_unresolved",
        ),
    )

    decision = EvidenceEngine(graph).assess(
        EvidenceEngine(graph).collect(request)
    )

    assert not decision.sufficient
    assert decision.action == "escalate"
    assert "no_unresolved" in decision.missing_obligations
