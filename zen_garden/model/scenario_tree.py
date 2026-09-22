"""Validated scenario-tree structure shared by model inputs and equations."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ScenarioNode:
    """One decision node and its explicit position in the tree."""

    node_id: int
    year: int
    probability: float
    parent_id: int | None
    children: tuple[int, ...]
    stage: int


class ScenarioTree:
    """Parse and validate unconditional-probability scenario trees."""

    def __init__(self, data: dict[str, Any], planning_years: list[int]):
        if not isinstance(data, dict):
            raise ValueError("Scenario tree root must be an object")
        if not planning_years:
            raise ValueError("Scenario tree needs at least one planning year")
        if data.get("node_id") != 0:
            raise ValueError("Scenario tree root node ID must be 0")
        self._data = data
        self._planning_years = tuple(planning_years)
        self._nodes: dict[int, ScenarioNode] = {}
        self._state_factors: dict[tuple[int, str, str], float] = {}
        self._parse(data, parent_id=None, stage=0)
        if sorted(self._nodes) != list(range(len(self._nodes))):
            raise ValueError("Scenario tree node IDs must be consecutive from 0")
        if self._nodes[0].probability != 1:
            raise ValueError("Scenario tree root node 0 must have probability 1")
        for node in self._nodes.values():
            if node.children:
                child_total = sum(
                    self._nodes[child].probability for child in node.children
                )
                if not math.isclose(child_total, node.probability, abs_tol=1e-9):
                    raise ValueError(
                        f"Scenario tree children of node {node.node_id} have "
                        f"probability {child_total}, expected {node.probability}"
                    )
            elif node.year != planning_years[-1]:
                raise ValueError(
                    f"Scenario tree path ending at node {node.node_id} "
                    f"stops before final year {planning_years[-1]}"
                )

    @classmethod
    def from_file(cls, path: str | Path, planning_years: list[int]) -> ScenarioTree:
        """Load a YAML tree, with JSON retained for older datasets and results."""
        path = Path(path)
        if not path.is_file() and path.suffix in {".yaml", ".yml"}:
            path = next(
                (
                    alternative
                    for alternative in (
                        path.with_suffix(".yaml"),
                        path.with_suffix(".yml"),
                        path.with_suffix(".json"),
                    )
                    if alternative.is_file()
                ),
                path,
            )
        if not path.is_file():
            raise FileNotFoundError(f"Scenario tree file is required: {path}")
        with path.open(encoding="utf-8") as stream:
            if path.suffix in {".yaml", ".yml"}:
                return cls(yaml.safe_load(stream), planning_years)
            if path.suffix == ".json":
                return cls(json.load(stream), planning_years)
        raise ValueError(f"Unsupported scenario-tree file type: {path.suffix}")

    def _parse(self, data: dict[str, Any], parent_id: int | None, stage: int) -> None:
        node_id = data.get("node_id")
        if type(node_id) is not int or node_id < 0:
            raise ValueError(f"Invalid scenario-tree node ID: {node_id!r}")
        if node_id in self._nodes:
            raise ValueError(f"Duplicate scenario-tree node ID {node_id}")
        year = data.get("year")
        if type(year) is not int or stage >= len(self._planning_years):
            raise ValueError(f"Invalid year or path length at node {node_id}")
        expected_year = self._planning_years[stage]
        if year != expected_year:
            raise ValueError(
                f"Scenario-tree node {node_id} has year {year}, "
                f"expected {expected_year} at stage {stage}"
            )
        probability = data.get("probability")
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(probability)
            or probability <= 0
            or probability > 1
        ):
            raise ValueError(
                f"Invalid probability {probability!r} at scenario-tree node {node_id}"
            )
        children_data = data.get("children", [])
        if not isinstance(children_data, list) or any(
            not isinstance(child, dict) for child in children_data
        ):
            raise ValueError(f"Invalid children at scenario-tree node {node_id}")
        child_ids = tuple(child.get("node_id") for child in children_data)
        self._nodes[node_id] = ScenarioNode(
            node_id, year, float(probability), parent_id, child_ids, stage
        )
        self._parse_state(node_id, data.get("state", []))
        for child in children_data:
            self._parse(child, parent_id=node_id, stage=stage + 1)

    def _parse_state(self, node_id: int, state: Any) -> None:
        if not isinstance(state, list):
            raise ValueError(f"Invalid state at scenario-tree node {node_id}")
        for item in state:
            if not isinstance(item, dict):
                raise ValueError(f"Invalid state at scenario-tree node {node_id}")
            for element, parameters in item.items():
                if not isinstance(parameters, dict):
                    raise ValueError(f"Invalid state for {element} at node {node_id}")
                for parameter, factor_spec in parameters.items():
                    if not isinstance(factor_spec, dict) or set(factor_spec) != {
                        "node_id_op"
                    }:
                        raise ValueError(
                            f"Invalid state factor for {element}.{parameter} "
                            f"at node {node_id}"
                        )
                    factors = factor_spec["node_id_op"]
                    if not isinstance(factors, list) or len(factors) != 1:
                        raise ValueError(
                            f"Expected one state factor for {element}.{parameter} "
                            f"at node {node_id}"
                        )
                    factor = factors[0]
                    if (
                        isinstance(factor, bool)
                        or not isinstance(factor, (int, float))
                        or not math.isfinite(factor)
                    ):
                        raise ValueError(
                            f"Invalid state factor for {element}.{parameter} "
                            f"at node {node_id}"
                        )
                    key = (node_id, element, parameter)
                    if key in self._state_factors:
                        raise ValueError(
                            f"Duplicate state factor for {element}.{parameter} "
                            f"at node {node_id}"
                        )
                    self._state_factors[key] = float(factor)

    @property
    def nodes(self) -> tuple[int, ...]:
        """Return node IDs in deterministic numerical order."""
        return tuple(sorted(self._nodes))

    @property
    def leaves(self) -> tuple[int, ...]:
        """Return all terminal node IDs."""
        return tuple(node for node in self.nodes if not self._nodes[node].children)

    def node(self, node_id: int) -> ScenarioNode:
        """Return a node's metadata."""
        return self._nodes[node_id]

    def parent(self, node_id: int) -> int | None:
        """Return a node's parent, or ``None`` for the root."""
        return self.node(node_id).parent_id

    def ancestors(self, node_id: int) -> tuple[int, ...]:
        """Return ancestors in root-to-parent order."""
        return self.path(node_id)[:-1]

    def path(self, node_id: int) -> tuple[int, ...]:
        """Return the complete root-to-node path."""
        path = [node_id]
        while (parent := self.parent(path[-1])) is not None:
            path.append(parent)
        return tuple(reversed(path))

    def ancestor_steps(self, node_id: int, count: int) -> int | None:
        """Return an ancestor ``count`` stages back, if one exists."""
        if count < 0:
            raise ValueError("Ancestor step count cannot be negative")
        path = self.path(node_id)
        return path[-count - 1] if count < len(path) else None

    def nodes_for_year(self, year: int) -> tuple[int, ...]:
        """Return all decision nodes in one calendar year."""
        return tuple(node for node in self.nodes if self.node(node).year == year)

    def probability(self, node_id: int) -> float:
        """Return unconditional probability of reaching one node."""
        return self.node(node_id).probability

    def state_multiplier(self, node_id: int, element: str, parameter: str) -> float:
        """Return the node-local multiplier, defaulting to one."""
        return self._state_factors.get((node_id, element, parameter), 1.0)

    @property
    def state_parameters(self) -> tuple[tuple[str, str], ...]:
        """Return every element/parameter pair varied anywhere in the tree."""
        return tuple(
            sorted(
                {(element, parameter) for _, element, parameter in self._state_factors}
            )
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the original validated tree for result persistence."""
        return json.loads(json.dumps(self._data))
