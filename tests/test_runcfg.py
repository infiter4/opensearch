"""BYOK per-run overrides: resolved through ContextVars so concurrent runs can't cross."""
import asyncio

from backend import config
from backend.providers import runcfg


def test_default_is_the_measured_model():
    runcfg.set_run_overrides(None, None)
    assert runcfg.model_for("verifier") == config.MODELS["verifier"]


def test_override_wins_and_blank_is_ignored():
    runcfg.set_run_overrides({"verifier": "groq/openai/gpt-oss-120b", "rewriter": ""}, None)
    assert runcfg.model_for("verifier") == "groq/openai/gpt-oss-120b"
    assert runcfg.model_for("rewriter") == config.MODELS["rewriter"]
    runcfg.set_run_overrides(None, None)


def test_effective_models_covers_every_stage_and_no_keys():
    runcfg.set_run_overrides({"lead": "groq/llama-3.3-70b-versatile"}, {"groq": "gsk_secret"})
    eff = runcfg.effective_models()
    assert set(eff) == set(config.MODELS)
    assert eff["lead"] == "groq/llama-3.3-70b-versatile"
    assert "gsk_secret" not in str(eff), "keys must never ride along with model info"
    runcfg.set_run_overrides(None, None)


def test_concurrent_runs_do_not_cross():
    # Two pipelines in one event loop: each task's overrides must stay its own.
    async def go():
        seen = {}

        async def run_a():
            runcfg.set_run_overrides({"verifier": "model-A"}, {"groq": "key-A"})
            await asyncio.sleep(0.02)
            seen["a"] = (runcfg.model_for("verifier"), runcfg.key_for("groq"))

        async def run_b():
            await asyncio.sleep(0.01)  # starts after A has set its overrides
            runcfg.set_run_overrides({"verifier": "model-B"}, {"groq": "key-B"})
            await asyncio.sleep(0.02)
            seen["b"] = (runcfg.model_for("verifier"), runcfg.key_for("groq"))

        await asyncio.gather(run_a(), run_b())
        return seen

    seen = asyncio.run(go())
    assert seen["a"] == ("model-A", "key-A")
    assert seen["b"] == ("model-B", "key-B")
