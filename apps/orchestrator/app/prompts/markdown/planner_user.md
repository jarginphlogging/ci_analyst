Conversation history:
{{history}}

Planning scope:
{{planner_scope_context}}

Max steps: {{max_steps}}
Question: {{user_message}}

Populate these structured fields:

- `relevance`: `in_domain|out_of_domain|unclear`
- `relevanceReason`: short string
- `presentationIntent`: `{displayType, chartType, tableStyle, rationale}`
- `tooComplex`: `true` only when minimum decomposition exceeds max steps
- `tasks`: array of task objects

Task object schema:
- `task`: natural-language task with all context needed for an independent Snowflake Cortex Analyst
- `dependsOn`: optional prior task ids only when unavoidable
- `independent`: boolean

Presentation intent constraints:

- `displayType`: `inline|table|chart`
- `chartType`: `line|bar|stacked_bar|grouped_bar|null` (chart only)
- `tableStyle`: `simple|ranked|comparison|null` (table only)

Task rules:

- Use the minimum number of independent tasks.
- If one task can answer the question, output exactly one task.
- Default to one task when requested outputs share the same business scope.
- Split into multiple tasks only when a single readable output would be materially worse or impossible.
- Keep tasks executable by SCA without follow-up.
- Do not include table names, column names, semantic-model field names, or SQL.
- Do not add additional business questions beyond the user request.
- If relevance is unclear, still provide a best-effort plan.
