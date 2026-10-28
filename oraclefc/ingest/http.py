"""Small polite HTTP helper with an on-disk cache (data/raw/... is gitignored)."""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36 ORACLE-FC research (github.com/lucksociety/oracle-fc)")
_S = requests.Session()
_S.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})


def get_json(url: str, cache: Path | None = None, max_age_h: float | None = None, headers: dict | None = None,
             retries: int = 4, timeout: float = 30.0, params: dict | None = None):
    """GET JSON with retries/backoff. If ``cache`` is given and fresh (or max_age_h is None and it
    exists), return the cached body. Returns None on persistent failure (never fabricates)."""
    if cache is not None and cache.exists():
        age_h = (time.time() - cache.stat().st_mtime) / 3600
        if max_age_h is None or age_h <= max_age_h:
            try:
                return json.loads(cache.read_text())
            except Exception:
                pass
    last = None
    for i in range(retries):
        try:
            r = _S.get(url, headers=headers, timeout=timeout, params=params)
            if r.status_code == 200:
                data = r.json()
                if cache is not None:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(data))
                return data
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404, 405, 401):
                break
        except Exception as e:  # network / JSON errors
            last = repr(e)
        time.sleep((2 ** i) + random.random())
    print(f"   ! GET failed {url}: {last}", flush=True)
    return None
