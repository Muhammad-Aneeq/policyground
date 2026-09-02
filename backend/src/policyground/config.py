"""Runtime settings and the repository paths everything else resolves against.

``APP_MODE`` is the switch the whole two-mode architecture turns on (PLAN.md §7). Nothing outside
``retrieval.factory`` and ``ingest`` reads it: compose, citation enforcement, refusal, evals and
the UI are identical in both modes, and keeping the mode check in one place is what makes that
claim checkable rather than aspirational.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(StrEnum):
    LOCAL = "local"
    AZURE = "azure"


def repo_root() -> Path:
    """The repository root, found by walking up from this file.

    ``backend/src/policyground/config.py`` → four parents up. Resolved from ``__file__`` rather
    than the working directory so ``pytest`` from any subdirectory, the CLI, and the API server
    all agree on where ``corpus/`` is.
    """
    return Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Environment-driven configuration. See ``.env.example`` for the documented surface."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_mode: AppMode = AppMode.LOCAL

    # ------------------------------------------------------------- models --
    # Absent in this build (BLOCKERS.md B1). Their absence selects the deterministic fallbacks
    # rather than raising, so the whole product runs offline.
    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-5-mini"

    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    azure_openai_chat_deployment: str = "gpt-5-mini"

    azure_search_endpoint: str | None = None
    azure_search_api_key: str | None = None
    azure_search_index: str = "policyground-chunks"

    # --------------------------------------------------------------- data --
    database_url: str = "sqlite:///data/policyground.db"

    # ---------------------------------------------------------- retrieval --
    retrieval_top_k: int = Field(default=6, ge=1, le=50)
    #: Below this fused-evidence score the graph refuses (spec 08 §4 F4). Calibrated on the
    #: question bank's *calibration* split only (PLAN.md D-019); see docs/evals_methodology.md.
    sufficiency_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    #: RRF constant. 60 is the published default and the value Azure AI Search uses for hybrid
    #: fusion, which is what keeps LOCAL and AZURE behaviourally comparable (PLAN.md D-005).
    rrf_k: int = Field(default=60, ge=1)
    embedding_dim: int = Field(default=384, ge=32)

    #: Cache-only judging and no network calls. CI sets this; a judge cache miss becomes fatal.
    offline: bool = False

    # --------------------------------------------------------------- paths --
    @property
    def corpus_dir(self) -> Path:
        return repo_root() / "corpus"

    @property
    def policies_dir(self) -> Path:
        return self.corpus_dir / "policies"

    @property
    def constants_path(self) -> Path:
        return self.corpus_dir / "constants.yaml"

    @property
    def canaries_path(self) -> Path:
        return self.corpus_dir / "canaries.yaml"

    @property
    def manifest_path(self) -> Path:
        return self.corpus_dir / "MANIFEST.json"

    @property
    def data_dir(self) -> Path:
        return repo_root() / "data"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "index.json"

    @property
    def vectors_path(self) -> Path:
        return self.data_dir / "vectors.npy"

    @property
    def judge_cache_dir(self) -> Path:
        return repo_root() / "evals" / "judge_cache"

    # -------------------------------------------------------- capabilities --
    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_azure_openai(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def has_azure_search(self) -> bool:
        return bool(self.azure_search_endpoint and self.azure_search_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings.

    ``OFFLINE=1`` is honoured as an alias for ``offline`` because CI, the Makefile and the
    PowerShell shim all speak that spelling.
    """
    settings = Settings()
    if os.environ.get("OFFLINE") in {"1", "true", "TRUE"}:
        settings = settings.model_copy(update={"offline": True})
    return settings


def reset_settings_cache() -> None:
    """Drop the cached settings — used by tests that manipulate the environment."""
    get_settings.cache_clear()
