"""Места в рейтинге: место из API, размер категории по умолчанию со страницы профиля (Cloudflare не даёт читать её роботом)."""
from typing import Optional

from .projects import Project

TOTALS = {180: 2692, 169: 949, 175: 2669, 99: 7147, 22: 4898}
OVERALL_TOTAL = 292101
STRONG = 20
SHORT = {"AI и машинное обучение": "AI", "Разработка ботов": "ботов", "Парсинг данных": "парсинга", "Веб-программирование": "веб"}


def positions(profile: dict, totals: Optional[dict] = None) -> list[tuple[str, int, Optional[int]]]:
    return [(name, pos, total) for _, name, pos, total in _positions(profile, totals)]


def _positions(profile: dict, totals: Optional[dict] = None) -> list[tuple[Optional[int], str, int, Optional[int]]]:
    t = {**TOTALS, **(totals or {})}
    out = []
    for sk in (profile.get("attributes") or {}).get("skills") or []:
        if isinstance(sk, dict) and sk.get("rating_position"):
            out.append((sk.get("id"), sk.get("name", ""), int(sk["rating_position"]), t.get(sk.get("id"))))
    return out


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def strong_fact(project: Project, profile: dict, totals: Optional[dict] = None) -> str:
    """Лучшее место в категории этого проекта, если оно в топ-20. Категорию сверяем по id: API отдаёт названия на разных языках."""
    best = None
    for sid, name, pos, total in _positions(profile, totals):
        same = (sid is not None and sid in project.skill_ids) or name in project.skills
        if same and 0 < pos <= STRONG and (best is None or pos < best[1]):
            best = (name, pos, total)
    if not best:
        return ""
    name, pos, total = best
    of = f" из {fmt(total)}" if total else ""
    return f"{pos} место{of} в рейтинге категории «{name}» на Freelancehunt"
