from __future__ import annotations

import random
from statistics import median

from replay import CoordinatePriorityPolicy, Node, World, evaluate_policy, learn_coordinate_priority

MEAN_GAINS = (0.018, 0.038, 0.115, 0.062)


def make_world(seed: int, world_id: str) -> World:
    rng = random.Random(seed)
    root_iou = 0.66 + rng.uniform(-0.015, 0.015)
    nodes = [Node("root", None, None, None, None, root_iou)]
    for coordinate, mean_gain in enumerate(MEAN_GAINS):
        gain = max(0.002, mean_gain + rng.uniform(-0.018, 0.018))
        loss = 0.01 + rng.uniform(0.0, 0.025)
        nodes.append(Node(f"c{coordinate}-", "root", coordinate, -1, 0.25, max(0.0, root_iou - loss)))
        gates = ("scale",) if coordinate == 3 and seed % 11 == 0 else ()
        nodes.append(Node(f"c{coordinate}+", "root", coordinate, 1, 0.25, min(0.99, root_iou + gain), gates))
    return World(world_id, "root", tuple(nodes))


def run() -> dict:
    train = tuple(make_world(seed, f"train-{seed:02d}") for seed in range(30))
    holdout = tuple(make_world(1000 + seed, f"holdout-{seed:02d}") for seed in range(30))
    learned_order = learn_coordinate_priority(train)
    fixed = CoordinatePriorityPolicy(tuple(range(len(MEAN_GAINS))), name="fixed-index-order")
    learned = CoordinatePriorityPolicy(learned_order, name="history-learned-order")
    rows = []
    for budget in (3, 5, 7, 9):
        fixed_report = evaluate_policy(holdout, fixed, budget, target_iou=0.75)
        learned_report = evaluate_policy(holdout, learned, budget, target_iou=0.75)
        fixed_best = [item.best_clean_iou for item in fixed_report["results"]]
        learned_best = [item.best_clean_iou for item in learned_report["results"]]
        rows.append({
            "budget": budget,
            "fixedMeanBestIoU": fixed_report["meanBestCleanIoU"],
            "learnedMeanBestIoU": learned_report["meanBestCleanIoU"],
            "deltaMeanBestIoU": learned_report["meanBestCleanIoU"] - fixed_report["meanBestCleanIoU"],
            "fixedMedianBestIoU": median(fixed_best),
            "learnedMedianBestIoU": median(learned_best),
            "fixedSuccessRate": fixed_report["successRate"],
            "learnedSuccessRate": learned_report["successRate"],
        })
    return {"learnedOrder": learned_order, "rows": rows}


if __name__ == "__main__":
    result = run()
    print("learned order:", result["learnedOrder"])
    for row in result["rows"]:
        print(row)
