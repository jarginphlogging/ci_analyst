from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.sandbox.sqlite_store import ensure_sandbox_database, execute_readonly_query, rewrite_sql_for_sqlite


class QueryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    sql: str
    warehouse: Optional[str] = None
    database: Optional[str] = None
    schema_name: Optional[str] = Field(default=None, alias="schema")

@asynccontextmanager
async def _lifespan(_: FastAPI):
    ensure_sandbox_database(settings.sandbox_sqlite_path, reset=settings.sandbox_seed_reset)
    yield


app = FastAPI(title="CI Analyst Sandbox Cortex Service", version="0.1.0", lifespan=_lifespan)


def _check_auth(authorization: Optional[str]) -> None:
    expected = f"Bearer {settings.sandbox_cortex_api_key}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "database": settings.sandbox_sqlite_path,
    }


@app.post("/api/v2/cortex/analyst/query")
@app.post("/query")
async def query(payload: QueryRequest, authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_auth(authorization)
    try:
        rows = execute_readonly_query(settings.sandbox_sqlite_path, payload.sql)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Sandbox SQL execution failed: {error}") from error

    return {
        "rows": rows,
        "rowCount": len(rows),
        "rewrittenSql": rewrite_sql_for_sqlite(payload.sql),
    }


if __name__ == "__main__":
    uvicorn.run("app.sandbox.cortex_service:app", host="0.0.0.0", port=8788, reload=False)
