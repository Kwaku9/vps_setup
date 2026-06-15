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
    usable = window - reserve - overhead
    target = min(int(v["history_target_pct"] * window), v["history_abs_cap"])
    trigger = min(int(v["history_trigger_pct"] * window), v["history_abs_cap"], usable)
    return {"reserve": reserve, "usable": usable, "target": target, "trigger": trigger}


def compact(convo: list, recap_text: str, first_n: int, last_n: int, target: int) -> list:
    """Keep first_n + last_n turns verbatim; replace the middle with one system
    recap. Shrinks the tail toward `target` tokens. No-op if there's no middle."""
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
