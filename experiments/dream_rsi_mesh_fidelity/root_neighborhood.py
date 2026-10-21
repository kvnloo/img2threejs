from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

from replay import Node, ReplayError, World

ParameterVector = tuple[float, ...]
RenderForParameters = Callable[[ParameterVector], str | Path]
Evaluator = Callable[[Path, Path], Mapping[str, object]]


def _parameters(values: Sequence[float]) -> ParameterVector:
    if not values:
        raise ReplayError("initial parameters must not be empty")
    return tuple(float(value) for value in values)


def _bounds(bounds: Sequence[Sequence[float]], dimensions: int) -> tuple[tuple[float, float], ...]:
    if len(bounds) != dimensions:
        raise ReplayError("bounds must have one pair per parameter")
    result = []
    for index, pair in enumerate(bounds):
        if len(pair) != 2:
            raise ReplayError(f"bounds[{index}] must contain lower and upper")
        lower, upper = float(pair[0]), float(pair[1])
        if lower >= upper:
            raise ReplayError(f"bounds[{index}] lower must be smaller than upper")
        result.append((lower, upper))
    return tuple(result)


def _iou(result: Mapping[str, object]) -> float:
    signals = result.get("signals")
    if not isinstance(signals, Mapping):
        raise ReplayError("evaluator result must contain signals")
    value = signals.get("silhouetteIoU")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
        raise ReplayError("signals.silhouetteIoU must be numeric in [0,1]")
    return float(value)


def _gates(result: Mapping[str, object]) -> tuple[str, ...]:
    raw = result.get("hardGateFailures", [])
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ReplayError("hardGateFailures must be an array of strings")
    return tuple(raw)


def capture_root_neighborhood(
    *,
    world_id: str,
    initial: Sequence[float],
    bounds: Sequence[Sequence[float]],
    render_for_parameters: RenderForParameters,
    reference_png: str | Path,
    evaluator: Evaluator,
    step_fraction: float = 0.25,
) -> World:
    if not 0.0 < step_fraction <= 1.0:
        raise ReplayError("step_fraction must be in (0,1]")
    root_parameters = _parameters(initial)
    normalized_bounds = _bounds(bounds, len(root_parameters))
    for index, (value, (lower, upper)) in enumerate(zip(root_parameters, normalized_bounds)):
        if not lower <= value <= upper:
            raise ReplayError(f"initial[{index}] must be within bounds")

    reference = Path(reference_png)

    def evaluate(parameters: ParameterVector) -> tuple[float, tuple[str, ...]]:
        render_path = Path(render_for_parameters(parameters))
        result = evaluator(reference, render_path)
        if not isinstance(result, Mapping):
            raise ReplayError("evaluator result must be a mapping")
        return _iou(result), _gates(result)

    root_iou, root_gates = evaluate(root_parameters)
    nodes = [Node("root", None, None, None, None, root_iou, root_gates)]

    for coordinate, (lower, upper) in enumerate(normalized_bounds):
        step = (upper - lower) * step_fraction
        for direction in (-1, 1):
            value = min(upper, max(lower, root_parameters[coordinate] + direction * step))
            if value == root_parameters[coordinate]:
                continue
            candidate = tuple(value if idx == coordinate else current for idx, current in enumerate(root_parameters))
            iou, gates = evaluate(candidate)
            suffix = "minus" if direction < 0 else "plus"
            nodes.append(Node(f"c{coordinate}-{suffix}", "root", coordinate, direction, step, iou, gates))

    return World(world_id, "root", tuple(nodes))
