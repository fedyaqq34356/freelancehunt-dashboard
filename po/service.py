"""Работа с Freelancehunt: кеш кейсов, лента проектов, входящие."""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from freelancehunt.client import FreelancehuntClient, FreelancehuntError

from .catalog import Case, parse_portfolio, parse_reviews
from .projects import Project, parse_project, passes
from .ranks import fmt, positions
from .text import clip, slugify, strip_html
from .state import State

log = logging.getLogger(__name__)

MAX_PAGES = 10


def select_new(items: list[dict], state: State) -> list[Project]:
    """Новые проекты из выдачи, от старых к новым, с учётом паузы и мин. бюджета."""
    fresh = []
    for item in items:
        try:
            p = parse_project(item)
        except (KeyError, ValueError, TypeError):
            continue
        if not state.mark("seen_project_ids", p.id):
            continue
        if state["paused"] or not passes(p, state["min_budget"]):
            continue
        fresh.append(p)
    return list(reversed(fresh))


def profile_facts(profile: dict) -> str:
    a = profile.get("attributes") or {}
    lines = []
    if a.get("completed_projects"):
        lines.append(f"Завершённых проектов на Freelancehunt: {a['completed_projects']}")
    if a.get("positive_reviews"):
        neg = a.get("negative_reviews") or 0
        lines.append(f"Отзывы: {a['positive_reviews']} положительных, {neg} отрицательных")
    if a.get("average_grade"):
        lines.append(f"Средняя оценка: {a['average_grade']} из 10")
    for name, pos, total in positions(profile):
        lines.append(f"Место в рейтинге категории «{name}»: {pos}" + (f" из {fmt(total)}" if total else ""))
    return "\n".join(lines)


class Service:
    def __init__(self, client: FreelancehuntClient, state: State, catalog_ttl: int = 6 * 3600):
        self.client = client
        self.state = state
        self.catalog_ttl = catalog_ttl
        self._cases: list[Case] = []
        self._cases_at = 0.0
        self._lock = asyncio.Lock()
        self._profile: dict = {}
        self._profile_at = 0.0

    async def call(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def my_id(self) -> int:
        if not self.state["my_id"]:
            await self.profile(force=True)
        return self.state["my_id"]

    async def _all_pages(self, fn: Callable[..., dict], *args) -> list[dict]:
        items: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            payload = await self.call(fn, *args, page=page)
            items.extend(payload.get("data") or [])
            if not (payload.get("links") or {}).get("next"):
                break
        return items

    async def cases(self, force: bool = False) -> list[Case]:
        async with self._lock:
            if self._cases and not force and time.time() - self._cases_at < self.catalog_ttl:
                return self._cases
            me = await self.my_id()
            reviews = parse_reviews({"data": await self._all_pages(self.client.reviews, me)})
            portfolio = parse_portfolio({"data": await self._all_pages(self.client.portfolio, me)})
            await self._mark_public(reviews)
            self._cases = reviews + portfolio
            self._cases_at = time.time()
            log.info("кейсы обновлены: %d отзывов, %d работ", len(reviews), len(portfolio))
            return self._cases

    async def _mark_public(self, reviews: list[Case]) -> None:
        """Личные проекты API не отдаёт (404): их нельзя приложить как «Пример проекта» и дать ссылку.
        У публичных берём ссылку и описание задачи, чтобы подбирать по сути, а не по названию."""
        known = self.state.data.setdefault("project_info", {})
        for c in reviews:
            if not c.project_id:
                continue
            key = str(c.project_id)
            if key not in known:
                try:
                    data = (await self.call(self.client.project, c.project_id))["data"]
                    attrs = data.get("attributes") or {}
                    known[key] = {
                        "url": ((data.get("links") or {}).get("self") or {}).get("web") or "",
                        "desc": clip(strip_html(attrs.get("description") or attrs.get("description_html") or ""), 900),
                    }
                except FreelancehuntError as e:
                    if e.status != 404:
                        continue
                    known[key] = None
            info = known[key]
            c.public = info is not None
            if info is None:
                c.url = f"https://freelancehunt.com/project/{slugify(c.title)}/{c.project_id}.html"
            if info:
                c.url = info.get("url") or c.url
                if info.get("desc") and not c.text:
                    c.text = info["desc"]
                    c.__post_init__()
        self.state.save()

    async def profile(self, force: bool = False) -> dict:
        if force or not self._profile or time.time() - self._profile_at > self.catalog_ttl:
            self._profile = (await self.call(self.client.my_profile))["data"]
            self._profile_at = time.time()
            if not self.state["my_id"]:
                self.state["my_id"] = self._profile["id"]
                self.state.save()
        return self._profile

    async def past_clients(self) -> set[int]:
        return {c.client_id for c in await self.cases() if c.client_id}

    async def bid_stats(self, days: int = 30) -> dict:
        """Ставки за последние N дней: всего, сколько выиграно."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        total = won = 0
        for page in range(1, 40):
            r = await self.call(self.client.get, "/my/bids", {"page[number]": page})
            stop = False
            for b in r.get("data") or []:
                a = b["attributes"]
                if datetime.fromisoformat(a["published_at"]) < since:
                    stop = True
                    continue
                total += 1
                won += bool(a.get("is_winner"))
            if stop or not (r.get("links") or {}).get("next"):
                break
        return {"days": days, "total": total, "won": won}

    async def facts(self) -> str:
        return profile_facts(await self.profile())

    async def latest_projects(self) -> list[dict]:
        skills = (await self.profile()).get("attributes", {}).get("skills") or []
        ids = ",".join(str(x["id"]) for x in skills if isinstance(x, dict) and x.get("id"))
        return (await self.call(self.client.projects, 1, {"skill_id": ids} if ids else None))["data"]

    async def new_projects(self) -> list[Project]:
        items = await self.latest_projects()
        if not self.state["projects_initialized"]:
            for item in items:
                self.state.mark("seen_project_ids", int(item["id"]))
            self.state["projects_initialized"] = True
            self.state.save()
            return []
        fresh = select_new(items, self.state)
        self.state.save()
        return fresh

    async def project(self, pid: int) -> Project:
        return parse_project((await self.call(self.client.project, pid))["data"])
