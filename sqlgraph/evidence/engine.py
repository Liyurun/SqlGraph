# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Evidence collection, expansion, and sufficiency decisions."""

from __future__ import annotations

from collections import deque
from dataclasses import replace

from sqlgraph.evidence.model import (
    EvidenceBundle,
    EvidenceFinding,
    EvidenceRequest,
    SufficiencyDecision,
)
from sqlgraph.model import EdgeType, TableNode


class EvidenceEngine:
    def __init__(self, graph):
        self.graph = graph
        self._edges = {edge.id: edge for edge in graph.edges}

    def collect(self, request: EvidenceRequest) -> EvidenceBundle:
        if request.direction not in {"upstream", "downstream", "both"}:
            raise ValueError("direction must be upstream, downstream, or both")
        if request.max_depth < 0:
            raise ValueError("max_depth must be non-negative")

        anchor_nodes = [
            self.graph.get_node_by_name(anchor)
            for anchor in request.anchors
        ]
        resolved_anchors = tuple(
            node.id for node in anchor_nodes if isinstance(node, TableNode)
        )
        table_ids = self._grow_tables(
            set(resolved_anchors),
            request.direction,
            request.max_depth,
        )
        included_nodes, included_edges = self._collect_detail(table_ids)
        excluded = tuple(sorted(
            edge.id
            for edge in self.graph.edges
            if edge.id not in included_edges
            and (
                edge.source_id in included_nodes
                or edge.target_id in included_nodes
            )
        ))

        supporting = tuple(
            EvidenceFinding(
                kind="lineage",
                summary="included table lineage edge",
                citations=(edge.id,),
            )
            for edge in self.graph.edges
            if edge.edge_type == EdgeType.TABLE_LINEAGE
            and edge.id in included_edges
        )
        counterevidence = self._counterevidence(request, resolved_anchors)
        residual_unknowns = tuple(sorted(
            node.id
            for node in self.graph.nodes
            if node.id in included_nodes
            and (
                getattr(node, "name", "") == "UNKNOWN"
                or getattr(node, "resolution", "") == "unresolved"
            )
        ))
        gaps = []
        if len(resolved_anchors) != len(request.anchors):
            gaps.append("one or more anchors could not be resolved")
        if residual_unknowns:
            gaps.append("included evidence contains unresolved physical columns")
        missing_external = sorted(
            set(request.required_external_facts) - set(request.external_facts)
        )
        if missing_external:
            gaps.append("required external facts are missing")

        coverage_contract = {
            "required": list(request.coverage_obligations),
            "resolved_anchors": list(resolved_anchors),
            "anchor_names": list(request.anchors),
            "direction": request.direction,
            "max_depth": request.max_depth,
            "required_external_facts": list(request.required_external_facts),
            "missing_external_facts": missing_external,
        }
        return EvidenceBundle(
            task_id=request.task_id,
            baseline_id=request.baseline_id,
            intent=request.intent,
            anchors=request.anchors,
            version=1,
            included_nodes=tuple(sorted(included_nodes)),
            included_edges=tuple(sorted(included_edges)),
            excluded=excluded,
            supporting=supporting,
            counterevidence=counterevidence,
            coverage_contract=coverage_contract,
            gaps=tuple(gaps),
            residual_unknowns=residual_unknowns,
            external_facts=request.external_facts,
        )

    def expand(self, bundle: EvidenceBundle, reason: str) -> EvidenceBundle:
        contract = bundle.coverage_contract
        request = EvidenceRequest(
            task_id=bundle.task_id,
            baseline_id=bundle.baseline_id,
            intent=bundle.intent,
            anchors=bundle.anchors,
            direction=contract["direction"],
            max_depth=int(contract["max_depth"]) + 1,
            coverage_obligations=tuple(contract["required"]),
            required_external_facts=tuple(
                contract.get("required_external_facts", ())
            ),
            external_facts=bundle.external_facts,
        )
        expanded = self.collect(request)
        return replace(
            expanded,
            version=bundle.version + 1,
            parent_hash=bundle.subgraph_hash,
            history=bundle.history + ({
                "from_version": bundle.version,
                "to_version": bundle.version + 1,
                "reason": reason,
            },),
        )

    def assess(self, bundle: EvidenceBundle) -> SufficiencyDecision:
        required = tuple(bundle.coverage_contract.get("required", ()))
        missing = []
        if "anchors_resolved" in required and (
            len(bundle.coverage_contract.get("resolved_anchors", ()))
            != len(bundle.anchors)
        ):
            missing.append("anchors_resolved")
        if "lineage_path" in required and not self._has_anchor_path(bundle):
            missing.append("lineage_path")
        if "counterevidence_checked" in required and bundle.counterevidence is None:
            missing.append("counterevidence_checked")
        if "no_unresolved" in required and bundle.residual_unknowns:
            missing.append("no_unresolved")
        if (
            "external_facts" in required
            and bundle.coverage_contract.get("missing_external_facts")
        ):
            missing.append("external_facts")

        if not missing and not bundle.gaps:
            action = "stop"
        elif "no_unresolved" in missing or "external_facts" in missing:
            action = "escalate"
        elif bundle.version == 1:
            action = "expand"
        else:
            action = "degrade"
        return SufficiencyDecision(
            sufficient=not missing and not bundle.gaps,
            action=action,
            missing_obligations=tuple(missing),
            reasons=tuple(bundle.gaps),
            coverage_contract=bundle.coverage_contract,
            disclosed_gaps=bundle.gaps,
            residual_unknowns=bundle.residual_unknowns,
        )

    def _grow_tables(
        self,
        anchors: set[str],
        direction: str,
        max_depth: int,
    ) -> set[str]:
        upstream: dict[str, set[str]] = {}
        downstream: dict[str, set[str]] = {}
        for edge in self.graph.edges:
            if edge.edge_type != EdgeType.TABLE_LINEAGE:
                continue
            downstream.setdefault(edge.source_id, set()).add(edge.target_id)
            upstream.setdefault(edge.target_id, set()).add(edge.source_id)

        included = set(anchors)
        queue = deque((anchor, 0) for anchor in sorted(anchors))
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            neighbors = set()
            if direction in {"downstream", "both"}:
                neighbors |= downstream.get(current, set())
            if direction in {"upstream", "both"}:
                neighbors |= upstream.get(current, set())
            for neighbor in sorted(neighbors):
                if neighbor not in included:
                    included.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return included

    def _collect_detail(self, table_ids: set[str]) -> tuple[set[str], set[str]]:
        nodes = set(table_ids)
        edges = set()

        for edge in self.graph.edges:
            if (
                edge.edge_type == EdgeType.TABLE_LINEAGE
                and edge.source_id in table_ids
                and edge.target_id in table_ids
            ):
                edges.add(edge.id)

        changed = True
        while changed:
            changed = False
            for edge in self.graph.edges:
                include = False
                if (
                    edge.edge_type == EdgeType.HAS_COLUMN
                    and (
                        edge.source_id in nodes
                        or edge.target_id in nodes
                    )
                ):
                    include = True
                elif (
                    edge.edge_type == EdgeType.PRODUCES
                    and edge.target_id in nodes
                ):
                    include = True
                elif (
                    edge.edge_type in {
                        EdgeType.COMPUTE_DEPENDENCY,
                        EdgeType.EXPR_OPERAND,
                    }
                    and edge.target_id in nodes
                ):
                    include = True
                elif (
                    edge.edge_type == EdgeType.CONTAINS
                    and edge.target_id in nodes
                ):
                    include = True
                elif (
                    edge.edge_type in {EdgeType.READS_FROM, EdgeType.WRITES_TO}
                    and edge.target_id in table_ids
                ):
                    include = True
                if not include:
                    continue
                old_size = len(nodes)
                nodes.update((edge.source_id, edge.target_id))
                edges.add(edge.id)
                changed = changed or len(nodes) != old_size
        return nodes, edges

    def _counterevidence(
        self,
        request: EvidenceRequest,
        resolved_anchors: tuple[str, ...],
    ) -> tuple[EvidenceFinding, ...]:
        if len(resolved_anchors) < 2:
            return ()
        expected_source = resolved_anchors[0]
        target = resolved_anchors[-1]
        findings = []
        for edge in self.graph.edges:
            if (
                edge.edge_type == EdgeType.TABLE_LINEAGE
                and edge.target_id == target
                and edge.source_id != expected_source
            ):
                source = self.graph.get_node(edge.source_id)
                findings.append(EvidenceFinding(
                    kind="alternative_upstream",
                    summary=(
                        f"{getattr(source, 'full_name', edge.source_id)} "
                        "also contributes to the target"
                    ),
                    citations=(edge.id,),
                ))
        return tuple(sorted(findings, key=lambda item: item.citations))

    def _has_anchor_path(self, bundle: EvidenceBundle) -> bool:
        if len(bundle.anchors) < 2:
            return bool(bundle.included_nodes)
        source = self.graph.get_node_by_name(bundle.anchors[0])
        target = self.graph.get_node_by_name(bundle.anchors[-1])
        if source is None or target is None:
            return False
        allowed_edges = set(bundle.included_edges)
        adjacency: dict[str, set[str]] = {}
        for edge in self.graph.edges:
            if (
                edge.id in allowed_edges
                and edge.edge_type == EdgeType.TABLE_LINEAGE
            ):
                adjacency.setdefault(edge.source_id, set()).add(edge.target_id)
        seen = set()
        stack = [source.id]
        while stack:
            current = stack.pop()
            if current == target.id:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, ()))
        return False
