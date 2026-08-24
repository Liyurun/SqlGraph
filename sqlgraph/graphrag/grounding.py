# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Validate natural-language assertions against an evidence bundle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlgraph.evidence import EvidenceBundle


@dataclass(frozen=True)
class GroundedAssertion:
    statement: str
    citations: tuple[str, ...]
    baseline_id: str
    evidence_hash: str


@dataclass(frozen=True)
class GroundingReport:
    status: str
    assertion_count: int
    valid_assertions: int
    invalid_citations: tuple[str, ...] = ()
    out_of_scope_citations: tuple[str, ...] = ()
    version_mismatches: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "assertion_count": self.assertion_count,
            "valid_assertions": self.valid_assertions,
            "invalid_citations": list(self.invalid_citations),
            "out_of_scope_citations": list(self.out_of_scope_citations),
            "version_mismatches": list(self.version_mismatches),
        }


def validate_assertions(
    assertions: Sequence[GroundedAssertion],
    evidence: EvidenceBundle,
) -> GroundingReport:
    """Reject assertions whose citations cannot be verified in the bundle."""
    allowed = set(evidence.included_nodes) | set(evidence.included_edges)
    excluded = set(evidence.excluded)
    invalid = set()
    out_of_scope = set()
    mismatches = []
    valid = 0

    for index, assertion in enumerate(assertions):
        mismatch = (
            assertion.baseline_id != evidence.baseline_id
            or assertion.evidence_hash != evidence.subgraph_hash
        )
        if mismatch:
            mismatches.append(f"assertion:{index}")
            continue
        if not assertion.citations:
            invalid.add(f"assertion:{index}:missing-citation")
            continue
        assertion_invalid = False
        for citation in assertion.citations:
            if citation in excluded:
                out_of_scope.add(citation)
                assertion_invalid = True
            elif citation not in allowed:
                invalid.add(citation)
                assertion_invalid = True
        if not assertion_invalid:
            valid += 1

    rejected = bool(invalid or out_of_scope or mismatches or valid != len(assertions))
    return GroundingReport(
        status="rejected" if rejected else "grounded",
        assertion_count=len(assertions),
        valid_assertions=valid,
        invalid_citations=tuple(sorted(invalid)),
        out_of_scope_citations=tuple(sorted(out_of_scope)),
        version_mismatches=tuple(mismatches),
    )
