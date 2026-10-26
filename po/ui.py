"""Тексты и кнопки бота."""
import html
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .agent import BidDraft
from .projects import Project
from .text import clip

BTN_PROJECTS = "Свежие проекты"
BTN_PAUSE = "Пауза"
BTN_RESUME = "Включить"
BTN_BUDGET = "Мин. бюджет"
BTN_PROFILE = "Профиль"

BUDGETS = [0, 1000, 2000, 3000, 5000, 10000]
FIT = {"high": "🟢 очень похоже", "medium": "🟡 частично похоже", "low": "🔴 похожего мало"}


def menu(paused: bool) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_PROJECTS), KeyboardButton(text=BTN_RESUME if paused else BTN_PAUSE)],
            [KeyboardButton(text=BTN_BUDGET), KeyboardButton(text=BTN_PROFILE)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def project_kb(p: Project) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Открыть", url=p.url),
                InlineKeyboardButton(text="✍️ Ставка", callback_data=f"bid:{p.id}"),
            ]
        ]
    )


def bid_kb(p: Project) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Открыть проект", url=p.url),
                InlineKeyboardButton(text="🔄 Другой вариант", callback_data=f"again:{p.id}"),
            ]
        ]
    )


def budget_kb(current: int) -> InlineKeyboardMarkup:
    row = []
    for b in BUDGETS:
        label = "без лимита" if b == 0 else f"{b // 1000}k"
        if b == current:
            label = f"• {label}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"min:{b}"))
    return InlineKeyboardMarkup(inline_keyboard=[row[:3], row[3:]])


def bid_message(p: Project, d: BidDraft) -> str:
    e = html.escape
    lines = [f"<b>Ставка</b> · {FIT.get(d.fit, d.fit)}", f"<pre>{e(d.text)}</pre>"]
    terms = []
    if d.price:
        terms.append(f"💰 {d.price:,} {e(d.currency)}".replace(",", " "))
    if d.days:
        terms.append(f"⏱ {d.days} дн.")
    if terms:
        lines.append(" · ".join(terms))
    if d.picks:
        lines.append("")
        lines.append("<b>Прикрепи к ставке:</b>")
        for pick in d.picks:
            title = e(clip(pick.case.title, 60))
            ref = f'<a href="{e(pick.case.url)}">{title}</a>' if pick.case.url else title
            extra = " (есть отзыв)" if pick.case.kind == "review" else ""
            lines.append(f"• {ref}{extra}: {e(clip(pick.why, 90))}")
    if d.note:
        lines.append("")
        lines.append(f"<i>По: {e(clip(d.note, 200))}</i>")
    lines.append("")
    lines.append("<i>Нажми на текст ставки, он скопируется.</i>")
    return "\n".join(lines)


def profile_message(
    profile: dict, cases_total: int, reviews_total: int, min_budget: int, paused: bool, stats: Optional[dict] = None
) -> str:
    a = (profile.get("data") or {}).get("attributes") or {}
    name = " ".join(x for x in (a.get("first_name"), a.get("last_name")) if x) or a.get("login", "")
    rating = a.get("rating") or {}
    lines = [f"<b>{html.escape(name)}</b>"]
    if isinstance(rating, dict) and rating.get("value") is not None:
        lines.append(f"Рейтинг: {rating.get('value')}")
    elif a.get("rating") is not None:
        lines.append(f"Рейтинг: {a.get('rating')}")
    lines.append(f"По знает {cases_total} работ, из них {reviews_total} с отзывами")
    lines.append(f"Мин. бюджет: {'без лимита' if not min_budget else f'{min_budget} UAH'}")
    lines.append("Лента проектов: " + ("на паузе" if paused else "включена"))
    if stats:
        rate = round(100 * stats["won"] / stats["total"]) if stats["total"] else 0
        lines.append(f"Ставки за {stats['days']} дней: {stats['total']}, выиграно {stats['won']} ({rate}%)")
    lines.append("")
    lines.append("🔥 в ленте: до 20 ставок, у заказчика 3+ проекта, AI или парсинг. 🤝 уже работали с заказчиком.")
    return "\n".join(lines)


def client_message(who: str, subject: str, text: Optional[str]) -> str:
    e = html.escape
    body = e(text) if text else "<i>(вложение)</i>"
    return f"✉️ <b>{e(who)}</b>\n<i>{e(subject)}</i>\n\n{body}\n\n<i>Ответь на это сообщение, чтобы написать заказчику.</i>"
