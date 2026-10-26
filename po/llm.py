import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Any, Optional, Protocol

log = logging.getLogger(__name__)

PRICES = {"in": 0.10, "cached": 0.01, "out": 0.50, "embed": 0.02}
_bucket: ContextVar[Optional[list]] = ContextVar("po_cost_bucket", default=None)


class Meter:
    """Считает деньги за вызовы: по дням в state["usage"] и по текущей операции (ставка, карточка)."""

    def __init__(self, state=None, prices: Optional[dict] = None):
        self.state = state
        self.prices = {**PRICES, **(prices or {})}

    def _day(self) -> dict:
        if self.state is None:
            return {}
        usage = self.state.data.setdefault("usage", {})
        return usage.setdefault(date.today().isoformat(), {"usd": 0.0, "bids": 0, "cards": 0})

    def record(self, tokens_in: int = 0, cached: int = 0, tokens_out: int = 0, embed: int = 0) -> float:
        p = self.prices
        usd = ((tokens_in - cached) * p["in"] + cached * p["cached"] + tokens_out * p["out"] + embed * p["embed"]) / 1e6
        day = self._day()
        if day:
            day["usd"] = day.get("usd", 0.0) + usd
        bucket = _bucket.get()
        if bucket is not None:
            bucket.append(usd)
        return usd

    @contextmanager
    def measure(self, label: str):
        bucket: list = []
        token = _bucket.set(bucket)
        try:
            yield bucket
        finally:
            _bucket.reset(token)
            day = self._day()
            if day:
                day[label] = day.get(label, 0) + 1
                day[f"{label}_usd"] = day.get(f"{label}_usd", 0.0) + sum(bucket)

    def summary(self, days: int = 30) -> dict:
        usage = (self.state.data.get("usage") if self.state else None) or {}
        keys = sorted(usage)[-days:]
        total = {"usd": 0.0, "bids": 0, "cards": 0, "bids_usd": 0.0, "cards_usd": 0.0}
        for k in keys:
            for f in total:
                total[f] += usage[k].get(f, 0)
        today = usage.get(date.today().isoformat(), {})
        return {"days": days, "today_usd": today.get("usd", 0.0), **total}


class LLM(Protocol):
    async def json(self, *, instructions: str, prompt: str, schema: dict, name: str,
                   effort: str = "low", max_tokens: int = 1500) -> dict[str, Any]: ...


class OpenAILLM:
    def __init__(self, api_key: str, model: str, meter: Optional[Meter] = None, embed_model: str = "text-embedding-3-small"):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.embed_model = embed_model
        self.meter = meter or Meter()

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
            cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
            usd = self.meter.record(u.input_tokens, cached, u.output_tokens)
            log.info("llm %s: in=%s out=%s $%.5f", name, u.input_tokens, u.output_tokens, usd)
        try:
            return json.JSONDecoder().raw_decode(r.output_text.strip())[0]
        except ValueError:
            if max_tokens >= 8000:
                raise
            log.warning("llm %s: ответ обрезан, повторяю с большим лимитом", name)
            return await self.json(
                instructions=instructions, prompt=prompt, schema=schema, name=name, effort=effort, max_tokens=max_tokens * 2
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            r = await self.client.embeddings.create(model=self.embed_model, input=texts[i : i + 100])
            self.meter.record(embed=r.usage.total_tokens if r.usage else 0)
            out.extend(d.embedding for d in r.data)
        return out
