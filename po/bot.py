"""Telegram-бот По для Freelancehunt."""
import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from freelancehunt.client import FreelancehuntClient, FreelancehuntError

from . import competitors, followup, ranks, ui
from .agent import Po
from .catalog import best_matches, render_for_prompt
from .config import Settings
from .llm import Meter, OpenAILLM
from .matcher import Matcher
from .projects import Project, card, parse_project, passes
from .service import Service
from .state import State
from .text import strip_html

log = logging.getLogger("po")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
UNANSWERED_MINUTES = 25


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
        self.card_match: dict[int, tuple] = {}
        self.busy: set[int] = set()
        self.sending: set[int] = set()

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

    async def build_card(self, p: Project) -> str:
        match, why, repeat = None, "", False
        try:
            cases = await self.service.cases()
            match, why = await self.find_match(p, cases)
            if match:
                self.card_match[p.id] = (match, why)
            repeat = p.employer_id in await self.service.past_clients()
        except FreelancehuntError as e:
            log.warning("кейсы недоступны: %s", e)
        return card(p, match, repeat, why)

    async def send_projects(self, projects: list[Project]) -> int:
        """Карточки только тех проектов, которые ещё не показывали; подсказки считаются параллельно."""
        shown = set(self.state["shown_project_ids"])
        fresh = []
        for p in projects:
            if p.id in shown or p.id in self.sending or any(x.id == p.id for x in fresh):
                continue
            fresh.append(p)
        if not fresh:
            return 0
        self.sending.update(p.id for p in fresh)
        try:
            texts = await asyncio.gather(*(self.build_card(p) for p in fresh))
            for p, text in zip(fresh, texts):
                await self.bot.send_message(
                    self.chat, text, parse_mode="HTML", reply_markup=ui.project_kb(p), link_preview_options=NO_PREVIEW
                )
                self.state.mark("shown_project_ids", p.id)
            self.state.save()
        finally:
            self.sending.difference_update(p.id for p in fresh)
        return len(fresh)

    async def send_project(self, p: Project) -> None:
        await self.send_projects([p])

    async def make_bid(self, cq: CallbackQuery, pid: int, again: bool) -> None:
        if pid in self.busy:
            await cq.answer("По уже пишет эту ставку")
            return
        self.busy.add(pid)
        await cq.answer("По пишет ставку…")
        try:
            await self.bot.send_chat_action(self.chat, "typing")
            profile = await self.service.profile()
            login = profile.get("attributes", {}).get("login", "")
            project = await self.service.project(pid)
            rivals_task = asyncio.create_task(competitors.load(project.url, login))
            cases = await self.service.cases()
            facts = await self.service.facts()
            hint = self.card_match.get(pid)
            if hint is None and self.matcher:
                match, why = await self.find_match(project, cases)
                hint = (match, why) if match else None
            repeat = project.employer_id in await self.service.past_clients()
            rivals = await rivals_task
            if rivals is None:
                summary = "прочитать не удалось (сайт не отдал страницу), ставка без их учёта"
            else:
                summary = competitors.summary(rivals, project.bid_count) if rivals else ""
            rivals = rivals or []
            with self.meter.measure("bids") as spent:
                draft = await self.po.write_bid(
                    project,
                    cases,
                    facts,
                    previous=self.last_bid.get(pid) if again else None,
                    repeat=repeat,
                    rivals=competitors.render_for_prompt(rivals),
                    rivals_summary=summary,
                    rank=ranks.strong_fact(project, profile),
                    profile_url=f"https://freelancehunt.com/freelancer/{login}.html" if login else "",
                    hint=hint,
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
                self.state.data.setdefault("thread_posts", {})[str(t["id"])] = t["attributes"].get("last_post_at")
            for f in (await self.service.call(client.feed))["data"]:
                self.state.mark("seen_feed_ids", f["id"])
            self.state["initialized"] = True
            self.state.save()
            return
        # Не по is_unread: если чат открыт на сайте, сайт сразу помечает ответ прочитанным.
        posts = self.state.data.setdefault("thread_posts", {})
        now = datetime.now(timezone.utc)
        for t in threads:
            last = t["attributes"].get("last_post_at")
            if not last or posts.get(str(t["id"])) == last:
                continue
            msgs = (await self.service.call(client.thread_messages, t["id"]))["data"]
            for m in msgs:
                if not self.state.mark("seen_message_ids", m["id"]):
                    continue
                a = m["attributes"]
                frm = (a.get("participants") or {}).get("from") or {}
                fresh = not a.get("posted_at") or now - followup.parse_time(a["posted_at"]) < timedelta(days=2)
                if frm.get("id") != my_id and fresh:
                    await self.forward_client_message(t["id"], t["attributes"].get("subject") or "", m)
            self.track_unanswered(t, msgs, my_id)
            posts[str(t["id"])] = last
        await self.remind_unanswered(now)
        for f in (await self.service.call(client.feed))["data"]:
            if not self.state.mark("seen_feed_ids", f["id"]):
                continue
            a = f["attributes"]
            new_project = followup.new_project_id(a.get("message") or "", f.get("links") or {})
            if new_project:
                asyncio.create_task(self.project_from_feed(new_project))
                continue
            text = strip_html(a.get("message") or "")
            if text:
                await self.bot.send_message(self.chat, f"🔔 {html.escape(text)}", parse_mode="HTML", link_preview_options=NO_PREVIEW)
            pid = followup.loss_project_id(a.get("message") or "")
            if pid:
                asyncio.create_task(self.report_loss(pid))
        self.state.save()

    def track_unanswered(self, thread: dict, msgs: list[dict], my_id: int) -> None:
        """Запоминает диалог, где последнее живое сообщение от заказчика."""
        pending = self.state.data.setdefault("unanswered", {})
        last = followup.last_real_message(msgs)
        sender = ((last or {}).get("attributes", {}).get("participants") or {}).get("from") or {}
        if not last or sender.get("id") == my_id:
            pending.pop(str(thread["id"]), None)
            return
        if (pending.get(str(thread["id"])) or {}).get("message_id") == last["id"]:
            return
        pending[str(thread["id"])] = {
            "message_id": last["id"],
            "posted_at": last["attributes"]["posted_at"],
            "who": f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip() or "Заказчик",
            "subject": thread["attributes"].get("subject") or "",
            "reminded": False,
        }

    async def remind_unanswered(self, now: datetime) -> None:
        for p in self.state.data.get("unanswered", {}).values():
            age = now - followup.parse_time(p["posted_at"])
            if p["reminded"] or age < timedelta(minutes=UNANSWERED_MINUTES) or age > timedelta(hours=12):
                continue
            p["reminded"] = True
            await self.bot.send_message(
                self.chat,
                f"❗️ <b>{html.escape(p['who'])}</b> ждёт ответа {int(age.total_seconds() // 60)} мин.\n"
                f"<i>{html.escape(p['subject'])}</i>",
                parse_mode="HTML",
            )

    async def report_loss(self, pid: int) -> None:
        try:
            client = self.service.client
            project = (await self.service.call(client.project, pid))["data"]
            winner = (project["attributes"].get("freelancer") or {})
            if not winner.get("id"):
                return
            winner_profile = (await self.service.call(client.freelancer, winner["id"]))["data"]
            me = await self.service.profile()
            my_bid = None
            for page in range(1, 4):
                r = await self.service.call(client.get, "/my/bids", {"page[number]": page})
                my_bid = next((b for b in r["data"] if b["attributes"]["project"]["id"] == pid), None)
                if my_bid or not (r.get("links") or {}).get("next"):
                    break
            url = (project.get("links") or {}).get("self", {}).get("web", "")
            rivals = (await competitors.load(url) if url else None) or []
            wbid = next((x for x in rivals if x.login == winner.get("login")), None)
            loss = followup.build_loss(project, winner_profile, wbid, my_bid, me["attributes"].get("rating") or 0)
            self.state.data.setdefault("losses", []).append(loss.__dict__)
            self.state.data["losses"] = self.state.data["losses"][-200:]
            self.state.save()
            await self.bot.send_message(self.chat, followup.loss_message(loss), parse_mode="HTML", link_preview_options=NO_PREVIEW)
        except Exception:  # noqa: BLE001
            log.exception("разбор проигрыша %s не получился", pid)

    async def check_followups(self) -> None:
        now = datetime.now(timezone.utc)
        client = self.service.client
        my_id = await self.service.my_id()
        nudged = self.state.data.setdefault("nudged", [])
        for t in (await self.service.call(client.threads))["data"]:
            last = t["attributes"].get("last_post_at")
            if not last or now - followup.parse_time(last) > timedelta(days=14):
                continue
            msgs = (await self.service.call(client.thread_messages, t["id"]))["data"]
            stale = followup.stale_thread(t, msgs, my_id, now)
            if not stale or stale["message_id"] in nudged:
                continue
            nudged.append(stale["message_id"])
            self.state.data["nudged"] = nudged[-500:]
            await self.bot.send_message(
                self.chat,
                f"⏰ <b>{html.escape(stale['client'] or 'Заказчик')}</b> видел твоё сообщение и молчит {stale['hours']} ч.\n"
                f"<i>{html.escape(stale['subject'])}</i>",
                parse_mode="HTML",
                reply_markup=ui.nudge_kb(stale["thread_id"]),
            )
        local = datetime.now()
        week = local.strftime("%G-%V")
        if local.weekday() == 0 and local.hour >= 10 and self.state.get("digest_week") != week:
            self.state["digest_week"] = week
            stats = await self.service.bid_stats(7)
            await self.bot.send_message(
                self.chat, followup.weekly_digest(self.state.data.get("losses", []), stats), parse_mode="HTML"
            )
        month = local.strftime("%Y-%m")
        if local.hour >= 10 and self.state.get("clients_month") != month:
            self.state["clients_month"] = month
            due = followup.due_for_reminder(followup.past_clients(await self.service.cases()), local.date().isoformat())
            if due:
                await self.bot.send_message(
                    self.chat, "🤝 <b>Пора напомнить о себе постоянным клиентам</b>", parse_mode="HTML"
                )
                for c in due[:3]:
                    await self.send_client(c)
        self.state.save()

    async def send_client(self, c) -> None:
        await self.bot.send_message(
            self.chat, ui.client_card(c), parse_mode="HTML", reply_markup=ui.client_kb(c.id)
        )

    async def make_nudge(self, cq: CallbackQuery, thread_id: int) -> None:
        await cq.answer("По пишет напоминание…")
        try:
            client = self.service.client
            my_id = await self.service.my_id()
            msgs = (await self.service.call(client.thread_messages, thread_id))["data"]
            thread = next((t for t in (await self.service.call(client.threads))["data"] if t["id"] == thread_id), None)
            subject = thread["attributes"].get("subject", "") if thread else ""
            with self.meter.measure("nudges") as spent:
                text = await self.po.write_nudge(subject, followup.render_dialog(msgs, my_id))
            sent = await cq.message.reply(
                f"<pre>{html.escape(text)}</pre>\n<i>Ответь на это сообщение (можно поправить текст), и оно уйдёт заказчику. "
                f"Стоило {ui.usd(sum(spent))}.</i>",
                parse_mode="HTML",
            )
            self.state["reply_map"][str(sent.message_id)] = thread_id
            self.state.save()
        except Exception as e:  # noqa: BLE001
            log.exception("напоминание %s не получилось", thread_id)
            await cq.message.reply(f"Не получилось: {html.escape(str(e))[:300]}", parse_mode="HTML")

    async def make_ideas(self, cq: CallbackQuery, client_id: int) -> None:
        await cq.answer("По думает…")
        try:
            cases = await self.service.cases()
            c = next((x for x in followup.past_clients(cases) if x.id == client_id), None)
            if not c:
                await cq.message.reply("Не нашёл этого заказчика в отзывах.")
                return
            portfolio = [x for x in cases if x.kind == "portfolio"]
            with self.meter.measure("ideas") as spent:
                out = await self.po.client_ideas(followup.render_client(c), render_for_prompt(portfolio))
            await cq.message.reply(ui.ideas_message(c, out, sum(spent)), parse_mode="HTML")
            self.state.save()
        except Exception as e:  # noqa: BLE001
            log.exception("идеи для %s не получились", client_id)
            await cq.message.reply(f"Не получилось: {html.escape(str(e))[:300]}", parse_mode="HTML")

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
        await self.send_projects(await self.service.new_projects())

    async def project_from_feed(self, pid: int) -> None:
        """Уведомление «добавил проект» превращается в обычную карточку с кнопками."""
        try:
            self.state.mark("seen_project_ids", pid)
            p = await self.service.project(pid)
            if not self.state["paused"] and passes(p, self.state["min_budget"]):
                await self.send_projects([p])
        except Exception:  # noqa: BLE001
            log.exception("проект %s из ленты не показан", pid)


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
        await app.bot.send_chat_action(m.chat.id, "typing")
        shown = set(app.state["shown_project_ids"])
        fresh = []
        for item in await app.service.latest_projects():
            p = parse_project(item)
            if p.id not in shown and passes(p, app.state["min_budget"]):
                fresh.append(p)
        if not await app.send_projects(fresh[:5][::-1]):
            await m.answer("Новых проектов нет, всё уже показано.")

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

    @r.message(owner, F.text == ui.BTN_CLIENTS)
    async def clients(m: Message):
        top = followup.past_clients(await app.service.cases())[:6]
        if not top:
            await m.answer("Постоянных заказчиков в отзывах пока нет.")
            return
        await m.answer("🤝 Твои заказчики по числу проектов. «💡 Идеи» = что ещё им предложить и готовое сообщение.")
        for c in top:
            await app.send_client(c)

    @r.callback_query(owner, F.data.startswith("nudge:"))
    async def nudge(cq: CallbackQuery):
        await app.make_nudge(cq, int(cq.data.split(":")[1]))

    @r.callback_query(owner, F.data.startswith("idea:"))
    async def idea(cq: CallbackQuery):
        await app.make_ideas(cq, int(cq.data.split(":")[1]))

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
    app = App(s, bot, Service(FreelancehuntClient(s.fh_token), state, s.catalog_ttl, s.extra_skills), Po(llm), state, matcher, meter)
    dp = Dispatcher()
    dp.include_router(build_router(app))
    asyncio.create_task(app.loop(s.poll_inbox, app.check_inbox))
    asyncio.create_task(app.loop(s.poll_projects, app.check_projects))
    asyncio.create_task(app.loop(3600, app.check_followups))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
