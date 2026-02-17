from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _as_float(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    node_env: str = os.getenv("NODE_ENV", "development")
    port: int = int(os.getenv("PORT", "8787"))
    use_mock_providers: bool = _as_bool(os.getenv("USE_MOCK_PROVIDERS"), True)

    azure_openai_endpoint: Optional[str] = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: Optional[str] = os.getenv("AZURE_OPENAI_API_KEY")
    azure_openai_deployment: Optional[str] = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    azure_openai_auth_mode: str = os.getenv("AZURE_OPENAI_AUTH_MODE", "api_key").strip().lower()
    azure_tenant_id: Optional[str] = os.getenv("AZURE_TENANT_ID")
    azure_spn_client_id: Optional[str] = os.getenv("AZURE_SPN_CLIENT_ID")
    azure_spn_cert_path: Optional[str] = os.getenv("AZURE_SPN_CERT_PATH")
    azure_spn_cert_password: Optional[str] = os.getenv("AZURE_SPN_CERT_PASSWORD")
    azure_openai_scope: str = os.getenv("AZURE_OPENAI_SCOPE", "https://cognitiveservices.azure.com/.default")
    azure_openai_gateway_api_key: Optional[str] = os.getenv("AZURE_OPENAI_GATEWAY_API_KEY")
    azure_openai_gateway_api_key_header: str = os.getenv("AZURE_OPENAI_GATEWAY_API_KEY_HEADER", "Api-Key")

    snowflake_cortex_base_url: Optional[str] = os.getenv("SNOWFLAKE_CORTEX_BASE_URL")
    snowflake_cortex_api_key: Optional[str] = os.getenv("SNOWFLAKE_CORTEX_API_KEY")
    snowflake_cortex_warehouse: Optional[str] = os.getenv("SNOWFLAKE_CORTEX_WAREHOUSE")
    snowflake_cortex_database: Optional[str] = os.getenv("SNOWFLAKE_CORTEX_DATABASE")
    snowflake_cortex_schema: Optional[str] = os.getenv("SNOWFLAKE_CORTEX_SCHEMA")
    semantic_model_path: Optional[str] = os.getenv("SEMANTIC_MODEL_PATH")
    real_fast_plan_steps: int = _as_int(os.getenv("REAL_FAST_PLAN_STEPS"), 2)
    real_deep_plan_steps: int = _as_int(os.getenv("REAL_DEEP_PLAN_STEPS"), 4)
    real_enable_parallel_sql: bool = _as_bool(os.getenv("REAL_ENABLE_PARALLEL_SQL"), False)
    real_max_parallel_queries: int = _as_int(os.getenv("REAL_MAX_PARALLEL_QUERIES"), 3)
    real_llm_temperature: float = _as_float(os.getenv("REAL_LLM_TEMPERATURE"), 0.1)
    real_llm_max_tokens: int = _as_int(os.getenv("REAL_LLM_MAX_TOKENS"), 1400)
    mock_stream_status_delay_ms: int = _as_int(os.getenv("MOCK_STREAM_STATUS_DELAY_MS"), 700)
    mock_stream_token_delay_ms: int = _as_int(os.getenv("MOCK_STREAM_TOKEN_DELAY_MS"), 120)
    mock_stream_response_delay_ms: int = _as_int(os.getenv("MOCK_STREAM_RESPONSE_DELAY_MS"), 450)

    def has_azure_credentials(self) -> bool:
        if not self.azure_openai_endpoint or not self.azure_openai_deployment:
            return False
        if self.azure_openai_auth_mode == "certificate":
            return bool(self.azure_tenant_id and self.azure_spn_client_id and self.azure_spn_cert_path)
        return bool(self.azure_openai_api_key)

    def has_snowflake_credentials(self) -> bool:
        return bool(self.snowflake_cortex_base_url and self.snowflake_cortex_api_key)


settings = Settings()
