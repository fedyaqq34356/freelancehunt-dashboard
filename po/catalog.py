"""Мои кейсы: работы из портфолио и завершённые проекты с отзывами."""
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from .text import clip, stems, strip_html


@dataclass
class Case:
    ref: str
    kind: str  # "portfolio" | "review"
    title: str
    text: str = ""
    skill: str = ""
    url: str = ""
    budget: str = ""
    review: str = ""
    grade: Optional[float] = None
    client_id: Optional[int] = None
    client_name: str = ""
    date: str = ""
    project_id: Optional[int] = None
    public: Optional[bool] = None
    _stems: set = field(default_factory=set, repr=False)

    def __post_init__(self):
        self._stems = stems(f"{self.title} {self.skill} {self.text}")


def _web_link(item: dict) -> str:
    links = item.get("links") or {}
    self_link = links.get("self")
    if isinstance(self_link, dict):
        return self_link.get("web") or ""
    if isinstance(self_link, str) and "api." not in self_link:
        return self_link
    return (item.get("attributes") or {}).get("url") or ""


def _money(b: Any) -> str:
    if isinstance(b, dict) and b.get("amount"):
        return f"{int(float(b['amount'])):,} {b.get('currency', '')}".replace(",", " ").strip()
    return ""


def parse_portfolio(payload: dict) -> list[Case]:
    out = []
    for item in payload.get("data") or []:
        a = item.get("attributes") or {}
        title = a.get("name") or a.get("title") or ""
        if not title:
            continue
        skill = a.get("skill")
        out.append(
            Case(
                ref=f"p{item.get('id')}",
                kind="portfolio",
                title=strip_html(title),
                text=strip_html(a.get("comment") or a.get("description") or a.get("description_html") or ""),
                skill=(skill or {}).get("name", "") if isinstance(skill, dict) else str(skill or ""),
                url=_web_link(item),
                budget=_money(a.get("budget")),
            )
        )
    return out


def parse_reviews(payload: dict) -> list[Case]:
    out = []
    for item in payload.get("data") or []:
        a = item.get("attributes") or {}
        project = a.get("project") or {}
        title = project.get("name") or a.get("project_name") or ""
        if not title:
            continue
        grades = a.get("grades") or {}
        grade = grades.get("total") if isinstance(grades, dict) else None
        out.append(
            Case(
                ref=f"r{item.get('id')}",
                kind="review",
                title=strip_html(title),
                text=strip_html(project.get("description") or ""),
                skill=", ".join(s.get("name", "") for s in project.get("skills") or [] if isinstance(s, dict)),
                url=(project.get("links") or {}).get("web", "") if isinstance(project.get("links"), dict) else "",
                budget=_money(project.get("budget") or a.get("budget")),
                review=strip_html(a.get("comment") or a.get("review") or a.get("text") or ""),
                grade=float(grade) if isinstance(grade, (int, float)) else None,
                client_id=(a.get("from") or {}).get("id"),
                client_name=" ".join(
                    x for x in ((a.get("from") or {}).get("first_name"), (a.get("from") or {}).get("last_name")) if x
                ),
                date=(a.get("published_at") or "")[:10],
                project_id=project.get("id"),
            )
        )
    return out


def idf(cases: list[Case]) -> dict[str, float]:
    df: dict[str, int] = {}
    for c in cases:
        for st in c._stems:
            df[st] = df.get(st, 0) + 1
    n = len(cases) or 1
    return {st: math.log((n + 1) / (k + 0.5)) for st, k in df.items()}


def score(query: set[str], case: Case, weights: Optional[dict[str, float]] = None) -> float:
    if not query or not case._stems:
        return 0.0
    w = weights or {}
    hit = sum(w.get(st, 1.0) for st in query & case._stems)
    bonus = 1.1 if case.kind == "review" else 1.0
    return hit / math.sqrt(len(case._stems)) * bonus


def best_matches(query_text: str, cases: list[Case], n: int = 3, min_score: float = 0.9) -> list[Case]:
    q = stems(query_text)
    w = idf(cases)
    ranked = sorted(((score(q, c, w), c) for c in cases), key=lambda t: t[0], reverse=True)
    return [c for s, c in ranked[:n] if s >= min_score]


def render_for_prompt(cases: list[Case]) -> str:
    """Компактный каталог для LLM: по одной строке на кейс."""
    lines = []
    for c in cases:
        parts = [f"[{c.ref}]", c.title]
        if c.skill:
            parts.append(f"({c.skill})")
        if c.budget:
            parts.append(f"бюджет {c.budget}")
        if c.text:
            parts.append("| " + clip(c.text, 500))
        if c.review:
            parts.append(f'| отзыв: "{clip(c.review, 160)}"')
        if c.kind == "review" and c.public is False:
            parts.append("| личный проект: в «Пример проекта» не приложить, ссылку не давать")
        lines.append(" ".join(parts))
    return "\n".join(lines)
