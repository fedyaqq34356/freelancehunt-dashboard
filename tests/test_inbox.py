import asyncio
from datetime import datetime, timedelta, timezone

from po.bot import App
from po.state import State


class FakeClient:
    def __init__(self, threads, messages):
        self._threads, self._messages = threads, messages

    def threads(self):
        return {"data": self._threads}

    def thread_messages(self, tid):
        return {"data": self._messages[tid]}

    def feed(self):
        return {"data": []}


class FakeService:
    def __init__(self, client):
        self.client = client

    async def my_id(self):
        return 1

    async def call(self, fn, *args):
        return fn(*args)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat, text, **kw):
        self.sent.append(text)

        class M:
            message_id = len(self.sent)

        return M()


def msg(mid, frm, when):
    return {"id": mid, "attributes": {"message_html": f"m{mid}", "posted_at": when.isoformat(),
                                      "participants": {"from": {"id": frm, "first_name": "Anton"}}}}


def test_read_on_site_thread_still_forwarded(tmp_path):
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=10)
    thread = {"id": 7, "attributes": {"subject": "S", "is_unread": False, "last_post_at": old.isoformat()}}
    messages = {7: [msg(1, 2, old)]}
    state = State(str(tmp_path / "s.json"))
    state["owner_chat_id"] = 5
    bot = FakeBot()
    app = App.__new__(App)
    app.bot, app.state, app.service = bot, state, FakeService(FakeClient([thread], messages))
    asyncio.run(app.check_inbox())  # первый запуск: всё старое помечено
    assert bot.sent == []

    messages[7] = [msg(3, 2, now), msg(2, 2, now - timedelta(days=5)), msg(1, 2, old)]
    thread["attributes"]["last_post_at"] = now.isoformat()  # прочитано на сайте, is_unread False
    asyncio.run(app.check_inbox())
    assert len(bot.sent) == 1 and "m3" in bot.sent[0]

    asyncio.run(app.check_inbox())
    assert len(bot.sent) == 1
