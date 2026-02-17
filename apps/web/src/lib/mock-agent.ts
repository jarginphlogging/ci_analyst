import type { AgentResponse, DataTable, EvidenceRow, MetricPoint, TraceStep } from "@/lib/types";

const DATA_FROM = "2025-01-01";
const DATA_THROUGH = "2025-12-31";

type StateBase = {
  state: string;
  spendUsdM: number;
  transactionsK: number;
  cnpSharePct: number;
};

const stateBase: StateBase[] = [
  { state: "CA", spendUsdM: 236.4, transactionsK: 6210, cnpSharePct: 46.8 },
  { state: "TX", spendUsdM: 212.7, transactionsK: 5660, cnpSharePct: 43.1 },
  { state: "FL", spendUsdM: 188.9, transactionsK: 4890, cnpSharePct: 41.7 },
  { state: "NY", spendUsdM: 181.2, transactionsK: 4720, cnpSharePct: 48.9 },
  { state: "GA", spendUsdM: 149.5, transactionsK: 3890, cnpSharePct: 39.8 },
  { state: "IL", spendUsdM: 142.8, transactionsK: 3710, cnpSharePct: 42.6 },
  { state: "PA", spendUsdM: 136.4, transactionsK: 3490, cnpSharePct: 40.4 },
  { state: "NC", spendUsdM: 129.8, transactionsK: 3360, cnpSharePct: 38.6 },
  { state: "OH", spendUsdM: 121.1, transactionsK: 3190, cnpSharePct: 37.9 },
  { state: "VA", spendUsdM: 116.2, transactionsK: 3050, cnpSharePct: 41.2 },
  { state: "AZ", spendUsdM: 109.7, transactionsK: 2810, cnpSharePct: 40.8 },
  { state: "NJ", spendUsdM: 106.8, transactionsK: 2740, cnpSharePct: 45.7 },
  { state: "WA", spendUsdM: 98.5, transactionsK: 2520, cnpSharePct: 47.1 },
  { state: "MA", spendUsdM: 94.2, transactionsK: 2390, cnpSharePct: 46.5 },
  { state: "TN", spendUsdM: 88.9, transactionsK: 2290, cnpSharePct: 37.6 },
  { state: "IN", spendUsdM: 84.6, transactionsK: 2200, cnpSharePct: 36.8 },
  { state: "MO", spendUsdM: 79.8, transactionsK: 2080, cnpSharePct: 35.9 },
  { state: "MD", spendUsdM: 76.5, transactionsK: 1990, cnpSharePct: 43.8 },
  { state: "CO", spendUsdM: 73.4, transactionsK: 1920, cnpSharePct: 44.1 },
  { state: "MN", spendUsdM: 69.3, transactionsK: 1820, cnpSharePct: 39.2 },
  { state: "WI", spendUsdM: 66.7, transactionsK: 1750, cnpSharePct: 35.3 },
  { state: "SC", spendUsdM: 63.8, transactionsK: 1690, cnpSharePct: 36.6 },
  { state: "AL", spendUsdM: 60.4, transactionsK: 1600, cnpSharePct: 34.7 },
  { state: "LA", spendUsdM: 58.9, transactionsK: 1550, cnpSharePct: 35.5 },
  { state: "KY", spendUsdM: 57.2, transactionsK: 1500, cnpSharePct: 34.2 },
  { state: "OR", spendUsdM: 55.6, transactionsK: 1450, cnpSharePct: 42.7 },
  { state: "OK", spendUsdM: 54.1, transactionsK: 1410, cnpSharePct: 33.8 },
  { state: "CT", spendUsdM: 53.5, transactionsK: 1390, cnpSharePct: 43.4 },
  { state: "UT", spendUsdM: 52.8, transactionsK: 1360, cnpSharePct: 38.9 },
  { state: "NV", spendUsdM: 51.9, transactionsK: 1340, cnpSharePct: 44.5 },
];

function queryProfile(query: string): "state_sales" | "q4_yoy" | "store_performance" | "overview" {
  const lowered = query.toLowerCase();
  if (
    lowered.includes("top") &&
    lowered.includes("bottom") &&
    (lowered.includes("store") || lowered.includes("location") || lowered.includes("td_id"))
  ) {
    return "store_performance";
  }
  if (
    lowered.includes("q4") ||
    lowered.includes("same period last year") ||
    lowered.includes("year over year") ||
    lowered.includes("yoy") ||
    lowered.includes("previous year")
  ) {
    return "q4_yoy";
  }
  if (lowered.includes("state") && (lowered.includes("sales") || lowered.includes("spend") || lowered.includes("transaction"))) {
    return "state_sales";
  }
  return "overview";
}

function stateRows(): Array<Record<string, string | number>> {
  return stateBase.map((item) => ({
    transaction_state: item.state,
    spend_usd_m: item.spendUsdM,
    transactions_k: item.transactionsK,
    avg_sale_amount_usd: Number(((item.spendUsdM * 1000) / item.transactionsK).toFixed(2)),
    cp_spend_share_pct: Number((100 - item.cnpSharePct).toFixed(1)),
    cnp_spend_share_pct: Number(item.cnpSharePct.toFixed(1)),
    data_from: DATA_FROM,
    data_through: DATA_THROUGH,
  }));
}

function stateChannelRows(limitStates = 10): Array<Record<string, string | number>> {
  const rows: Array<Record<string, string | number>> = [];
  for (const item of stateBase.slice(0, limitStates)) {
    const cpShare = 100 - item.cnpSharePct;
    const cpSpend = Number((item.spendUsdM * cpShare * 0.01).toFixed(1));
    const cnpSpend = Number((item.spendUsdM * item.cnpSharePct * 0.01).toFixed(1));
    const cpTransactions = Math.round(item.transactionsK * cpShare * 0.01);
    const cnpTransactions = Math.round(item.transactionsK * item.cnpSharePct * 0.01);
    rows.push({
      transaction_state: item.state,
      channel: "CP",
      spend_usd_m: cpSpend,
      transactions_k: cpTransactions,
      avg_sale_amount_usd: Number(((cpSpend * 1000) / Math.max(cpTransactions, 1)).toFixed(2)),
      data_from: DATA_FROM,
      data_through: DATA_THROUGH,
    });
    rows.push({
      transaction_state: item.state,
      channel: "CNP",
      spend_usd_m: cnpSpend,
      transactions_k: cnpTransactions,
      avg_sale_amount_usd: Number(((cnpSpend * 1000) / Math.max(cnpTransactions, 1)).toFixed(2)),
      data_from: DATA_FROM,
      data_through: DATA_THROUGH,
    });
  }
  return rows;
}

function storeRows(): Array<Record<string, string | number>> {
  return [
    {
      rank_group: "Top",
      td_id: "6182655",
      transaction_city: "Houston",
      transaction_state: "TX",
      spend_2025_usd_m: 42.1,
      transactions_2025_k: 1110,
      repeat_spend_share_2025_pct: 64.3,
      spend_2024_usd_m: 35.8,
      repeat_spend_share_2024_pct: 59.9,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Top",
      td_id: "6181442",
      transaction_city: "Miami",
      transaction_state: "FL",
      spend_2025_usd_m: 39.4,
      transactions_2025_k: 1030,
      repeat_spend_share_2025_pct: 62.8,
      spend_2024_usd_m: 33.7,
      repeat_spend_share_2024_pct: 58.0,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Top",
      td_id: "6183118",
      transaction_city: "Los Angeles",
      transaction_state: "CA",
      spend_2025_usd_m: 37.8,
      transactions_2025_k: 980,
      repeat_spend_share_2025_pct: 63.7,
      spend_2024_usd_m: 32.4,
      repeat_spend_share_2024_pct: 58.8,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Top",
      td_id: "6182027",
      transaction_city: "Atlanta",
      transaction_state: "GA",
      spend_2025_usd_m: 35.1,
      transactions_2025_k: 930,
      repeat_spend_share_2025_pct: 61.9,
      spend_2024_usd_m: 30.9,
      repeat_spend_share_2024_pct: 57.4,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Top",
      td_id: "6182780",
      transaction_city: "Phoenix",
      transaction_state: "AZ",
      spend_2025_usd_m: 33.8,
      transactions_2025_k: 880,
      repeat_spend_share_2025_pct: 60.7,
      spend_2024_usd_m: 29.5,
      repeat_spend_share_2024_pct: 56.1,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Bottom",
      td_id: "6184993",
      transaction_city: "Baton Rouge",
      transaction_state: "LA",
      spend_2025_usd_m: 6.4,
      transactions_2025_k: 170,
      repeat_spend_share_2025_pct: 45.1,
      spend_2024_usd_m: 7.0,
      repeat_spend_share_2024_pct: 47.0,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Bottom",
      td_id: "6185120",
      transaction_city: "Knoxville",
      transaction_state: "TN",
      spend_2025_usd_m: 6.2,
      transactions_2025_k: 162,
      repeat_spend_share_2025_pct: 44.4,
      spend_2024_usd_m: 6.9,
      repeat_spend_share_2024_pct: 46.2,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Bottom",
      td_id: "6185308",
      transaction_city: "Cleveland",
      transaction_state: "OH",
      spend_2025_usd_m: 6.0,
      transactions_2025_k: 158,
      repeat_spend_share_2025_pct: 43.5,
      spend_2024_usd_m: 6.7,
      repeat_spend_share_2024_pct: 45.8,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Bottom",
      td_id: "6185442",
      transaction_city: "Oklahoma City",
      transaction_state: "OK",
      spend_2025_usd_m: 5.9,
      transactions_2025_k: 153,
      repeat_spend_share_2025_pct: 42.8,
      spend_2024_usd_m: 6.5,
      repeat_spend_share_2024_pct: 44.9,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
    {
      rank_group: "Bottom",
      td_id: "6185581",
      transaction_city: "Las Vegas",
      transaction_state: "NV",
      spend_2025_usd_m: 5.7,
      transactions_2025_k: 149,
      repeat_spend_share_2025_pct: 42.1,
      spend_2024_usd_m: 6.3,
      repeat_spend_share_2024_pct: 44.1,
      portfolio_avg_spend_2025_usd_m: 18.6,
    },
  ];
}

function buildTrace(query: string, sql: string): TraceStep[] {
  return [
    {
      id: "t1",
      title: "Resolve intent and date context",
      summary: `Mapped request to semantic model entities and resolved latest RESP_DATE context for "${query.slice(0, 100)}".`,
      status: "done",
      qualityChecks: ["Date context resolved", "Semantic model entities matched"],
    },
    {
      id: "t2",
      title: "Generate governed SQL",
      summary: "Built allowlisted SQL against customer-insights tables with read-only constraints.",
      status: "done",
      sql,
      qualityChecks: ["Allowlist guard passed", "Read-only SQL guard passed"],
    },
    {
      id: "t3",
      title: "Validate and rank insights",
      summary: "Reconciled aggregates and prioritized findings by impact and decision relevance.",
      status: "done",
      qualityChecks: ["Totals reconcile", "No restricted columns accessed"],
    },
  ];
}

function tableFromRows(
  id: string,
  name: string,
  rows: Array<Record<string, string | number | boolean | null>>,
  sourceSql: string,
  description: string,
): DataTable {
  return {
    id,
    name,
    columns: rows[0] ? Object.keys(rows[0]) : [],
    rows,
    rowCount: rows.length,
    sourceSql,
    description,
  };
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
    description: "Segment-level share decomposition used to generate driver analysis.",
    sourceSql,
  };
}

function overviewMetrics(): MetricPoint[] {
  return [
    { label: "Total Spend", value: 2.83, delta: 0.27, unit: "usd" },
    { label: "Total Transactions", value: 74200000, delta: 5300000, unit: "count" },
    { label: "Repeat Spend Share", value: 54.8, delta: 1.1, unit: "pct" },
  ];
}

export function getMockAgentResponse(userQuery: string): AgentResponse {
  const profile = queryProfile(userQuery);

  if (profile === "state_sales") {
    const evidence: EvidenceRow[] = [
      { segment: "California spend share", prior: 19.8, current: 20.5, changeBps: 70, contribution: 0.22 },
      { segment: "Texas spend share", prior: 17.5, current: 18.4, changeBps: 90, contribution: 0.19 },
      { segment: "Florida spend share", prior: 15.2, current: 15.8, changeBps: 60, contribution: 0.14 },
      { segment: "CNP channel share", prior: 37.4, current: 39.8, changeBps: 240, contribution: 0.27 },
    ];
    const sql =
      "SELECT TRANSACTION_STATE, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k, MIN(RESP_DATE) AS data_from, MAX(RESP_DATE) AS data_through FROM cia_sales_insights_cortex GROUP BY TRANSACTION_STATE ORDER BY spend_usd_m DESC;";
    return {
      answer:
        "Sales are highest in CA, TX, FL, NY, and GA. Across the latest window, CNP share increased to 39.8%, with CA and TX contributing the largest dollar movement.",
      confidence: "high",
      whyItMatters:
        "State concentration and channel mix explain most variance, so growth and risk interventions can be targeted to a small set of geographies.",
      metrics: [
        { label: "Total Spend", value: 2.83, delta: 0.27, unit: "usd" },
        { label: "Total Transactions", value: 74200000, delta: 5300000, unit: "count" },
        { label: "CNP Spend Share", value: 39.8, delta: 2.4, unit: "pct" },
      ],
      evidence,
      insights: [
        {
          id: "i1",
          title: "Top 5 states drive most movement",
          detail: "CA, TX, FL, NY, and GA account for roughly 63% of total spend.",
          importance: "high",
        },
        {
          id: "i2",
          title: "CNP is growing faster than CP",
          detail: "CNP share rose 240 bps, concentrated in high-volume coastal states.",
          importance: "high",
        },
        {
          id: "i3",
          title: "Ticket size is stable",
          detail: "Average sale amount moved modestly, indicating growth is mainly transaction-volume driven.",
          importance: "medium",
        },
      ],
      suggestedQuestions: [
        "Break out each state by CP vs CNP spend and transactions.",
        "Which states have the largest repeat customer share gains?",
        "Show weekly trend for the top 5 states in the latest quarter.",
      ],
      assumptions: [
        "Latest data window uses MIN/MAX RESP_DATE from cia_sales_insights_cortex.",
        "Spend and transaction values are aggregated across consumer and commercial traffic.",
      ],
      trace: buildTrace(userQuery, sql),
      dataTables: [
        tableFromEvidence("state_driver_breakdown", "State and Channel Driver Breakdown", evidence, sql),
        tableFromRows(
          "state_sales_2025",
          "Sales by State (Latest Window)",
          stateRows(),
          sql,
          "State-level spend, transactions, ticket size, and CP/CNP shares.",
        ),
        tableFromRows(
          "state_channel_mix",
          "State x Channel Mix (Top States)",
          stateChannelRows(10),
          "SELECT TRANSACTION_STATE, CHANNEL, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k FROM cia_sales_insights_cortex GROUP BY TRANSACTION_STATE, CHANNEL;",
          "CP/CNP split for top states by spend.",
        ),
      ],
    };
  }

  if (profile === "q4_yoy") {
    const evidence: EvidenceRow[] = [
      { segment: "CNP share", prior: 39.1, current: 41.2, changeBps: 210, contribution: 0.31 },
      { segment: "Repeat spend share", prior: 52.4, current: 54.0, changeBps: 160, contribution: 0.22 },
      { segment: "CP share", prior: 60.9, current: 58.8, changeBps: -210, contribution: -0.16 },
      { segment: "Top 5 states share", prior: 61.7, current: 63.0, changeBps: 130, contribution: 0.19 },
    ];
    const sql =
      "SELECT 'spend_usd_m' AS metric, 742.6 AS q4_2025, 656.4 AS q4_2024, 13.1 AS yoy_pct UNION ALL SELECT 'transactions_k', 21410, 19880, 7.7 UNION ALL SELECT 'avg_sale_amount_usd', 34.68, 33.02, 5.0;";
    return {
      answer:
        "For Q4 2025 versus Q4 2024: sales increased from $656.4M to $742.6M (+13.1%), transactions rose from 19.88M to 21.41M (+7.7%), and average sale amount increased from $33.02 to $34.68 (+5.0%).",
      confidence: "high",
      whyItMatters:
        "Growth came from both volume and ticket size, while channel mix shifted toward CNP. That suggests expansion opportunity with concurrent online-risk and operations implications.",
      metrics: [
        { label: "Q4 2025 Spend", value: 0.74, delta: 0.09, unit: "usd" },
        { label: "Q4 2025 Transactions", value: 21410000, delta: 1530000, unit: "count" },
        { label: "Q4 CNP Share", value: 41.2, delta: 2.1, unit: "pct" },
      ],
      evidence,
      insights: [
        {
          id: "i1",
          title: "YoY growth is balanced",
          detail: "Both transactions and ticket size increased, not just one lever.",
          importance: "high",
        },
        {
          id: "i2",
          title: "CNP acceleration is material",
          detail: "CNP share gained 210 bps year-over-year, concentrated in high-volume states.",
          importance: "high",
        },
        {
          id: "i3",
          title: "Repeat mix improved",
          detail: "Repeat spend share improved by 160 bps, supporting healthier retention.",
          importance: "medium",
        },
      ],
      suggestedQuestions: [
        "Show the same Q4 YoY comparison by state and channel.",
        "Which states contributed most to average ticket growth?",
        "Split YoY performance by consumer versus commercial transactions.",
      ],
      assumptions: [
        "Q4 window is interpreted as October 1 through December 31 for each year.",
        "Latest available year in mock data is anchored to RESP_DATE max of 2025-12-31.",
      ],
      trace: buildTrace(userQuery, sql),
      dataTables: [
        tableFromEvidence("q4_yoy_driver_breakdown", "Q4 YoY Driver Breakdown", evidence, sql),
        tableFromRows(
          "q4_yoy_summary",
          "Q4 2025 vs Q4 2024 Summary",
          [
            { metric: "spend_usd_m", q4_2025: 742.6, q4_2024: 656.4, yoy_pct: 13.1, yoy_abs_usd_m: 86.2 },
            { metric: "transactions_k", q4_2025: 21410, q4_2024: 19880, yoy_pct: 7.7, yoy_abs_k: 1530 },
            { metric: "avg_sale_amount_usd", q4_2025: 34.68, q4_2024: 33.02, yoy_pct: 5.0, yoy_abs_usd: 1.66 },
            { metric: "cp_spend_share_pct", q4_2025: 58.8, q4_2024: 60.9, yoy_pct: -3.4, yoy_abs_pp: -2.1 },
            { metric: "cnp_spend_share_pct", q4_2025: 41.2, q4_2024: 39.1, yoy_pct: 5.4, yoy_abs_pp: 2.1 },
            { metric: "repeat_spend_share_pct", q4_2025: 54.0, q4_2024: 52.4, yoy_pct: 3.1, yoy_abs_pp: 1.6 },
          ],
          sql,
          "Year-over-year summary for spend, transactions, average sale amount, and channel/repeat mix.",
        ),
        tableFromRows(
          "q4_state_channel_top",
          "Q4 State x Channel (Top States)",
          stateChannelRows(8),
          "SELECT TRANSACTION_STATE, CHANNEL, SUM(SPEND), SUM(TRANSACTIONS) FROM cia_sales_insights_cortex WHERE RESP_DATE BETWEEN '2025-10-01' AND '2025-12-31' GROUP BY TRANSACTION_STATE, CHANNEL;",
          "State/channel detail supporting the YoY movement explanation.",
        ),
      ],
    };
  }

  if (profile === "store_performance") {
    const evidence: EvidenceRow[] = [
      { segment: "Top 5 stores repeat share", prior: 58.0, current: 62.7, changeBps: 470, contribution: 0.48 },
      { segment: "Bottom 5 stores repeat share", prior: 45.6, current: 43.6, changeBps: -200, contribution: -0.19 },
      { segment: "Portfolio repeat share", prior: 53.5, current: 54.8, changeBps: 130, contribution: 0.12 },
      { segment: "Top vs bottom spend gap", prior: 22.8, current: 28.4, changeBps: 560, contribution: 0.27 },
    ];
    const sql =
      "SELECT TD_ID, TRANSACTION_CITY, TRANSACTION_STATE, SUM(SPEND) AS spend_2025_usd_m, SUM(TRANSACTIONS) AS transactions_2025_k FROM cia_sales_insights_cortex WHERE RESP_DATE BETWEEN '2025-01-01' AND '2025-12-31' GROUP BY TD_ID, TRANSACTION_CITY, TRANSACTION_STATE;";
    return {
      answer:
        "Top stores in 2025 outperform bottom stores and portfolio average on spend growth and repeat-customer mix. Top 5 stores average +16.6% YoY spend with 62.7% repeat share, while bottom 5 stores are -8.1% YoY with 43.6% repeat share.",
      confidence: "high",
      whyItMatters:
        "The spread between top and bottom stores is widening. New/repeat mix and local execution patterns are likely key levers for lift at underperforming locations.",
      metrics: [
        { label: "Top Store Spend", value: 0.04, delta: 0.01, unit: "usd" },
        { label: "Bottom Store Spend", value: 0.01, delta: -0.0, unit: "usd" },
        { label: "Repeat Share Gap", value: 19.1, delta: 6.7, unit: "pct" },
      ],
      evidence,
      insights: [
        {
          id: "i1",
          title: "Repeat mix strongly predicts winners",
          detail: "Top stores are materially more repeat-heavy than bottom stores in both years.",
          importance: "high",
        },
        {
          id: "i2",
          title: "Bottom cohort is losing momentum",
          detail: "Bottom stores show negative YoY spend with rising new-customer dependency.",
          importance: "high",
        },
        {
          id: "i3",
          title: "Portfolio average masks dispersion",
          detail: "Aggregate performance looks healthy, but tail underperformance is expanding.",
          importance: "medium",
        },
      ],
      suggestedQuestions: [
        "For bottom stores, break out CP vs CNP and day-of-week patterns.",
        "Which bottom stores have the largest repeat-share deterioration YoY?",
        "Compare household coverage for top and bottom stores.",
      ],
      assumptions: [
        "Store performance uses TD_ID-level aggregation for calendar year 2025.",
        "Repeat/new mix is derived from repeat_spend and new_spend ratios.",
      ],
      trace: buildTrace(userQuery, sql),
      dataTables: [
        tableFromEvidence("store_driver_breakdown", "Top vs Bottom Store Driver Breakdown", evidence, sql),
        tableFromRows(
          "store_rankings_2025",
          "Top and Bottom Stores (2025)",
          storeRows(),
          sql,
          "TD_ID-level ranking with city/state context and YoY comparisons.",
        ),
        tableFromRows(
          "store_mix_summary",
          "Store Mix vs Portfolio Average",
          [
            {
              segment: "Top 5 Stores",
              repeat_spend_share_2025_pct: 62.7,
              new_spend_share_2025_pct: 37.3,
              repeat_spend_share_2024_pct: 58.0,
              spend_growth_yoy_pct: 16.6,
            },
            {
              segment: "Bottom 5 Stores",
              repeat_spend_share_2025_pct: 43.6,
              new_spend_share_2025_pct: 56.4,
              repeat_spend_share_2024_pct: 45.6,
              spend_growth_yoy_pct: -8.1,
            },
            {
              segment: "Portfolio Average",
              repeat_spend_share_2025_pct: 54.8,
              new_spend_share_2025_pct: 45.2,
              repeat_spend_share_2024_pct: 53.5,
              spend_growth_yoy_pct: 9.4,
            },
          ],
          "SELECT TD_ID, SUM(REPEAT_SPEND), SUM(NEW_SPEND) FROM cia_sales_insights_cortex GROUP BY TD_ID;",
          "New vs repeat mix for top/bottom cohorts against portfolio average.",
        ),
      ],
    };
  }

  const sql =
    "SELECT DATE_TRUNC('MONTH', RESP_DATE) AS month, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k FROM cia_sales_insights_cortex GROUP BY 1 ORDER BY 1;";
  return {
    answer:
      "Latest-period sales and transactions are trending up, with growth concentrated in the largest states and a gradual shift toward CNP and repeat-customer contribution.",
    confidence: "medium",
    whyItMatters: "The direction is positive, but state/channel concentration should be monitored to balance growth and risk.",
    metrics: overviewMetrics(),
    evidence: [
      { segment: "CNP channel share", prior: 38.9, current: 39.8, changeBps: 90, contribution: 0.24 },
      { segment: "Repeat spend share", prior: 53.7, current: 54.8, changeBps: 110, contribution: 0.19 },
      { segment: "Top 5 states share", prior: 62.3, current: 63.0, changeBps: 70, contribution: 0.15 },
    ],
    insights: [
      {
        id: "i1",
        title: "Growth remains concentrated",
        detail: "A handful of states explain the majority of the aggregate uplift.",
        importance: "high",
      },
      {
        id: "i2",
        title: "Channel mix keeps shifting",
        detail: "CNP penetration is climbing steadily and should inform operations planning.",
        importance: "medium",
      },
    ],
    suggestedQuestions: [
      "Show monthly trend by state for the last 12 months.",
      "Break down growth by CP vs CNP by state.",
      "How does repeat/new mix vary by store cohort?",
    ],
    assumptions: [
      "Response summarizes latest available calendar window in the mock dataset.",
      "All results use semantic-model allowlisted tables only.",
    ],
    trace: buildTrace(userQuery, sql),
    dataTables: [
      tableFromRows(
        "overview_monthly_trend",
        "Monthly Spend and Transactions",
        [
          { month: "2025-08-01", spend_usd_m: 214.2, transactions_k: 6140 },
          { month: "2025-09-01", spend_usd_m: 221.6, transactions_k: 6290 },
          { month: "2025-10-01", spend_usd_m: 236.3, transactions_k: 6890 },
          { month: "2025-11-01", spend_usd_m: 245.1, transactions_k: 7120 },
          { month: "2025-12-01", spend_usd_m: 261.2, transactions_k: 7400 },
        ],
        sql,
        "High-level monthly trend across spend and transactions.",
      ),
      tableFromRows(
        "overview_channel_mix",
        "Channel Mix Snapshot",
        [
          { channel: "CP", spend_usd_m: 1703.0, transactions_k: 45420 },
          { channel: "CNP", spend_usd_m: 1127.6, transactions_k: 28780 },
        ],
        "SELECT CHANNEL, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k FROM cia_sales_insights_cortex GROUP BY CHANNEL;",
        "Current mix between card-present and card-not-present activity.",
      ),
    ],
  };
}
