import json
import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)


class LLM(Protocol):
    async def json(self, *, instructions: str, prompt: str, schema: dict, name: str,
                   effort: str = "low", max_tokens: int = 1500) -> dict[str, Any]: ...


class OpenAILLM:
    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def json(self, *, instructions: str, prompt: str, schema: dict, name: str,
                   effort: str = "low", max_tokens: int = 1500) -> dict[str, Any]:
        extra: dict[str, Any] = {"reasoning": {"effort": effort}} if effort else {}
        r = await self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=prompt,
            max_output_tokens=max_tokens,
            store=False,
            text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
            **extra,
        )
        u = r.usage
        if u:
            log.info("llm %s: in=%s out=%s", name, u.input_tokens, u.output_tokens)
        return json.loads(r.output_text)
