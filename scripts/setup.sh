#!/usr/bin/env bash
set -euo pipefail

BACKEND="${1:-codex}"
OLLAMA_MODE="${2:-auto}"
MODEL="${MODEL:-gpt-oss:20b}"

log() {
  printf '[setup] %s\n' "$1"
}

fail() {
  printf '[setup] ERROR: %s\n' "$1" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

is_wsl() {
  grep -qi microsoft /proc/version 2>/dev/null
}

windows_host_ip() {
  awk '/^nameserver / {print $2; exit}' /etc/resolv.conf 2>/dev/null
}

ollama_hosts() {
  local host_ip
  host_ip="$(windows_host_ip || true)"
  case "$OLLAMA_MODE" in
    auto)
      printf '%s\n' "http://127.0.0.1:11434" "http://localhost:11434"
      if [ -n "$host_ip" ]; then
        printf '%s\n' "http://${host_ip}:11434"
      fi
      printf '%s\n' "http://host.docker.internal:11434"
      ;;
    wsl)
      printf '%s\n' "http://127.0.0.1:11434" "http://localhost:11434"
      ;;
    windows)
      if [ -n "$host_ip" ]; then
        printf '%s\n' "http://${host_ip}:11434"
      fi
      printf '%s\n' "http://host.docker.internal:11434"
      ;;
    *)
      fail "unknown Ollama mode: ${OLLAMA_MODE} (expected auto, wsl, windows)"
      ;;
  esac
}

probe_ollama() {
  local base
  if [ -n "${OLLAMA_HOST:-}" ]; then
    base="${OLLAMA_HOST%/}"
    case "$base" in
      http://*|https://*) ;;
      *) base="http://${base}" ;;
    esac
    if curl -fsS --max-time 3 "${base}/api/tags" >/dev/null 2>&1; then
      printf '%s\n' "$base"
      return 0
    fi
  fi

  while IFS= read -r base; do
    [ -n "$base" ] || continue
    if curl -fsS --max-time 3 "${base}/api/tags" >/dev/null 2>&1; then
      printf '%s\n' "$base"
      return 0
    fi
  done < <(ollama_hosts)

  return 1
}

install_base_packages() {
  log "updating apt metadata"
  sudo apt update
  sudo apt install -y curl git gh

  if ! command -v node >/dev/null 2>&1; then
    log "installing Node.js"
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt install -y nodejs
  fi
}

install_codex() {
  if command -v codex >/dev/null 2>&1; then
    log "codex already installed"
  else
    log "installing codex CLI"
    sudo npm install -g @openai/codex
  fi
}

install_ollama_in_wsl() {
  if command -v ollama >/dev/null 2>&1; then
    log "ollama CLI already installed"
    return
  fi
  log "installing ollama in WSL"
  curl -fsSL https://ollama.com/install.sh | sh
}

ensure_model_present() {
  need_cmd ollama
  if ollama list | awk '{print $1}' | grep -qx "$MODEL"; then
    log "model present: $MODEL"
  else
    log "pulling model: $MODEL"
    ollama pull "$MODEL"
  fi
}

validate_codex_backend() {
  codex --version >/dev/null
  gh --version >/dev/null
  if ! codex login status >/dev/null 2>&1; then
    fail "codex is installed but not authenticated; run: codex login"
  fi
}

validate_codex_oss_backend() {
  local base
  base="$(probe_ollama)" || fail "unable to reach Ollama; start it in WSL or on the Windows host, or set OLLAMA_HOST"
  export OLLAMA_HOST="$base"
  log "using Ollama at ${OLLAMA_HOST}"

  ensure_model_present
  codex --version >/dev/null
  codex exec --oss --local-provider ollama --full-auto -C "$PWD" "Reply with exactly: OK" >/dev/null
}

main() {
  need_cmd bash
  install_base_packages
  install_codex

  if is_wsl; then
    log "detected WSL"
  else
    log "running outside WSL"
  fi

  case "$BACKEND" in
    codex)
      validate_codex_backend
      ;;
    codex-oss)
      if ! command -v ollama >/dev/null 2>&1; then
        install_ollama_in_wsl
      fi
      if [ "$OLLAMA_MODE" = "wsl" ] || { [ "$OLLAMA_MODE" = "auto" ] && ! probe_ollama >/dev/null 2>&1; }; then
        install_ollama_in_wsl
      fi
      validate_codex_oss_backend
      ;;
    *)
      fail "unknown backend: ${BACKEND} (expected codex or codex-oss)"
      ;;
  esac

  log "setup complete for backend: ${BACKEND}"
}

main "$@"
