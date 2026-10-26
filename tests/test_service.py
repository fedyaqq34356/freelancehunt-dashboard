import asyncio

from conftest import PORTFOLIO, REVIEWS, project_item

from po.service import Service, profile_facts
from po.state import State


class FakeClient:
    def __init__(self, skills=True):
        self.skills = skills
        self.project_calls = []
        self.items = [project_item(1), project_item(2)]
        self.review_pages = 0

    def my_profile(self):
        skills = [{"id": 180, "name": "Разработка ботов", "rating_position": 17}, {"id": 175, "name": "AI", "rating_position": 3}]
        return {"data": {"id": 42, "attributes": {
            "first_name": "Г", "skills": skills if self.skills else [], "completed_projects": 31,
            "positive_reviews": 31, "negative_reviews": 0, "average_grade": 10,
        }}}

    def reviews(self, pid, page=1):
        self.review_pages += 1
        if page == 1:
            return {"data": REVIEWS["data"], "links": {"next": "x"}}
        return {"data": [], "links": {}}

    def portfolio(self, pid, page=1):
        return PORTFOLIO

    def projects(self, page=1, filters=None):
        self.project_calls.append(filters)
        return {"data": self.items}

    def get(self, path, params=None):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        mk = lambda d, w: {"attributes": {"published_at": (now - timedelta(days=d)).isoformat(), "is_winner": w}}
        if params["page[number]"] == 1:
            return {"data": [mk(1, True), mk(5, False), mk(10, False)], "links": {"next": "x"}}
        return {"data": [mk(20, True), mk(40, False)], "links": {"next": "x"}}

    def project(self, pid):
        return {"data": project_item(pid)}


def run(coro):
    return asyncio.run(coro)


def test_cases_cached_and_paginated(tmp_path):
    c = FakeClient()
    s = Service(c, State(str(tmp_path / "s.json")))
    cs = run(s.cases())
    assert [x.ref for x in cs] == ["r77", "p1", "p2"]
    assert c.review_pages == 2
    run(s.cases())
    assert c.review_pages == 2
    run(s.cases(force=True))
    assert c.review_pages == 4


def test_first_run_marks_projects_seen(tmp_path):
    c = FakeClient()
    st = State(str(tmp_path / "s.json"))
    s = Service(c, st)
    assert run(s.new_projects()) == []
    c.items = [project_item(3), project_item(1), project_item(2)]
    assert [p.id for p in run(s.new_projects())] == [3]
    assert c.project_calls[0] == {"skill_id": "180,175"}


def test_projects_filtered_by_profile_skills(tmp_path):
    c = FakeClient()
    s = Service(c, State(str(tmp_path / "s.json")))
    run(s.latest_projects())
    assert c.project_calls == [{"skill_id": "180,175"}]
    c2 = FakeClient(skills=False)
    run(Service(c2, State(str(tmp_path / "s2.json"))).latest_projects())
    assert c2.project_calls == [None]


def test_profile_facts(tmp_path):
    s = Service(FakeClient(), State(str(tmp_path / "s.json")))
    facts = run(s.facts())
    assert "Завершённых проектов на Freelancehunt: 31" in facts
    assert "10 из 10" in facts and "рейтинг" not in facts.lower()
    assert profile_facts({}) == ""
    assert run(s.my_id()) == 42


def test_project_fetch(tmp_path):
    s = Service(FakeClient(), State(str(tmp_path / "s.json")))
    assert run(s.project(55)).id == 55


def test_router_builds_and_owner_check(tmp_path):
    from po.bot import App, build_router
    from po.config import Settings

    st = State(str(tmp_path / "s.json"))
    app = App(Settings("t", "f", "o", owner_id=7), bot=None, service=None, po=None, state=st)
    r = build_router(app)
    assert len(r.message.handlers) >= 6 and len(r.callback_query.handlers) == 5
    assert app.is_owner(7) and not app.is_owner(8)
    app.s.owner_id = None
    assert not app.is_owner(7)
    st["owner_chat_id"] = 9
    assert app.is_owner(9)


def test_bid_stats_counts_recent_and_stops(tmp_path):
    s = Service(FakeClient(), State(str(tmp_path / "s.json")))
    assert run(s.bid_stats(30)) == {"days": 30, "total": 4, "won": 2}


def test_past_clients_from_reviews(tmp_path):
    import copy
    import conftest

    c = FakeClient()
    rev = copy.deepcopy(conftest.REVIEWS)
    rev["data"][0]["attributes"]["from"] = {"id": 99}
    c.reviews = lambda pid, page=1: rev
    s = Service(c, State(str(tmp_path / "s.json")))
    assert run(s.past_clients()) == {99}


def test_send_projects_skips_shown_and_duplicates(tmp_path):
    from po.bot import App
    from po.config import Settings
    from po.projects import parse_project
    from conftest import project_item

    sent = []

    class Bot:
        async def send_message(self, chat, text, **kw):
            sent.append(text)

    st = State(str(tmp_path / "s.json"))
    st["owner_chat_id"] = 1
    st["shown_project_ids"] = [1]
    app = App(Settings("t", "f", "o"), Bot(), Service(FakeClient(), st), po=None, state=st)
    ps = [parse_project(project_item(i)) for i in (1, 2, 2, 3)]
    assert run(app.send_projects(ps)) == 2
    assert len(sent) == 2 and st["shown_project_ids"] == [1, 2, 3]
    assert run(app.send_projects(ps)) == 0


def test_extra_skills_added_to_feed_filter(tmp_path):
    c = FakeClient()
    run(Service(c, State(str(tmp_path / "s.json")), extra_skills=(99, 180)).latest_projects())
    assert c.project_calls == [{"skill_id": "180,175,99"}]
