# @ci/web

Next.js + Tailwind frontend for the conversational analytics agent.

## Features

- Distinctive 3-panel decision cockpit UI
- Multi-turn conversation timeline
- Streamed answer rendering over NDJSON
- Interactive evidence table and insight cards
- Retrieved Data explorer with CSV/JSON export
- Expandable analysis trace summary (SQL + QA checks)

## API Integration Modes

- Web mock mode (`WEB_BACKEND_MODE=web_mock`)
- Orchestrator mode (`WEB_BACKEND_MODE=orchestrator`, `ORCHESTRATOR_URL` set)

## Run

```bash
cd /Users/joe/Code/ci_analyst
npm --workspace @ci/web run dev
```

## Build

```bash
npm --workspace @ci/web run build
```
