Conversation history:
{{history}}

Semantic model summary:
{{semantic_model_summary}}

Question: {{user_message}}
Step id: {{step_id}}
Step goal: {{step_goal}}
Route: {{route}}

Prior SQL queries generated in this conversation turn (for context only — do not repeat patterns that failed):
{{prior_sql}}

Retry feedback from prior attempts:
{{retry_feedback}}

Populate these structured fields:

- `generationType`: `sql_ready|clarification|not_relevant`
- `sql`: string (required when `generationType=sql_ready`)
- `rationale`: short string
- `clarificationQuestion`: string (required when `generationType=clarification`)
- `notRelevantReason`: string (required when `generationType=not_relevant`)
- `assumptions`: array of strings
