from __future__ import annotations

from app.models import AgentResponse, ChatTurnRequest, DataTable, EvidenceRow, QueryPlanStep, SqlExecutionResult, ValidationResult

DATA_FROM = "2025-01-01"
DATA_THROUGH = "2025-12-31"

STATE_BASE = [
    ("CA", 236.4, 6210, 46.8),
    ("TX", 212.7, 5660, 43.1),
    ("FL", 188.9, 4890, 41.7),
    ("NY", 181.2, 4720, 48.9),
    ("GA", 149.5, 3890, 39.8),
    ("IL", 142.8, 3710, 42.6),
    ("PA", 136.4, 3490, 40.4),
    ("NC", 129.8, 3360, 38.6),
    ("OH", 121.1, 3190, 37.9),
    ("VA", 116.2, 3050, 41.2),
    ("AZ", 109.7, 2810, 40.8),
    ("NJ", 106.8, 2740, 45.7),
    ("WA", 98.5, 2520, 47.1),
    ("MA", 94.2, 2390, 46.5),
    ("TN", 88.9, 2290, 37.6),
    ("IN", 84.6, 2200, 36.8),
    ("MO", 79.8, 2080, 35.9),
    ("MD", 76.5, 1990, 43.8),
    ("CO", 73.4, 1920, 44.1),
    ("MN", 69.3, 1820, 39.2),
    ("WI", 66.7, 1750, 35.3),
    ("SC", 63.8, 1690, 36.6),
    ("AL", 60.4, 1600, 34.7),
    ("LA", 58.9, 1550, 35.5),
    ("KY", 57.2, 1500, 34.2),
    ("OR", 55.6, 1450, 42.7),
    ("OK", 54.1, 1410, 33.8),
    ("CT", 53.5, 1390, 43.4),
    ("UT", 52.8, 1360, 38.9),
    ("NV", 51.9, 1340, 44.5),
]


def _query_profile(message: str) -> str:
    lowered = message.lower()
    if ("top" in lowered and "bottom" in lowered) and any(token in lowered for token in ["store", "location", "td_id"]):
        return "store_performance"
    if any(token in lowered for token in ["q4", "same period last year", "year over year", "yoy", "previous year"]):
        return "q4_yoy"
    if "state" in lowered and any(token in lowered for token in ["sales", "spend", "transaction"]):
        return "state_sales"
    return "overview"


def _state_rows() -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    for state, spend_m, transactions_k, cnp_share_pct in STATE_BASE:
        avg_ticket = round((spend_m * 1000) / transactions_k, 2)
        rows.append(
            {
                "transaction_state": state,
                "spend_usd_m": spend_m,
                "transactions_k": transactions_k,
                "avg_sale_amount_usd": avg_ticket,
                "cp_spend_share_pct": round(100 - cnp_share_pct, 1),
                "cnp_spend_share_pct": round(cnp_share_pct, 1),
                "data_from": DATA_FROM,
                "data_through": DATA_THROUGH,
            }
        )
    return rows


def _state_channel_rows(limit_states: int = 10) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    for state, spend_m, transactions_k, cnp_share_pct in STATE_BASE[:limit_states]:
        cp_share_pct = 100 - cnp_share_pct
        cp_spend_m = round(spend_m * cp_share_pct / 100, 1)
        cnp_spend_m = round(spend_m * cnp_share_pct / 100, 1)
        cp_transactions_k = int(round(transactions_k * cp_share_pct / 100))
        cnp_transactions_k = int(round(transactions_k * cnp_share_pct / 100))
        cp_avg = round((cp_spend_m * 1000) / max(cp_transactions_k, 1), 2)
        cnp_avg = round((cnp_spend_m * 1000) / max(cnp_transactions_k, 1), 2)

        rows.append(
            {
                "transaction_state": state,
                "channel": "CP",
                "spend_usd_m": cp_spend_m,
                "transactions_k": cp_transactions_k,
                "avg_sale_amount_usd": cp_avg,
                "data_from": DATA_FROM,
                "data_through": DATA_THROUGH,
            }
        )
        rows.append(
            {
                "transaction_state": state,
                "channel": "CNP",
                "spend_usd_m": cnp_spend_m,
                "transactions_k": cnp_transactions_k,
                "avg_sale_amount_usd": cnp_avg,
                "data_from": DATA_FROM,
                "data_through": DATA_THROUGH,
            }
        )
    return rows


def _store_rows() -> list[dict[str, float | int | str]]:
    return [
        {
            "rank_group": "Top",
            "td_id": "6182655",
            "transaction_city": "Houston",
            "transaction_state": "TX",
            "spend_2025_usd_m": 42.1,
            "transactions_2025_k": 1110,
            "repeat_spend_share_2025_pct": 64.3,
            "spend_2024_usd_m": 35.8,
            "repeat_spend_share_2024_pct": 59.9,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Top",
            "td_id": "6181442",
            "transaction_city": "Miami",
            "transaction_state": "FL",
            "spend_2025_usd_m": 39.4,
            "transactions_2025_k": 1030,
            "repeat_spend_share_2025_pct": 62.8,
            "spend_2024_usd_m": 33.7,
            "repeat_spend_share_2024_pct": 58.0,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Top",
            "td_id": "6183118",
            "transaction_city": "Los Angeles",
            "transaction_state": "CA",
            "spend_2025_usd_m": 37.8,
            "transactions_2025_k": 980,
            "repeat_spend_share_2025_pct": 63.7,
            "spend_2024_usd_m": 32.4,
            "repeat_spend_share_2024_pct": 58.8,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Top",
            "td_id": "6182027",
            "transaction_city": "Atlanta",
            "transaction_state": "GA",
            "spend_2025_usd_m": 35.1,
            "transactions_2025_k": 930,
            "repeat_spend_share_2025_pct": 61.9,
            "spend_2024_usd_m": 30.9,
            "repeat_spend_share_2024_pct": 57.4,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Top",
            "td_id": "6182780",
            "transaction_city": "Phoenix",
            "transaction_state": "AZ",
            "spend_2025_usd_m": 33.8,
            "transactions_2025_k": 880,
            "repeat_spend_share_2025_pct": 60.7,
            "spend_2024_usd_m": 29.5,
            "repeat_spend_share_2024_pct": 56.1,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Bottom",
            "td_id": "6184993",
            "transaction_city": "Baton Rouge",
            "transaction_state": "LA",
            "spend_2025_usd_m": 6.4,
            "transactions_2025_k": 170,
            "repeat_spend_share_2025_pct": 45.1,
            "spend_2024_usd_m": 7.0,
            "repeat_spend_share_2024_pct": 47.0,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Bottom",
            "td_id": "6185120",
            "transaction_city": "Knoxville",
            "transaction_state": "TN",
            "spend_2025_usd_m": 6.2,
            "transactions_2025_k": 162,
            "repeat_spend_share_2025_pct": 44.4,
            "spend_2024_usd_m": 6.9,
            "repeat_spend_share_2024_pct": 46.2,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Bottom",
            "td_id": "6185308",
            "transaction_city": "Cleveland",
            "transaction_state": "OH",
            "spend_2025_usd_m": 6.0,
            "transactions_2025_k": 158,
            "repeat_spend_share_2025_pct": 43.5,
            "spend_2024_usd_m": 6.7,
            "repeat_spend_share_2024_pct": 45.8,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Bottom",
            "td_id": "6185442",
            "transaction_city": "Oklahoma City",
            "transaction_state": "OK",
            "spend_2025_usd_m": 5.9,
            "transactions_2025_k": 153,
            "repeat_spend_share_2025_pct": 42.8,
            "spend_2024_usd_m": 6.5,
            "repeat_spend_share_2024_pct": 44.9,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
        {
            "rank_group": "Bottom",
            "td_id": "6185581",
            "transaction_city": "Las Vegas",
            "transaction_state": "NV",
            "spend_2025_usd_m": 5.7,
            "transactions_2025_k": 149,
            "repeat_spend_share_2025_pct": 42.1,
            "spend_2024_usd_m": 6.3,
            "repeat_spend_share_2024_pct": 44.1,
            "portfolio_avg_spend_2025_usd_m": 18.6,
        },
    ]


def _table_from_evidence(id_: str, name: str, rows: list[EvidenceRow], source_sql: str) -> DataTable:
    return DataTable(
        id=id_,
        name=name,
        columns=["segment", "prior", "current", "changeBps", "contribution"],
        rows=[
            {
                "segment": row.segment,
                "prior": row.prior,
                "current": row.current,
                "changeBps": row.changeBps,
                "contribution": row.contribution,
            }
            for row in rows
        ],
        rowCount=len(rows),
        description="Segment-level share decomposition used in the analysis narrative.",
        sourceSql=source_sql,
    )


def _table_from_rows(
    *,
    id_: str,
    name: str,
    rows: list[dict[str, float | int | str]],
    source_sql: str,
    description: str,
) -> DataTable:
    return DataTable(
        id=id_,
        name=name,
        columns=list(rows[0].keys()) if rows else [],
        rows=rows,
        rowCount=len(rows),
        description=description,
        sourceSql=source_sql,
    )


def _tables_from_sql_results(results: list[SqlExecutionResult]) -> list[DataTable]:
    tables: list[DataTable] = []
    for index, result in enumerate(results, start=1):
        columns = list(result.rows[0].keys()) if result.rows else []
        tables.append(
            DataTable(
                id=f"sql_step_{index}",
                name=f"SQL Step {index} Output",
                columns=columns,
                rows=result.rows,
                rowCount=result.rowCount,
                sourceSql=result.sql,
            )
        )
    return tables


async def mock_create_plan(request: ChatTurnRequest) -> list[QueryPlanStep]:
    profile = _query_profile(request.message)
    if profile == "state_sales":
        return [
            QueryPlanStep(id="step_1", goal="Resolve latest available RESP_DATE window"),
            QueryPlanStep(id="step_2", goal="Aggregate spend and transactions by transaction_state"),
        ]
    if profile == "q4_yoy":
        return [
            QueryPlanStep(id="step_1", goal="Resolve latest available RESP_DATE and identify comparison windows"),
            QueryPlanStep(id="step_2", goal="Compute Q4 2025 versus Q4 2024 sales, transactions, and ticket metrics"),
            QueryPlanStep(id="step_3", goal="Decompose YoY movement by channel and top states"),
        ]
    if profile == "store_performance":
        return [
            QueryPlanStep(id="step_1", goal="Rank top and bottom TD_ID stores for 2025 spend"),
            QueryPlanStep(id="step_2", goal="Compute repeat versus new customer mix for ranked stores"),
            QueryPlanStep(id="step_3", goal="Compare store performance to 2024 baseline and portfolio averages"),
            QueryPlanStep(id="step_4", goal="Surface household/store context for low-performing locations"),
        ]
    return [
        QueryPlanStep(id="step_1", goal="Retrieve spend and transactions trend by month"),
        QueryPlanStep(id="step_2", goal="Highlight channel and repeat/new mix drivers"),
    ]


async def mock_run_sql(request: ChatTurnRequest, plan: list[QueryPlanStep]) -> list[SqlExecutionResult]:
    profile = _query_profile(request.message)
    state_rows = _state_rows()
    state_channel_rows = _state_channel_rows()
    store_rows = _store_rows()

    if profile == "state_sales":
        outputs = [
            SqlExecutionResult(
                sql="SELECT MAX(RESP_DATE) AS max_dt FROM cia_sales_insights_cortex;",
                rows=[{"max_dt": DATA_THROUGH}],
                rowCount=1,
            ),
            SqlExecutionResult(
                sql=(
                    "SELECT TRANSACTION_STATE, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k, "
                    "MIN(RESP_DATE) AS data_from, MAX(RESP_DATE) AS data_through "
                    "FROM cia_sales_insights_cortex GROUP BY TRANSACTION_STATE ORDER BY spend_usd_m DESC;"
                ),
                rows=state_rows,
                rowCount=len(state_rows),
            ),
        ]
        return outputs[: len(plan)]

    if profile == "q4_yoy":
        outputs = [
            SqlExecutionResult(
                sql="SELECT MAX(RESP_DATE) AS max_dt FROM cia_sales_insights_cortex;",
                rows=[{"max_dt": DATA_THROUGH}],
                rowCount=1,
            ),
            SqlExecutionResult(
                sql=(
                    "WITH windows AS (SELECT DATE '2025-10-01' AS q4_start_2025, DATE '2025-12-31' AS q4_end_2025, "
                    "DATE '2024-10-01' AS q4_start_2024, DATE '2024-12-31' AS q4_end_2024) "
                    "SELECT 'spend_usd_m' AS metric, 742.6 AS q4_2025, 656.4 AS q4_2024, 13.1 AS yoy_pct UNION ALL "
                    "SELECT 'transactions_k', 21410, 19880, 7.7 UNION ALL "
                    "SELECT 'avg_sale_amount_usd', 34.68, 33.02, 5.0;"
                ),
                rows=[
                    {"metric": "spend_usd_m", "q4_2025": 742.6, "q4_2024": 656.4, "yoy_pct": 13.1},
                    {"metric": "transactions_k", "q4_2025": 21410, "q4_2024": 19880, "yoy_pct": 7.7},
                    {"metric": "avg_sale_amount_usd", "q4_2025": 34.68, "q4_2024": 33.02, "yoy_pct": 5.0},
                ],
                rowCount=3,
            ),
            SqlExecutionResult(
                sql=(
                    "SELECT TRANSACTION_STATE, CHANNEL, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k "
                    "FROM cia_sales_insights_cortex "
                    "WHERE RESP_DATE BETWEEN '2025-10-01' AND '2025-12-31' "
                    "GROUP BY TRANSACTION_STATE, CHANNEL ORDER BY spend_usd_m DESC;"
                ),
                rows=state_channel_rows[:16],
                rowCount=16,
            ),
        ]
        return outputs[: len(plan)]

    if profile == "store_performance":
        outputs = [
            SqlExecutionResult(
                sql=(
                    "SELECT TD_ID, TRANSACTION_CITY, TRANSACTION_STATE, SUM(SPEND) AS spend_2025_usd_m, "
                    "SUM(TRANSACTIONS) AS transactions_2025_k "
                    "FROM cia_sales_insights_cortex "
                    "WHERE RESP_DATE BETWEEN '2025-01-01' AND '2025-12-31' "
                    "GROUP BY TD_ID, TRANSACTION_CITY, TRANSACTION_STATE;"
                ),
                rows=store_rows,
                rowCount=len(store_rows),
            ),
            SqlExecutionResult(
                sql=(
                    "SELECT TD_ID, SUM(REPEAT_SPEND) / NULLIF(SUM(SPEND), 0) * 100 AS repeat_spend_share_2025_pct, "
                    "SUM(NEW_SPEND) / NULLIF(SUM(SPEND), 0) * 100 AS new_spend_share_2025_pct "
                    "FROM cia_sales_insights_cortex "
                    "WHERE RESP_DATE BETWEEN '2025-01-01' AND '2025-12-31' "
                    "GROUP BY TD_ID;"
                ),
                rows=[
                    {
                        "segment": "Top 5 Stores",
                        "repeat_spend_share_2025_pct": 62.7,
                        "new_spend_share_2025_pct": 37.3,
                        "repeat_spend_share_2024_pct": 58.0,
                    },
                    {
                        "segment": "Bottom 5 Stores",
                        "repeat_spend_share_2025_pct": 43.6,
                        "new_spend_share_2025_pct": 56.4,
                        "repeat_spend_share_2024_pct": 45.6,
                    },
                    {
                        "segment": "Portfolio Average",
                        "repeat_spend_share_2025_pct": 54.8,
                        "new_spend_share_2025_pct": 45.2,
                        "repeat_spend_share_2024_pct": 53.5,
                    },
                ],
                rowCount=3,
            ),
            SqlExecutionResult(
                sql=(
                    "SELECT TD_ID, MIN(RESP_DATE) AS data_from, MAX(RESP_DATE) AS data_through "
                    "FROM cia_household_insights_cortex GROUP BY TD_ID;"
                ),
                rows=[
                    {"td_id": "6184993", "data_from": "2025-01-01", "data_through": "2025-12-31"},
                    {"td_id": "6185120", "data_from": "2025-01-01", "data_through": "2025-12-31"},
                    {"td_id": "6185308", "data_from": "2025-01-01", "data_through": "2025-12-31"},
                ],
                rowCount=3,
            ),
            SqlExecutionResult(
                sql=(
                    "SELECT DATE_TRUNC('MONTH', RESP_DATE) AS month, SUM(SPEND) AS spend_usd_m "
                    "FROM cia_sales_insights_cortex "
                    "WHERE TD_ID IN ('6182655', '6184993') "
                    "GROUP BY 1 ORDER BY 1;"
                ),
                rows=[
                    {"month": "2025-01-01", "top_store_spend_usd_m": 3.2, "bottom_store_spend_usd_m": 0.6},
                    {"month": "2025-04-01", "top_store_spend_usd_m": 3.4, "bottom_store_spend_usd_m": 0.5},
                    {"month": "2025-07-01", "top_store_spend_usd_m": 3.6, "bottom_store_spend_usd_m": 0.5},
                    {"month": "2025-10-01", "top_store_spend_usd_m": 3.8, "bottom_store_spend_usd_m": 0.4},
                ],
                rowCount=4,
            ),
        ]
        return outputs[: len(plan)]

    outputs = [
        SqlExecutionResult(
            sql=(
                "SELECT DATE_TRUNC('MONTH', RESP_DATE) AS month, SUM(SPEND) AS spend_usd_m, "
                "SUM(TRANSACTIONS) AS transactions_k FROM cia_sales_insights_cortex GROUP BY 1 ORDER BY 1;"
            ),
            rows=[
                {"month": "2025-08-01", "spend_usd_m": 214.2, "transactions_k": 6140},
                {"month": "2025-09-01", "spend_usd_m": 221.6, "transactions_k": 6290},
                {"month": "2025-10-01", "spend_usd_m": 236.3, "transactions_k": 6890},
                {"month": "2025-11-01", "spend_usd_m": 245.1, "transactions_k": 7120},
                {"month": "2025-12-01", "spend_usd_m": 261.2, "transactions_k": 7400},
            ],
            rowCount=5,
        ),
        SqlExecutionResult(
            sql=(
                "SELECT CHANNEL, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k "
                "FROM cia_sales_insights_cortex GROUP BY CHANNEL;"
            ),
            rows=[
                {"channel": "CP", "spend_usd_m": 1703.0, "transactions_k": 45420},
                {"channel": "CNP", "spend_usd_m": 1127.6, "transactions_k": 28780},
            ],
            rowCount=2,
        ),
    ]
    return outputs[: len(plan)]


async def mock_validate_results(results: list[SqlExecutionResult]) -> ValidationResult:
    total_rows = sum(result.rowCount for result in results)
    return ValidationResult(
        passed=True,
        checks=[
            f"Executed {len(results)} governed SQL step(s)",
            f"Retrieved {total_rows} total rows across result tables",
            "SQL references are constrained to semantic-model allowlisted tables",
        ],
    )


def _build_state_sales_response(results: list[SqlExecutionResult]) -> AgentResponse:
    evidence = [
        EvidenceRow(segment="California spend share", prior=19.8, current=20.5, changeBps=70, contribution=0.22),
        EvidenceRow(segment="Texas spend share", prior=17.5, current=18.4, changeBps=90, contribution=0.19),
        EvidenceRow(segment="Florida spend share", prior=15.2, current=15.8, changeBps=60, contribution=0.14),
        EvidenceRow(segment="CNP channel share", prior=37.4, current=39.8, changeBps=240, contribution=0.27),
    ]
    state_rows = _state_rows()
    channel_rows = _state_channel_rows(10)
    return AgentResponse(
        answer=(
            "Sales are highest in CA, TX, FL, NY, and GA. Across the latest window, CNP share increased to 39.8%, "
            "with CA and TX contributing the largest dollar movement."
        ),
        confidence="high",
        whyItMatters=(
            "State concentration and channel mix explain most of the variance, so growth and risk interventions can "
            "be targeted to a small set of geographies."
        ),
        metrics=[
            {"label": "Total Spend", "value": 2.83, "delta": 0.27, "unit": "usd"},
            {"label": "Total Transactions", "value": 74200000, "delta": 5300000, "unit": "count"},
            {"label": "CNP Spend Share", "value": 39.8, "delta": 2.4, "unit": "pct"},
        ],
        evidence=evidence,
        insights=[
            {
                "id": "i1",
                "title": "Top 5 states drive most movement",
                "detail": "CA, TX, FL, NY, and GA account for roughly 63% of total spend.",
                "importance": "high",
            },
            {
                "id": "i2",
                "title": "CNP is growing faster than CP",
                "detail": "CNP share rose 240 bps, concentrated in high-volume coastal states.",
                "importance": "high",
            },
            {
                "id": "i3",
                "title": "Ticket size is stable",
                "detail": "Average sale amount moved modestly, indicating growth is mainly transaction-volume driven.",
                "importance": "medium",
            },
        ],
        suggestedQuestions=[
            "Break out each state by CP vs CNP spend and transactions.",
            "Which states have the largest repeat customer share gains?",
            "Show weekly trend for the top 5 states in the latest quarter.",
        ],
        assumptions=[
            "Latest data window uses MIN/MAX RESP_DATE from cia_sales_insights_cortex.",
            "Spend and transaction values are aggregated across consumer and commercial traffic.",
        ],
        trace=[
            {
                "id": "t1",
                "title": "Resolve intent and date context",
                "summary": "Mapped question to state-level spend/transactions and resolved latest RESP_DATE window.",
                "status": "done",
                "qualityChecks": ["Date context resolved", "Semantic model entities matched"],
            },
            {
                "id": "t2",
                "title": "Generate governed SQL",
                "summary": "Queried allowlisted customer-insights tables with state and channel aggregations.",
                "status": "done",
                "sql": results[1].sql if len(results) > 1 else (results[0].sql if results else None),
                "qualityChecks": ["Allowlist guard passed", "Row limit guard passed"],
            },
            {
                "id": "t3",
                "title": "Validate and rank insights",
                "summary": "Ranked state and channel contributors by impact and consistency checks.",
                "status": "done",
                "qualityChecks": ["Contribution shares reconcile", "No restricted columns accessed"],
            },
        ],
        dataTables=[
            _table_from_evidence(
                "state_driver_breakdown",
                "State and Channel Driver Breakdown",
                evidence,
                "SELECT TRANSACTION_STATE, SUM(SPEND) AS spend_usd_m FROM cia_sales_insights_cortex GROUP BY TRANSACTION_STATE;",
            ),
            _table_from_rows(
                id_="state_sales_2025",
                name="Sales by State (Latest Window)",
                rows=state_rows,
                source_sql=(
                    "SELECT TRANSACTION_STATE, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k, "
                    "MIN(RESP_DATE) AS data_from, MAX(RESP_DATE) AS data_through "
                    "FROM cia_sales_insights_cortex GROUP BY TRANSACTION_STATE ORDER BY spend_usd_m DESC;"
                ),
                description="State-level spend, transactions, ticket size, and CP/CNP shares.",
            ),
            _table_from_rows(
                id_="state_channel_mix",
                name="State x Channel Mix (Top States)",
                rows=channel_rows,
                source_sql=(
                    "SELECT TRANSACTION_STATE, CHANNEL, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k "
                    "FROM cia_sales_insights_cortex GROUP BY TRANSACTION_STATE, CHANNEL;"
                ),
                description="CP/CNP split for top states by spend.",
            ),
            *_tables_from_sql_results(results),
        ],
    )


def _build_q4_yoy_response(results: list[SqlExecutionResult]) -> AgentResponse:
    evidence = [
        EvidenceRow(segment="CNP share", prior=39.1, current=41.2, changeBps=210, contribution=0.31),
        EvidenceRow(segment="Repeat spend share", prior=52.4, current=54.0, changeBps=160, contribution=0.22),
        EvidenceRow(segment="CP share", prior=60.9, current=58.8, changeBps=-210, contribution=-0.16),
        EvidenceRow(segment="Top 5 states share", prior=61.7, current=63.0, changeBps=130, contribution=0.19),
    ]
    yoy_summary = [
        {"metric": "spend_usd_m", "q4_2025": 742.6, "q4_2024": 656.4, "yoy_pct": 13.1, "yoy_abs_usd_m": 86.2},
        {"metric": "transactions_k", "q4_2025": 21410, "q4_2024": 19880, "yoy_pct": 7.7, "yoy_abs_k": 1530},
        {"metric": "avg_sale_amount_usd", "q4_2025": 34.68, "q4_2024": 33.02, "yoy_pct": 5.0, "yoy_abs_usd": 1.66},
        {"metric": "cp_spend_share_pct", "q4_2025": 58.8, "q4_2024": 60.9, "yoy_pct": -3.4, "yoy_abs_pp": -2.1},
        {"metric": "cnp_spend_share_pct", "q4_2025": 41.2, "q4_2024": 39.1, "yoy_pct": 5.4, "yoy_abs_pp": 2.1},
        {"metric": "repeat_spend_share_pct", "q4_2025": 54.0, "q4_2024": 52.4, "yoy_pct": 3.1, "yoy_abs_pp": 1.6},
    ]
    return AgentResponse(
        answer=(
            "For Q4 2025 versus Q4 2024: sales increased from $656.4M to $742.6M (+13.1%), transactions rose from "
            "19.88M to 21.41M (+7.7%), and average sale amount increased from $33.02 to $34.68 (+5.0%)."
        ),
        confidence="high",
        whyItMatters=(
            "Growth came from both volume and ticket size, while channel mix shifted toward CNP. That suggests "
            "expansion opportunity with concurrent online-risk and operations implications."
        ),
        metrics=[
            {"label": "Q4 2025 Spend", "value": 0.74, "delta": 0.09, "unit": "usd"},
            {"label": "Q4 2025 Transactions", "value": 21410000, "delta": 1530000, "unit": "count"},
            {"label": "Q4 CNP Share", "value": 41.2, "delta": 2.1, "unit": "pct"},
        ],
        evidence=evidence,
        insights=[
            {
                "id": "i1",
                "title": "YoY growth is balanced",
                "detail": "Both transactions and ticket size increased, rather than growth being purely price or volume.",
                "importance": "high",
            },
            {
                "id": "i2",
                "title": "CNP acceleration is material",
                "detail": "CNP share gained 210 bps year-over-year, concentrated in high-volume states.",
                "importance": "high",
            },
            {
                "id": "i3",
                "title": "Repeat mix improved",
                "detail": "Repeat spend share improved by 160 bps, supporting healthier retention.",
                "importance": "medium",
            },
        ],
        suggestedQuestions=[
            "Show the same Q4 YoY comparison by state and channel.",
            "Which states contributed most to average ticket growth?",
            "Split YoY performance by consumer versus commercial transactions.",
        ],
        assumptions=[
            "Q4 window is interpreted as October 1 through December 31 for each year.",
            "Latest available year in mock data is anchored to RESP_DATE max of 2025-12-31.",
        ],
        trace=[
            {
                "id": "t1",
                "title": "Resolve intent and comparison windows",
                "summary": "Detected explicit period comparison and resolved Q4 2025 versus Q4 2024 windows.",
                "status": "done",
                "qualityChecks": ["Time windows validated", "Metric set recognized"],
            },
            {
                "id": "t2",
                "title": "Generate governed SQL",
                "summary": "Executed allowlisted SQL for summary metrics and channel decomposition.",
                "status": "done",
                "sql": results[1].sql if len(results) > 1 else (results[0].sql if results else None),
                "qualityChecks": ["Allowlist guard passed", "Read-only SQL guard passed"],
            },
            {
                "id": "t3",
                "title": "Validate and rank insights",
                "summary": "Validated YoY deltas and ranked findings by impact and operational relevance.",
                "status": "done",
                "qualityChecks": ["YoY arithmetic reconciled", "Segment shares cross-checked"],
            },
        ],
        dataTables=[
            _table_from_evidence(
                "q4_yoy_driver_breakdown",
                "Q4 YoY Driver Breakdown",
                evidence,
                "SELECT CHANNEL, SUM(SPEND) FROM cia_sales_insights_cortex GROUP BY CHANNEL;",
            ),
            _table_from_rows(
                id_="q4_yoy_summary",
                name="Q4 2025 vs Q4 2024 Summary",
                rows=yoy_summary,
                source_sql=(
                    "WITH max_date AS (SELECT MAX(RESP_DATE) AS max_dt FROM cia_sales_insights_cortex) "
                    "SELECT ... FROM cia_sales_insights_cortex;"
                ),
                description="Year-over-year summary for spend, transactions, average sale amount, and channel/repeat mix.",
            ),
            _table_from_rows(
                id_="q4_state_channel_top",
                name="Q4 State x Channel (Top States)",
                rows=_state_channel_rows(8),
                source_sql=(
                    "SELECT TRANSACTION_STATE, CHANNEL, SUM(SPEND) AS spend_usd_m, SUM(TRANSACTIONS) AS transactions_k "
                    "FROM cia_sales_insights_cortex "
                    "WHERE RESP_DATE BETWEEN '2025-10-01' AND '2025-12-31' "
                    "GROUP BY TRANSACTION_STATE, CHANNEL;"
                ),
                description="State/channel detail supporting the YoY movement explanation.",
            ),
            *_tables_from_sql_results(results),
        ],
    )


def _build_store_response(results: list[SqlExecutionResult]) -> AgentResponse:
    evidence = [
        EvidenceRow(segment="Top 5 stores repeat share", prior=58.0, current=62.7, changeBps=470, contribution=0.48),
        EvidenceRow(segment="Bottom 5 stores repeat share", prior=45.6, current=43.6, changeBps=-200, contribution=-0.19),
        EvidenceRow(segment="Portfolio repeat share", prior=53.5, current=54.8, changeBps=130, contribution=0.12),
        EvidenceRow(segment="Top vs bottom spend gap", prior=22.8, current=28.4, changeBps=560, contribution=0.27),
    ]
    store_rows = _store_rows()
    mix_rows = [
        {
            "segment": "Top 5 Stores",
            "repeat_spend_share_2025_pct": 62.7,
            "new_spend_share_2025_pct": 37.3,
            "repeat_spend_share_2024_pct": 58.0,
            "spend_growth_yoy_pct": 16.6,
        },
        {
            "segment": "Bottom 5 Stores",
            "repeat_spend_share_2025_pct": 43.6,
            "new_spend_share_2025_pct": 56.4,
            "repeat_spend_share_2024_pct": 45.6,
            "spend_growth_yoy_pct": -8.1,
        },
        {
            "segment": "Portfolio Average",
            "repeat_spend_share_2025_pct": 54.8,
            "new_spend_share_2025_pct": 45.2,
            "repeat_spend_share_2024_pct": 53.5,
            "spend_growth_yoy_pct": 9.4,
        },
    ]
    return AgentResponse(
        answer=(
            "Top stores in 2025 outperform both bottom stores and portfolio average on spend growth and repeat-customer "
            "mix. Top 5 stores average +16.6% YoY spend with 62.7% repeat share, while bottom 5 stores are -8.1% YoY "
            "with 43.6% repeat share."
        ),
        confidence="high",
        whyItMatters=(
            "The spread between top and bottom stores is widening. New/repeat mix and local execution patterns are "
            "likely key levers for lift at underperforming locations."
        ),
        metrics=[
            {"label": "Top Store Spend", "value": 0.04, "delta": 0.01, "unit": "usd"},
            {"label": "Bottom Store Spend", "value": 0.01, "delta": -0.00, "unit": "usd"},
            {"label": "Repeat Share Gap", "value": 19.1, "delta": 6.7, "unit": "pct"},
        ],
        evidence=evidence,
        insights=[
            {
                "id": "i1",
                "title": "Repeat mix strongly predicts winners",
                "detail": "Top stores are materially more repeat-heavy than bottom stores in both years.",
                "importance": "high",
            },
            {
                "id": "i2",
                "title": "Bottom cohort is losing momentum",
                "detail": "Bottom stores show negative YoY spend with rising new-customer dependency.",
                "importance": "high",
            },
            {
                "id": "i3",
                "title": "Portfolio average masks dispersion",
                "detail": "Aggregate performance looks healthy, but tail underperformance is expanding.",
                "importance": "medium",
            },
        ],
        suggestedQuestions=[
            "For bottom stores, break out CP vs CNP and day-of-week patterns.",
            "Which bottom stores have the largest repeat-share deterioration YoY?",
            "Compare household coverage for top and bottom stores.",
        ],
        assumptions=[
            "Store performance uses TD_ID-level aggregation for calendar year 2025.",
            "Repeat/new mix is derived from repeat_spend and new_spend ratios.",
        ],
        trace=[
            {
                "id": "t1",
                "title": "Resolve intent and ranking scope",
                "summary": "Identified top/bottom store ranking request and year-over-year comparison requirement.",
                "status": "done",
                "qualityChecks": ["Ranking scope validated", "Store granularity set to TD_ID + city/state"],
            },
            {
                "id": "t2",
                "title": "Generate governed SQL",
                "summary": "Queried allowlisted sales and household tables for store ranking and mix analysis.",
                "status": "done",
                "sql": results[0].sql if results else None,
                "qualityChecks": ["Allowlist guard passed", "Store context enrichment applied"],
            },
            {
                "id": "t3",
                "title": "Validate and rank insights",
                "summary": "Validated cohort comparisons and ranked actionable findings for intervention planning.",
                "status": "done",
                "qualityChecks": ["Top/bottom cohorts reconciled", "YoY comparison checks passed"],
            },
        ],
        dataTables=[
            _table_from_evidence(
                "store_driver_breakdown",
                "Top vs Bottom Store Driver Breakdown",
                evidence,
                "SELECT TD_ID, SUM(SPEND), SUM(REPEAT_SPEND), SUM(NEW_SPEND) FROM cia_sales_insights_cortex GROUP BY TD_ID;",
            ),
            _table_from_rows(
                id_="store_rankings_2025",
                name="Top and Bottom Stores (2025)",
                rows=store_rows,
                source_sql=(
                    "SELECT TD_ID, TRANSACTION_CITY, TRANSACTION_STATE, SUM(SPEND) AS spend_2025_usd_m "
                    "FROM cia_sales_insights_cortex WHERE RESP_DATE BETWEEN '2025-01-01' AND '2025-12-31' "
                    "GROUP BY TD_ID, TRANSACTION_CITY, TRANSACTION_STATE;"
                ),
                description="TD_ID-level ranking with city/state context and YoY comparisons.",
            ),
            _table_from_rows(
                id_="store_mix_summary",
                name="Store Mix vs Portfolio Average",
                rows=mix_rows,
                source_sql=(
                    "SELECT TD_ID, SUM(REPEAT_SPEND), SUM(NEW_SPEND) FROM cia_sales_insights_cortex GROUP BY TD_ID;"
                ),
                description="New vs repeat mix for top/bottom cohorts against portfolio average.",
            ),
            *_tables_from_sql_results(results),
        ],
    )


def _build_overview_response(results: list[SqlExecutionResult]) -> AgentResponse:
    evidence = [
        EvidenceRow(segment="CNP channel share", prior=38.9, current=39.8, changeBps=90, contribution=0.24),
        EvidenceRow(segment="Repeat spend share", prior=53.7, current=54.8, changeBps=110, contribution=0.19),
        EvidenceRow(segment="Top 5 states share", prior=62.3, current=63.0, changeBps=70, contribution=0.15),
    ]
    return AgentResponse(
        answer=(
            "Latest-period sales and transactions are trending up, with growth concentrated in the largest states and "
            "a gradual shift toward CNP and repeat-customer contribution."
        ),
        confidence="medium",
        whyItMatters=(
            "The direction is positive, but state/channel concentration should be monitored to balance growth and risk."
        ),
        metrics=[
            {"label": "Total Spend", "value": 2.83, "delta": 0.27, "unit": "usd"},
            {"label": "Total Transactions", "value": 74200000, "delta": 5300000, "unit": "count"},
            {"label": "Repeat Spend Share", "value": 54.8, "delta": 1.1, "unit": "pct"},
        ],
        evidence=evidence,
        insights=[
            {
                "id": "i1",
                "title": "Growth remains concentrated",
                "detail": "A handful of states explain the majority of the aggregate uplift.",
                "importance": "high",
            },
            {
                "id": "i2",
                "title": "Channel mix keeps shifting",
                "detail": "CNP penetration is climbing steadily and should inform operations planning.",
                "importance": "medium",
            },
        ],
        suggestedQuestions=[
            "Show monthly trend by state for the last 12 months.",
            "Break down growth by CP vs CNP by state.",
            "How does repeat/new mix vary by store cohort?",
        ],
        assumptions=[
            "Response summarizes latest available calendar window in the mock dataset.",
            "All results use semantic-model allowlisted tables only.",
        ],
        trace=[
            {
                "id": "t1",
                "title": "Resolve intent and scope",
                "summary": "Mapped broad query to high-level trend and mix diagnostics.",
                "status": "done",
            },
            {
                "id": "t2",
                "title": "Generate governed SQL",
                "summary": "Executed aggregate trend and channel mix SQL over allowlisted tables.",
                "status": "done",
                "sql": results[0].sql if results else None,
            },
            {
                "id": "t3",
                "title": "Validate and rank insights",
                "summary": "Checked consistency and ranked the strongest directional signals.",
                "status": "done",
            },
        ],
        dataTables=[*_tables_from_sql_results(results)],
    )


async def mock_build_response(request: ChatTurnRequest, results: list[SqlExecutionResult]) -> AgentResponse:
    profile = _query_profile(request.message)
    if profile == "state_sales":
        return _build_state_sales_response(results)
    if profile == "q4_yoy":
        return _build_q4_yoy_response(results)
    if profile == "store_performance":
        return _build_store_response(results)
    return _build_overview_response(results)
