"""После ставки: разбор проигрышей, напоминания молчащим заказчикам, повторные клиенты."""
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .catalog import Case
from .competitors import Rival
from .text import clip, strip_html

SYSTEM_SENDER = 4
LOSS = re.compile(r"выбрал(?:а)? другого исполнителя|обрав(?:ла)? іншого виконавця", re.I)
PROJECT_ID = re.compile(r"/project/[^\"']*?/(\d+)\.html")


NEW_PROJECT = re.compile(r"добавил(?:а)? проект|додав(?:ла)? проєкт", re.I)


def new_project_id(message: str, links: dict) -> Optional[int]:
    """Уведомление о новом проекте: id из ссылки API или из адреса в тексте."""
    if not NEW_PROJECT.search(message or ""):
        return None
    api = (links or {}).get("project") or ""
    m = re.search(r"/projects/(\d+)", api) or PROJECT_ID.search(message)
    return int(m.group(1)) if m else None


def loss_project_id(message: str) -> Optional[int]:
    if not LOSS.search(message or ""):
        return None
    m = PROJECT_ID.search(message)
    return int(m.group(1)) if m else None


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ---------- Разбор проигрыша ----------


@dataclass
class Loss:
    project_id: int
    project: str
    date: str
    winner: str = ""
    winner_projects: Optional[int] = None
    winner_rating: Optional[int] = None
    winner_plus: bool = False
    winner_amount: Optional[int] = None
    winner_days: Optional[int] = None
    winner_hidden: bool = False
    winner_text: str = ""
    my_amount: Optional[int] = None
    my_days: Optional[int] = None
    my_rating: Optional[int] = None
    bid_count: int = 0
    currency: str = "UAH"


def build_loss(project: dict, winner_profile: dict, winner_bid: Optional[Rival], my_bid: Optional[dict], my_rating: int) -> Loss:
    a = project.get("attributes") or {}
    w = (winner_profile or {}).get("attributes") or {}
    fr = a.get("freelancer") or {}
    mb = (my_bid or {}).get("attributes") or {}
    return Loss(
        project_id=int(project["id"]),
        project=a.get("name", ""),
        date=datetime.now(timezone.utc).date().isoformat(),
        winner=" ".join(x for x in (fr.get("first_name"), fr.get("last_name")) if x) or fr.get("login", ""),
        winner_projects=w.get("completed_projects"),
        winner_rating=w.get("rating"),
        winner_plus=bool(w.get("is_plus_active")),
        winner_amount=winner_bid.amount if winner_bid else None,
        winner_days=winner_bid.days if winner_bid else None,
        winner_hidden=bool(winner_bid and winner_bid.hidden),
        winner_text=winner_bid.text if winner_bid else "",
        my_amount=(mb.get("budget") or {}).get("amount"),
        my_days=mb.get("days"),
        my_rating=my_rating,
        bid_count=int(a.get("bid_count") or 0),
        currency=((a.get("budget") or {}).get("currency")) or "UAH",
    )


def loss_message(x: Loss) -> str:
    import html

    e = html.escape
    lines = [f"📉 <b>Выбрали другого</b>: {e(x.project)}", ""]
    who = f"Победил {e(x.winner) or 'исполнитель'}"
    if x.winner_projects is not None:
        who += f": {x.winner_projects} проектов, рейтинг {x.winner_rating}"
    if x.winner_plus:
        who += ", Plus"
    lines.append(who)
    if x.winner_amount or x.winner_days:
        lines.append(f"Его ставка: {x.winner_amount or '?'} {e(x.currency)}, {x.winner_days or '?'} дн." + (" Текст скрыт." if x.winner_hidden else ""))
    if x.my_amount or x.my_days:
        lines.append(f"Твоя: {x.my_amount or '?'} {e(x.currency)}, {x.my_days or '?'} дн. Рейтинг {x.my_rating}.")
    hints = []
    if x.winner_days and x.my_days and x.winner_days < x.my_days:
        hints.append("срок у него короче")
    if x.winner_amount and x.my_amount and x.winner_amount < x.my_amount:
        hints.append("цена у него ниже")
    if x.winner_hidden:
        hints.append("ставка скрыта")
    if x.winner_rating and x.my_rating and x.winner_rating < x.my_rating:
        hints.append("рейтинг у него ниже твоего, решил не профиль")
    if hints:
        lines.append("Заметно: " + ", ".join(hints) + ".")
    if x.winner_text:
        lines.append("")
        lines.append(f"<i>Его текст:</i> {e(clip(x.winner_text, 700))}")
    lines.append(f"\n<i>Ставок было {x.bid_count}. Перешли мне этот разбор, если хочешь поправить стиль.</i>")
    return "\n".join(lines)


def weekly_digest(losses: list[dict], my_stats: dict, today: Optional[datetime] = None) -> str:
    today = today or datetime.now(timezone.utc)
    since = (today - timedelta(days=7)).date().isoformat()
    week = [x for x in losses if x.get("date", "") >= since]
    lines = ["📊 <b>Неделя</b>", f"Ставок: {my_stats.get('total', 0)}, выиграно: {my_stats.get('won', 0)}"]
    if not week:
        lines.append("Разборов проигрышей за неделю нет.")
        return "\n".join(lines)
    lines.append(f"Проигрышей с известным победителем: {len(week)}")
    projects = [x["winner_projects"] for x in week if x.get("winner_projects") is not None]
    if projects:
        lines.append(f"У победителей медиана {int(statistics.median(projects))} проектов")
    weaker = sum(1 for x in week if x.get("winner_rating") and x.get("my_rating") and x["winner_rating"] < x["my_rating"])
    shorter = sum(1 for x in week if x.get("winner_days") and x.get("my_days") and x["winner_days"] < x["my_days"])
    cheaper = sum(1 for x in week if x.get("winner_amount") and x.get("my_amount") and x["winner_amount"] < x["my_amount"])
    hidden = sum(1 for x in week if x.get("winner_hidden"))
    lines.append(f"Рейтинг ниже твоего: {weaker}. Срок короче: {shorter}. Цена ниже: {cheaper}. Ставка скрыта: {hidden}.")
    lines.append("<i>Перешли мне эту сводку, разберём, что поменять.</i>")
    return "\n".join(lines)


# ---------- Напоминания ----------


def last_real_message(messages: list[dict]) -> Optional[dict]:
    real = [m for m in messages if ((m["attributes"].get("participants") or {}).get("from") or {}).get("id") != SYSTEM_SENDER]
    return max(real, key=lambda m: m["attributes"]["posted_at"]) if real else None


def stale_thread(thread: dict, messages: list[dict], my_id: int, now: datetime, min_hours: int = 24, max_days: int = 14) -> Optional[dict]:
    """Последнее живое сообщение моё, прошло больше суток, заказчик после него заходил и не ответил."""
    last = last_real_message(messages)
    if not last:
        return None
    sender = ((last["attributes"].get("participants") or {}).get("from") or {}).get("id")
    if sender != my_id:
        return None
    posted = parse_time(last["attributes"]["posted_at"])
    age = now - posted
    if age < timedelta(hours=min_hours) or age > timedelta(days=max_days):
        return None
    parts = thread["attributes"].get("participants") or {}
    client = parts.get("from") if (parts.get("from") or {}).get("id") != my_id else parts.get("to")
    visited = (client or {}).get("visited_at")
    if not visited or parse_time(visited) <= posted:
        return None
    return {
        "thread_id": thread["id"],
        "message_id": last["id"],
        "subject": thread["attributes"].get("subject", ""),
        "client": " ".join(x for x in ((client or {}).get("first_name"), (client or {}).get("last_name")) if x),
        "hours": int(age.total_seconds() // 3600),
    }


def render_dialog(messages: list[dict], my_id: int, limit: int = 8) -> str:
    real = [m for m in messages if ((m["attributes"].get("participants") or {}).get("from") or {}).get("id") != SYSTEM_SENDER]
    real.sort(key=lambda m: m["attributes"]["posted_at"])
    lines = []
    for m in real[-limit:]:
        who = "Я" if ((m["attributes"].get("participants") or {}).get("from") or {}).get("id") == my_id else "Заказчик"
        text = strip_html(m["attributes"].get("message_html") or m["attributes"].get("message_text") or "")
        lines.append(f"{who} ({m['attributes']['posted_at'][:16]}): {clip(text, 600)}")
    return "\n".join(lines)


NUDGE_RULES = """Ты По, помощник фрилансера. Заказчик видел последнее сообщение фрилансера больше суток назад и молчит.
Напиши короткое напоминание от первого лица фрилансера, на языке переписки.
- 1-3 предложения. Не «ну что, берёте?» и не «напоминаю о себе».
- Добавь одну новую полезную деталь по его задаче: что можно сделать первым шагом, риск, который стоит учесть, вариант попроще или быстрее.
- Закончи лёгким вопросом, на который можно ответить одним словом.
- Без давления, без извинений, без эмодзи и длинных тире. Не выдумывай фактов, которых нет в переписке."""

IDEAS_RULES = """Ты По, помощник фрилансера. Это его постоянный заказчик: список проектов, которые фрилансер для него сделал, и отзывы.
Задача: предложить, что ещё полезного можно сделать для этого заказчика, чтобы он заказал снова.
- 2-3 идеи, каждая привязана к его уже сделанным системам (доработка, автоматизация, мониторинг, отчёты, поддержка). Без фантазий о его бизнесе, которых не видно из проектов.
- Одна из идей, если уместно: поддержка за фиксированную сумму в месяц, оформленная как персональный проект на Freelancehunt через Сейф (работать в обход площадки нельзя).
- message: готовое сообщение заказчику от первого лица, 3-5 предложений, на языке его отзывов. Начни с имени, напомни конкретно, что уже сделано, предложи одну главную идею и закончи лёгким вопросом. Без воды, без эмодзи и длинных тире.
- price_hint: ориентир цены в грн для главной идеи, по бюджетам его прошлых проектов."""

NUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}
IDEAS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ideas": {"type": "array", "items": {"type": "string"}},
        "message": {"type": "string"},
        "price_hint": {"type": "string"},
    },
    "required": ["ideas", "message", "price_hint"],
}


# ---------- Повторные клиенты ----------


@dataclass
class Client:
    id: int
    name: str
    cases: list[Case] = field(default_factory=list)

    @property
    def last_date(self) -> str:
        return max((c.date for c in self.cases if c.date), default="")

    @property
    def total(self) -> int:
        return sum(int(re.sub(r"\D", "", c.budget) or 0) for c in self.cases if c.budget.endswith("UAH"))


def past_clients(cases: list[Case]) -> list[Client]:
    by: dict[int, Client] = {}
    for c in cases:
        if c.kind != "review" or not c.client_id:
            continue
        cl = by.setdefault(c.client_id, Client(c.client_id, c.client_name))
        cl.cases.append(c)
    return sorted(by.values(), key=lambda x: (-len(x.cases), -x.total))


def due_for_reminder(clients: list[Client], today: str, min_days: int = 21) -> list[Client]:
    t = datetime.fromisoformat(today)
    out = []
    for c in clients:
        if c.last_date and (t - datetime.fromisoformat(c.last_date)).days >= min_days:
            out.append(c)
    return out


def render_client(c: Client) -> str:
    lines = [f"Заказчик: {c.name}. Проектов: {len(c.cases)}, на сумму около {c.total} грн. Последний: {c.last_date}."]
    for x in sorted(c.cases, key=lambda k: k.date):
        lines.append(f"- {x.date} {x.title} ({x.budget}). Отзыв: {clip(x.review, 160)}")
    return "\n".join(lines)
