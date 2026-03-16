from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency availability is environment-specific
    load_dotenv = None


_ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1]
_ORCHESTRATOR_ENV_FILE = _ORCHESTRATOR_DIR / ".env"
if load_dotenv and _ORCHESTRATOR_ENV_FILE.exists():
    load_dotenv(_ORCHESTRATOR_ENV_FILE, override=False)


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


def _as_nonempty(value: Optional[str], default: str) -> str:
    if value is None:
        return default
    trimmed = value.strip()
    return trimmed if trimmed else default


def _as_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed if trimmed else None


@dataclass(frozen=True)
class Settings:
    node_env: str = os.getenv("NODE_ENV", "development")
    port: int = int(os.getenv("PORT", "8787"))
    log_level: str = _as_nonempty(os.getenv("LOG_LEVEL"), "INFO").upper()
    provider_mode_raw: Optional[str] = os.getenv("PROVIDER_MODE")
    llm_provider_raw: Optional[str] = os.getenv("LLM_PROVIDER")

    azure_openai_endpoint: Optional[str] = _as_optional(os.getenv("AZURE_OPENAI_ENDPOINT"))
    azure_openai_api_key: Optional[str] = _as_optional(os.getenv("AZURE_OPENAI_API_KEY"))
    azure_openai_deployment: Optional[str] = _as_optional(
        os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_MODEL")
    )
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    azure_openai_auth_mode: str = os.getenv("AZURE_OPENAI_AUTH_MODE", "api_key").strip().lower()
    azure_tenant_id: Optional[str] = os.getenv("AZURE_TENANT_ID")
    azure_spn_client_id: Optional[str] = os.getenv("AZURE_SPN_CLIENT_ID")
    azure_spn_cert_path: Optional[str] = os.getenv("AZURE_SPN_CERT_PATH")
    azure_spn_cert_password: Optional[str] = os.getenv("AZURE_SPN_CERT_PASSWORD")
    azure_openai_scope: str = os.getenv("AZURE_OPENAI_SCOPE", "https://cognitiveservices.azure.com/.default")
    azure_openai_gateway_api_key: Optional[str] = _as_optional(
        os.getenv("AZURE_OPENAI_GATEWAY_API_KEY") or os.getenv("AZURE_API_KEY")
    )
    azure_openai_gateway_api_key_header: str = os.getenv("AZURE_OPENAI_GATEWAY_API_KEY_HEADER", "Api-Key")

    anthropic_base_url: str = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    anthropic_api_key: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    anthropic_api_version: str = os.getenv("ANTHROPIC_API_VERSION", "2023-06-01")
    anthropic_bedrock_aws_account_number: Optional[str] = _as_optional(
        os.getenv("ANTHROPIC_BEDROCK_AWS_ACCOUNT_NUMBER")
    )
    anthropic_bedrock_aws_region: Optional[str] = _as_optional(os.getenv("ANTHROPIC_BEDROCK_AWS_REGION"))
    anthropic_bedrock_workspace_id: Optional[str] = _as_optional(os.getenv("ANTHROPIC_BEDROCK_WORKSPACE_ID"))
    anthropic_bedrock_is_execution_role: bool = _as_bool(os.getenv("ANTHROPIC_BEDROCK_IS_EXECUTION_ROLE"), False)
    anthropic_bedrock_model_id: Optional[str] = _as_optional(os.getenv("ANTHROPIC_BEDROCK_MODEL_ID"))
    anthropic_bedrock_model_name: str = _as_nonempty(
        os.getenv("ANTHROPIC_BEDROCK_MODEL_NAME"),
        "anthropic.claude-opus-4-1-20250805-v1:0",
    )
    anthropic_bedrock_anthropic_version: str = _as_nonempty(
        os.getenv("ANTHROPIC_BEDROCK_ANTHROPIC_VERSION"),
        "bedrock-2023-05-31",
    )

    snowflake_cortex_base_url: Optional[str] = os.getenv("SNOWFLAKE_CORTEX_BASE_URL")
    snowflake_cortex_api_key: Optional[str] = os.getenv("SNOWFLAKE_CORTEX_API_KEY")
    snowflake_cortex_auth_token_type: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_CORTEX_AUTH_TOKEN_TYPE"))
    snowflake_cortex_semantic_model_file: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_CORTEX_SEMANTIC_MODEL_FILE"))
    snowflake_cortex_semantic_model: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_CORTEX_SEMANTIC_MODEL"))
    snowflake_cortex_semantic_view: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_CORTEX_SEMANTIC_VIEW"))
    snowflake_cortex_semantic_models_json: Optional[str] = _as_optional(
        os.getenv("SNOWFLAKE_CORTEX_SEMANTIC_MODELS_JSON")
    )

    snowflake_account: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_ACCOUNT"))
    snowflake_user: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_USER"))
    snowflake_password: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_PASSWORD"))
    snowflake_private_key_file: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE"))
    snowflake_private_key_file_pwd: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE_PWD"))
    snowflake_role: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_ROLE"))
    snowflake_authenticator: Optional[str] = _as_optional(os.getenv("SNOWFLAKE_AUTHENTICATOR"))
    snowflake_warehouse: Optional[str] = _as_optional(
        os.getenv("SNOWFLAKE_WAREHOUSE") or os.getenv("SNOWFLAKE_CORTEX_WAREHOUSE")
    )
    snowflake_database: Optional[str] = _as_optional(
        os.getenv("SNOWFLAKE_DATABASE") or os.getenv("SNOWFLAKE_CORTEX_DATABASE")
    )
    snowflake_schema: Optional[str] = _as_optional(
        os.getenv("SNOWFLAKE_SCHEMA") or os.getenv("SNOWFLAKE_CORTEX_SCHEMA")
    )
    sandbox_cortex_base_url: str = _as_nonempty(
        os.getenv("SANDBOX_CORTEX_BASE_URL"),
        "http://127.0.0.1:8788/api/v2/cortex/analyst",
    )
    sandbox_cortex_api_key: Optional[str] = _as_optional(os.getenv("SANDBOX_CORTEX_API_KEY"))
    sandbox_sql_timeout_seconds: float = max(1.0, _as_float(os.getenv("SANDBOX_SQL_TIMEOUT_SECONDS"), 120.0))
    sql_step_sla_seconds: float = max(1.0, _as_float(os.getenv("SQL_STEP_SLA_SECONDS"), 120.0))
    sandbox_sqlite_path: str = _as_nonempty(
        os.getenv("SANDBOX_SQLITE_PATH"),
        str(Path(__file__).resolve().parents[1] / ".sandbox" / "ci_analyst_sandbox.db"),
    )
    sandbox_seed_reset: bool = _as_bool(os.getenv("SANDBOX_SEED_RESET"), False)
    semantic_model_path: Optional[str] = os.getenv("SEMANTIC_MODEL_PATH")
    semantic_policy_path: Optional[str] = os.getenv("SEMANTIC_POLICY_PATH")
    real_fast_plan_steps: int = _as_int(os.getenv("REAL_FAST_PLAN_STEPS"), 2)
    real_deep_plan_steps: int = _as_int(os.getenv("REAL_DEEP_PLAN_STEPS"), 4)
    plan_max_steps: int = max(1, _as_int(os.getenv("PLAN_MAX_STEPS"), 5))
    real_max_parallel_queries: int = _as_int(os.getenv("REAL_MAX_PARALLEL_QUERIES"), 3)
    sql_max_attempts: int = max(1, _as_int(os.getenv("SQL_MAX_ATTEMPTS"), 3))
    real_llm_temperature: float = _as_float(os.getenv("REAL_LLM_TEMPERATURE"), 0.1)
    real_llm_max_tokens: int = _as_int(os.getenv("REAL_LLM_MAX_TOKENS"), 1400)

    @property
    def provider_mode(self) -> str:
        raw = (self.provider_mode_raw or "").strip().lower().replace("_", "-")
        if raw in {"sandbox", "prod", "prod-sandbox"}:
            return raw
        if raw == "production":
            return "prod"
        if raw in {"production-sandbox", "sandbox-prod"}:
            return "prod-sandbox"
        return "sandbox"

    @property
    def llm_provider(self) -> str:
        raw = (self.llm_provider_raw or "").strip().lower().replace("-", "_")
        if not raw:
            if self.provider_mode == "sandbox":
                return "anthropic_direct"
            raise RuntimeError(
                "LLM_PROVIDER must be set for prod and prod-sandbox. "
                "Use one of: azure_openai, anthropic_bedrock."
            )
        if raw in {"azure_openai", "anthropic_bedrock", "anthropic_direct"}:
            return raw
        raise RuntimeError(
            f"Unsupported LLM_PROVIDER '{self.llm_provider_raw}'. "
            "Use one of: azure_openai, anthropic_bedrock, anthropic_direct."
        )

    def has_azure_credentials(self) -> bool:
        if not self.azure_openai_endpoint or not self.azure_openai_deployment:
            return False
        if self.azure_openai_auth_mode == "certificate":
            return bool(self.azure_tenant_id and self.azure_spn_client_id and self.azure_spn_cert_path)
        return bool(self.azure_openai_api_key)

    def has_anthropic_credentials(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_model)

    def has_anthropic_bedrock_credentials(self) -> bool:
        return bool(
            self.anthropic_bedrock_aws_account_number
            and self.anthropic_bedrock_aws_region
            and self.anthropic_bedrock_workspace_id
            and self.anthropic_bedrock_model_id
        )

    def has_snowflake_credentials(self) -> bool:
        return bool(self.snowflake_cortex_base_url and self.snowflake_cortex_api_key)

    def has_snowflake_analyst_credentials(self) -> bool:
        has_model_ref = bool(
            self.snowflake_cortex_semantic_model_file
            or self.snowflake_cortex_semantic_model
            or self.snowflake_cortex_semantic_view
            or self.snowflake_cortex_semantic_models_json
        )
        return bool(self.snowflake_cortex_base_url and self.snowflake_cortex_api_key and has_model_ref)

    def has_snowflake_connector_credentials(self) -> bool:
        has_auth = bool(self.snowflake_password or self.snowflake_private_key_file)
        return bool(self.snowflake_account and self.snowflake_user and has_auth)


settings = Settings()
