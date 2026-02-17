# Frontend UX Specification

## UX Vision

The interface is a decision cockpit, not a generic chat app.

1. Direct answer first.
2. Evidence and insight immediately visible.
3. Governed transparency through analysis trace summaries.
4. Follow-up suggestions that move the analysis forward.

## Layout

- Left rail: session context + system mode.
- Center: multi-turn conversation and structured answer cards.
- Right rail: active decision brief.

## Streaming Behaviors

- Start placeholder assistant bubble immediately.
- Append status chips as orchestration progresses.
- Stream answer tokens in the same bubble.
- Hydrate full data cards when final `response` event arrives.

## Interaction Model

- Suggested questions are one-click prompt injectors.
- Driver table supports sort pivots by impact and delta.
- Trace panel is collapsed by default; expandable for audit.
- Retrieved Data panel supports:
  - selecting returned datasets
  - viewing full rows/columns in-table
  - exporting current dataset as CSV or JSON

## Chain-of-thought Handling

- Show concise structured trace summaries only.
- Do not expose private raw chain-of-thought.
- Include SQL and quality checks for explainability.
