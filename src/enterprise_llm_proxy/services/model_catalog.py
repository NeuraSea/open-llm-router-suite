from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from fastapi import HTTPException, status
from enterprise_llm_proxy.services.compat_models import (
    COMPAT_PROVIDERS,
    build_compat_public_model_id,
    split_compat_public_model_id,
)

if TYPE_CHECKING:
    from enterprise_llm_proxy.domain.models import Principal
    from enterprise_llm_proxy.services.credentials import CredentialPoolService


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    object: str
    owned_by: str
    provider: str
    model_profile: str
    upstream_model: str
    display_name: str
    supported_protocols: list[str]
    supported_clients: list[str]
    auth_modes: list[str]
    description: str
    provider_alias: str | None = None
    experimental: bool = False
    context_window: int = 128000
    max_output_tokens: int = 8192

    def to_public_model(self) -> dict[str, object]:
        return {
            "id": self.id,
            "object": self.object,
            "owned_by": self.owned_by,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
        }

    def to_ui_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "provider": self.provider,
            "provider_alias": self.provider_alias,
            "description": self.description,
            "model_profile": self.model_profile,
            "upstream_model": self.upstream_model,
            "supported_protocols": list(self.supported_protocols),
            "supported_clients": list(self.supported_clients),
            "auth_modes": list(self.auth_modes),
            "experimental": self.experimental,
        }

    def to_runtime_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "object": self.object,
            "owned_by": self.owned_by,
            "provider": self.provider,
            "model_profile": self.model_profile,
            "upstream_model": self.upstream_model,
            "display_name": self.display_name,
            "supported_protocols": list(self.supported_protocols),
            "supported_clients": list(self.supported_clients),
            "auth_modes": list(self.auth_modes),
            "provider_alias": self.provider_alias,
            "description": self.description,
            "experimental": self.experimental,
        }


class ModelCatalog:
    def __init__(
        self,
        custom_models_loader: Callable[[], list[dict]] | None = None,
        compat_models_loader: Callable[[], list[ModelDefinition]] | None = None,
    ) -> None:
        self._custom_models_loader = custom_models_loader
        self._compat_models_loader = compat_models_loader
        self._models = {
            "openai/gpt-4.1": ModelDefinition(
                id="openai/gpt-4.1",
                object="model",
                owned_by="openai",
                provider="openai",
                model_profile="openai/gpt-4.1",
                upstream_model="gpt-4.1",
                display_name="GPT-4.1",
                supported_protocols=["openai_chat", "openai_responses"],
                supported_clients=["codex"],
                auth_modes=["api_key"],
                description="Standard OpenAI-compatible GPT model for Codex and API clients.",
            ),
            "openai/gpt-4.1-mini": ModelDefinition(
                id="openai/gpt-4.1-mini",
                object="model",
                owned_by="openai",
                provider="openai",
                model_profile="openai/gpt-4.1-mini",
                upstream_model="gpt-4.1-mini",
                display_name="GPT-4.1 Mini",
                supported_protocols=["openai_chat", "openai_responses"],
                supported_clients=["codex"],
                auth_modes=["api_key"],
                description="Lower-latency OpenAI-compatible GPT model for lightweight tasks.",
            ),
            "openai-codex/gpt-5-codex": ModelDefinition(
                id="openai-codex/gpt-5-codex",
                object="model",
                owned_by="openai",
                provider="openai-codex",
                model_profile="openai-codex/gpt-5-codex",
                upstream_model="gpt-5-codex",
                display_name="GPT-5 Codex",
                supported_protocols=["openai_chat", "openai_responses", "anthropic_messages"],
                supported_clients=["claude_code", "codex"],
                auth_modes=[
                    "codex_chatgpt_oauth_managed",
                    "codex_chatgpt_oauth_imported",
                ],
                description="Codex OAuth-backed GPT model routed through the ChatGPT Codex backend.",
                experimental=True,
            ),
            "openai-codex/gpt-5.4": ModelDefinition(
                id="openai-codex/gpt-5.4",
                object="model",
                owned_by="openai",
                provider="openai-codex",
                model_profile="openai-codex/gpt-5.4",
                upstream_model="gpt-5.4",
                display_name="GPT-5.4 (Codex)",
                supported_protocols=["openai_chat", "openai_responses", "anthropic_messages"],
                supported_clients=["claude_code", "codex"],
                auth_modes=[
                    "codex_chatgpt_oauth_managed",
                    "codex_chatgpt_oauth_imported",
                ],
                description="GPT-5.4 via Codex OAuth backend.",
                experimental=True,
            ),
            "claude-max/claude-sonnet-4-6": ModelDefinition(
                id="claude-max/claude-sonnet-4-6",
                object="model",
                owned_by="anthropic",
                provider="claude-max",
                model_profile="anthropic/claude-sonnet-4-6",
                upstream_model="claude-sonnet-4-6",
                display_name="Claude Sonnet 4.6",
                supported_protocols=["anthropic_messages", "openai_chat", "openai_responses"],
                supported_clients=["claude_code", "codex"],
                auth_modes=["oauth_subscription", "api_key"],
                description="Latest Claude Sonnet — fast, capable, ideal for everyday coding.",
                context_window=200000,
                max_output_tokens=16000,
            ),
            "claude-max/claude-opus-4-6": ModelDefinition(
                id="claude-max/claude-opus-4-6",
                object="model",
                owned_by="anthropic",
                provider="claude-max",
                model_profile="anthropic/claude-opus-4-6",
                upstream_model="claude-opus-4-6",
                display_name="Claude Opus 4.6",
                supported_protocols=["anthropic_messages", "openai_chat", "openai_responses"],
                supported_clients=["claude_code", "codex"],
                auth_modes=["oauth_subscription", "api_key"],
                description="Most powerful Claude model for complex, multi-step tasks.",
                context_window=200000,
                max_output_tokens=32000,
            ),
            "claude-max/claude-haiku-4-5-20251001": ModelDefinition(
                id="claude-max/claude-haiku-4-5-20251001",
                object="model",
                owned_by="anthropic",
                provider="claude-max",
                model_profile="anthropic/claude-haiku-4-5-20251001",
                upstream_model="claude-haiku-4-5-20251001",
                display_name="Claude Haiku 4.5",
                supported_protocols=["anthropic_messages", "openai_chat", "openai_responses"],
                supported_clients=["claude_code", "codex"],
                auth_modes=["oauth_subscription", "api_key"],
                description="Fastest, most compact Claude model for lightweight tasks.",
                context_window=200000,
                max_output_tokens=8192,
            ),
            "claude-max/claude-sonnet-4-20250514": ModelDefinition(
                id="claude-max/claude-sonnet-4-20250514",
                object="model",
                owned_by="anthropic",
                provider="claude-max",
                model_profile="anthropic/claude-sonnet-4-20250514",
                upstream_model="claude-sonnet-4-20250514",
                display_name="Claude Sonnet 4 (legacy)",
                supported_protocols=["anthropic_messages", "openai_chat", "openai_responses"],
                supported_clients=["claude_code", "codex"],
                auth_modes=["oauth_subscription", "api_key"],
                description="Previous Claude Sonnet 4 release.",
                context_window=200000,
                max_output_tokens=16000,
                experimental=True,
            ),
        }

    _DISCOVERED_PROVIDER_DEFAULTS = {
        "openai-codex": {
            "owned_by": "openai",
            "model_profile_prefix": "openai-codex",
            "supported_protocols": ["openai_chat", "openai_responses", "anthropic_messages"],
            "supported_clients": ["claude_code", "codex"],
            "auth_modes": ["codex_chatgpt_oauth_managed", "codex_chatgpt_oauth_imported"],
            "description": "Codex OAuth-backed model routed through the ChatGPT Codex backend.",
            "experimental": True,
            "context_window": 128000,
            "max_output_tokens": 8192,
        },
        "claude-max": {
            "owned_by": "anthropic",
            "model_profile_prefix": "anthropic",
            "supported_protocols": ["anthropic_messages", "openai_chat", "openai_responses"],
            "supported_clients": ["claude_code", "codex"],
            "auth_modes": ["oauth_subscription", "api_key"],
            "description": "Claude subscription model available through the bound account.",
            "experimental": False,
            "context_window": 200000,
            "max_output_tokens": 16000,
        },
        "jina": {
            "owned_by": "jina",
            "model_profile_prefix": "jina",
            "supported_protocols": ["openai_embeddings", "jina_rerank"],
            "supported_clients": [],
            "auth_modes": ["api_key"],
            "description": "Jina embedding and rerank model available through the bound API key.",
            "experimental": False,
            "context_window": 8192,
            "max_output_tokens": 0,
        },
    }

    _DISCOVERED_MODEL_TEMPLATES = {
        "openai-codex/gpt-5.4": {
            "display_name": "GPT-5.4 (Codex)",
            "description": "GPT-5.4 via Codex OAuth backend.",
        },
        "openai-codex/gpt-5.4-mini": {
            "display_name": "GPT-5.4 Mini",
            "description": "Smaller frontier agentic coding model.",
        },
        "openai-codex/gpt-5.3-codex": {
            "display_name": "GPT-5.3 Codex",
            "description": "Frontier Codex-optimized agentic coding model.",
        },
        "openai-codex/gpt-5.3-codex-spark": {
            "display_name": "GPT-5.3 Codex Spark",
            "description": "Ultra-fast coding model.",
        },
        "openai-codex/gpt-5.2": {
            "display_name": "GPT-5.2",
            "description": "Optimized for professional work and long-running agents.",
        },
        "openai-codex/gpt-5.2-codex": {
            "display_name": "GPT-5.2 Codex",
            "description": "Frontier agentic coding model.",
        },
        "openai-codex/gpt-5.1-codex-max": {
            "display_name": "GPT-5.1 Codex Max",
            "description": "Codex-optimized flagship for deep and fast reasoning.",
        },
        "openai-codex/gpt-5.1-codex-mini": {
            "display_name": "GPT-5.1 Codex Mini",
            "description": "Optimized for codex. Cheaper, faster, but less capable.",
        },
        "claude-max/claude-sonnet-4-6": {
            "display_name": "Claude Sonnet 4.6",
            "description": "Latest Claude Sonnet — fast, capable, ideal for everyday coding.",
        },
        "claude-max/claude-opus-4-6": {
            "display_name": "Claude Opus 4.6",
            "description": "Most powerful Claude model for complex, multi-step tasks.",
            "max_output_tokens": 32000,
        },
        "claude-max/claude-haiku-4-5-20251001": {
            "display_name": "Claude Haiku 4.5",
            "description": "Fastest, most compact Claude model for lightweight tasks.",
            "max_output_tokens": 8192,
        },
    }

    def _merged_models(self) -> dict[str, ModelDefinition]:
        merged = dict(self._models)
        if self._custom_models_loader is not None:
            for row in self._custom_models_loader():
                merged[row["id"]] = ModelDefinition(
                    id=row["id"],
                    object="model",
                    owned_by=row.get("provider", "custom"),
                    provider=row["provider"],
                    model_profile=row["model_profile"],
                    upstream_model=row["upstream_model"],
                    display_name=row["display_name"],
                    supported_protocols=[],
                    supported_clients=row.get("supported_clients", []),
                    auth_modes=row.get("auth_modes", []),
                    description=row.get("description", ""),
                )
        return merged

    def list_models(self) -> list[dict[str, str]]:
        return [item.to_public_model() for item in self._ordered_models()]

    def list_ui_models(self) -> list[dict[str, object]]:
        return [item.to_ui_dict() for item in self._ordered_models()]

    def resolve_model(self, model_name: str) -> dict[str, object]:
        merged = self._merged_models()
        model = merged.get(model_name)
        if model is None:
            model = self._discovered_model_from_id(model_name)
        if model is None:
            for compat_model in self._compat_models():
                if compat_model.id == model_name:
                    model = compat_model
        if model is None:
            raise HTTPException(status_code=404, detail=f"Unknown model: {model_name}")
        return model.to_runtime_dict()

    def resolve_model_for_principal(
        self,
        model_name: str,
        principal: Principal,
        credential_pool: CredentialPoolService,
    ) -> dict[str, object]:
        merged = self._merged_models()
        # Layer 1: enterprise catalog
        if model_name in merged:
            return merged[model_name].to_runtime_dict()
        discovered_model = self._discovered_model_from_id(model_name)
        if discovered_model is not None:
            return discovered_model.to_runtime_dict()

        compat_model = self._compat_model_from_id(model_name, principal, credential_pool)
        if compat_model is not None:
            return compat_model.to_runtime_dict()

        # Layer 2: system compat models (for example, LM Studio)
        for compat_model in self._compat_models():
            if compat_model.id == model_name:
                return compat_model.to_runtime_dict()

        # Layer 3: BYOK registry (litellm model_cost)
        from enterprise_llm_proxy.services import provider_registry

        byok_def = provider_registry.find_model_by_id(model_name)
        if byok_def is not None:
            return byok_def.to_runtime_dict()

        # Layer 3b: explicit provider/model names for known BYOK providers should
        # keep their provider identity, even if the exact model id isn't in
        # litellm's static registry yet. This prevents accidental compat fallback.
        if "/" in model_name:
            provider, upstream_model = model_name.split("/", 1)
            if provider in provider_registry.PROVIDER_PREFIXES and upstream_model:
                fallback = ModelDefinition(
                    id=model_name,
                    object="model",
                    owned_by=provider,
                    provider=provider,
                    model_profile=model_name,
                    upstream_model=upstream_model,
                    display_name=model_name,
                    supported_protocols=["openai_chat", "anthropic_messages"],
                    supported_clients=[],
                    auth_modes=["api_key"],
                    description=f"{model_name} via {provider}",
                )
                return fallback.to_runtime_dict()

        raise HTTPException(status_code=404, detail=f"Model not found: {model_name}")

    def list_models_for_principal(
        self,
        principal: Principal,
        credential_pool: CredentialPoolService,
        *,
        routable_only: bool = False,
    ) -> list[dict[str, object]]:
        from enterprise_llm_proxy.services import provider_registry

        merged = self._merged_models()
        results: list[dict[str, object]] = []
        all_creds = self._accessible_credentials(principal, credential_pool)
        discovered_models_by_provider = self._discovered_models_by_provider(all_creds)
        # Enterprise catalog
        for m in self._ordered_models():
            if m.provider in discovered_models_by_provider:
                continue
            results.append({**m.to_ui_dict(), "source": "catalog"})

        seen_profiles = {
            m.model_profile
            for m in merged.values()
            if m.provider not in discovered_models_by_provider
        }
        for provider, available_models in discovered_models_by_provider.items():
            for discovered_model in self._discovered_models(provider, available_models):
                if discovered_model.model_profile in seen_profiles:
                    continue
                seen_profiles.add(discovered_model.model_profile)
                results.append({**discovered_model.to_ui_dict(), "source": "catalog"})

        for source, compat_model in self._compat_models_from_credentials(all_creds):
            if compat_model.id in {item["id"] for item in results}:
                continue
            results.append({**compat_model.to_ui_dict(), "source": source})

        for compat_model in self._compat_models():
            if compat_model.id in {item["id"] for item in results}:
                continue
            seen_profiles.add(compat_model.model_profile)
            results.append({**compat_model.to_ui_dict(), "source": "compat"})

        # BYOK models from user's credentials
        providers_seen: set[str] = set()
        for cred in all_creds:
            if cred.provider in providers_seen:
                continue
            providers_seen.add(cred.provider)
            for model_def in provider_registry.get_provider_models(cred.provider):
                if model_def.model_profile not in seen_profiles:
                    seen_profiles.add(model_def.model_profile)
                    results.append({**model_def.to_ui_dict(), "source": "byok"})

        if routable_only:
            results = [
                model
                for model in results
                if self._model_is_routable(model, principal, credential_pool)
            ]

        return results

    def _ordered_models(self) -> list[ModelDefinition]:
        return sorted(self._merged_models().values(), key=lambda item: item.id)

    def _compat_models(self) -> list[ModelDefinition]:
        if self._compat_models_loader is None:
            return []
        return self._compat_models_loader()

    @classmethod
    def _credential_available_models(cls, credential: object) -> list[str]:
        catalog_info = getattr(credential, "catalog_info", None)
        raw_models = catalog_info.get("available_models") if isinstance(catalog_info, dict) else None
        if not isinstance(raw_models, list):
            quota_info = getattr(credential, "quota_info", None)
            raw_models = quota_info.get("available_models") if isinstance(quota_info, dict) else None
        if not isinstance(raw_models, list):
            return []
        discovered: list[str] = []
        seen: set[str] = set()
        for raw_model in raw_models:
            model_id = str(raw_model).strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            discovered.append(model_id)
        return discovered

    @classmethod
    def _discovered_model_from_id(cls, model_name: str) -> ModelDefinition | None:
        if "/" not in model_name:
            return None
        provider, upstream_model = model_name.split("/", 1)
        if provider not in cls._DISCOVERED_PROVIDER_DEFAULTS or not upstream_model:
            return None
        return cls._build_discovered_model(provider, upstream_model)

    @classmethod
    def _discovered_models(cls, provider: str, model_ids: list[str]) -> list[ModelDefinition]:
        return [cls._build_discovered_model(provider, model_id) for model_id in model_ids if model_id]

    @classmethod
    def _build_discovered_model(cls, provider: str, model_id: str) -> ModelDefinition:
        provider_defaults = cls._DISCOVERED_PROVIDER_DEFAULTS[provider]
        full_model_id = f"{provider}/{model_id}"
        template = cls._DISCOVERED_MODEL_TEMPLATES.get(full_model_id, {})
        return ModelDefinition(
            id=full_model_id,
            object="model",
            owned_by=str(template.get("owned_by", provider_defaults["owned_by"])),
            provider=provider,
            model_profile=f"{provider_defaults['model_profile_prefix']}/{model_id}",
            upstream_model=model_id,
            display_name=str(template.get("display_name", model_id)),
            supported_protocols=list(template.get("supported_protocols", provider_defaults["supported_protocols"])),
            supported_clients=list(template.get("supported_clients", provider_defaults["supported_clients"])),
            auth_modes=list(template.get("auth_modes", provider_defaults["auth_modes"])),
            description=str(template.get("description", provider_defaults["description"])),
            experimental=bool(template.get("experimental", provider_defaults["experimental"])),
            context_window=int(template.get("context_window", provider_defaults["context_window"])),
            max_output_tokens=int(template.get("max_output_tokens", provider_defaults["max_output_tokens"])),
        )

    @staticmethod
    def _accessible_credentials(
        principal: Principal,
        credential_pool: CredentialPoolService,
    ) -> list[object]:
        seen_ids: set[str] = set()
        credentials = []
        for credential in [*credential_pool.list_for_owner(principal.user_id), *credential_pool.list_credentials()]:
            credential_id = getattr(credential, "id", None)
            if not credential_id or credential_id in seen_ids:
                continue
            seen_ids.add(credential_id)
            credentials.append(credential)
        return credentials

    @classmethod
    def _discovered_models_by_provider(cls, credentials: list[object]) -> dict[str, list[str]]:
        discovered_by_provider: dict[str, list[str]] = {}
        for credential in credentials:
            provider = getattr(credential, "provider", "")
            if provider in COMPAT_PROVIDERS:
                continue
            available_models = cls._credential_available_models(credential)
            if not available_models:
                continue
            merged = discovered_by_provider.setdefault(provider, [])
            for model_id in available_models:
                if model_id not in merged:
                    merged.append(model_id)
        return discovered_by_provider

    @classmethod
    def _compat_models_from_credentials(cls, credentials: list[object]) -> list[tuple[str, ModelDefinition]]:
        models: list[tuple[str, ModelDefinition]] = []
        for credential in credentials:
            provider = getattr(credential, "provider", "")
            provider_alias = getattr(credential, "provider_alias", None)
            if provider not in COMPAT_PROVIDERS or not isinstance(provider_alias, str) or not provider_alias:
                continue
            available_models = cls._credential_available_models(credential)
            if not available_models:
                continue
            source = "compat" if getattr(credential, "source", None) == "system_lm_studio" else "byok"
            for model_id in available_models:
                models.append((source, cls._build_compat_model(provider, provider_alias, model_id)))
        return models

    @classmethod
    def _compat_model_from_id(
        cls,
        model_name: str,
        principal: Principal,
        credential_pool: CredentialPoolService,
    ) -> ModelDefinition | None:
        parsed = split_compat_public_model_id(model_name)
        if parsed is None:
            return None
        provider_alias, upstream_model = parsed
        for credential in cls._accessible_credentials(principal, credential_pool):
            provider = getattr(credential, "provider", "")
            if provider not in COMPAT_PROVIDERS:
                continue
            if getattr(credential, "provider_alias", None) != provider_alias:
                continue
            available_models = cls._credential_available_models(credential)
            if upstream_model not in available_models:
                return None
            return cls._build_compat_model(provider, provider_alias, upstream_model)
        return None

    @staticmethod
    def _build_compat_model(provider: str, provider_alias: str, upstream_model: str) -> ModelDefinition:
        if provider == "anthropic_compat":
            supported_protocols = ["anthropic_messages"]
            supported_clients = ["claude_code"]
        else:
            supported_protocols = ["openai_chat", "openai_responses"]
            supported_clients = ["codex"]
        return ModelDefinition(
            id=build_compat_public_model_id(provider_alias, upstream_model),
            object="model",
            owned_by=provider,
            provider=provider,
            provider_alias=provider_alias,
            model_profile=upstream_model,
            upstream_model=upstream_model,
            display_name=upstream_model,
            supported_protocols=supported_protocols,
            supported_clients=supported_clients,
            auth_modes=["api_key"],
            description=f"{upstream_model} via {provider_alias}",
        )

    @staticmethod
    def _model_is_routable(
        model: dict[str, object],
        principal: Principal,
        credential_pool: CredentialPoolService,
    ) -> bool:
        provider = str(model.get("provider", ""))
        auth_modes = [str(mode) for mode in model.get("auth_modes", [])]
        provider_alias = model.get("provider_alias")
        provider_alias_value = str(provider_alias) if isinstance(provider_alias, str) and provider_alias else None
        for auth_kind in auth_modes:
            if credential_pool.has_available(
                provider=provider,
                auth_kind=auth_kind,
                provider_alias=provider_alias_value,
                upstream_model=str(model.get("upstream_model", "")) or None,
                principal=principal,
            ):
                return True
        return False
