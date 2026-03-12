const RETIRED_MESSAGE =
  "The legacy @ci/semantic-model JSON package has been retired. Use /semantic_model.yaml and /semantic_guardrails.json instead.";

export type SemanticModel = never;

export function loadSemanticModel(): never {
  throw new Error(RETIRED_MESSAGE);
}

export function findMetricTable(_: string): never {
  throw new Error(RETIRED_MESSAGE);
}

export function isRestrictedColumn(_: string): never {
  throw new Error(RETIRED_MESSAGE);
}
