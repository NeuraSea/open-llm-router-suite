from __future__ import annotations

import litellm

from enterprise_llm_proxy.services.model_catalog import ModelDefinition

# Our provider name → litellm prefix (for prefix-based lookup)
PROVIDER_PREFIXES: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "deepseek": "deepseek",
    "zhipu": "zai",
    "qwen": "dashscope",
    "minimax": "minimax",
    "jina": "jina",
}

# Our provider name → litellm_provider metadata value (for metadata-based lookup)
_LITELLM_PROVIDER_NAMES: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "deepseek": "deepseek",
}


def _match_provider(litellm_name: str, meta: dict, provider: str) -> tuple[bool, str]:
    """Check if a litellm model belongs to the given provider.

    Returns (matched, model_id).
    Uses prefix-based matching first, then falls back to litellm_provider metadata.
    """
    prefix = PROVIDER_PREFIXES.get(provider, "")
    if prefix and litellm_name.startswith(prefix + "/"):
        return True, litellm_name[len(prefix) + 1 :]

    litellm_provider = _LITELLM_PROVIDER_NAMES.get(provider)
    if litellm_provider and meta.get("litellm_provider") == litellm_provider:
        # Bare model name (no prefix) — use as-is
        if "/" not in litellm_name:
            return True, litellm_name

    return False, ""


def get_provider_models(provider: str) -> list[ModelDefinition]:
    if provider not in PROVIDER_PREFIXES:
        return []
    results = []
    seen_ids: set[str] = set()
    for litellm_name, meta in litellm.model_cost.items():
        matched, model_id = _match_provider(litellm_name, meta, provider)
        if not matched or model_id in seen_ids:
            continue
        seen_ids.add(model_id)
        ctx = meta.get("max_input_tokens") or meta.get("max_tokens")
        litellm_prefix = PROVIDER_PREFIXES[provider]
        # Ensure model_profile always uses prefix/model format for litellm
        model_profile = litellm_name if "/" in litellm_name else f"{litellm_prefix}/{litellm_name}"
        results.append(
            ModelDefinition(
                id=f"{provider}/{model_id}",
                object="model",
                owned_by=provider,
                provider=provider,
                model_profile=model_profile,
                upstream_model=model_id,
                display_name=model_id,
                supported_protocols=["openai_chat", "anthropic_messages"],
                supported_clients=[],
                auth_modes=["api_key"],
                description=f"{model_id} via {provider}",
            )
        )
    return results


def find_model_by_id(model_id: str) -> ModelDefinition | None:
    for provider in PROVIDER_PREFIXES:
        for m in get_provider_models(provider):
            if m.id == model_id:
                return m
    return None
