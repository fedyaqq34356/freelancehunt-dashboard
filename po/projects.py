import html
from dataclasses import dataclass, field
from typing import Optional

from .catalog import Case
from .text import clip, strip_html


@dataclass
class Project:
    id: int
    name: str
    description: str = ""
    amount: Optional[float] = None
    currency: str = ""
    bid_count: int = 0
    skills: list[str] = field(default_factory=list)
    url: str = ""
    employer: str = ""
    employer_name: str = ""
    plus_only: bool = False
    status: str = ""

    @property
    def budget(self) -> str:
        if not self.amount:
            return "бюджет не указан"
        return f"{int(self.amount):,} {self.currency}".replace(",", " ")

    @property
    def search_text(self) -> str:
        return f"{self.name} {self.name} {' '.join(self.skills)} {self.description}"


def parse_project(item: dict) -> Project:
    a = item.get("attributes") or {}
    budget = a.get("budget") or {}
    emp = a.get("employer") or {}
    links = (item.get("links") or {}).get("self") or {}
    pid = int(item["id"])
    status = a.get("status")
    return Project(
        id=pid,
        name=strip_html(a.get("name") or ""),
        description=strip_html(a.get("description") or a.get("description_html") or ""),
        amount=float(budget["amount"]) if budget.get("amount") else None,
        currency=budget.get("currency") or "",
        bid_count=int(a.get("bid_count") or 0),
        skills=[s.get("name", "") for s in a.get("skills") or [] if isinstance(s, dict)],
        url=(links.get("web") if isinstance(links, dict) else "") or f"https://freelancehunt.com/project/{pid}.html",
        employer=" ".join(x for x in (emp.get("first_name"), emp.get("last_name")) if x) or emp.get("login", ""),
        employer_name=(emp.get("first_name") or "").strip(),
        plus_only=bool(a.get("is_only_for_plus")),
        status=(status or {}).get("name", "") if isinstance(status, dict) else str(status or ""),
    )


def passes(p: Project, min_budget: int) -> bool:
    """Проекты без бюджета пропускаем всегда, с бюджетом в гривнах режем по минимуму."""
    if not min_budget or not p.amount:
        return True
    if p.currency.upper() not in ("UAH", "₴", ""):
        return True
    return p.amount >= min_budget


def card(p: Project, match: Optional[Case] = None) -> str:
    e = html.escape
    lines = [f"<b>{e(p.name)}</b>"]
    meta = [f"💰 {e(p.budget)}", f"ставок: {p.bid_count}"]
    if p.plus_only:
        meta.append("Plus")
    lines.append(" · ".join(meta))
    if p.skills:
        lines.append(f"<i>{e(', '.join(p.skills))}</i>")
    if p.description:
        lines.append("")
        lines.append(e(clip(p.description, 450)))
    if match:
        lines.append("")
        lines.append(f"🎯 Похоже на твоё: {e(clip(match.title, 70))}")
    return "\n".join(lines)
