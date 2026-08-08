"""agent.py — agent factory + runner, per skills/agent-spec.md §3.

Structured output comes from the submit_result terminal tool + StopAtTools, NOT output_type=
(spec §6.2: response_format + function tools breaks on several providers).
"""
import json
import logging
import time

import litellm
from agents import Agent, ModelSettings, Runner, StopAtTools, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel

from config import MODEL, settings
from prompts import PANEL
from tools import (
    delegate_to_subagent,
    firecrawl_scrape,
    firecrawl_search,
    search_google,
    set_parent_spec,
    submit_result,
    visit_webpage,
    wait_for_human,
)

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True
litellm.request_timeout = settings.litellm_timeout


def _web_tools() -> list:
    """WEB_BACKEND swaps the research tools. Everything else about the agent is identical."""
    if settings.web_backend == "firecrawl":
        return [firecrawl_search, firecrawl_scrape]      # no browser; better on bad wifi
    return [search_google, visit_webpage, wait_for_human]


def create_agent(name: str, instructions: str) -> Agent:
    """Build one agent. Model is pinned in config — never parameterised."""
    set_tracing_disabled(disabled=True)          # otherwise the SDK spams OpenAI tracing
    return Agent(
        name=name,
        instructions=instructions,
        model=LitellmModel(model=MODEL, api_key=settings.deepinfra_api_key),
        model_settings=ModelSettings(),          # bare — spec §3.2, reasoning_effort is not portable
        tools=_web_tools() + [delegate_to_subagent, submit_result],
        tool_use_behavior=StopAtTools(stop_at_tool_names=["submit_result"]),
    )


def warmup() -> float:
    """Fire one throwaway completion so the endpoint is warm.

    Measured 2026-08-08: a COLD call took 46s, every warm call after was 2.3-3.1s.
    Skipping this turns the 60-second demo beat into a dead projector.
    """
    t = time.time()
    try:
        litellm.completion(
            model=MODEL,
            api_key=settings.deepinfra_api_key,
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=1,
        )
    except Exception as e:
        logger.warning("warmup failed (continuing): %s", e)
    dt = time.time() - t
    logger.info("warmup %.1fs", dt)
    return dt


def _fallback(reason: str) -> dict:
    """Spec §6.3 — never let a parse error bubble up mid-demo."""
    return {
        "verdict": False,
        "confidence": 0.0,
        "reasoning": f"agent did not return a parsable result: {reason}",
        "citations": [],
        "ok": False,
    }


async def run_panel_agent(key: str, claim: str, seed_urls: list[str]) -> dict:
    """Run one panel member end to end and return its structured verdict."""
    spec = PANEL[key]
    set_parent_spec(spec["name"], spec["instructions"])   # subagents reuse this prompt (§5.2)
    agent = create_agent(spec["name"], spec["instructions"])

    seeds = "\n".join(f"  - {u}" for u in seed_urls)
    task = (
        f"CLAIM TO JUDGE:\n{claim}\n\n"
        f"Start with these primary sources (visit them first, do not search unless they fail):\n{seeds}\n\n"
        f"Read the evidence, then call submit_result exactly once."
    )

    t = time.time()
    try:
        result = await Runner.run(
            starting_agent=agent, input=task, max_turns=settings.agent_max_turns
        )
        raw = str(result.final_output)
    except Exception as e:
        logger.exception("%s crashed", key)
        return {**_fallback(f"{type(e).__name__}: {e}"), "agent": key, "elapsed": time.time() - t}

    try:
        data = json.loads(raw)
        data["ok"] = True
    except Exception as e:
        logger.error("%s returned unparsable output: %s", key, raw[:300])
        data = _fallback(str(e))

    data["agent"] = key
    data["name"] = spec["name"]
    data["elapsed"] = round(time.time() - t, 1)
    return data
