import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { EvidenceTable } from "./evidence-table";

describe("EvidenceTable comparison rendering", () => {
  it("renders date-only values without timezone day-shift", () => {
    const html = renderToStaticMarkup(
      <EvidenceTable
        tableConfig={{
          style: "simple",
          columns: [
            { key: "data_from", label: "Data From", format: "date", align: "left" },
            { key: "data_through", label: "Data Through", format: "date", align: "left" },
            { key: "total_sales", label: "Total Sales", format: "number", align: "right" },
          ],
        }}
        dataTables={[
          {
            id: "date_bounds",
            name: "date_bounds",
            columns: ["data_from", "data_through", "total_sales"],
            rows: [{ data_from: "2025-11-01", data_through: "2025-11-30", total_sales: 98395723.5 }],
            rowCount: 1,
          },
        ]}
      />,
    );

    const expectedFrom = new Date(2025, 10, 1).toLocaleDateString();
    const expectedThrough = new Date(2025, 10, 30).toLocaleDateString();
    const utcShiftedFrom = new Date("2025-11-01").toLocaleDateString();
    const utcShiftedThrough = new Date("2025-11-30").toLocaleDateString();

    assert.ok(html.includes(expectedFrom));
    assert.ok(html.includes(expectedThrough));
    if (utcShiftedFrom !== expectedFrom) assert.ok(!html.includes(utcShiftedFrom));
    if (utcShiftedThrough !== expectedThrough) assert.ok(!html.includes(utcShiftedThrough));
  });

  it("renders date-only month labels without timezone month drift", () => {
    const html = renderToStaticMarkup(
      <EvidenceTable
        chartConfig={{
          type: "line",
          x: "month_start",
          y: "customers",
          xLabel: "Month",
          yLabel: "Customers",
          yFormat: "number",
        }}
        dataTables={[
          {
            id: "monthly_mix",
            name: "Monthly Mix",
            columns: ["month_start", "customers"],
            rows: [
              { month_start: "2025-06-01", customers: 100 },
              { month_start: "2025-07-01", customers: 110 },
              { month_start: "2025-08-01", customers: 120 },
            ],
            rowCount: 3,
          },
        ]}
      />,
    );

    assert.ok(html.includes("Jun 2025"));
    assert.ok(!html.includes("May 2025"));
  });

  it("renders comparison table with configured comparison keys and delta columns", () => {
    const html = renderToStaticMarkup(
      <EvidenceTable
        tableConfig={{
          style: "comparison",
          columns: [
            { key: "metric", label: "Metric", format: "string", align: "left" },
            { key: "q4_2023", label: "Q4 2023", format: "number", align: "right" },
            { key: "q4_2024", label: "Q4 2024", format: "number", align: "right" },
            { key: "q4_2025", label: "Q4 2025", format: "number", align: "right" },
          ],
          comparisonMode: "baseline",
          comparisonKeys: ["q4_2023", "q4_2024", "q4_2025"],
          baselineKey: "q4_2023",
          deltaPolicy: "both",
          maxComparandsBeforeChartSwitch: 6,
        }}
        dataTables={[
          {
            id: "q4_rollup",
            name: "Q4 rollup",
            columns: ["metric", "q4_2023", "q4_2024", "q4_2025"],
            rows: [
              { metric: "sales", q4_2023: 251.9, q4_2024: 259.1, q4_2025: 301.7 },
              { metric: "transactions", q4_2023: 7427510, q4_2024: 7428740, q4_2025: 8428740 },
            ],
            rowCount: 2,
          },
        ]}
      />,
    );

    assert.ok(html.includes("Comparison Table"));
    assert.ok(html.includes("Q4 2023"));
    assert.ok(html.includes("Q4 2025"));
    assert.ok(html.includes("%Δ Q4 2025 vs Q4 2023"));
  });

  it("renders compact comparison message when comparands exceed threshold", () => {
    const html = renderToStaticMarkup(
      <EvidenceTable
        tableConfig={{
          style: "comparison",
          columns: [
            { key: "metric", label: "Metric", format: "string", align: "left" },
            { key: "y2022", label: "2022", format: "number", align: "right" },
            { key: "y2023", label: "2023", format: "number", align: "right" },
            { key: "y2024", label: "2024", format: "number", align: "right" },
            { key: "y2025", label: "2025", format: "number", align: "right" },
          ],
          comparisonMode: "pairwise",
          comparisonKeys: ["y2022", "y2023", "y2024", "y2025"],
          baselineKey: "y2022",
          deltaPolicy: "abs",
          maxComparandsBeforeChartSwitch: 3,
        }}
        dataTables={[
          {
            id: "year_rollup",
            name: "Year rollup",
            columns: ["metric", "y2022", "y2023", "y2024", "y2025"],
            rows: [
              { metric: "sales", y2022: 91, y2023: 96, y2024: 102, y2025: 125 },
              { metric: "transactions", y2022: 3500, y2023: 3600, y2024: 3700, y2025: 3980 },
            ],
            rowCount: 2,
          },
        ]}
      />,
    );

    assert.ok(html.includes("Showing top movers only"));
  });

  it("renders semantic comparison rows from comparison signals", () => {
    const html = renderToStaticMarkup(
      <EvidenceTable
        tableConfig={{
          style: "comparison",
          columns: [{ key: "total_sales", label: "Total Sales", format: "number", align: "right" }],
        }}
        comparisons={[
          {
            id: "cmp_sales",
            metric: "total_sales",
            priorPeriod: "Q4 2024",
            currentPeriod: "Q4 2025",
            priorValue: 259073236.5,
            currentValue: 301732926.9,
            absDelta: 42659690.4,
            pctDelta: 16.5,
            provenance: [],
          },
          {
            id: "cmp_transactions",
            metric: "total_transactions",
            priorPeriod: "Q4 2024",
            currentPeriod: "Q4 2025",
            priorValue: 7435140,
            currentValue: 8428740,
            absDelta: 993600,
            pctDelta: 13.4,
            provenance: [],
          },
        ]}
        dataTables={[
          {
            id: "single_row",
            name: "single_row",
            columns: ["total_sales", "total_transactions", "average_sale_amount"],
            rows: [{ total_sales: 301732926.9, total_transactions: 8428740, average_sale_amount: 35.8 }],
            rowCount: 1,
          },
        ]}
      />,
    );

    assert.ok(html.includes("Q4 2025 vs Q4 2024"));
    assert.ok(html.includes(">Q4 2024<"));
    assert.ok(html.includes(">Q4 2025<"));
    assert.ok(html.includes("+$42.7M"));
    assert.ok(!html.includes("Prior Period"));
    assert.ok(!html.includes("Current Period"));
  });

  it("prefers semantic comparison panel even if table style drifts from comparison", () => {
    const html = renderToStaticMarkup(
      <EvidenceTable
        tableConfig={{
          style: "ranked",
          columns: [{ key: "sales", label: "Sales", format: "number", align: "right" }],
          showRank: true,
        }}
        primaryVisual={{ title: "Primary table", visualType: "comparison" }}
        comparisons={[
          {
            id: "cmp_sales",
            metric: "sales",
            priorPeriod: "Q4 2024",
            currentPeriod: "Q4 2025",
            priorValue: 259073236.5,
            currentValue: 301732926.9,
            absDelta: 42659690.4,
            pctDelta: 16.5,
            provenance: [],
          },
        ]}
        dataTables={[
          {
            id: "single_row",
            name: "single_row",
            columns: ["sales"],
            rows: [{ sales: 301732926.9 }],
            rowCount: 1,
          },
        ]}
      />,
    );

    assert.ok(html.includes("Q4 2025 vs Q4 2024"));
    assert.ok(!html.includes("Rank"));
  });
});
