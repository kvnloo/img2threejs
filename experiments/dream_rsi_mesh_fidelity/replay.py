from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable, Protocol


class ReplayError(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    id: str
    parent_id: str | None
    coordinate: int | None
    direction: int | None
    step: float | None
    silhouette_iou: float
    hard_gate_failures: tuple[str, ...] = ()
    cost: int = 1

    @property
    def clean(self) -> bool:
        return not self.hard_gate_failures


@dataclass(frozen=True)
class World:
    id: str
    root_id: str
    nodes: tuple[Node, ...]

    def index(self) -> dict[str, Node]:
        by_id = {node.id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ReplayError(f"world {self.id!r} has duplicate node ids")
        if self.root_id not in by_id:
            raise ReplayError(f"world {self.id!r} root is missing")
        root = by_id[self.root_id]
        if root.parent_id is not None:
            raise ReplayError("root node must not have a parent")
        for node in self.nodes:
            if node.parent_id is not None and node.parent_id not in by_id:
                raise ReplayError(f"node {node.id!r} has missing parent {node.parent_id!r}")
            if not 0.0 <= node.silhouette_iou <= 1.0:
                raise ReplayError(f"node {node.id!r} silhouette_iou must be in [0,1]")
            if node.cost < 1:
                raise ReplayError(f"node {node.id!r} cost must be >=1")
        return by_id

    def children(self) -> dict[str, tuple[str, ...]]:
        by_parent: dict[str, list[str]] = {}
        for node in self.nodes:
            if node.parent_id is not None:
                by_parent.setdefault(node.parent_id, []).append(node.id)
        return {key: tuple(sorted(value)) for key, value in by_parent.items()}


@dataclass(frozen=True)
class VisibleNode:
    id: str
    parent_id: str | None
    coordinate: int | None
    direction: int | None
    step: float | None
    silhouette_iou: float
    hard_gate_failures: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    id: str
    parent_id: str
    coordinate: int | None
    direction: int | None
    step: float | None


@dataclass(frozen=True)
class Observation:
    visited: tuple[VisibleNode, ...]
    candidates: tuple[Candidate, ...]
    spent: int
    budget: int


class Policy(Protocol):
    name: str

    def choose(self, observation: Observation) -> str | None:
        ...


@dataclass(frozen=True)
class CoordinatePriorityPolicy:
    coordinate_order: tuple[int, ...]
    name: str = "coordinate-priority"

    def choose(self, observation: Observation) -> str | None:
        if not observation.candidates:
            return None
        rank = {coordinate: idx for idx, coordinate in enumerate(self.coordinate_order)}
        return min(
            observation.candidates,
            key=lambda item: (
                rank.get(item.coordinate, len(rank)),
                0 if item.direction == -1 else 1,
                item.id,
            ),
        ).id


@dataclass(frozen=True)
class ReplayResult:
    world_id: str
    policy_name: str
    visited: tuple[str, ...]
    spent: int
    best_clean_iou: float
    best_node_id: str | None
    evaluations_to_target: int | None


def _visible(node: Node) -> VisibleNode:
    return VisibleNode(
        id=node.id,
        parent_id=node.parent_id,
        coordinate=node.coordinate,
        direction=node.direction,
        step=node.step,
        silhouette_iou=node.silhouette_iou,
        hard_gate_failures=node.hard_gate_failures,
    )


def replay(world: World, policy: Policy, budget: int, target_iou: float = 0.85) -> ReplayResult:
    if budget < 1:
        raise ReplayError("budget must be >=1")
    by_id = world.index()
    children = world.children()
    root = by_id[world.root_id]
    spent = root.cost
    if spent > budget:
        raise ReplayError("budget cannot pay for the recorded root")
    visited = [root.id]
    visited_set = {root.id}
    best_node = root if root.clean else None
    evals_to_target = spent if root.clean and root.silhouette_iou >= target_iou else None

    while spent < budget:
        candidate_ids = sorted({
            child_id
            for parent_id in visited_set
            for child_id in children.get(parent_id, ())
            if child_id not in visited_set
        })
        candidates = tuple(
            Candidate(
                id=child_id,
                parent_id=by_id[child_id].parent_id or "",
                coordinate=by_id[child_id].coordinate,
                direction=by_id[child_id].direction,
                step=by_id[child_id].step,
            )
            for child_id in candidate_ids
            if spent + by_id[child_id].cost <= budget
        )
        observation = Observation(
            visited=tuple(_visible(by_id[node_id]) for node_id in visited),
            candidates=candidates,
            spent=spent,
            budget=budget,
        )
        choice = policy.choose(observation)
        if choice is None:
            break
        if choice not in {candidate.id for candidate in candidates}:
            raise ReplayError(f"policy selected out-of-support node {choice!r}")
        node = by_id[choice]
        spent += node.cost
        visited.append(node.id)
        visited_set.add(node.id)
        if node.clean and (best_node is None or node.silhouette_iou > best_node.silhouette_iou):
            best_node = node
        if evals_to_target is None and node.clean and node.silhouette_iou >= target_iou:
            evals_to_target = spent

    return ReplayResult(
        world_id=world.id,
        policy_name=policy.name,
        visited=tuple(visited),
        spent=spent,
        best_clean_iou=best_node.silhouette_iou if best_node else -1.0,
        best_node_id=best_node.id if best_node else None,
        evaluations_to_target=evals_to_target,
    )


def learn_coordinate_priority(worlds: Iterable[World], *, root_only: bool = True) -> tuple[int, ...]:
    gains: dict[int, list[float]] = {}
    for world in worlds:
        by_id = world.index()
        for node in world.nodes:
            if node.parent_id is None or node.coordinate is None or not node.clean:
                continue
            if root_only and node.parent_id != world.root_id:
                continue
            parent = by_id[node.parent_id]
            if not parent.clean:
                continue
            gains.setdefault(node.coordinate, []).append(node.silhouette_iou - parent.silhouette_iou)
    if not gains:
        return ()
    return tuple(sorted(gains, key=lambda coordinate: (-mean(gains[coordinate]), coordinate)))


def evaluate_policy(worlds: Iterable[World], policy: Policy, budget: int, target_iou: float = 0.85) -> dict[str, Any]:
    results = [replay(world, policy, budget, target_iou) for world in worlds]
    if not results:
        raise ReplayError("at least one world is required")
    successes = [result for result in results if result.evaluations_to_target is not None]
    return {
        "policy": policy.name,
        "worlds": len(results),
        "meanBestCleanIoU": mean(result.best_clean_iou for result in results),
        "successRate": len(successes) / len(results),
        "meanEvaluationsToTarget": mean(result.evaluations_to_target for result in successes) if successes else None,
        "results": results,
    }


def promote_if_no_regression(
    worlds: Iterable[World],
    incumbent: Policy,
    candidate: Policy,
    budget: int,
    target_iou: float = 0.85,
) -> Policy:
    frozen = tuple(worlds)
    incumbent_report = evaluate_policy(frozen, incumbent, budget, target_iou)
    candidate_report = evaluate_policy(frozen, candidate, budget, target_iou)
    candidate_key = (candidate_report["successRate"], candidate_report["meanBestCleanIoU"])
    incumbent_key = (incumbent_report["successRate"], incumbent_report["meanBestCleanIoU"])
    return candidate if candidate_key > incumbent_key else incumbent
