# AGENTS.md

## Product
I am building the best conversational analytics (aka chat with data aka natural language querying) agent the world has ever seen - this means taking queries from nontechnical users, exploring a handful of curated tables to retrieve the proper data, structuring the data in an intuitive way, and highlighting the information most important to the user based on their query, while also anticipating new insights the user may not have known they needed. The agent should be able to handle complex multi-step questions and multi-turn conversation. The main objective functions are minimal latency, and maximum insight/data quality.

## Regulatory Context

This product operates in a governed corporate banking environment. This is not optional context — it shapes every architectural decision.

- **Never be prescriptive.** The system describes what the data shows. It does not recommend actions, suggest strategies, or tell the user what to do. This is a legal requirement.
- **Auditability is mandatory.** Every numeric claim in a synthesized response must be traceable through a deterministic provenance chain back to the step and time window that produced it.

## Data Foundation

The pipeline is built on Snowflake Cortex Analyst with a semantic model YAML as the single source of truth for the data domain. The semantic model defines dimensions, measures, time dimensions, co-display rules, query guidance, and verified query patterns.

- **Relevance classification is a two-layer filter.** The Planner does a first pass using a semantic model summary to catch clearly out-of-domain questions before any SQL generation. The SQL agent can independently classify a step as not relevant using the full semantic model — catching edge cases the summary-level check missed.
- The **SQL agent** is the domain expert — it receives the full semantic model YAML and resolves ambiguous business terms (e.g., "performing," "recent," "customer split") against its descriptions, measures, and verified queries.
- The **Planner** receives a semantic model summary for relevance classification, but does not use it to interpret business terms — it preserves the user's original language and passes ambiguity through to the SQL agent.
- The **Synthesizer** does not have access to the semantic model. It works exclusively from the synthesis context package produced by the summary engine.
- No stage should hardcode business logic that belongs in the semantic model. If a metric definition, co-display rule, or query pattern needs to change, it should change in the YAML — not in Python or prompt strings.

## Best Practices

NEVER hardcode.

Our agent is a generalist, prompts and logic should not be overfit to specific problems.

Think critically about all decisions, ask yourself how this will impact the final product and user experience. 

Decision making should be handled by the llm as much as possible, not complex python logic.

LLM decides semantics; Python enforces contracts/safety and compresses data context.

Planner handles first relevance classification attempt, query decomposition, and presentation intent.

SQL Generator only writes SQL based on the Planner's plan, it may also ask for clarification or classify query as irrelevant.

Synthesizer narrates the story using the synthesis context package and fills out the UI contract.

## Pipeline Boundaries

Each stage has strict, non-overlapping responsibilities. Violations of these boundaries are bugs.

**Planner:**
- Does: first-pass relevance classification (using semantic model summary), task decomposition, presentation intent selection.
- Does not: resolve business terms, interpret what metrics mean, write SQL, add specificity the user didn't ask for. It preserves the user's original language and passes ambiguity through to the SQL agent.

**SQL Agent:**
- Does: resolve business terms against the full semantic model, generate read-only SQL, make reasonable assumptions and log them, handle retries, second-pass relevance classification for individual steps.
- Does not: decompose multi-step questions (planner's job), narrate results (synthesizer's job), alter the step goal it receives.

**Synthesizer:**
- Does: narrate findings using the evidence layer (facts, comparisons, headline), build visual config from presentation intent, produce summary cards, insights, follow-ups, confidence, and assumptions.
- Does not: access the semantic model, reference SQL or pipeline internals, or recommend actions (legal requirement).

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

## Testing Philosophy

- **Prompts are code.** Changes to system prompts are behavioral changes. Test them against the golden dataset before merging.
- **Deterministic before AI-judged.** Prefer mechanical checks (provenance chain validation, column existence, enum correctness) over LLM judges. Add LLM judges only for qualities that can't be checked deterministically (narrative quality, insight relevance).
- **Regression is the priority.** Every prompt or pipeline change should be validated against existing golden dataset examples to confirm it doesn't degrade known-good outputs.
- **Test the boundaries.** Pipeline stage violations (planner interpreting business terms, synthesizer doing arithmetic, SQL agent overstepping its step goal) are the highest-priority test cases because they cause the subtlest bugs.

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