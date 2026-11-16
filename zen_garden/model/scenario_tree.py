"""Scenario-tree structure shared by model inputs and equations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ScenarioNode:
    """One temporal node and its position in the scenario tree."""

    node_id: int
    year: int
    probability: float
    parent_id: int | None
    children: tuple[int, ...]
    stage: int


class ScenarioTree:
    """Read and expose Baeniv's scenario-tree input in the v3 model structure."""

    def __init__(self, data: dict[str, Any], planning_years: list[int] | None = None):
        self._data = data
        self._nodes: dict[int, ScenarioNode] = {}
        self._state_factors: dict[tuple[int, str, str], float] = {}
        self._parse(data, parent_id=None, stage=0)

    @classmethod
    def from_file(
        cls, path: str | Path, planning_years: list[int] | None = None
    ) -> ScenarioTree:
        """Load the v3 YAML form or Baeniv's original JSON form."""
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
        node_id = data["node_id"]
        children_data = data.get("children", [])
        self._nodes[node_id] = ScenarioNode(
            node_id=node_id,
            year=data["year"],
            probability=data["probability"],
            parent_id=parent_id,
            children=tuple(child["node_id"] for child in children_data),
            stage=stage,
        )
        self._parse_state(node_id, data.get("state"))
        for child in children_data:
            self._parse(child, parent_id=node_id, stage=stage + 1)

    def _parse_state(self, node_id: int, state: Any) -> None:
        for item in state or []:
            for element, parameters in item.items():
                for parameter, factor_spec in parameters.items():
                    if (
                        not isinstance(factor_spec, dict)
                        or "node_id_op" not in factor_spec
                    ):
                        continue
                    factor = factor_spec["node_id_op"]
                    if isinstance(factor, list):
                        factor = factor[0]
                    self._state_factors[(node_id, element, parameter)] = float(factor)

    @property
    def nodes(self) -> tuple[int, ...]:
        """Return temporal node IDs in numerical order."""
        return tuple(sorted(self._nodes))

    @property
    def leaves(self) -> tuple[int, ...]:
        """Return terminal temporal node IDs."""
        return tuple(node for node in self.nodes if not self._nodes[node].children)

    def node(self, node_id: int) -> ScenarioNode:
        """Return a temporal node's metadata."""
        return self._nodes[node_id]

    def parent(self, node_id: int) -> int | None:
        """Return a temporal node's parent, or ``None`` for the root."""
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
        """Return the ancestor ``count`` stages back, if it exists."""
        path = self.path(node_id)
        return path[-count - 1] if 0 <= count < len(path) else None

    def nodes_for_year(self, year: int) -> tuple[int, ...]:
        """Return every temporal node assigned to one calendar year."""
        return tuple(node for node in self.nodes if self.node(node).year == year)

    def probability(self, node_id: int) -> float:
        """Return the node's unconditional probability."""
        return self.node(node_id).probability

    def state_multiplier(self, node_id: int, element: str, parameter: str) -> float:
        """Return a node-local input multiplier, defaulting to one."""
        return self._state_factors.get((node_id, element, parameter), 1.0)

    def to_dict(self) -> dict[str, Any]:
        """Return the original tree for result persistence."""
        return json.loads(json.dumps(self._data))
