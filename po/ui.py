"""Тексты и кнопки бота."""
import html
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .agent import BidDraft
from .projects import Project
from .ranks import OVERALL_TOTAL, fmt, positions
from .text import clip

BTN_PROJECTS = "Свежие проекты"
BTN_PAUSE = "Пауза"
BTN_RESUME = "Включить"
BTN_BUDGET = "Мин. бюджет"
BTN_PROFILE = "Профиль"
BTN_CLIENTS = "Клиенты"

BUDGETS = [0, 1000, 2000, 3000, 5000, 10000]
FIT = {"high": "🟢 очень похоже", "medium": "🟡 частично похоже", "low": "🔴 похожего мало"}


def menu(paused: bool) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_PROJECTS), KeyboardButton(text=BTN_RESUME if paused else BTN_PAUSE)],
            [KeyboardButton(text=BTN_BUDGET), KeyboardButton(text=BTN_PROFILE)],
            [KeyboardButton(text=BTN_CLIENTS)],
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


def usd(x: float) -> str:
    return f"${x:.4f}" if x < 0.01 else f"${x:.2f}"


def bid_message(p: Project, d: BidDraft) -> str:
    e = html.escape
    lines = [f"<b>Ставка</b> · {FIT.get(d.fit, d.fit)}", f"<pre>{e(d.text)}</pre>"]
    terms = []
    for i, st in enumerate(d.stages, 1):
        price = f"{st['price']:,}".replace(",", " ")
        lines.append(f"Этап {i}: {price} {e(d.currency)}, {st['days']} дн. · {e(clip(st['title'], 60))}")
    if d.stages:
        first = f"{d.stages[0]['price']:,}".replace(",", " ")
        lines.append(f"<i>В поле цены на сайте ставь сумму Этапа 1: {first} {e(d.currency)}, срок {d.stages[0]['days']} дн.</i>")
    elif d.price:
        terms.append(f"💰 {d.price:,} {e(d.currency)}".replace(",", " "))
    if d.minutes and not d.stages:
        terms.append(f"⏱ {d.minutes} мин" if d.minutes < 60 else f"⏱ {round(d.minutes / 60)} ч (на сайте ставь 1 день)")
    elif d.days and not d.stages:
        terms.append(f"⏱ {d.days} дн.")
    if terms:
        lines.append(" · ".join(terms))
    def link(c) -> str:
        title = e(clip(c.title, 70))
        return f'<a href="{e(c.url)}">{title}</a>' if c.url else title

    if d.work or d.example:
        lines.append("")
        if d.work:
            lines.append(f"📎 <b>Пример работы:</b> «{link(d.work)}»")
        if d.example and d.example.public is False:
            lines.append(f"🔒 Отзыв из личного проекта «{e(clip(d.example.title, 70))}»: приложить нельзя, в тексте ссылка на отзывы в профиле")
        elif d.example:
            lines.append(f"📎 <b>Пример проекта:</b> «{link(d.example)}» (поставь в поле «Пример проекта»)")
    elif d.picks:
        lines.append("")
        lines.append(f"📎 <b>Приложи:</b> «{link(d.picks[0].case)}»")
    used = {x.ref for x in (d.work, d.example) if x}
    rest = [e(clip(x.case.title, 50)) for x in d.picks if x.case.ref not in used]
    if rest:
        lines.append("Ещё подходят: " + "; ".join(rest[:2]))
    if d.hide:
        lines.append("")
        lines.append(f"🙈 <b>Скрой ставку</b> (Plus): {e(clip(d.hide_reason, 140))}")
    if d.rivals_summary:
        lines.append("")
        lines.append(f"👀 Конкуренты: {e(d.rivals_summary)}")
        if d.rivals_note:
            lines.append(f"<i>{e(clip(d.rivals_note, 260))}</i>")
    if d.note:
        lines.append("")
        lines.append(f"<i>По: {e(clip(d.note, 200))}</i>")
    lines.append("")
    tail = "<i>Нажми на текст ставки, он скопируется.</i>"
    if d.cost:
        tail += f" <i>Стоила {usd(d.cost)}.</i>"
    lines.append(tail)
    return "\n".join(lines)


def usage_lines(u: dict, budget: float = 20.0) -> list[str]:
    lines = [f"Расходы: сегодня {usd(u['today_usd'])}, за {u['days']} дней {usd(u['usd'])}"]
    per_bid = u["bids_usd"] / u["bids"] if u.get("bids") else 0.006
    per_card = u["cards_usd"] / u["cards"] if u.get("cards") else 0.0003
    lines.append(f"Ставок {u.get('bids', 0)}, карточек {u.get('cards', 0)}. В среднем ставка {usd(per_bid)}, карточка {usd(per_card)}")
    lines.append(f"${budget:.0f} хватит примерно на {int(budget / per_bid):,} ставок или {int(budget / per_card):,} карточек".replace(",", " "))
    return lines


def profile_message(
    profile: dict,
    cases_total: int,
    reviews_total: int,
    min_budget: int,
    paused: bool,
    stats: Optional[dict] = None,
    usage: Optional[dict] = None,
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
    pos = positions(profile.get("data") or {})
    if pos:
        lines.append("")
        lines.append("<b>Позиции</b>")
        overall = a.get("rating_position")
        if overall:
            lines.append(f"В общем рейтинге: <b>{fmt(int(overall))}</b> / {fmt(OVERALL_TOTAL)}")
        for name, p, total in pos:
            crown = " 👑" if p <= 3 else (" 🔥" if p <= 20 else "")
            lines.append(f"{html.escape(name)}: <b>{p}</b>" + (f" / {fmt(total)}" if total else "") + crown)
        lines.append("")
    lines.append(f"Мин. бюджет: {'без лимита' if not min_budget else f'{min_budget} UAH'}")
    lines.append("Лента проектов: " + ("на паузе" if paused else "включена"))
    if stats:
        rate = round(100 * stats["won"] / stats["total"]) if stats["total"] else 0
        lines.append(f"Ставки за {stats['days']} дней: {stats['total']}, выиграно {stats['won']} ({rate}%)")
    if usage:
        lines.append("")
        lines.extend(usage_lines(usage))
    lines.append("")
    lines.append("🔥 в ленте: до 20 ставок, у заказчика 3+ проекта, AI или парсинг. 🤝 уже работали с заказчиком.")
    return "\n".join(lines)


def client_message(who: str, subject: str, text: Optional[str]) -> str:
    e = html.escape
    body = e(text) if text else "<i>(вложение)</i>"
    return f"✉️ <b>{e(who)}</b>\n<i>{e(subject)}</i>\n\n{body}\n\n<i>Ответь на это сообщение, чтобы написать заказчику.</i>"


def nudge_kb(thread_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✍️ Напоминание", callback_data=f"nudge:{thread_id}")]]
    )


def client_kb(client_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💡 Идеи", callback_data=f"idea:{client_id}")]]
    )


def client_card(c) -> str:
    e = html.escape
    titles = "; ".join(clip(x.title, 40) for x in sorted(c.cases, key=lambda k: k.date, reverse=True)[:4])
    total = f"{c.total:,}".replace(",", " ")
    return f"<b>{e(c.name)}</b>: {len(c.cases)} проектов, около {total} грн, последний {e(c.last_date)}\n<i>{e(titles)}</i>"


def ideas_message(c, out: dict, cost: float) -> str:
    e = html.escape
    lines = [f"💡 <b>{e(c.name)}</b>"]
    for i, idea in enumerate(out.get("ideas") or [], 1):
        lines.append(f"{i}. {e(idea)}")
    if out.get("price_hint"):
        lines.append(f"<i>Ориентир цены: {e(out['price_hint'])}</i>")
    lines.append("")
    lines.append(f"<pre>{e(out.get('message', ''))}</pre>")
    lines.append(f"<i>Отправь заказчику на сайте. Стоило {usd(cost)}.</i>")
    return "\n".join(lines)
