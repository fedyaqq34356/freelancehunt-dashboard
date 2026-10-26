"""Места в рейтинге: место из API, размер категории по умолчанию со страницы профиля (Cloudflare не даёт читать её роботом)."""
from typing import Optional

from .projects import Project

TOTALS = {180: 2689, 169: 949, 175: 2665, 99: 7147}
OVERALL_TOTAL = 291877
STRONG = 20
SHORT = {"AI и машинное обучение": "AI", "Разработка ботов": "ботов", "Парсинг данных": "парсинга", "Веб-программирование": "веб"}


def positions(profile: dict, totals: Optional[dict] = None) -> list[tuple[str, int, Optional[int]]]:
    t = {**TOTALS, **(totals or {})}
    out = []
    for sk in (profile.get("attributes") or {}).get("skills") or []:
        if isinstance(sk, dict) and sk.get("rating_position"):
            out.append((sk.get("name", ""), int(sk["rating_position"]), t.get(sk.get("id"))))
    return out


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def strong_fact(project: Project, profile: dict, totals: Optional[dict] = None) -> str:
    """Лучшее место в категории этого проекта, если оно в топ-20."""
    best = None
    for name, pos, total in positions(profile, totals):
        if name in project.skills and pos <= STRONG and (best is None or pos < best[1]):
            best = (name, pos, total)
    if not best:
        return ""
    name, pos, total = best
    of = f" из {fmt(total)}" if total else ""
    return f"{pos} место{of} в рейтинге категории «{name}» на Freelancehunt"
