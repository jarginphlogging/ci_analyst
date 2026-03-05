# AGENTS.md

## Product
I am building the best conversational analytics (aka chat with data aka natural language querying) agent the world has ever seen - this means taking queries from nontechnical users, exploring a handful of curated tables to retrieve the proper data, structuring the data in an intuitive way, and highlighting the information most important to the user based on their query, while also anticipating new insights the user may not have known they needed. The agent should be able to handle complex multi-step questions and multi-turn conversation. The main objective functions are minimal latency, and maximum insight/data quality.

## Best Practices

NEVER hardcode.

Our agent is a generalist, prompts and logic should not be overfit to specific problems.

Think critically about all decisions, ask yourself how this will impact the final product and user experience. 

Decision making should be handled by the llm as much as possible, not complex python logic.

LLM decides semantics; Python enforces contracts/safety and compresses data context.

Planner handles first relevance classification attempt, query decomposition, and presentation intent.

SQL Generator only writes SQL based on the Planner's plan, it may also ask for clarification or classify query as irrelevant.

Synthesizer narrates the story using the synthesis context package and fills out the UI contract.

## Strategic Principles

1. Architecture is policy: Planner, SQL Generator, and Synthesizer have strict, non-overlapping responsibilities.
2. Semantics vs contracts: LLMs decide meaning; deterministic code enforces safety, validity, and interface contracts.
3. Generalize by default: Build reusable capabilities and avoid hardcoded or overfit logic.
4. State is explicit: Cross-stage context must be structured, portable, and machine-readable.
5. Single source of truth: Resolve intent, scope, and entities once, then propagate without reinterpretation.
6. Deterministic core, probabilistic edge: Core execution and validation are deterministic; model creativity is bounded by contracts.
7. Composable over clever: Prefer simple, composable interfaces over hidden coupling.
8. Trustworthiness over fluency: Correctness and consistency outrank narrative polish.
9. Latency is a product feature: Preserve responsiveness while maintaining quality.
10. Evolve without rewrite: Extend contracts and interfaces instead of replacing architecture.

## Design Best Practices
Create distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

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
