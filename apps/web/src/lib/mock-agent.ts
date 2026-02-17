import type { AgentResponse, DataTable, EvidenceRow, MetricPoint, TraceStep } from "@/lib/types";

const baseEvidence: EvidenceRow[] = [
  {
    segment: "North America - Unsecured",
    prior: 1.82,
    current: 2.43,
    changeBps: 61,
    contribution: 0.56,
  },
  {
    segment: "North America - Secured",
    prior: 1.09,
    current: 1.21,
    changeBps: 12,
    contribution: 0.09,
  },
  {
    segment: "EMEA - Unsecured",
    prior: 1.58,
    current: 1.88,
    changeBps: 30,
    contribution: 0.21,
  },
  {
    segment: "APAC - Unsecured",
    prior: 1.44,
    current: 1.49,
    changeBps: 5,
    contribution: 0.03,
  },
];

function buildMetrics(currentRate: number, deltaBps: number): MetricPoint[] {
  return [
    { label: "Portfolio Charge-Off Rate", value: currentRate, delta: deltaBps, unit: "pct" },
    { label: "Quarter-over-Quarter Change", value: deltaBps, delta: deltaBps, unit: "bps" },
    { label: "At-Risk Balance", value: 4.8, delta: 0.6, unit: "usd" },
  ];
}

function buildTrace(query: string): TraceStep[] {
  return [
    {
      id: "t1",
      title: "Resolve intent and scope",
      summary: `Mapped request to metric definitions, time window, and segmentation from the semantic model for query: \"${query.slice(
        0,
        96,
      )}\"`,
      status: "done",
      qualityChecks: ["Metric dictionary hit", "Time window recognized"],
    },
    {
      id: "t2",
      title: "Generate governed SQL",
      summary: "Built allowlisted SQL against curated risk tables with controlled joins.",
      status: "done",
      sql: "SELECT region, product_type, q3_rate, q4_rate, (q4_rate-q3_rate)*10000 AS delta_bps FROM curated.credit_risk_summary WHERE quarter IN ('2025Q3','2025Q4');",
      qualityChecks: ["Join graph constraint passed", "No restricted columns accessed"],
    },
    {
      id: "t3",
      title: "Validate and rank insights",
      summary: "Ran reconciliation checks and ranked drivers by impact x confidence x relevance.",
      status: "done",
      qualityChecks: ["Subtotal reconciliation <= 0.5 bps", "Null-rate threshold < 1%"],
    },
  ];
}

function tableFromEvidence(id: string, name: string, rows: EvidenceRow[], sourceSql: string): DataTable {
  return {
    id,
    name,
    columns: ["segment", "prior", "current", "changeBps", "contribution"],
    rows: rows.map((row) => ({
      segment: row.segment,
      prior: row.prior,
      current: row.current,
      changeBps: row.changeBps,
      contribution: row.contribution,
    })),
    rowCount: rows.length,
    description: "Segment-level decomposition used to generate driver analysis.",
    sourceSql,
  };
}

export function getMockAgentResponse(userQuery: string): AgentResponse {
  const query = userQuery.toLowerCase();

  const isFraud = query.includes("fraud") || query.includes("dispute");
  const isDeposit = query.includes("deposit") || query.includes("liquidity");

  if (isFraud) {
    return {
      answer:
        "Fraud loss rate rose 28 bps quarter-over-quarter, with card-not-present traffic in North America driving most of the increase.",
      confidence: "high",
      whyItMatters:
        "The concentration pattern indicates controllable operational exposure, not broad portfolio deterioration. Targeting top merchant corridors can reduce losses quickly.",
      metrics: [
        { label: "Fraud Loss Rate", value: 1.31, delta: 28, unit: "pct" },
        { label: "High-Risk Corridor Share", value: 42, delta: 7, unit: "pct" },
        { label: "Recovered Disputes", value: 0.74, delta: -0.11, unit: "usd" },
      ],
      evidence: [
        {
          segment: "NA - CNP",
          prior: 0.82,
          current: 1.26,
          changeBps: 44,
          contribution: 0.61,
        },
        {
          segment: "NA - Card Present",
          prior: 0.33,
          current: 0.42,
          changeBps: 9,
          contribution: 0.08,
        },
        {
          segment: "EMEA - CNP",
          prior: 0.55,
          current: 0.68,
          changeBps: 13,
          contribution: 0.14,
        },
      ],
      insights: [
        {
          id: "i1",
          title: "Losses are corridor-concentrated",
          detail: "Top 3 merchant corridors now account for 64% of incremental fraud losses.",
          importance: "high",
        },
        {
          id: "i2",
          title: "Chargeback recovery deteriorated",
          detail: "Recovery dropped 11% QoQ, amplifying net fraud pressure.",
          importance: "medium",
        },
      ],
      suggestedQuestions: [
        "Which merchant corridors generated the highest incremental losses?",
        "How much of the increase is volume versus severity?",
        "What controls have the fastest expected loss reduction?",
      ],
      assumptions: [
        "Fraud rate uses confirmed-loss basis and excludes pending investigations.",
        "Quarter is based on transaction settlement date.",
      ],
      trace: buildTrace(userQuery),
      dataTables: [
        tableFromEvidence(
          "fraud_drivers",
          "Fraud Driver Breakdown",
          [
            {
              segment: "NA - CNP",
              prior: 0.82,
              current: 1.26,
              changeBps: 44,
              contribution: 0.61,
            },
            {
              segment: "NA - Card Present",
              prior: 0.33,
              current: 0.42,
              changeBps: 9,
              contribution: 0.08,
            },
            {
              segment: "EMEA - CNP",
              prior: 0.55,
              current: 0.68,
              changeBps: 13,
              contribution: 0.14,
            },
          ],
          "SELECT region_channel AS segment, prior_rate AS prior, current_rate AS current, delta_bps AS changeBps, contribution_share AS contribution FROM curated.fraud_summary WHERE quarter IN ('2025Q3','2025Q4');",
        ),
      ],
    };
  }

  if (isDeposit) {
    return {
      answer:
        "Net deposit growth slowed to 2.1% in the latest quarter, driven by commercial outflows in rate-sensitive accounts.",
      confidence: "medium",
      whyItMatters:
        "Liquidity coverage remains healthy, but mix shift toward higher-cost funding can compress NIM if the trend persists.",
      metrics: [
        { label: "Net Deposit Growth", value: 2.1, delta: -1.8, unit: "pct" },
        { label: "Commercial Outflow", value: 1.4, delta: 0.6, unit: "usd" },
        { label: "LCR Buffer", value: 129, delta: -4, unit: "pct" },
      ],
      evidence: [
        {
          segment: "Commercial - Rate Sensitive",
          prior: 5.1,
          current: 2.4,
          changeBps: -270,
          contribution: -0.44,
        },
        {
          segment: "Retail - Transactional",
          prior: 2.2,
          current: 2.9,
          changeBps: 70,
          contribution: 0.18,
        },
        {
          segment: "Wealth - Sweep",
          prior: 1.8,
          current: 1.3,
          changeBps: -50,
          contribution: -0.07,
        },
      ],
      insights: [
        {
          id: "i1",
          title: "Pricing sensitivity is concentrated",
          detail: "Outflows cluster in accounts repriced within the last 45 days.",
          importance: "high",
        },
        {
          id: "i2",
          title: "Retail balances partially offset",
          detail: "Transactional inflows offset 27% of commercial attrition.",
          importance: "medium",
        },
      ],
      suggestedQuestions: [
        "Which client cohorts show the highest repricing sensitivity?",
        "How does mix shift affect forward NIM scenarios?",
        "What is the projected liquidity impact if trend persists 2 more quarters?",
      ],
      assumptions: [
        "Deposit growth is period-end average balance basis.",
        "Commercial segment excludes brokered deposits.",
      ],
      trace: buildTrace(userQuery),
      dataTables: [
        tableFromEvidence(
          "deposit_mix",
          "Deposit Mix Shift",
          [
            {
              segment: "Commercial - Rate Sensitive",
              prior: 5.1,
              current: 2.4,
              changeBps: -270,
              contribution: -0.44,
            },
            {
              segment: "Retail - Transactional",
              prior: 2.2,
              current: 2.9,
              changeBps: 70,
              contribution: 0.18,
            },
            {
              segment: "Wealth - Sweep",
              prior: 1.8,
              current: 1.3,
              changeBps: -50,
              contribution: -0.07,
            },
          ],
          "SELECT client_segment AS segment, prior_growth AS prior, current_growth AS current, delta_bps AS changeBps, contribution_share AS contribution FROM curated.deposit_mix_summary WHERE quarter IN ('2025Q3','2025Q4');",
        ),
      ],
    };
  }

  return {
    answer:
      "Charge-off rate increased 42 bps quarter-over-quarter, with North America unsecured cards contributing most of the deterioration.",
    confidence: "high",
    whyItMatters:
      "The increase is concentrated rather than broad-based. That creates a targeted mitigation path in underwriting and collections without over-tightening healthy segments.",
    metrics: buildMetrics(2.42, 42),
    evidence: baseEvidence,
    insights: [
      {
        id: "i1",
        title: "Concentration risk is rising",
        detail: "North America unsecured now represents 56% of total worsening while only 38% of exposure.",
        importance: "high",
      },
      {
        id: "i2",
        title: "Severity outran volume",
        detail: "Default severity increased faster than default counts, suggesting collections efficacy drift.",
        importance: "high",
      },
      {
        id: "i3",
        title: "APAC stayed resilient",
        detail: "APAC movement is noise-level and can serve as a policy benchmark.",
        importance: "medium",
      },
    ],
    suggestedQuestions: [
      "Break down NA unsecured by FICO band and vintage.",
      "How much of the increase came from new originations versus existing book?",
      "Which interventions reduced severity in similar historical periods?",
    ],
    assumptions: [
      "Rates shown as balance-weighted portfolio rates.",
      "Comparisons use quarter-end snapshots aligned to finance calendar.",
    ],
    trace: buildTrace(userQuery),
    dataTables: [
      tableFromEvidence(
        "charge_off_drivers",
        "Charge-Off Driver Breakdown",
        baseEvidence,
        "SELECT region || ' - ' || product_type AS segment, q3_rate AS prior, q4_rate AS current, (q4_rate-q3_rate)*10000 AS changeBps, contribution_share AS contribution FROM curated.credit_risk_summary WHERE quarter IN ('2025Q3','2025Q4');",
      ),
    ],
  };
}
