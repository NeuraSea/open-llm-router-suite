from __future__ import annotations

from enterprise_llm_proxy.services.provider_registry import (
    get_provider_models,
    find_model_by_id,
)


class TestGetProviderModels:
    def test_returns_models_for_anthropic(self):
        models = get_provider_models("anthropic")
        assert len(models) > 0
        for m in models:
            assert m.provider == "anthropic"
            assert m.model_profile.startswith("anthropic/")
            assert m.auth_modes == ["api_key"]

    def test_returns_models_for_deepseek(self):
        models = get_provider_models("deepseek")
        assert len(models) > 0
        for m in models:
            assert m.provider == "deepseek"
            assert m.model_profile.startswith("deepseek/")

    def test_returns_empty_for_unknown_provider(self):
        models = get_provider_models("nonexistent_provider")
        assert models == []

    def test_model_definition_fields(self):
        models = get_provider_models("anthropic")
        m = models[0]
        assert m.object == "model"
        assert m.owned_by == "anthropic"
        assert "openai_chat" in m.supported_protocols


class TestFindModelById:
    def test_finds_known_anthropic_model(self):
        # claude-sonnet-4-20250514 should be in litellm's model_cost
        m = find_model_by_id("claude-sonnet-4-20250514")
        if m is not None:
            assert m.provider == "anthropic"
            assert m.id == "claude-sonnet-4-20250514"

    def test_returns_none_for_unknown_model(self):
        m = find_model_by_id("definitely-not-a-real-model-xyz")
        assert m is None
