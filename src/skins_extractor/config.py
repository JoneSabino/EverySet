from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

_ROOT = Path(__file__).parent.parent.parent


class LLMConfig(BaseModel):
    provider: str
    model: str
    enable_caching: bool = False
    max_tokens: int = 4096


class ProfileConfig(BaseModel):
    description: str = ""
    outliner: LLMConfig
    row_fallback: LLMConfig
    vision_fallback: LLMConfig


class PipelineConfig(BaseModel):
    trust_mode: str = "human_approval"
    pattern_store_path: str = "data/patterns.duckdb"
    llm_outline_threshold: float = 0.6
    fuzzy_threshold: float = 0.70
    fuzzy_high_threshold: float = 0.95
    ocr_min_chars: int = 50
    enable_color_detection: bool = True
    log_level: str = "INFO"


class NotificationsConfig(BaseModel):
    slack_webhook_url: str = ""


class OutputConfig(BaseModel):
    clean_csv: str = "output/clean.csv"
    debug_csv: str = "output/debug.csv"
    log_file: str = "output/extraction.log"


class AppConfig(BaseModel):
    profile_name: str
    profile: ProfileConfig
    pipeline: PipelineConfig
    notifications: NotificationsConfig
    output: OutputConfig


def load_config(profile_name: str | None = None) -> AppConfig:
    profiles_path = _ROOT / "config" / "profiles.yaml"
    with open(profiles_path) as f:
        data: dict[str, Any] = yaml.safe_load(f)

    selected = profile_name or os.getenv("SKINS_PROFILE", "default")
    profiles = data.get("profiles", {})
    if selected not in profiles:
        raise ValueError(f"Unknown profile: {selected!r}. Available: {list(profiles)}")

    profile_data = profiles[selected]
    pipeline_data = data.get("pipeline", {})
    notif_data = data.get("notifications", {})
    output_data = data.get("output", {})

    # Resolve env vars in slack webhook
    slack_url = notif_data.get("slack_webhook_url", "") or os.getenv("SLACK_WEBHOOK_URL", "")
    log_level = os.getenv("SKINS_LOG_LEVEL", pipeline_data.get("log_level", "INFO"))

    pipeline_data["log_level"] = log_level

    return AppConfig(
        profile_name=selected,
        profile=ProfileConfig(**profile_data),
        pipeline=PipelineConfig(**pipeline_data),
        notifications=NotificationsConfig(slack_webhook_url=slack_url),
        output=OutputConfig(**output_data),
    )
