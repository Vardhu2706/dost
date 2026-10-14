"""Sarvam chat completions (OpenAI-style, POST /v1/chat/completions)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"


class SarvamLLM:
    def __init__(self, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            headers={"api-subscription-key": api_key}, timeout=timeout
        )

    def _body(self, messages: list[dict], **extra: object) -> dict:
        # Thinking is on by default ("low"); null disables it for low-latency voice turns.
        return {"model": self.model, "messages": messages, "reasoning_effort": None, **extra}

    async def stream(self, messages: list[dict], max_tokens: int = 300) -> AsyncIterator[str]:
        body = self._body(messages, stream=True, max_tokens=max_tokens)
        async with self._client.stream("POST", CHAT_URL, json=body) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"LLM {resp.status_code}: {(await resp.aread()).decode()}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    return
                chunk = json.loads(data)
                for choice in chunk.get("choices", []):
                    text = choice.get("delta", {}).get("content")
                    if text:
                        yield text

    async def complete(self, messages: list[dict], max_tokens: int = 500) -> str:
        resp = await self._client.post(
            CHAT_URL, json=self._body(messages, max_tokens=max_tokens)
        )
        if resp.status_code != 200:
            raise RuntimeError(f"LLM {resp.status_code}: {resp.text}")
        return resp.json()["choices"][0]["message"]["content"] or ""

    async def json(self, messages: list[dict], max_tokens: int = 500) -> dict:
        """Ask for a JSON object and parse it (tolerates ```json fences)."""
        text = (await self.complete(messages, max_tokens)).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start : end + 1])

    async def aclose(self) -> None:
        await self._client.aclose()
