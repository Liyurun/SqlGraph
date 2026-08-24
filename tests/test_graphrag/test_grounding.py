from __future__ import annotations

from sqlgraph.api import build_graph
from sqlgraph.evidence import EvidenceEngine, EvidenceRequest
from sqlgraph.graphrag import GroundedAssertion, validate_assertions


def _evidence():
    graph = build_graph(
        "INSERT INTO dst SELECT id FROM src",
        dialect="spark",
    )
    request = EvidenceRequest(
        task_id="task-1",
        baseline_id="base-1",
        intent="lineage",
        anchors=("src", "dst"),
        max_depth=1,
    )
    return EvidenceEngine(graph).collect(request)


def test_nonexistent_reference_rejects_assertion():
    evidence = _evidence()
    report = validate_assertions(
        [GroundedAssertion(
            statement="dst depends on src",
            citations=("edge_missing",),
            baseline_id=evidence.baseline_id,
            evidence_hash=evidence.subgraph_hash,
        )],
        evidence,
    )

    assert report.status == "rejected"
    assert report.invalid_citations == ("edge_missing",)


def test_valid_reference_is_grounded():
    evidence = _evidence()
    citation = evidence.supporting[0].citations[0]
    report = validate_assertions(
        [GroundedAssertion(
            statement="dst depends on src",
            citations=(citation,),
            baseline_id=evidence.baseline_id,
            evidence_hash=evidence.subgraph_hash,
        )],
        evidence,
    )

    assert report.status == "grounded"
    assert report.valid_assertions == 1


def test_cross_baseline_reference_is_rejected():
    evidence = _evidence()
    citation = evidence.supporting[0].citations[0]
    report = validate_assertions(
        [GroundedAssertion(
            statement="dst depends on src",
            citations=(citation,),
            baseline_id="base-other",
            evidence_hash=evidence.subgraph_hash,
        )],
        evidence,
    )

    assert report.status == "rejected"
    assert report.version_mismatches
