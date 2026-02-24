from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.config import settings
from app.models import QueryPlanStep
from app.services.stages.sql_stage_models import ExecutionDispatch

AnalystFn = Callable[..., Awaitable[dict[str, Any]]]


def dependency_indices(plan: list[QueryPlanStep]) -> dict[int, set[int]]:
    id_to_index = {step.id: index for index, step in enumerate(plan)}
    dependencies: dict[int, set[int]] = {index: set() for index in range(len(plan))}

    for index, step in enumerate(plan):
        explicit_dependencies = [dep.strip() for dep in step.dependsOn if dep and dep.strip()]
        for dependency_id in explicit_dependencies:
            dependency_index = id_to_index.get(dependency_id)
            if dependency_index is None or dependency_index == index:
                continue
            dependencies[index].add(dependency_index)

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
    if mode == "sandbox":
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
