from __future__ import annotations

from dataclasses import replace

from sqlgraph.api import build_graph
from sqlgraph.evidence import EvidenceEngine, EvidenceRequest


def _request() -> EvidenceRequest:
    return EvidenceRequest(
        task_id="task-1",
        baseline_id="base_1",
        intent="caliber_repair",
        anchors=("src", "dst"),
        direction="both",
        max_depth=1,
        coverage_obligations=(
            "anchors_resolved",
            "lineage_path",
            "counterevidence_checked",
            "no_unresolved",
        ),
    )


def test_evidence_bundle_contains_support_counterevidence_and_exclusions():
    graph = build_graph(
        "INSERT INTO dst SELECT s.id FROM src s JOIN alternate a ON s.id=a.id; "
        "INSERT INTO downstream SELECT id FROM dst;",
        dialect="spark",
    )

    bundle = EvidenceEngine(graph).collect(_request())

    assert bundle.supporting
    assert any(item.kind == "alternative_upstream" for item in bundle.counterevidence)
    assert bundle.coverage_contract["required"]
    assert bundle.subgraph_hash.startswith("evidence_")


def test_removed_required_evidence_cannot_remain_sufficient():
    graph = build_graph(
        "INSERT INTO dst SELECT id FROM src",
        dialect="spark",
    )
    engine = EvidenceEngine(graph)
    bundle = engine.collect(_request())

    stripped = replace(bundle, included_edges=())
    decision = engine.assess(stripped)

    assert not decision.sufficient
    assert decision.action in {"expand", "degrade", "refuse", "escalate"}


def test_expansion_creates_new_version_and_history():
    graph = build_graph(
        "INSERT INTO mid SELECT id FROM src; "
        "INSERT INTO dst SELECT id FROM mid;",
        dialect="spark",
    )
    request = replace(_request(), max_depth=0)
    engine = EvidenceEngine(graph)
    first = engine.collect(request)

    expanded = engine.expand(first, "lineage path not covered")

    assert expanded.version == first.version + 1
    assert expanded.parent_hash == first.subgraph_hash
    assert expanded.history[-1]["reason"] == "lineage path not covered"
