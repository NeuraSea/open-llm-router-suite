from __future__ import annotations

import json
from urllib.parse import urlparse

from enterprise_llm_proxy.config import AppSettings


class BootstrapScriptService:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def control_plane_host(self) -> str:
        return urlparse(self.control_plane_base_url()).hostname or "localhost"

    def control_plane_no_proxy_value(self) -> str:
        return f"{self.control_plane_host()},localhost,127.0.0.1"

    @staticmethod
    def is_native_claude_model(model: str) -> bool:
        return model.startswith("claude-")

    def control_plane_base_url(self) -> str:
        normalized = self._settings.router_public_base_url.rstrip("/")
        if normalized.endswith("/v1"):
            return normalized[:-3]
        return normalized

    def routerctl_install_url(self) -> str:
        return f"{self.control_plane_base_url()}/install/routerctl.sh"

    def routerctl_powershell_install_url(self) -> str:
        return f"{self.control_plane_base_url()}/install/routerctl.ps1"

    def routerctl_wheel_url(self, wheel_filename: str) -> str:
        return f"{self.control_plane_base_url()}/install/artifacts/{wheel_filename}"

    def build_routerctl_install_command(self, *, bootstrap_token: str) -> str:
        quoted_token = json.dumps(bootstrap_token)
        quoted_no_proxy = json.dumps(self.control_plane_no_proxy_value())
        return " ".join(
            [
                f"export NO_PROXY={quoted_no_proxy};",
                'export no_proxy="$NO_PROXY";',
                f"export ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN={quoted_token};",
                f"curl --noproxy {self.control_plane_host()} -fsSL {self.routerctl_install_url()} | bash",
            ]
        )

    @staticmethod
    def _powershell_single_quote(value: str) -> str:
        return value.replace("'", "''")

    def _build_powershell_install_command(
        self,
        *,
        install_url: str,
        extra_statements: list[str] | None = None,
    ) -> str:
        quoted_no_proxy = self._powershell_single_quote(self.control_plane_no_proxy_value())
        quoted_install_url = self._powershell_single_quote(install_url)
        statements = [
            "[Net.ServicePointManager]::SecurityProtocol = "
            "[Net.ServicePointManager]::SecurityProtocol -bor "
            "[Net.SecurityProtocolType]::Tls12;",
            f"$env:NO_PROXY='{quoted_no_proxy}';",
            "$env:no_proxy=$env:NO_PROXY;",
        ]
        if extra_statements:
            statements.extend(extra_statements)
        statements.append(f"iwr '{quoted_install_url}' -UseBasicParsing | iex")
        inline_command = " ".join(statements)
        return " ".join(
            [
                "powershell -NoProfile -ExecutionPolicy Bypass -Command",
                f'"{inline_command}"',
            ]
        )

    def build_routerctl_powershell_install_command(self, *, bootstrap_token: str) -> str:
        token = self._powershell_single_quote(bootstrap_token)
        return self._build_powershell_install_command(
            install_url=self.routerctl_powershell_install_url(),
            extra_statements=[
                f"$env:ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN='{token}';",
            ],
        )

    def build_routerctl_install_script(self, *, wheel_filename: str) -> str:
        return f"""#!/usr/bin/env bash
set -euo pipefail

ROUTER_BASE_URL="{self.control_plane_base_url()}"
ROUTER_HOST="{self.control_plane_host()}"
WHEEL_URL="{self.routerctl_wheel_url(wheel_filename)}?ts=$(date +%s)"
BOOTSTRAP_TOKEN="${{ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN:-}}"

if [ -z "$BOOTSTRAP_TOKEN" ]; then
  echo "ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN is required" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to install routerctl" >&2
  exit 1
fi

export NO_PROXY="{self.control_plane_no_proxy_value()}"
export no_proxy="$NO_PROXY"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

uv --native-tls tool install --force --from "$WHEEL_URL" enterprise-llm-proxy

# Detect if the router resolves to a loopback address (local dev with self-signed cert)
_INSECURE_FLAG=""
if command -v python3 >/dev/null 2>&1; then
  if python3 - "$ROUTER_HOST" <<'PY'
import ipaddress, socket, sys
host = sys.argv[1]
try:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
except OSError:
    raise SystemExit(1)
addresses = [ipaddress.ip_address(i[4][0]) for i in infos if i[4]]
raise SystemExit(0 if addresses and all(a.is_loopback for a in addresses) else 1)
PY
  then
    _INSECURE_FLAG="--insecure"
  fi
fi

routerctl auth bootstrap \
  --router-base-url "$ROUTER_BASE_URL" \
  --bootstrap-token "$BOOTSTRAP_TOKEN" \
  $_INSECURE_FLAG

echo
echo "routerctl 安装并登录完成。下一步："
echo "  routerctl claude bind"
echo "  routerctl codex bind"
echo "  用 cc-switch 启动/切换 Claude Code 或 Codex 模型"
"""

    def build_routerctl_powershell_install_script(self, *, wheel_filename: str) -> str:
        return f"""$ErrorActionPreference = "Stop"

$RouterBaseUrl = "{self.control_plane_base_url()}"
$RouterHost = "{self.control_plane_host()}"
$WheelUrl = "{self.routerctl_wheel_url(wheel_filename)}?ts=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
$BootstrapToken = $env:ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN

if ([string]::IsNullOrWhiteSpace($BootstrapToken)) {{
    throw "ENTERPRISE_LLM_PROXY_BOOTSTRAP_TOKEN is required"
}}

if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {{
    throw "python is required to install routerctl"
}}

$env:NO_PROXY = "{self.control_plane_no_proxy_value()}"
$env:no_proxy = $env:NO_PROXY

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {{
    irm https://astral.sh/uv/install.ps1 | iex
    $UserLocalBin = Join-Path $HOME ".local\\bin"
    $CargoBin = Join-Path $HOME ".cargo\\bin"
    $env:Path = "$UserLocalBin;$CargoBin;$env:Path"
}}

uv --native-tls tool install --force --from "$WheelUrl" enterprise-llm-proxy

$InsecureFlag = @()
try {{
    $Addresses = [System.Net.Dns]::GetHostAddresses($RouterHost)
    if ($Addresses.Count -gt 0 -and ($Addresses | Where-Object {{ -not $_.IsLoopback }}).Count -eq 0) {{
        $InsecureFlag = @("--insecure")
    }}
}} catch {{
}}

routerctl auth bootstrap `
  --router-base-url "$RouterBaseUrl" `
  --bootstrap-token "$BootstrapToken" `
  @InsecureFlag

Write-Host ""
Write-Host "routerctl 安装并登录完成。下一步："
Write-Host "  routerctl claude bind"
Write-Host "  routerctl codex bind"
Write-Host "  用 cc-switch 启动/切换 Claude Code 或 Codex 模型"
"""

    def build_claude_code_env_content(self, *, api_key: str, model: str) -> str:
        lines = [
            f'export ANTHROPIC_BASE_URL="{self.control_plane_base_url()}"',
            f'export ANTHROPIC_AUTH_TOKEN="{api_key}"',
            "unset ANTHROPIC_API_KEY",
            f'export ANTHROPIC_MODEL="{model}"',
        ]
        if self.is_native_claude_model(model):
            lines.extend(
                [
                    "unset ANTHROPIC_CUSTOM_MODEL_OPTION",
                    "unset ANTHROPIC_CUSTOM_MODEL_OPTION_NAME",
                    "unset ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION",
                ]
            )
        else:
            lines.append(f'export ANTHROPIC_CUSTOM_MODEL_OPTION="{model}"')
        lines.append("")
        return "\n".join(lines)

    def build_codex_env_content(self, *, api_key: str, env_var_name: str) -> str:
        return f'export {env_var_name}="{api_key}"\n'

    def build_codex_config_content(self, *, model: str, env_var_name: str) -> str:
        return f"""[model_providers.enterprise_router]
name = "Enterprise Router"
base_url = "{self._settings.router_public_base_url}"
env_key = "{env_var_name}"
wire_api = "responses"

[profiles.enterprise_router]
model_provider = "enterprise_router"
model = "{model}"
"""

    def build_claude_code_script(self, *, api_key: str, model: str) -> str:
        router_host = urlparse(self._settings.router_public_base_url).hostname or "localhost"
        return f"""#!/usr/bin/env bash
set -euo pipefail

ENV_DIR="${{HOME}}/.enterprise-llm-proxy"
ENV_FILE="${{ENV_DIR}}/claude-code.env"
LOCAL_CA_FILE="${{ENV_DIR}}/router-local-ca.pem"
ROUTER_HOST="{router_host}"
mkdir -p "${{ENV_DIR}}"

cat > "${{ENV_FILE}}" <<'EOF'
{self.build_claude_code_env_content(api_key=api_key, model=model).rstrip()}
EOF

if command -v python3 >/dev/null 2>&1; then
  if python3 - "$ROUTER_HOST" <<'PY'
import ipaddress
import socket
import sys

host = sys.argv[1]
try:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
except OSError:
    raise SystemExit(1)

addresses = []
for info in infos:
    sockaddr = info[4]
    if not sockaddr:
        continue
    addresses.append(ipaddress.ip_address(sockaddr[0]))

raise SystemExit(0 if addresses and all(address.is_loopback for address in addresses) else 1)
PY
  then
    export NO_PROXY="{router_host},localhost,127.0.0.1"
    export no_proxy="$NO_PROXY"
    if [ "$(uname -s)" = "Darwin" ] && command -v security >/dev/null 2>&1; then
      security find-certificate -a -p -c 'Caddy Local Authority' /Library/Keychains/System.keychain > "$LOCAL_CA_FILE" 2>/dev/null || true
      if grep -q "BEGIN CERTIFICATE" "$LOCAL_CA_FILE" 2>/dev/null; then
        export NODE_EXTRA_CA_CERTS="${{ENV_DIR}}/router-local-ca.pem"
      else
        rm -f "$LOCAL_CA_FILE"
      fi
    fi
  fi
fi

SHELL_RC="${{HOME}}/.zshrc"
if [ -n "${{SHELL:-}}" ] && [[ "${{SHELL}}" == *"bash" ]]; then
  SHELL_RC="${{HOME}}/.bashrc"
fi

LINE='source "${{HOME}}/.enterprise-llm-proxy/claude-code.env"'
grep -Fqx "$LINE" "$SHELL_RC" 2>/dev/null || echo "$LINE" >> "$SHELL_RC"

echo "Claude Code enterprise routing configured. Restart your shell or run: source $ENV_FILE"
"""

    def build_codex_script(self, *, api_key: str, model: str) -> str:
        env_var_name = self._settings.platform_api_key_env
        return f"""#!/usr/bin/env bash
set -euo pipefail

ENV_DIR="${{HOME}}/.enterprise-llm-proxy"
ENV_FILE="${{ENV_DIR}}/codex.env"
CONFIG_DIR="${{HOME}}/.codex"
CONFIG_FILE="${{CONFIG_DIR}}/config.toml"
mkdir -p "${{ENV_DIR}}" "${{CONFIG_DIR}}"

cat > "${{ENV_FILE}}" <<'EOF'
{self.build_codex_env_content(api_key=api_key, env_var_name=env_var_name).rstrip()}
EOF

SHELL_RC="${{HOME}}/.zshrc"
if [ -n "${{SHELL:-}}" ] && [[ "${{SHELL}}" == *"bash" ]]; then
  SHELL_RC="${{HOME}}/.bashrc"
fi

LINE='source "${{HOME}}/.enterprise-llm-proxy/codex.env"'
grep -Fqx "$LINE" "$SHELL_RC" 2>/dev/null || echo "$LINE" >> "$SHELL_RC"

cat > "${{CONFIG_FILE}}" <<'EOF'
{self.build_codex_config_content(model=model, env_var_name=env_var_name).rstrip()}
EOF

echo "Codex enterprise routing configured. Restart your shell or run: source $ENV_FILE"
"""

    def hosts_fallback(self) -> dict[str, object]:
        if not (
            self._settings.hosts_fallback_enabled
            and self._settings.hosts_fallback_domain
            and self._settings.hosts_fallback_target
        ):
            return {
                "enabled": False,
                "message": "Claude Code and Codex both support configurable base URLs, so hosts overrides are disabled by default.",
            }

        return {
            "enabled": True,
            "message": "Use only with enterprise-owned DNS names and matching TLS certificates.",
            "entry": f"{self._settings.hosts_fallback_target} {self._settings.hosts_fallback_domain}",
        }
