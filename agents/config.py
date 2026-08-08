"""config.py — settings for the Assay research agents.

MODEL IS A HARD RULE: deepinfra/google/gemma-4-31B-it. One model. No alternatives,
no profiles to switch, no fallback. Verified live on DeepInfra 2026-08-08 — exact
match, tool calling confirmed, warm latency 2.3-3.1s.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

MODEL = "deepinfra/google/gemma-4-31B-it"
API_KEY_ENV = "DEEPINFRA_API_KEY"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"), extra="ignore", case_sensitive=False
    )

    deepinfra_api_key: str = ""

    # --- agent loop ---
    agent_max_turns: int = 12
    agent_subagent_max_turns: int = 20
    tool_output_max_chars: int = 12000
    panel_budget_seconds: int = 120   # hard wall-clock cap per agent; nothing else bounds a stall

    # --- browser (skill defaults 2.0/5.0/30000 are too slow for a 3-min demo) ---
    min_navigation_delay: float = 0.0
    max_navigation_delay: float = 1.0
    page_load_timeout: int = 60000  # ms
    # skill uses "networkidle"; news sites never reach it, so they burn the whole budget
    page_wait_until: str = "domcontentloaded"

    litellm_timeout: int = 600
    firecrawl_api_key: str = ""

    # "crawl4ai"  -> local Playwright + crawl4ai. Free, supports wait_for_human.
    # "firecrawl" -> Firecrawl REST. No browser, ~5x faster, better under bad venue wifi.
    web_backend: str = "crawl4ai"

    # --- chain ---
    monad_rpc: str = "https://testnet-rpc.monad.xyz"
    monad_chain_id: int = 10143
    x402_facilitator: str = "https://x402-facilitator.molandak.org"
    usdc_address: str = "0x534b2f3A21130d7a60830c2Df862319e593943A3"
    sec_identity: str = ""

    # --- keys ---
    coord_pk: str = ""
    agent_a_pk: str = ""
    agent_b_pk: str = ""
    agent_c_pk: str = ""


settings = Settings()
