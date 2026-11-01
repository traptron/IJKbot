"""Role detection for multi-machine setups (AI vs Operator vs All)."""

from typing import Optional
import json
import urllib.request
import urllib.error


def is_ollama_available(host: str = "http://localhost:11434", timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                return "models" in data
    except Exception:
        pass
    return False


def resolve_role(requested_role: str = "auto", mock: bool = False, is_local: bool = False) -> str:
    """
    Resolve role to 'ai', 'operator', or 'all'.
    """
    if requested_role in ("all", "ai", "operator"):
        return requested_role

    # In mock or local mode, single laptop handles everything
    if mock or is_local:
        return "all"

    # Auto-detect: if this laptop has Ollama running, it can serve as AI or All.
    # By default, a single user running ./ijk wants the full experience ('all').
    return "all"

