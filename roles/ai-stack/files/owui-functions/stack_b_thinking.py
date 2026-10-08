"""
title: Stack B Thinking
author: nucybersec
version: 1.0.0
description: Toggle in the chat bar. On: Qwen thinks (enable_thinking) and gpt-oss uses the chosen reasoning effort. Off: direct answers (the gateway default).
"""
from pydantic import BaseModel, Field
from typing import Optional


class Filter:
    class Valves(BaseModel):
        EFFORT: str = Field(
            default="high",
            description="gpt-oss reasoning effort when the toggle is on: low, medium or high. Qwen has no levels, only on/off.",
        )
        ONLY_STACK_B: bool = Field(
            default=True,
            description="Apply only to models whose id starts with stack-b/.",
        )

    class UserValves(BaseModel):
        EFFORT: Optional[str] = Field(
            default=None,
            description="Per-user override of the gpt-oss effort: low, medium or high.",
        )

    def __init__(self):
        self.valves = self.Valves()
        # A toggle filter shows as a button beside the chat input; the user turns
        # thinking on per conversation. Nothing happens unless it is on.
        self.toggle = True
        self.icon = (
            "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIg"
            "ZmlsbD0ibm9uZSIgc3Ryb2tlPSJjdXJyZW50Q29sb3IiIHN0cm9rZS13aWR0aD0iMiI+PHBhdGggZD0iTTEyIDJhNyA3IDAgMCAwLTQgMTIu"
            "OFYxN2gyLjVsMS41IDNoMGwxLjUtM0gxNnYtMi4yQTcgNyAwIDAgMCAxMiAyeiIvPjwvc3ZnPg=="
        )

    def inlet(self, body: dict, __user__: Optional[dict] = None, __model__: Optional[dict] = None) -> dict:
        model = str(body.get("model") or (__model__ or {}).get("id") or "")
        if self.valves.ONLY_STACK_B and not model.startswith("stack-b/"):
            return body
        effort = self.valves.EFFORT
        uv = (__user__ or {}).get("valves")
        if uv is not None and getattr(uv, "EFFORT", None):
            effort = uv.EFFORT
        if effort not in ("low", "medium", "high"):
            effort = "high"
        if "cand-a" in model:
            body["reasoning_effort"] = effort
        else:
            body["chat_template_kwargs"] = {"enable_thinking": True}
        return body
