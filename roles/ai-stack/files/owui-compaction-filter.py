"""
title: Context Compaction
author: aicortex
description: Model-aware conversation compaction. When chat history exceeds a
    percentage of the selected model's context window, keep the first/last N
    turns verbatim and replace the middle with a cached summary. Storage is
    never mutated — only the request body sent to the model.
version: 0.1.0
requirements: httpx
"""

import hashlib
import json

import httpx
from pydantic import BaseModel, Field

LITELLM_URL = "http://localhost:4000"


def est_tokens(text: str) -> int:
    """Heuristic token count: ~4 chars/token with a 15% safety margin."""
    return round(len(text or "") / 4 * 1.15)


def est_messages_tokens(msgs: list) -> int:
    return sum(est_tokens(m.get("content", "") or "") for m in msgs)


def compute_budget(window: int, overhead: int, v: dict) -> dict:
    reserve = max(v["min_output_reserve"], int(v["output_reserve_pct"] * window))
    usable = max(0, window - reserve - overhead)
    target = min(int(v["history_target_pct"] * window), v["history_abs_cap"])
    trigger = max(0, min(int(v["history_trigger_pct"] * window), v["history_abs_cap"], usable))
    return {"reserve": reserve, "usable": usable, "target": target, "trigger": trigger}


def compact(convo: list, recap_text: str, first_n: int, last_n: int, target: int) -> list:
    """Keep first_n + last_n turns verbatim; replace the middle with one system
    recap. Shrinks the tail toward `target` tokens. No-op if there's no middle.
    `last_n` must be >= 1 (enforced by the Filter Valve) so the recap is always
    followed by at least one real turn rather than ending the prompt."""
    if len(convo) <= first_n + last_n:
        return convo
    head = convo[:first_n]
    tail = convo[len(convo) - last_n:] if last_n else []
    recap_msg = {"role": "system",
                 "content": f"Summary of earlier conversation:\n{recap_text}"}
    rebuilt = head + [recap_msg] + tail
    while est_messages_tokens(rebuilt) > target and len(tail) > 1:
        tail = tail[1:]
        rebuilt = head + [recap_msg] + tail
    return rebuilt


def parse_window(info_json: dict, model: str, fallback: int) -> int:
    for m in info_json.get("data", []):
        if m.get("model_name") == model:
            mi = m.get("model_info") or {}
            w = mi.get("max_input_tokens") or mi.get("max_tokens")
            if w:
                return int(w)
    return fallback


class Filter:
    class Valves(BaseModel):
        enabled: bool = Field(default=True)
        litellm_url: str = Field(default=LITELLM_URL, description="LiteLLM base URL")
        output_reserve_pct: float = Field(default=0.25, ge=0.0, le=0.9)
        min_output_reserve: int = Field(default=4096, ge=0)
        history_target_pct: float = Field(default=0.10, ge=0.0, le=1.0)
        history_trigger_pct: float = Field(default=0.15, ge=0.0, le=1.0)
        history_abs_cap: int = Field(default=65536, ge=1)
        first_n: int = Field(default=3, ge=0)
        last_n: int = Field(default=9, ge=1)
        window_fallback: int = Field(default=131072, ge=1)
        summary_model: str = Field(default="gemini-3.0-flash-lite")
        scope: str = Field(default="all", description='"all" or "voice"')

    def __init__(self):
        self.valves = self.Valves()
        self._recap_cache: dict[str, str] = {}
        self._window_cache: dict[str, int] = {}

    def _v(self) -> dict:
        return self.valves.model_dump()

    def _model_window(self, model: str) -> int:
        if model in self._window_cache:
            return self._window_cache[model]
        window = self.valves.window_fallback
        try:
            r = httpx.get(f"{self.valves.litellm_url}/model/info", timeout=5)
            r.raise_for_status()
            window = parse_window(r.json(), model, self.valves.window_fallback)
        except Exception:
            pass
        self._window_cache[model] = window
        return window

    def _summarize(self, mid: list) -> str:
        excerpt = "\n".join(f"{m.get('role')}: {m.get('content','')}" for m in mid)
        prompt = ("Summarize the following conversation excerpt, preserving facts, "
                  "decisions, names, and open questions. Be concise.\n\n" + excerpt)
        r = httpx.post(
            f"{self.valves.litellm_url}/v1/chat/completions",
            json={"model": self.valves.summary_model,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        try:
            if not self.valves.enabled:
                return body
            msgs = body.get("messages", []) or []
            sys_msgs = [m for m in msgs if m.get("role") == "system"]
            convo = [m for m in msgs if m.get("role") != "system"]

            window = self._model_window(body.get("model", "") or "")
            overhead = est_messages_tokens(sys_msgs)
            b = compute_budget(window, overhead, self._v())
            if est_messages_tokens(convo) <= b["trigger"]:
                return body  # under budget → verbatim

            fn, ln = self.valves.first_n, self.valves.last_n
            if len(convo) <= fn + ln:
                return body  # no middle to compress
            mid = convo[fn:len(convo) - ln]
            key = hashlib.sha256(json.dumps(mid, sort_keys=True).encode()).hexdigest()
            recap = self._recap_cache.get(key)
            if recap is None:
                recap = self._summarize(mid)
                if not recap:
                    return body  # empty summary → pass verbatim
                self._recap_cache[key] = recap
            body["messages"] = sys_msgs + compact(convo, recap, fn, ln, b["target"])
            return body
        except Exception:
            return body  # fail-open: never break a chat
