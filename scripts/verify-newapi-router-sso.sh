#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEWAPI_DIR="$ROOT_DIR/third_party/new-api"
NEWAPI_WEB_DIR="$NEWAPI_DIR/web/default"
TMP_DIR="$(mktemp -d)"
CREATED_ENV_LOCAL=0

cleanup() {
  if [[ "$CREATED_ENV_LOCAL" -eq 1 ]]; then
    rm -f "$ROOT_DIR/.env.local"
  fi
  rm -rf "$TMP_DIR"
}

trap cleanup EXIT

log_step() {
  printf '\n==> %s\n' "$1"
}

require_dir() {
  local path="$1"
  if [[ ! -d "$path" ]]; then
    printf 'missing required directory: %s\n' "$path" >&2
    exit 1
  fi
}

ensure_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'required command not found: %s\n' "$command_name" >&2
    exit 1
  fi
}

find_go_command() {
  local candidate
  for candidate in \
    "${GO:-}" \
    go \
    /opt/homebrew/bin/go \
    /opt/homebrew/Cellar/go/1.26.1/libexec/bin/go \
    /usr/local/go/bin/go; do
    if [[ -z "$candidate" ]]; then
      continue
    fi
    if [[ "$candidate" == */* && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    if [[ "$candidate" != */* ]] && command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

docker_pull_with_retry() {
  local image="$1"
  local attempt

  if docker image inspect "$image" >/dev/null 2>&1; then
    return 0
  fi

  for attempt in 1 2 3; do
    if docker pull "$image"; then
      return 0
    fi
    if [[ "$attempt" -lt 3 ]]; then
      sleep $((attempt * 2))
    fi
  done

  printf 'failed to pull docker image after retries: %s\n' "$image" >&2
  exit 1
}

ensure_compose_env_file() {
  if [[ -f "$ROOT_DIR/.env.local" ]]; then
    return 0
  fi

  cat >"$ROOT_DIR/.env.local" <<'EOF'
ROUTER_SSO_ISSUER=enterprise-llm-proxy
ROUTER_SSO_AUDIENCE=new-api
ROUTER_SSO_PUBLIC_KEY_PEM=dummy-router-sso-public-key
NEWAPI_SESSION_SECRET=dummy-newapi-session-secret
EOF
  CREATED_ENV_LOCAL=1
}

run_parent_pytest() {
  log_step "Parent pytest"
  ensure_command uv
  (
    cd "$ROOT_DIR"
    uv run pytest -q
  )
}

run_newapi_go_tests() {
  log_step "new-api Router SSO go tests"
  local go_cmd

  if go_cmd="$(find_go_command)"; then
    (
      cd "$NEWAPI_DIR"
      "$go_cmd" test ./middleware ./service ./controller
    )
    return 0
  fi

  ensure_command docker
  local go_image="${GO_DOCKER_IMAGE:-golang:1.25.1-bookworm}"
  docker_pull_with_retry "$go_image"

  docker run --rm \
    -v "$NEWAPI_DIR:/workspace" \
    -w /workspace \
    "$go_image" \
    bash -lc "apt-get update >/dev/null && apt-get install -y --no-install-recommends build-essential ca-certificates git pkg-config >/dev/null && go test ./middleware ./service ./controller"
}

run_newapi_web_typecheck() {
  log_step "new-api web typecheck"
  ensure_command bun
  (
    cd "$NEWAPI_WEB_DIR"
    bun install --frozen-lockfile
    bun run typecheck
  )
}

run_docker_compose_config() {
  log_step "docker compose config"
  ensure_command docker
  ensure_compose_env_file
  (
    cd "$ROOT_DIR"
    ROUTER_SSO_ISSUER="${ROUTER_SSO_ISSUER:-enterprise-llm-proxy}" \
    ROUTER_SSO_AUDIENCE="${ROUTER_SSO_AUDIENCE:-new-api}" \
    ROUTER_SSO_PUBLIC_KEY_PEM="${ROUTER_SSO_PUBLIC_KEY_PEM:-dummy-router-sso-public-key}" \
    NEWAPI_SESSION_SECRET="${NEWAPI_SESSION_SECRET:-dummy-newapi-session-secret}" \
      docker compose config -q
  )
}

prepare_nginx_inputs() {
  cp "$ROOT_DIR/nginx.conf" "$TMP_DIR/router.conf"

  if [[ -f "$ROOT_DIR/certs/router.crt" && -f "$ROOT_DIR/certs/router.key" ]]; then
    cp "$ROOT_DIR/certs/router.crt" "$TMP_DIR/router.crt"
    cp "$ROOT_DIR/certs/router.key" "$TMP_DIR/router.key"
    return 0
  fi

  ensure_command openssl
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "$TMP_DIR/router.key" \
    -out "$TMP_DIR/router.crt" \
    -subj "/CN=router.local" >/dev/null 2>&1
}

run_nginx_syntax() {
  log_step "nginx syntax"
  prepare_nginx_inputs

  if command -v nginx >/dev/null 2>&1; then
    sed \
      -e "s#/etc/nginx/certs#$TMP_DIR#g" \
      -e "s/server app:8000;/server 127.0.0.1:8000;/" \
      -e "s/server new-api:3000;/server 127.0.0.1:3000;/" \
      -e "s#proxy_pass http://librechat:3080/#proxy_pass http://127.0.0.1:3080/#" \
      "$TMP_DIR/router.conf" >"$TMP_DIR/router-local.conf"
    cat >"$TMP_DIR/nginx-main.conf" <<EOF
worker_processes 1;
pid $TMP_DIR/nginx.pid;
error_log $TMP_DIR/error.log;
events { worker_connections 1024; }
http {
    access_log $TMP_DIR/access.log;
    include $TMP_DIR/router-local.conf;
}
EOF
    nginx -t -p "$TMP_DIR" -c "$TMP_DIR/nginx-main.conf"
    return 0
  fi

  ensure_command docker
  local nginx_image="${NGINX_DOCKER_IMAGE:-nginx:1.27-alpine}"
  if ! docker image inspect "$nginx_image" >/dev/null 2>&1; then
    if [[ -z "${NGINX_DOCKER_IMAGE:-}" ]] && docker image inspect nginx:latest >/dev/null 2>&1; then
      nginx_image="nginx:latest"
    else
      docker_pull_with_retry "$nginx_image"
    fi
  fi

  docker run --rm \
    --add-host app:127.0.0.1 \
    --add-host new-api:127.0.0.1 \
    --add-host librechat:127.0.0.1 \
    -v "$TMP_DIR/router.conf:/etc/nginx/conf.d/router.conf:ro" \
    -v "$TMP_DIR/router.crt:/etc/nginx/certs/router.crt:ro" \
    -v "$TMP_DIR/router.key:/etc/nginx/certs/router.key:ro" \
    "$nginx_image" nginx -t
}

main() {
  require_dir "$NEWAPI_DIR"
  require_dir "$NEWAPI_WEB_DIR"

  run_parent_pytest
  run_newapi_go_tests
  run_newapi_web_typecheck
  run_docker_compose_config
  run_nginx_syntax
}

main "$@"
