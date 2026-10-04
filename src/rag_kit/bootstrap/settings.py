"""Validated environment-backed configuration."""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaSettings(BaseModel):
    host: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b-instruct-q4_K_M"
    embed_model: str = "bge-m3"
    keep_alive: str = "10m"
    num_ctx: int = Field(default=4096, gt=0)
    timeout_s: float = Field(default=120.0, gt=0)


class BackendSettings(BaseModel):
    name: str
    url: str


class BalancerSettings(BaseModel):
    strategy: Literal["round_robin", "least_busy", "latency"] = "round_robin"
    backends: list[BackendSettings] = []
    cooldown_s: float = Field(default=15.0, ge=0)
    max_failovers: int = Field(default=1, ge=0)


class LLMSettings(BaseModel):
    provider: Literal["ollama", "openai_compat"] = "ollama"
    base_url: str = "http://localhost:1234/v1"
    max_concurrent: int = Field(default=1, gt=0)
    retries: int = Field(default=3, ge=0)
    breaker_failures: int = Field(default=5, gt=0)
    breaker_reset_s: float = Field(default=30.0, gt=0)
    cache_enabled: bool = False
    balancer: BalancerSettings | None = None


class EmbeddingSettings(BaseModel):
    provider: Literal["ollama", "sentence_transformers"] = "ollama"
    batch_size: int = Field(default=32, gt=0)
    model: str = "BAAI/bge-m3"
    device: str = "cpu"
    cache_enabled: bool = True
    cache_capacity: int = Field(default=10000, gt=0)


class RerankSettings(BaseModel):
    provider: Literal["none", "cross_encoder"] = "none"
    model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    device: Literal["cpu", "cuda"] = "cpu"
    batch_size: int = Field(default=16, gt=0)
    fp16: bool = True


class DatabaseSettings(BaseModel):
    url: str = "postgresql+psycopg://ragkit:ragkit@localhost:5433/ragkit"
    pool_size: int = Field(default=5, gt=0)
    hnsw_ef_search: int = Field(default=64, gt=0)


class RetrievalSettings(BaseModel):
    mode: Literal["dense", "lexical", "hybrid"] = "hybrid"
    dense_k: int = Field(default=20, gt=0)
    lexical_k: int = Field(default=20, gt=0)
    fused_k: int = Field(default=8, gt=0)
    rrf_k: int = Field(default=60, gt=0)


class WorkflowSettings(BaseModel):
    max_corrections: int = Field(default=1, ge=0)
    pipeline_version: str = "1"
    max_context_tokens: int = Field(default=4096, gt=512)
    prompt_output_reserve_tokens: int = Field(default=1200, gt=0)


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    trace_dir: str = "evaluation/traces"
    redact: bool = True


class PackSettings(BaseModel):
    name: str = "scrap"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAGKIT_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    rerank: RerankSettings = Field(default_factory=RerankSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    pack: PackSettings = Field(default_factory=PackSettings)
