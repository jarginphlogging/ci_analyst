from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from app.config import settings
from app.models import QueryPlanStep
from app.services.stages.sql_stage_models import ExecutionDispatch

AnalystFn = Callable[..., Awaitable[dict[str, Any]]]
_STEP_REF_PATTERN = re.compile(r"(?:^|\b)(?:step|task)?\s*[_\-#:]?\s*(\d+)\s*$", re.IGNORECASE)


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def dependency_indices(plan: list[QueryPlanStep]) -> dict[int, set[int]]:
    id_to_index = {step.id: index for index, step in enumerate(plan)}
    goal_to_index = {_normalized(step.goal): index for index, step in enumerate(plan)}
    dependencies: dict[int, set[int]] = {index: set() for index in range(len(plan))}

    for index, step in enumerate(plan):
        explicit_dependencies = [dep.strip() for dep in step.dependsOn if dep and dep.strip()]
        resolved_dependencies: set[int] = set()
        for dependency_id in explicit_dependencies:
            dependency_index: int | None = id_to_index.get(dependency_id)
            if dependency_index is None:
                dependency_index = goal_to_index.get(_normalized(dependency_id))
            if dependency_index is None:
                ordinal_match = _STEP_REF_PATTERN.search(dependency_id)
                if ordinal_match:
                    candidate_index = int(ordinal_match.group(1)) - 1
                    if 0 <= candidate_index < len(plan):
                        dependency_index = candidate_index
            if dependency_index is None or dependency_index == index or dependency_index > index:
                continue
            resolved_dependencies.add(dependency_index)

        # If a step is explicitly marked dependent but no valid dependency
        # reference could be resolved, serialize it behind the prior step.
        if not resolved_dependencies and not step.independent and index > 0:
            resolved_dependencies.add(index - 1)

        dependencies[index] = resolved_dependencies

    return dependencies


def dependency_levels(plan: list[QueryPlanStep]) -> list[list[int]]:
    if not plan:
        return []

    dependencies = dependency_indices(plan)
    in_degree = {index: len(dep_set) for index, dep_set in dependencies.items()}
    children: dict[int, set[int]] = {index: set() for index in range(len(plan))}
    for child_index, parent_indices in dependencies.items():
        for parent_index in parent_indices:
            children[parent_index].add(child_index)

    ready = [index for index, count in in_degree.items() if count == 0]
    levels: list[list[int]] = []
    remaining = set(range(len(plan)))

    while ready:
        level = sorted(ready)
        levels.append(level)
        ready = []
        for node in level:
            remaining.discard(node)
            for child in children[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    ready.append(child)

    if not remaining:
        return levels

    # Cycle fallback: deterministic serial order by plan index.
    return [[index] for index in range(len(plan))]


def execution_dispatch(analyst_fn: AnalystFn | None) -> ExecutionDispatch:
    mode = settings.provider_mode
    if mode in {"sandbox", "prod-sandbox"}:
        return ExecutionDispatch(
            target_label="SQLite sandbox warehouse",
            parallel_capable=True,
        )
    if mode == "prod":
        return ExecutionDispatch(
            target_label="Snowflake warehouse",
            parallel_capable=True,
        )

    # Fallback for direct stage tests or custom dependency injection.
    return ExecutionDispatch(
        target_label="configured SQL warehouse",
        parallel_capable=bool(analyst_fn),
    )
