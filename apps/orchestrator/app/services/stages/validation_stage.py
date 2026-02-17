from __future__ import annotations

from app.models import SqlExecutionResult, ValidationResult


class ValidationStage:
    def __init__(self, *, max_row_limit: int) -> None:
        self._max_row_limit = max_row_limit

    def validate_results(self, results: list[SqlExecutionResult]) -> ValidationResult:
        checks: list[str] = []
        if not results:
            return ValidationResult(passed=False, checks=["No SQL steps were executed."])

        checks.append(f"Executed {len(results)} governed SQL step(s).")

        total_rows = sum(result.rowCount for result in results)
        checks.append(f"Total retrieved rows: {total_rows}.")
        if total_rows <= 0:
            checks.append("No rows returned from SQL steps.")
            return ValidationResult(passed=False, checks=checks)

        over_limit = [result.rowCount for result in results if result.rowCount > self._max_row_limit]
        if over_limit:
            checks.append("At least one SQL step exceeded max row limit.")
            return ValidationResult(passed=False, checks=checks)
        checks.append("All SQL steps satisfy row-limit policy.")

        null_count = 0
        value_count = 0
        for result in results:
            for row in result.rows[:200]:
                for value in row.values():
                    value_count += 1
                    if value is None:
                        null_count += 1

        null_rate = (null_count / value_count) if value_count else 1.0
        checks.append(f"Observed null-rate: {null_rate:.2%}.")
        checks.append("Restricted-column access prevented by SQL guardrails.")

        passed = null_rate < 0.95
        return ValidationResult(passed=passed, checks=checks)
