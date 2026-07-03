"""Telegram bot (aiogram v3) for the Freelancehunt account.

Features:
  - Notifies the owner about new incoming messages from clients (with photos/files).
  - Notifies about new feed items (notifications).
  - Reply to a client straight from Telegram: reply to a forwarded message.
  - Place a bid:  /bid <project_id> <amount> <days> <comment...>
  - Browse latest projects:  /projects
"""
import asyncio
import html
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from freelancehunt.client import FreelancehuntClient, FreelancehuntError

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

POLL_SECONDS = 30
STATE_FILE = Path(__file__).parent / "bot_state.json"

client = FreelancehuntClient()
bot = Bot(TOKEN)
dp = Dispatcher()


# ---------- Persistent state ----------
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "owner_chat_id": None,
        "my_id": None,
        "seen_message_ids": [],   # thread message ids already forwarded
        "seen_feed_ids": [],      # feed ids already forwarded
        "reply_map": {},          # telegram_message_id -> thread_id
        "initialized": False,
    }


def save_state(s: dict) -> None:
    # Cap history so the file doesn't grow forever.
    s["seen_message_ids"] = s["seen_message_ids"][-2000:]
    s["seen_feed_ids"] = s["seen_feed_ids"][-2000:]
    if len(s["reply_map"]) > 1000:
        s["reply_map"] = dict(list(s["reply_map"].items())[-1000:])
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False))


state = load_state()


def is_owner(message: Message) -> bool:
    return state.get("owner_chat_id") == message.chat.id


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


# ---------- Commands ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    if state.get("owner_chat_id") is None:
        state["owner_chat_id"] = message.chat.id
        profile = client.my_profile()
        state["my_id"] = profile["data"]["id"]
        save_state(state)
        await message.answer(
            "✅ Бот привязан к этому чату.\n\n"
            "Что я умею:\n"
            "• Пришлю новые сообщения от заказчиков (с фото и файлами)\n"
            "• Пришлю новые уведомления\n"
            "• Ответить клиенту — <b>ответь (reply)</b> на пересланное сообщение\n"
            "• Последние проекты — /projects (ставку ставишь на сайте — API закрыл подачу)\n\n"
            "Готово, слежу за аккаунтом.",
            parse_mode="HTML",
        )
    elif is_owner(message):
        await message.answer("Бот уже привязан к этому чату. /help — список команд.")
    else:
        await message.answer("Этот бот приватный.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    if not is_owner(message):
        return
    await message.answer(
        "Команды:\n"
        "/projects — последние проекты\n"
        "/bid <id> — ссылка на проект (ставку ставишь на сайте, API закрыл подачу)\n"
        "Ответить клиенту — reply на пересланное сообщение",
    )


@dp.message(Command("projects"))
async def cmd_projects(message: Message):
    if not is_owner(message):
        return
    try:
        data = client.projects(page=1)["data"][:8]
    except FreelancehuntError as e:
        await message.answer(f"Ошибка: {e}")
        return
    lines = ["<b>Последние проекты:</b>\n"]
    for p in data:
        a = p["attributes"]
        budget = a.get("budget")
        b = f"{budget['amount']} {budget['currency']}" if budget else "бюджет не указан"
        lines.append(f"🆔 <code>{p['id']}</code> · {html.escape(a['name'])}\n💰 {b} · {a.get('bid_count', 0)} ставок\n")
    lines.append("\nСтавки через API закрыты — открой проект на сайте: /bid &lt;id&gt; даст ссылку.")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("bid"))
async def cmd_bid(message: Message):
    if not is_owner(message):
        return
    parts = message.text.split(maxsplit=1)
    pid = parts[1].strip() if len(parts) > 1 else ""
    link = f"https://freelancehunt.com/project/x/{pid}.html" if pid.isdigit() else "https://freelancehunt.com/my/projects"
    await message.answer(
        "⚠️ Freelancehunt закрыл подачу ставок через API (v2 deprecated) — из бота поставить нельзя.\n\n"
        f"Открой проект и поставь ставку на сайте:\n{link}"
    )


# ---------- Reply to a client ----------
@dp.message(F.reply_to_message)
async def handle_reply(message: Message):
    if not is_owner(message):
        return
    key = str(message.reply_to_message.message_id)
    thread_id = state["reply_map"].get(key)
    if not thread_id:
        return  # not a reply to a forwarded client message
    text = message.text or message.caption or ""
    if not text.strip():
        await message.answer("Пустое сообщение не отправлено.")
        return
    body = "".join(f"<p>{html.escape(line)}</p>" for line in text.split("\n"))
    try:
        client.reply_thread(int(thread_id), body)
        await message.answer("✅ Отправлено заказчику.")
    except FreelancehuntError as e:
        await message.answer(f"❌ Ошибка отправки: {e}")


# ---------- Background polling ----------
async def forward_message(thread_id: int, subject: str, m: dict):
    a = m["attributes"]
    sender = a.get("participants", {}).get("from", {})
    who = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or "Заказчик"
    text = strip_html(a.get("message_html") or a.get("message_text") or "")
    header = f"✉️ <b>{html.escape(who)}</b>\n<i>{html.escape(subject)}</i>\n\n"
    body = header + html.escape(text) if text else header + "<i>(вложение)</i>"

    sent = await bot.send_message(state["owner_chat_id"], body, parse_mode="HTML")
    state["reply_map"][str(sent.message_id)] = thread_id

    # Attachments (public URLs — Telegram fetches them directly).
    for at in a.get("attachments") or []:
        try:
            if at.get("file_type") == "image":
                await bot.send_photo(state["owner_chat_id"], at["url"], caption=at.get("name", ""))
            else:
                await bot.send_document(state["owner_chat_id"], at["url"], caption=at.get("name", ""))
        except Exception:
            # Fallback to a plain link if Telegram can't fetch it.
            await bot.send_message(state["owner_chat_id"], f"📎 {at.get('name','файл')}: {at['url']}")


async def poll_loop():
    # Warm-up: mark everything currently present as seen, so we only push NEW items.
    while state.get("owner_chat_id") is None:
        await asyncio.sleep(3)

    if not state.get("initialized"):
        try:
            for t in client.threads()["data"]:
                for m in client.thread_messages(t["id"])["data"]:
                    state["seen_message_ids"].append(m["id"])
            for f in client.feed()["data"]:
                state["seen_feed_ids"].append(f["id"])
            state["initialized"] = True
            save_state(state)
        except FreelancehuntError:
            pass

    while True:
        try:
            my_id = state.get("my_id")
            # New incoming thread messages
            for t in client.threads()["data"]:
                ta = t["attributes"]
                if not ta.get("is_unread"):
                    continue
                subject = ta.get("subject", "")
                for m in client.thread_messages(t["id"])["data"]:
                    if m["id"] in state["seen_message_ids"]:
                        continue
                    state["seen_message_ids"].append(m["id"])
                    frm = m["attributes"].get("participants", {}).get("from", {})
                    if frm.get("id") == my_id:
                        continue  # skip my own messages
                    await forward_message(t["id"], subject, m)
                save_state(state)

            # New feed notifications
            for f in client.feed()["data"]:
                if f["id"] in state["seen_feed_ids"]:
                    continue
                state["seen_feed_ids"].append(f["id"])
                a = f["attributes"]
                frm = a.get("from", {})
                who = f"{frm.get('first_name', '')} {frm.get('last_name', '')}".strip()
                text = strip_html(a.get("message") or "")
                msg = f"🔔 <b>Уведомление</b>\n{html.escape(who)}\n\n{html.escape(text)}"
                await bot.send_message(state["owner_chat_id"], msg, parse_mode="HTML")
            save_state(state)

        except FreelancehuntError:
            pass
        except Exception:
            pass

        await asyncio.sleep(POLL_SECONDS)


async def main():
    asyncio.create_task(poll_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
