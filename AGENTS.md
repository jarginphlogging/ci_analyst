# AGENTS.md

## Work Machine Priority

All future development must treat the user work machine as the primary target environment:

- Windows corporate environment with internal package mirrors and strict security controls.
- No code/data/keys can be pushed from the work machine.
- Setup and runtime must be deterministic and low-friction.

## Engineering Constraints

- Prefer cross-platform scripts (`python`, `py -3`, `python3`) and avoid shell assumptions that break on Windows.
- Avoid dependencies that require fragile native binaries when practical (especially in frontend build pipelines).
- Keep `npm ci` as the canonical install path; do not rely on ad-hoc `npm install` behavior.
- Minimize install churn: only introduce dependencies when necessary and justify them.
- Ensure orchestrator setup and runtime use the same Python interpreter path.
- Document exact step-by-step setup commands in `README.md` whenever scripts or dependencies change.

## Delivery Rules

- Before merging changes that affect setup/build tooling, validate:
  - `npm ci`
  - `npm run setup:orchestrator`
  - `npm run dev:orchestrator`
  - `npm run dev:web`
- Prefer solutions that are stable long term in enterprise environments over short-term local optimizations.
