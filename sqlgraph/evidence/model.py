# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Versioned evidence contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


EVIDENCE_SCHEMA_VERSION = "evidence-bundle-v1"
EVIDENCE_RULE_VERSION = "evidence-v1"


@dataclass(frozen=True)
class EvidenceRequest:
    task_id: str
    baseline_id: str
    intent: str
    anchors: tuple[str, ...]
    direction: str = "both"
    max_depth: int = 1
    coverage_obligations: tuple[str, ...] = (
        "anchors_resolved",
        "lineage_path",
        "counterevidence_checked",
        "no_unresolved",
    )
    required_external_facts: tuple[str, ...] = ()
    external_facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceFinding:
    kind: str
    summary: str
    citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceBundle:
    task_id: str
    baseline_id: str
    intent: str
    anchors: tuple[str, ...]
    version: int
    included_nodes: tuple[str, ...]
    included_edges: tuple[str, ...]
    excluded: tuple[str, ...]
    supporting: tuple[EvidenceFinding, ...]
    counterevidence: tuple[EvidenceFinding, ...]
    coverage_contract: dict
    gaps: tuple[str, ...]
    residual_unknowns: tuple[str, ...]
    external_facts: tuple[str, ...] = ()
    parent_hash: str | None = None
    history: tuple[dict, ...] = ()
    schema_version: str = EVIDENCE_SCHEMA_VERSION
    rule_version: str = EVIDENCE_RULE_VERSION

    @property
    def subgraph_hash(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "rule_version": self.rule_version,
            "task_id": self.task_id,
            "baseline_id": self.baseline_id,
            "intent": self.intent,
            "anchors": self.anchors,
            "version": self.version,
            "included_nodes": self.included_nodes,
            "included_edges": self.included_edges,
            "excluded": self.excluded,
            "supporting": [asdict(item) for item in self.supporting],
            "counterevidence": [asdict(item) for item in self.counterevidence],
            "coverage_contract": self.coverage_contract,
            "gaps": self.gaps,
            "residual_unknowns": self.residual_unknowns,
            "external_facts": self.external_facts,
            "parent_hash": self.parent_hash,
            "history": self.history,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "evidence_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def version_id(self) -> str:
        return f"{self.task_id}@v{self.version}#{self.subgraph_hash[-12:]}"

    @property
    def node_ids(self) -> set[str]:
        return set(self.included_nodes)

    @property
    def edge_ids(self) -> set[str]:
        return set(self.included_edges)

    @property
    def coverage(self) -> dict:
        return self.coverage_contract

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "rule_version": self.rule_version,
            "task_id": self.task_id,
            "baseline_id": self.baseline_id,
            "intent": self.intent,
            "anchors": list(self.anchors),
            "version": self.version,
            "version_id": self.version_id,
            "subgraph_hash": self.subgraph_hash,
            "included_nodes": list(self.included_nodes),
            "included_edges": list(self.included_edges),
            "excluded": list(self.excluded),
            "supporting": [asdict(item) for item in self.supporting],
            "counterevidence": [asdict(item) for item in self.counterevidence],
            "coverage_contract": self.coverage_contract,
            "gaps": list(self.gaps),
            "residual_unknowns": list(self.residual_unknowns),
            "external_facts": list(self.external_facts),
            "parent_hash": self.parent_hash,
            "history": list(self.history),
        }


@dataclass(frozen=True)
class SufficiencyDecision:
    sufficient: bool
    action: str
    missing_obligations: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    coverage_contract: dict = field(default_factory=dict)
    disclosed_gaps: tuple[str, ...] = ()
    residual_unknowns: tuple[str, ...] = ()

    @property
    def decision(self) -> str:
        return self.action
