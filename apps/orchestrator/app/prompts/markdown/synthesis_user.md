Conversation history:
{{history}}

Question: {{user_message}}
Presentation intent: {{presentation_intent}}

Synthesis context package:
{{result_summary}}

Evidence summary:
{{evidence_summary}}

Populate these structured fields:

- `answer`: concise direct answer
- `whyItMatters`: concise impact statement
- `confidence`: `high|medium|low`
- `confidenceReason`: rationale for confidence grounded in provided summaries
- `summaryCards`: array of 1-3 objects `{label, value, detail(optional)}`
- `chartConfig`: object or null with keys `{type, x, y, series, xLabel, yLabel, yFormat}`
- `tableConfig`: object or null with keys `{style, columns, sortBy, sortDir, showRank}`
- `insights`: array of up to 4 objects `{title, detail, importance(high|medium)}`
- `suggestedQuestions`: array of exactly 3 strings
- `assumptions`: array of up to 5 concise assumptions grounded in supplied analysis context only

`tableConfig.columns` item schema:

```json
{
  "key": "column_name",
  "label": "Human Label",
  "format": "currency|number|percent|date|string",
  "align": "left|right"
}
```

Enum constraints:

- `chartConfig.type`: `line|bar|stacked_bar|stacked_area|grouped_bar`
- `chartConfig.yFormat`: `currency|number|percent`
- `tableConfig.style`: `simple|ranked|comparison`
- `tableConfig.sortDir`: `asc|desc|null`

Final self-check before responding:

1. Any referenced column exists in provided table summaries.
2. `chartConfig` and `tableConfig` are coherent with presentation intent and data shape.
3. All numerical claims are traceable to supplied summaries.
