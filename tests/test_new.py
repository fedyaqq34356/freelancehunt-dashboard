import asyncio

from conftest import FakeLLM, PORTFOLIO, REVIEWS, project_item

from po import competitors, ui
from po.projects import Project
from po.agent import Po, assemble, duration, opening, restated, review_bid
from po.catalog import parse_portfolio, parse_reviews
from po.llm import Meter
from po.matcher import Matcher
from po.projects import parse_project
from po.state import State


def bid_article(login, name, rating, amount, days, projects, text, plus=True, hidden=False):
    body = "Деталі ставки приховані" if hidden else f'<span class="bid-comment"><span class="text-collapse"><span>{text}</span></span></div>'
    return (
        f'<article class="widget bid " id="bid-1" data-rating="{rating}" data-hasplus="{1 if plus else 0}" '
        f'data-amount="{amount}" data-days="{days}"><div class="bid-header">'
        f'<a href="https://freelancehunt.com/ua/freelancer/{login}.html"><img alt="{name}"></a>'
        f'<li class="stats-cell"><span class="x">Проєкти</span> <span class="stats-value"><span class="text-desktop-h6">{projects}</span></span></li>'
        f"</div><div>{body}</article>"
    )


PAGE = (
    "<html>"
    + bid_article("me_login", "Я", 8183, 4000, 2, 31, "моя ставка")
    + bid_article("alice", "Аліса", 1200, 4000, 1, 12, "Найризикованіше тут зведення дублів. " * 8)
    + bid_article("bob", "Боб", 300, 3500, 3, 0, "Готовий зробити.")
    + bid_article("carl", "Карл", 1349, 4000, 1, 6, "", hidden=True)
    + "<p>У списку не показані ставки, приховані замовником</p></html>"
)


RU_ARTICLE = (
    '<article class="widget bid " data-rating="391" data-hasplus="1" data-amount="4000" data-days="1"><div class="bid-header">'
    '<a href="https://freelancehunt.com/freelancer/dan.html"><img alt="Дан"></a>'
    '<li class="stats-cell"><span>Проекты</span> <span class="stats-value"><span class="text-desktop-h6">2</span></span></li></div>'
    '<div> <div data-translation-entity="bid-1" class=" bid-comment unsafe-links-container formatted-text"> '
    '<span class="text-collapse wrap-anywhere"> <span>Добрый день.<br><br>Сделаю скрипт.</span> </span></div></article>'
)


def test_competitors_parse_russian_translated_markup():
    r = competitors.parse(RU_ARTICLE)[0]
    assert (r.login, r.projects, r.days) == ("dan", 2, 1)
    assert r.text == "Добрый день.\nСделаю скрипт."


def test_competitors_parse_skips_me_and_detects_hidden():
    rivals = competitors.parse(PAGE, "me_login")
    assert [r.login for r in rivals] == ["alice", "bob", "carl"]
    a, b, c = rivals
    assert (a.rating, a.amount, a.days, a.projects, a.plus) == (1200, 4000, 1, 12, True)
    assert a.text.startswith("Найризикованіше")
    assert c.hidden and c.text == ""
    assert competitors.hidden_note(PAGE)


def test_competitors_prompt_keeps_only_meaningful_and_summary():
    rivals = competitors.parse(PAGE, "me_login")
    text = competitors.render_for_prompt(rivals)
    assert "Найризикованіше" in text and "Готовий зробити" not in text
    s = competitors.summary(rivals, 64)
    assert s.startswith("видно 3 из 64") and "цены 3500-4000" in s and "содержательных 1" in s


def test_competitors_load_survives_errors(monkeypatch):
    async def boom(url, timeout_ms=30000):
        raise RuntimeError("no browser")

    monkeypatch.setattr(competitors, "fetch_html", boom)
    assert asyncio.run(competitors.load("http://x")) is None

    async def challenge(url, timeout_ms=30000):
        return "<html><title>Just a moment...</title></html>"

    monkeypatch.setattr(competitors, "fetch_html", challenge)
    assert asyncio.run(competitors.load("http://x")) is None

    async def ok(url, timeout_ms=30000):
        return PAGE

    monkeypatch.setattr(competitors, "fetch_html", ok)
    assert [r.login for r in asyncio.run(competitors.load("http://x", "me_login"))] == ["alice", "bob", "carl"]


def test_meter_records_and_summarizes(tmp_path):
    st = State(str(tmp_path / "s.json"))
    m = Meter(st, {"in": 1.0, "cached": 0.1, "out": 2.0, "embed": 0.5})
    with m.measure("bids") as spent:
        m.record(1_000_000, 0, 500_000)
        m.record(embed=1_000_000)
    assert abs(sum(spent) - 2.5) < 1e-9
    with m.measure("cards"):
        m.record(1_000_000, 1_000_000, 0)
    s = m.summary(30)
    assert s["bids"] == 1 and s["cards"] == 1
    assert abs(s["usd"] - 2.6) < 1e-9 and abs(s["bids_usd"] - 2.5) < 1e-9 and abs(s["cards_usd"] - 0.1) < 1e-9
    lines = ui.usage_lines(s, 20)
    assert "$20 хватит примерно на 8 ставок или 200 карточек" in lines[2]


def test_duration_and_minutes_terms():
    assert duration(30, True) == "30 хвилин" and duration(120, True) == "2 години" and duration(60, False) == "1 час"
    p = parse_project(project_item())
    t = assemble("Тело.", {"price": 1000, "minutes": 30, "days": None}, p, "Пишите.")
    assert "Срок: 30 минут" in t and "Бюджет: 1 000 грн" in t


def test_restated_detects_tz_paraphrase():
    tz = "Кладу прайси в папку, скрипт робить один ексель з артикулом, ціною в гривнях за курсом НБУ або вручну заданим курсом, найдешевший постачальник, інші постачальники в окремій колонці."
    para = "Долари перераховуватиму за курсом НБУ або вручну заданим курсом. Найдешевший постачальник по артикулу, інші постачальники з ціною в окремій колонці."
    fresh = "Найризикованіше тут зведення дублів: один артикул пишеться по-різному. Без нормалізації той самий товар пройде як два різні."
    assert restated(para, tz) == 2 and restated(fresh, tz) == 0
    assert any("пересказыва" in i for i in review_bid(para, {}, "UAH", tz))


def test_opening_after_greeting_must_not_restate_tz():
    tz = "Кладу прайси в папку, скрипт робить один ексель з артикулом, ціною в гривнях за курсом НБУ або вручну заданим курсом, найдешевший постачальник, інші постачальники в окремій колонці."
    weak = "Олександре, добрий день. Скрипт робитиме один ексель з артикулом і ціною в гривнях за курсом НБУ. Решта потім."
    strong = "Олександре, добрий день. Найризикованіше тут зведення дублів: один артикул пишеться по-різному. Схожий скрипт у мене вже зводить прайси трьох постачальників."
    assert opening(strong).startswith("Найризикованіше")
    assert any("первая фраза" in i for i in review_bid(weak, {}, "UAH", tz))
    assert not any("ТЗ" in i for i in review_bid(strong, {}, "UAH", tz))


def test_write_bid_gets_rivals_and_new_fields():
    llm = FakeLLM()
    llm.bid = {**llm.bid, "minutes": 60, "hide": True, "hide_reason": "своя идея", "rivals_note": "все пересказывают ТЗ"}
    cs = parse_reviews(REVIEWS) + parse_portfolio(PORTFOLIO)
    p = parse_project(project_item())
    d = asyncio.run(Po(llm).write_bid(p, cs, rivals="1. текст конкурента", rivals_summary="видно 3 из 10"))
    assert "СТАВКИ КОНКУРЕНТОВ (видно 3 из 10)" in llm.calls[0]["prompt"]
    assert d.hide and d.rivals_note == "все пересказывают ТЗ" and d.minutes == 60
    d.cost = 0.0042
    msg = ui.bid_message(p, d)
    assert "📎 <b>Приложи:</b>" in msg and "🙈" in msg and "👀 Конкуренты: видно 3 из 10" in msg
    assert "Стоила $0.0042" in msg and "⏱ 1 ч" in msg


class EmbedLLM(FakeLLM):
    def __init__(self, pick="p1"):
        super().__init__()
        self.pick = pick
        self.embeds = 0

    async def embed(self, texts):
        self.embeds += len(texts)
        return [[1.0, 0.0] if ("прайс" in t.lower() or "цен" in t.lower()) else [0.0, 1.0] for t in texts]

    async def json(self, **kw):
        self.calls.append(kw)
        if kw["name"] == "summaries":
            return {"items": [{"ref": "[p1]", "task": "сводит прайсы поставщиков"}]}
        return {"ref": self.pick, "why": "та же задача"}


def test_matcher_caches_index_and_picks(tmp_path):
    cs = parse_portfolio(PORTFOLIO)
    llm = EmbedLLM()
    m = Matcher(llm, str(tmp_path / "index.json"))
    p = parse_project(project_item(name="Звести прайси постачальників", desc="ціни у різних форматах"))
    case, why = asyncio.run(m.best(p, cs))
    assert case.ref == "p1" and why == "та же задача"
    assert m.task(cs[0]) == f"{cs[0].title}. сводит прайсы поставщиков"
    first_embeds = llm.embeds
    m2 = Matcher(llm, str(tmp_path / "index.json"))
    asyncio.run(m2.best(p, cs))
    assert llm.embeds == first_embeds + 1
    assert asyncio.run(Matcher(EmbedLLM("none"), str(tmp_path / "index.json")).best(p, cs)) is None


PROFILE = {
    "id": 1,
    "attributes": {
        "first_name": "Г",
        "rating_position": 458,
        "skills": [
            {"id": 180, "name": "Разработка ботов", "rating_position": 17},
            {"id": 175, "name": "AI и машинное обучение", "rating_position": 3},
            {"id": 99, "name": "Веб-программирование", "rating_position": 138},
        ],
    },
}


def test_strong_rank_fact_only_for_project_category_in_top20():
    from po.ranks import strong_fact

    ai = parse_project(project_item(skills=("AI и машинное обучение", "Разработка ботов")))
    assert strong_fact(ai, PROFILE) == "3 место из 2 669 в рейтинге категории «AI и машинное обучение» на Freelancehunt"
    assert strong_fact(parse_project(project_item(skills=("Разработка ботов",))), PROFILE).startswith("17 место из 2 692")
    assert strong_fact(parse_project(project_item(skills=("Веб-программирование",))), PROFILE) == ""
    assert strong_fact(parse_project(project_item(skills=("Дизайн",))), PROFILE) == ""


def test_rank_goes_into_prompt_and_profile_shows_positions():
    llm = FakeLLM()
    cs = parse_reviews(REVIEWS)
    asyncio.run(Po(llm).write_bid(parse_project(project_item()), cs, rank="3 место из 2 665"))
    assert "СИЛЬНЫЙ ФАКТ\n3 место из 2 665" in llm.calls[0]["prompt"]
    text = ui.profile_message({"data": PROFILE}, 79, 31, 0, False)
    assert "В общем рейтинге: <b>458</b> / 292 101" in text
    assert "AI и машинное обучение: <b>3</b> / 2 669 👑" in text and "Разработка ботов: <b>17</b> / 2 692 🔥" in text


def test_two_attachments_public_vs_personal_review():
    from po.catalog import render_for_prompt

    cs = parse_reviews(REVIEWS) + parse_portfolio(PORTFOLIO)
    cs[0].public, cs[0].url = True, "https://freelancehunt.com/project/bot/900.html"
    llm = FakeLLM()
    llm.bid = {**llm.bid, "work_ref": "[p1]", "project_ref": "r77"}
    p = parse_project(project_item())
    prof = "https://freelancehunt.com/freelancer/me.html"
    d = asyncio.run(Po(llm).write_bid(p, cs, profile_url=prof))
    assert d.work.ref == "p1" and d.example.ref == "r77"
    assert "http" not in d.text
    msg = ui.bid_message(p, d)
    assert "📎 <b>Пример работы:</b>" in msg and "поставь в поле «Пример проекта»" in msg
    cs[0].public = False
    assert "личный проект" in render_for_prompt(cs[:1])
    cs[0].url = "https://freelancehunt.com/project/dorabotat-bota/1629552.html"
    d2 = asyncio.run(Po(llm).write_bid(p, cs, profile_url=prof))
    assert d2.example.ref == "r77" and "https://freelancehunt.com/project/dorabotat-bota/1629552.html - отзыв заказчика" in d2.text
    cs[0].url = ""
    d3 = asyncio.run(Po(llm).write_bid(p, cs, profile_url=prof))
    assert f"{prof} - отзывы заказчиков в профиле" in d3.text
    assert "🔒 Отзыв из личного проекта" in ui.bid_message(p, d2)


def test_latin_name_flagged_for_cyrillic_project():
    assert any("латиницей" in i for i in review_bid("Dima, добрый день. Текст.", {}, "UAH", "Чат блок в CRM"))
    assert not any("латиницей" in i for i in review_bid("Дима, добрый день.", {}, "UAH", "Чат блок в CRM"))
    assert not any("латиницей" in i for i in review_bid("John, hello.", {}, "USD", "Chat block in CRM"))


def test_service_marks_private_reviews(tmp_path):
    from freelancehunt.client import FreelancehuntError
    from po.service import Service

    class C:
        def my_profile(self):
            return {"data": {"id": 1, "attributes": {}}}

        def reviews(self, pid, page=1):
            return {"data": [
                {"id": 1, "attributes": {"comment": "ok", "project": {"id": 10, "name": "Публичный"}}},
                {"id": 2, "attributes": {"comment": "ok", "project": {"id": 20, "name": "Личный"}}},
            ], "links": {}}

        def portfolio(self, pid, page=1):
            return {"data": []}

        def project(self, pid):
            if pid == 20:
                raise FreelancehuntError(404, "Not Found")
            return {"data": {"attributes": {"description": "<p>Бот пересылает вопросы менеджерам</p>"},
                             "links": {"self": {"web": f"https://freelancehunt.com/project/x/{pid}.html"}}}}

    st = State(str(tmp_path / "s.json"))
    cs = asyncio.run(Service(C(), st).cases())
    assert [(c.public, c.url) for c in cs] == [
        (True, "https://freelancehunt.com/project/x/10.html"),
        (False, "https://freelancehunt.com/project/lichnyiy/20.html"),
    ]
    assert cs[0].text == "Бот пересылает вопросы менеджерам" and "перес" in cs[0]._stems
    assert st["project_info"]["20"] is None and st["project_info"]["10"]["url"].endswith("/10.html")


def test_no_match_means_no_examples_in_bid():
    llm = FakeLLM()
    llm.bid = {**llm.bid, "fit": "low", "cases": [], "work_ref": "", "project_ref": ""}
    p = parse_project(project_item())
    d = asyncio.run(Po(llm).write_bid(p, parse_reviews(REVIEWS) + parse_portfolio(PORTFOLIO)))
    assert d.work is None and d.example is None and d.picks == []
    msg = ui.bid_message(p, d)
    assert "📎" not in msg and "отзыв заказчика" not in d.text
    assert "Лучше пусто, чем притянуто" in llm.calls[0]["instructions"]


def test_slugify_like_site():
    from po.text import slugify

    assert slugify("Доработать бота") == "dorabotat-bota"
    assert slugify("Доопрацювати бота") == "doopratsyuvati-bota"
    assert slugify("Разработка Telegram-бота с ИИ для общения с кандидатками и отбора анкет") == "razrabotka-telegram-bota-ii-dlya-obscheniya"
    assert slugify("") == "project"


def test_move_rank_out_of_preview():
    from po.agent import move_rank

    body = ("Дима, добрый день. В рейтинге разработки ботов на Freelancehunt я на 18-м месте из 2 689. "
            "Важно привязать ответ к диалогу.\nВ проекте «Бот» уже работает передача вопросов.")
    out = move_rank(body)
    assert out.startswith("Дима, добрый день. Важно привязать ответ к диалогу.")
    assert out.endswith("уже работает передача вопросов. В рейтинге разработки ботов на Freelancehunt я на 18-м месте из 2 689.")
    late = "Дима, добрый день. " + "Длинная мысль про задачу заказчика. " * 6 + "У рейтингу AI на Freelancehunt я на 3-му місці."
    assert move_rank(late) == late
    assert move_rank("Без рейтинга.") == "Без рейтинга."


def test_zero_position_is_not_a_fact():
    from po.ranks import strong_fact

    prof = {"attributes": {"skills": [{"id": 22, "name": "Python", "rating_position": 0}]}}
    assert strong_fact(parse_project(project_item(skills=("Python",))), prof) == ""


def test_single_restated_sentence_and_boilerplate_are_flagged():
    tz = "Кладу прайси в папку, скрипт робить один ексель з артикулом, ціною в гривнях за курсом НБУ або вручну заданим курсом, найдешевший постачальник, інші постачальники в окремій колонці."
    one = "Ірино, добрий день. Схожий скрипт у мене вже працює. Долари перераховуватиму за курсом НБУ або вручну заданим курсом."
    assert any("пересказыва" in i for i in review_bid(one, {}, "UAH", tz))
    assert any("шаблонная фраза" in i for i in review_bid("Спосіб підключення перевірю окремо.", {}, "UAH", tz))
    assert not any("шаблонная" in i for i in review_bid("Схожий бот у мене вже працює.", {}, "UAH", tz))


def test_assemble_dedupes_closing_and_speaks_english():
    p = parse_project(project_item())
    t = assemble("Тело. Магазин на OpenCart?", {"price": 1000, "minutes": 60, "start_today": True}, p, "Могу начать сегодня.")
    assert t.count("сегодня") == 1 and "Магазин на OpenCart?" in t
    t = assemble("Тело. Магазин на OpenCart?", {"price": 1000, "days": 2}, p, "На какой платформе магазин?")
    assert "OpenCart" not in t and t.endswith("На какой платформе магазин?")
    en = Project(id=1, name="Scrape reviews", description="Need a scraper", currency="USD")
    t = assemble("Джон, hello.", {"price": 300, "days": 4, "start_today": True}, en, "")
    assert "Timeline: 4 days" in t and "Budget: 300 USD" in t and "Starting today." in t
    t = assemble("Поправлю шапку. Почну сьогодні.", {"price": 1500, "minutes": 120, "start_today": True}, Project(id=2, name="Шапка", description="Поправити тему"), "")
    assert t.count("сьогодні") == 1
