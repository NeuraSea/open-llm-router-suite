from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator

import httpx
from fastapi import HTTPException, status

from enterprise_llm_proxy.domain.credentials import ProviderCredential
from enterprise_llm_proxy.domain.inference import UnifiedInferenceRequest
from enterprise_llm_proxy.services.execution import (
    ExecutionResult,
    UpstreamCredentialInvalidError,
    UpstreamRateLimitError,
    is_invalid_credential_status,
)


class OpenAICompatExecutor:
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http_client = http_client

    def execute(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> ExecutionResult:
        api_key, base_url = self._parse_credential(credential)
        payload, endpoint = self._build_request(request)
        with self._client() as client:
            response = client.post(
                self._url_for(base_url, endpoint),
                headers=self._headers(api_key),
                json=payload,
            )

        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise UpstreamRateLimitError("Upstream credential hit rate limits")
        if is_invalid_credential_status(response.status_code):
            raise UpstreamCredentialInvalidError(self._error_detail(response))
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=self._error_detail(response),
            )

        try:
            body = response.json()
        except ValueError as exc:
            snippet = response.text.strip()
            if len(snippet) > 200:
                snippet = f"{snippet[:200]}..."
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Upstream request returned a non-JSON success payload: {snippet or '<empty>'}",
            ) from exc
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upstream request returned a non-object JSON payload",
            )
        usage = body.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return ExecutionResult(
            body=body,
            tokens_in=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            tokens_out=int(
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            ),
        )

    def execute_stream(
        self,
        request: UnifiedInferenceRequest,
        credential: ProviderCredential,
    ) -> Iterator[bytes]:
        api_key, base_url = self._parse_credential(credential)
        payload, endpoint = self._build_request(request)
        with self._client() as client:
            with client.stream(
                "POST",
                self._url_for(base_url, endpoint),
                headers={**self._headers(api_key), "Accept": "text/event-stream"},
                json=payload,
            ) as response:
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    raise UpstreamRateLimitError("Upstream credential hit rate limits")
                if is_invalid_credential_status(response.status_code):
                    raise UpstreamCredentialInvalidError(self._error_detail(response))
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=self._error_detail(response),
                    )
                for chunk in response.iter_bytes():
                    yield chunk

    def _build_request(
        self,
        request: UnifiedInferenceRequest,
    ) -> tuple[dict[str, object], str]:
        payload = dict(request.payload)
        payload["model"] = request.upstream_model
        if request.protocol == "openai_chat":
            return payload, "/chat/completions"
        if request.protocol == "openai_responses":
            return payload, "/responses"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported protocol: {request.protocol}",
        )

    @staticmethod
    def _parse_credential(
        credential: ProviderCredential,
    ) -> tuple[str, str]:
        data = json.loads(credential.access_token or "{}")
        api_key = str(data.get("api_key", "")).strip()
        base_url = str(data.get("base_url", "")).strip().rstrip("/")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Selected upstream credential is missing an api key",
            )
        if not base_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Selected upstream credential is missing a base url",
            )
        return api_key, base_url

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _url_for(base_url: str, endpoint: str) -> str:
        return f"{base_url}/{endpoint.lstrip('/')}"

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return str(error["message"])
        return "Upstream request failed"

    @contextmanager
    def _client(self) -> Iterator[httpx.Client]:
        if self._http_client is not None:
            yield self._http_client
            return
        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=30.0)) as client:
            yield client
