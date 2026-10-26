"""Telegram-бот По для Freelancehunt."""
import asyncio
import html
import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from freelancehunt.client import FreelancehuntClient, FreelancehuntError

from . import competitors, ranks, ui
from .agent import Po
from .catalog import best_matches
from .config import Settings
from .llm import Meter, OpenAILLM
from .matcher import Matcher
from .projects import Project, card, parse_project
from .service import Service
from .state import State
from .text import strip_html

log = logging.getLogger("po")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


class App:
    def __init__(
        self,
        settings: Settings,
        bot: Bot,
        service: Service,
        po: Po,
        state: State,
        matcher: Optional[Matcher] = None,
        meter: Optional[Meter] = None,
    ):
        self.s = settings
        self.bot = bot
        self.service = service
        self.po = po
        self.state = state
        self.matcher = matcher
        self.meter = meter or Meter(state)
        self.last_bid: dict[int, str] = {}
        self.busy: set[int] = set()

    @property
    def chat(self):
        return self.state["owner_chat_id"]

    def is_owner(self, user_id: int) -> bool:
        owner = self.s.owner_id or self.state["owner_chat_id"]
        return owner is not None and user_id == owner

    async def find_match(self, p: Project, cases: list) -> tuple:
        if self.matcher:
            try:
                with self.meter.measure("cards"):
                    found = await self.matcher.best(p, cases)
                return found if found else (None, "")
            except Exception as e:  # noqa: BLE001
                log.warning("точный подбор не сработал, беру по словам: %s", e)
        matches = best_matches(p.search_text, cases, n=1)
        return (matches[0], "") if matches else (None, "")

    async def send_project(self, p: Project) -> None:
        match, why, repeat = None, "", False
        try:
            cases = await self.service.cases()
            match, why = await self.find_match(p, cases)
            repeat = p.employer_id in await self.service.past_clients()
        except FreelancehuntError as e:
            log.warning("кейсы недоступны: %s", e)
        self.state.save()
        await self.bot.send_message(
            self.chat, card(p, match, repeat, why), parse_mode="HTML", reply_markup=ui.project_kb(p),
            link_preview_options=NO_PREVIEW,
        )

    async def make_bid(self, cq: CallbackQuery, pid: int, again: bool) -> None:
        if pid in self.busy:
            await cq.answer("По уже пишет эту ставку")
            return
        self.busy.add(pid)
        await cq.answer("По пишет ставку…")
        try:
            await self.bot.send_chat_action(self.chat, "typing")
            project = await self.service.project(pid)
            cases = await self.service.cases()
            facts = await self.service.facts()
            repeat = project.employer_id in await self.service.past_clients()
            profile = await self.service.profile()
            login = profile.get("attributes", {}).get("login", "")
            rivals = await competitors.load(project.url, login)
            with self.meter.measure("bids") as spent:
                draft = await self.po.write_bid(
                    project,
                    cases,
                    facts,
                    previous=self.last_bid.get(pid) if again else None,
                    repeat=repeat,
                    rivals=competitors.render_for_prompt(rivals),
                    rivals_summary=competitors.summary(rivals, project.bid_count) if rivals else "",
                    rank=ranks.strong_fact(project, profile),
                )
            draft.cost = sum(spent)
            self.state.save()
            self.last_bid[pid] = draft.text
            await cq.message.reply(
                ui.bid_message(project, draft), parse_mode="HTML", reply_markup=ui.bid_kb(project), link_preview_options=NO_PREVIEW
            )
        except Exception as e:  # noqa: BLE001
            log.exception("ставка %s не получилась", pid)
            await cq.message.reply(f"Не получилось написать ставку: {html.escape(str(e))[:300]}", parse_mode="HTML")
        finally:
            self.busy.discard(pid)

    async def forward_client_message(self, thread_id: int, subject: str, m: dict) -> None:
        a = m["attributes"]
        sender = (a.get("participants") or {}).get("from") or {}
        who = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or "Заказчик"
        text = strip_html(a.get("message_html") or a.get("message_text") or "")
        sent = await self.bot.send_message(self.chat, ui.client_message(who, subject, text), parse_mode="HTML")
        self.state["reply_map"][str(sent.message_id)] = thread_id
        for at in a.get("attachments") or []:
            try:
                if at.get("file_type") == "image":
                    await self.bot.send_photo(self.chat, at["url"], caption=at.get("name", ""), reply_to_message_id=sent.message_id)
                else:
                    await self.bot.send_document(self.chat, at["url"], caption=at.get("name", ""), reply_to_message_id=sent.message_id)
            except Exception:  # noqa: BLE001
                await self.bot.send_message(self.chat, f"📎 {at.get('name', 'файл')}: {at.get('url', '')}")

    async def check_inbox(self) -> None:
        client = self.service.client
        my_id = await self.service.my_id()
        threads = (await self.service.call(client.threads))["data"]
        if not self.state["initialized"]:
            for t in threads:
                for m in (await self.service.call(client.thread_messages, t["id"]))["data"]:
                    self.state.mark("seen_message_ids", m["id"])
            for f in (await self.service.call(client.feed))["data"]:
                self.state.mark("seen_feed_ids", f["id"])
            self.state["initialized"] = True
            self.state.save()
            return
        for t in threads:
            if not t["attributes"].get("is_unread"):
                continue
            for m in (await self.service.call(client.thread_messages, t["id"]))["data"]:
                if not self.state.mark("seen_message_ids", m["id"]):
                    continue
                frm = (m["attributes"].get("participants") or {}).get("from") or {}
                if frm.get("id") != my_id:
                    await self.forward_client_message(t["id"], t["attributes"].get("subject", ""), m)
        for f in (await self.service.call(client.feed))["data"]:
            if not self.state.mark("seen_feed_ids", f["id"]):
                continue
            a = f["attributes"]
            text = strip_html(a.get("message") or "")
            if text:
                await self.bot.send_message(self.chat, f"🔔 {html.escape(text)}", parse_mode="HTML", link_preview_options=NO_PREVIEW)
        self.state.save()

    async def loop(self, interval: int, job) -> None:
        while True:
            if self.chat is not None:
                try:
                    await job()
                except FreelancehuntError as e:
                    log.warning("%s: %s", job.__name__, e)
                except Exception:  # noqa: BLE001
                    log.exception("%s упал", job.__name__)
            await asyncio.sleep(interval)

    async def check_projects(self) -> None:
        for p in await self.service.new_projects():
            await self.send_project(p)


def build_router(app: App) -> Router:
    r = Router()
    owner = F.from_user.func(lambda u: app.is_owner(u.id))

    @r.message(CommandStart())
    async def start(m: Message):
        if app.state["owner_chat_id"] is None and (app.s.owner_id in (None, m.from_user.id)):
            app.state["owner_chat_id"] = m.chat.id
            app.state.save()
        if not app.is_owner(m.from_user.id):
            await m.answer("Это личный бот.")
            return
        await m.answer(
            "Я По. Присылаю новые проекты по твоим специализациям.\n\n"
            "Под каждым проектом две кнопки: «Открыть» ведёт на сайт, «✍️ Ставка» пишет ставку по твоим работам и отзывам. "
            "Токены тратятся только когда жмёшь «Ставка».\n\n"
            "Сообщения заказчиков тоже приходят сюда. Ответь на такое сообщение, и ответ уйдёт заказчику.",
            reply_markup=ui.menu(app.state["paused"]),
        )

    @r.message(owner, F.text == ui.BTN_PROJECTS)
    @r.message(owner, Command("projects"))
    async def projects(m: Message):
        items = await app.service.latest_projects()
        if not items:
            await m.answer("Проектов пока нет.")
            return
        for item in items[:5][::-1]:
            await app.send_project(parse_project(item))

    @r.message(owner, F.text.in_({ui.BTN_PAUSE, ui.BTN_RESUME}))
    async def toggle(m: Message):
        app.state["paused"] = m.text == ui.BTN_PAUSE
        app.state.save()
        text = "Лента на паузе. Сообщения заказчиков всё равно приходят." if app.state["paused"] else "Лента проектов включена."
        await m.answer(text, reply_markup=ui.menu(app.state["paused"]))

    @r.message(owner, F.text == ui.BTN_BUDGET)
    async def budget(m: Message):
        await m.answer("Проекты дешевле этой суммы (UAH) не присылаю:", reply_markup=ui.budget_kb(app.state["min_budget"]))

    @r.message(owner, F.text == ui.BTN_PROFILE)
    async def profile(m: Message):
        prof = {"data": await app.service.profile(force=True)}
        cases = await app.service.cases(force=True)
        reviews = sum(1 for c in cases if c.kind == "review")
        stats = await app.service.bid_stats(30)
        await m.answer(
            ui.profile_message(
                prof, len(cases), reviews, app.state["min_budget"], app.state["paused"], stats, app.meter.summary(30)
            ),
            parse_mode="HTML",
        )

    @r.callback_query(owner, F.data.startswith("min:"))
    async def set_budget(cq: CallbackQuery):
        app.state["min_budget"] = int(cq.data.split(":")[1])
        app.state.save()
        await cq.message.edit_reply_markup(reply_markup=ui.budget_kb(app.state["min_budget"]))
        await cq.answer("Сохранил")

    @r.callback_query(owner, F.data.startswith("bid:"))
    async def bid(cq: CallbackQuery):
        await app.make_bid(cq, int(cq.data.split(":")[1]), again=False)

    @r.callback_query(owner, F.data.startswith("again:"))
    async def again(cq: CallbackQuery):
        await app.make_bid(cq, int(cq.data.split(":")[1]), again=True)

    @r.message(owner, F.reply_to_message)
    async def reply_client(m: Message):
        thread_id = app.state["reply_map"].get(str(m.reply_to_message.message_id))
        if not thread_id:
            await m.answer("Чтобы написать заказчику, ответь на его сообщение.")
            return
        text = (m.text or m.caption or "").strip()
        if not text:
            await m.answer("Пустое сообщение не отправил.")
            return
        body = "".join(f"<p>{html.escape(line)}</p>" for line in text.split("\n"))
        try:
            await app.service.call(app.service.client.reply_thread, int(thread_id), body)
            await m.reply("Отправил заказчику.")
        except FreelancehuntError as e:
            await m.reply(f"Не отправилось: {e}")

    return r


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings.from_env()
    state = State(s.state_path)
    if s.owner_id and state["owner_chat_id"] is None:
        state["owner_chat_id"] = s.owner_id
    bot = Bot(s.telegram_token)
    meter = Meter(state, s.prices)
    llm = OpenAILLM(s.openai_key, s.model, meter)
    matcher = Matcher(llm, str(Path(s.state_path).with_name("index.json")))
    app = App(s, bot, Service(FreelancehuntClient(s.fh_token), state, s.catalog_ttl), Po(llm), state, matcher, meter)
    dp = Dispatcher()
    dp.include_router(build_router(app))
    asyncio.create_task(app.loop(s.poll_inbox, app.check_inbox))
    asyncio.create_task(app.loop(s.poll_projects, app.check_projects))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
