"""Точный и быстрый подбор работы под проект для карточки.

Один раз на каждую работу: короткое описание задачи (LLM) и эмбеддинг, всё в кеше на диске.
На каждый проект: эмбеддинг проекта, 6 ближайших работ, быстрая модель выбирает одну или «нет».
"""
import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Optional

from .catalog import Case, render_for_prompt
from .projects import Project
from .text import clip

log = logging.getLogger(__name__)

SHORTLIST = 6

SUMMARY_RULES = (
    "Для каждой работы одно предложение на русском: какую задачу заказчика она решает и с какими данными "
    "и сервисами работает. Без оценок и отзывов, 15-30 слов. ref копируй как есть, без скобок."
)
SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"ref": {"type": "string"}, "task": {"type": "string"}},
                "required": ["ref", "task"],
            },
        }
    },
    "required": ["items"],
}

PICK_RULES = (
    "Выбери из списка одну работу фрилансера, которая решает ту же задачу, что нужна заказчику в проекте: "
    "тот же тип системы и те же данные. Совпадение темы (например, автозапчасти) без совпадения задачи не считается. "
    "Если ни одна не решает похожую задачу, ref = \"none\". why: до 12 слов, чем именно похожа, на русском."
)
PICK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"ref": {"type": "string"}, "why": {"type": "string"}},
    "required": ["ref", "why"],
}


def _key(c: Case) -> str:
    return hashlib.sha1(f"{c.ref}|{c.title}|{c.text}".encode()).hexdigest()[:16]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Matcher:
    def __init__(self, llm, path: str):
        self.llm = llm
        self.path = Path(path)
        self.index: dict[str, dict] = {}
        if self.path.exists():
            try:
                self.index = json.loads(self.path.read_text())
            except ValueError:
                self.index = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.index))

    async def prepare(self, cases: list[Case]) -> None:
        missing = [c for c in cases if _key(c) not in self.index]
        if not missing:
            return
        for i in range(0, len(missing), 40):
            chunk = missing[i : i + 40]
            out = await self.llm.json(
                instructions=SUMMARY_RULES, prompt=render_for_prompt(chunk), schema=SUMMARY_SCHEMA,
                name="summaries", effort="none", max_tokens=6000,
            )
            tasks = {str(it["ref"]).strip("[] "): it["task"] for it in out.get("items") or []}
            texts = [f"{c.title}. {tasks.get(c.ref) or clip(c.text, 300)}" for c in chunk]
            vectors = await self.llm.embed(texts)
            for c, t, v in zip(chunk, texts, vectors):
                self.index[_key(c)] = {"task": t, "vec": [round(x, 5) for x in v]}
        self._save()
        log.info("индекс работ: добавлено %d", len(missing))

    def task(self, c: Case) -> str:
        return (self.index.get(_key(c)) or {}).get("task", c.title)

    async def best(self, project: Project, cases: list[Case]) -> Optional[tuple[Case, str]]:
        await self.prepare(cases)
        q = (await self.llm.embed([clip(f"{project.name}. {project.description}", 2000)]))[0]
        ranked = sorted(cases, key=lambda c: -cosine(q, self.index[_key(c)]["vec"]))[:SHORTLIST]
        listing = "\n".join(f"[{c.ref}] {self.task(c)}" for c in ranked)
        prompt = f"ПРОЕКТ\n{project.name}\n{clip(project.description, 1500)}\n\nРАБОТЫ\n{listing}"
        out = await self.llm.json(
            instructions=PICK_RULES, prompt=prompt, schema=PICK_SCHEMA, name="pick", effort="none", max_tokens=300
        )
        ref = str(out.get("ref", "")).strip("[] ")
        by_ref = {c.ref: c for c in ranked}
        if ref in by_ref:
            return by_ref[ref], out.get("why", "")
        return None
