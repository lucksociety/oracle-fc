"""Auditable experiment log (append-only JSONL) and champion/challenger registry."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess

from . import __version__, config
from .governance import now_utc_iso


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "uncommitted"


def log_experiment(kind: str, payload: dict) -> dict:
    rec = {"ts": now_utc_iso(), "kind": kind, "code_version": __version__, "git": _git_sha(),
           "python": platform.python_version(), **payload}
    rec["id"] = hashlib.sha1(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()[:12]
    config.EXPERIMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(config.EXPERIMENT_LOG, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def load_registry() -> dict:
    if config.REGISTRY_PATH.exists():
        return json.loads(config.REGISTRY_PATH.read_text())
    return {}


def save_registry(reg: dict) -> None:
    config.REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = load_registry().get("history", [])
    if reg.get("champion"):
        history.append({"ts": now_utc_iso(), "champion": reg["champion"].get("name"),
                        "version": reg["champion"].get("version")})
    reg["history"] = history[-50:]
    config.REGISTRY_PATH.write_text(json.dumps(reg, indent=2, default=str))
