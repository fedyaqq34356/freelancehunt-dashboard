import asyncio

from conftest import PORTFOLIO, REVIEWS, FakeLLM, project_item

from po import humanizer, ui
from po.agent import Po
from po.catalog import best_matches, parse_portfolio, parse_reviews, render_for_prompt
from po.projects import card, parse_project, passes
from po.service import select_new
from po.state import State


def cases():
    return parse_reviews(REVIEWS) + parse_portfolio(PORTFOLIO)


def test_parse_project():
    p = parse_project(project_item())
    assert p.id == 101
    assert p.amount == 5000 and p.currency == "UAH"
    assert p.url == "https://freelancehunt.com/project/x/101.html"
    assert p.skills == ["Разработка ботов"]
    assert p.employer == "Иван П." and p.employer_name == "Иван"
    assert p.budget == "5 000 UAH"


def test_parse_project_without_budget_and_link():
    item = project_item(amount=None)
    del item["links"]
    p = parse_project(item)
    assert p.amount is None and p.budget == "бюджет не указан"
    assert p.url.endswith("/101.html")


def test_passes_min_budget():
    assert passes(parse_project(project_item(amount=5000)), 3000)
    assert not passes(parse_project(project_item(amount=1000)), 3000)
    assert passes(parse_project(project_item(amount=None)), 3000)
    assert passes(parse_project(project_item(amount=100, currency="USD")), 3000)
    assert passes(parse_project(project_item(amount=1)), 0)


def test_card_escapes_html_and_shows_match():
    p = parse_project(project_item(name="Бот <b>A & B</b>", desc="x < y " * 200))
    text = card(p, cases()[0])
    assert "<b>Бот A &amp; B</b>" in text and "x &lt; y" in text
    assert "Похоже на твоё" in text
    assert len(text) < 1000


def test_parse_catalog():
    cs = cases()
    assert [c.ref for c in cs] == ["r77", "p1", "p2"]
    r = cs[0]
    assert r.kind == "review" and r.budget == "4 200 UAH" and r.grade == 5.0
    assert "быстро" in r.review
    assert cs[1].url.endswith("/portfolio/1.html")
    assert "прайсы поставщиков" in cs[1].text
    assert cs[2].url == ""


def test_best_matches_picks_relevant_case():
    top = best_matches("Нужен телеграм бот для записи клиентов с оплатой", cases(), n=1)
    assert top and top[0].ref == "r77"
    top = best_matches("агент обновления цен поставщиков для магазина", cases(), n=1)
    assert top[0].ref == "p1"
    assert best_matches("дизайн логотипа для кофейни", cases()) == []


def test_render_for_prompt_has_refs_and_reviews():
    text = render_for_prompt(cases())
    assert "[r77]" in text and "[p1]" in text
    assert "отзыв:" in text


def test_select_new_dedup_pause_and_budget(tmp_path):
    st = State(str(tmp_path / "s.json"))
    items = [project_item(1), project_item(2, amount=500), project_item(3)]
    assert [p.id for p in select_new(items, st)] == [3, 2, 1]
    assert select_new(items, st) == []
    st["min_budget"] = 1000
    assert [p.id for p in select_new([project_item(4, amount=500), project_item(5)], st)] == [5]
    st["paused"] = True
    assert select_new([project_item(6)], st) == []
    assert 6 in st["seen_project_ids"]


def test_state_roundtrip_and_caps(tmp_path):
    path = tmp_path / "d" / "s.json"
    st = State(str(path))
    st["seen_project_ids"] = list(range(5000))
    st["reply_map"] = {str(i): i for i in range(1500)}
    st.save()
    again = State(str(path))
    assert len(again["seen_project_ids"]) == 3000 and again["seen_project_ids"][-1] == 4999
    assert len(again["reply_map"]) == 1000
    assert again["min_budget"] == 0


def test_state_survives_broken_file(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{oops")
    assert State(str(path))["paused"] is False


def test_humanizer_cleanup_and_tells():
    raw = "Здравствуйте! У меня уже есть бот — с оплатой и **админкой** 🚀. Буду рад сотрудничеству!"
    assert {"длинное тире", "markdown или список", "эмодзи", "шаблонная концовка", "восклицательный знак"} <= set(
        humanizer.find_tells(raw)
    )
    out = humanizer.cleanup(raw)
    assert "—" not in out and "**" not in out and "🚀" not in out and "!" not in out
    assert "бот, с оплатой" in out
    assert humanizer.find_tells("У меня уже работает такой бот. Сделаю за 3 дня, 4000 грн.") == []


def test_po_writes_bid_with_only_real_cases():
    llm = FakeLLM()
    draft = asyncio.run(Po(llm).write_bid(parse_project(project_item()), cases()))
    assert [p.case.ref for p in draft.picks] == ["r77"]
    assert draft.price == 4500 and draft.days == 4 and draft.currency == "UAH"
    assert draft.text.startswith("У меня уже работает бот записи")
    assert [c["name"] for c in llm.calls] == ["bid", "humanize"]
    assert "[r77]" in llm.calls[0]["prompt"] and "ПРОЕКТ" in llm.calls[0]["prompt"]
    assert "Образцы его реальных выигравших ставок" in llm.calls[0]["instructions"]
    assert "ставь ровно бюджет" in llm.calls[0]["instructions"]
    assert "Заказчик: Иван (завершённых проектов у него: 0)" in llm.calls[0]["prompt"]
    assert "УЖЕ РАБОТАЛ" not in llm.calls[0]["prompt"]
    assert llm.calls[1]["instructions"] == humanizer.RULES


def test_po_retries_humanizer_then_cleans():
    llm = FakeLLM(human=["Бот уже есть — работает!", "Бот уже есть — работает."])
    draft = asyncio.run(Po(llm).write_bid(parse_project(project_item()), cases()))
    assert [c["name"] for c in llm.calls] == ["bid", "humanize", "humanize"]
    assert "остались признаки" in llm.calls[2]["prompt"]
    assert "—" not in draft.text and "!" not in draft.text


def test_po_again_passes_previous_variant():
    llm = FakeLLM()
    asyncio.run(Po(llm).write_bid(parse_project(project_item()), cases(), "Место: 3", previous="старый текст"))
    assert "старый текст" in llm.calls[0]["prompt"]
    assert "ФАКТЫ ПРОФИЛЯ\nМесто: 3" in llm.calls[0]["prompt"]


def test_bid_message_and_keyboards():
    p = parse_project(project_item())
    draft = asyncio.run(Po(FakeLLM()).write_bid(p, cases()))
    text = ui.bid_message(p, draft)
    assert "<pre>" in text and "4 500 UAH" in text and "4 дн." in text
    assert "(есть отзыв)" in text
    kb = ui.project_kb(p).inline_keyboard[0]
    assert kb[0].url == p.url and kb[1].callback_data == "bid:101"
    kb = ui.bid_kb(p).inline_keyboard[0]
    assert kb[0].url == p.url and kb[1].callback_data == "again:101"
    for row in ui.budget_kb(2000).inline_keyboard:
        for b in row:
            assert len(b.callback_data.encode()) <= 64
    assert any(b.text.startswith("•") for row in ui.budget_kb(2000).inline_keyboard for b in row)


def test_menu_toggles_pause_button():
    assert ui.menu(False).keyboard[0][1].text == ui.BTN_PAUSE
    assert ui.menu(True).keyboard[0][1].text == ui.BTN_RESUME


def test_review_bid_flags_plans_generic_length_and_refs():
    from po.agent import review_bid

    assert review_bid("Иван, у меня уже работает бот записи с оплатой. Подключу календарь. 4000 грн за 4 дня, оплата картой или Monobank?") == []
    issues = review_bid("Проверю код, подключу бота, настрою сервер и сделаю. У меня есть опыт. " + "x" * 700 + " [r12]")
    assert len(issues) == 4


def test_po_rewrites_bid_when_critic_finds_issues():
    bad = {"fit": "high", "cases": [], "bid": "Проверю, настрою, подключу и сделаю. Есть опыт.", "price": 1, "days": 1, "note": ""}
    good = {"fit": "high", "cases": [{"ref": "r77", "why": "x"}], "bid": "У меня уже работает бот записи.", "price": 2, "days": 2, "note": ""}

    class Seq(FakeLLM):
        def __init__(self):
            super().__init__()
            self.bids = [bad, good]

        async def json(self, **kw):
            if kw["name"] == "bid":
                self.calls.append(kw)
                return self.bids.pop(0)
            return await super().json(**kw)

    llm = Seq()
    draft = asyncio.run(Po(llm).write_bid(parse_project(project_item()), cases()))
    assert draft.price == 2 and [p.case.ref for p in draft.picks] == ["r77"]
    assert "Перепиши ставку" in llm.calls[1]["prompt"] and "слишком много обещаний" in llm.calls[1]["prompt"]


def test_cleanup_removes_refs():
    assert humanizer.cleanup("Сайт работает ([r588708]). Бот [p12] тоже.") == "Сайт работает. Бот тоже."


def test_cleanup_keeps_number_ranges():
    assert humanizer.cleanup("Срок 2–3 дня — нормально") == "Срок 2-3 дня, нормально"


def test_rewrite_keeps_cases_if_model_drops_them():
    bad = {"fit": "high", "cases": [{"ref": "r77", "why": "x"}], "bid": "Имею большой опыт.", "price": 1, "days": 1, "note": ""}
    good = {"fit": "high", "cases": [], "bid": "Бот записи уже работает.", "price": 2, "days": 2, "note": ""}

    class Seq(FakeLLM):
        def __init__(self):
            super().__init__()
            self.bids = [bad, good]

        async def json(self, **kw):
            if kw["name"] == "bid":
                return self.bids.pop(0)
            return await super().json(**kw)

    draft = asyncio.run(Po(Seq()).write_bid(parse_project(project_item()), cases()))
    assert [p.case.ref for p in draft.picks] == ["r77"] and draft.price == 2


def test_review_bid_flags_hourly_rate_and_self_doubt():
    from po.agent import review_bid

    assert any("почасовая" in i for i in review_bid("Работаю по ставке $10/ч."))
    assert review_bid("Готового WebApp среди работ нет.")
    assert review_bid("У меня есть отдельные работы по ботам.")
    assert review_bid("Моя ставка 10 USD/час.") and review_bid("Работаю за 400 грн в час.")
    assert review_bid("У меня есть завершённая доработка сайта.")
    assert not review_bid("За 5 000 грн и 2 дня. Срок 3 часа на созвон?")


def test_hot_and_repeat_marks():
    from po.projects import is_hot

    def proj(nb, done, skill):
        item = project_item(skills=(skill,))
        item["attributes"]["bid_count"] = nb
        item["attributes"]["employer"]["completed_projects"] = done
        item["attributes"]["employer"]["id"] = 5
        return parse_project(item)

    hot = proj(12, 5, "Парсинг данных")
    assert is_hot(hot) and hot.employer_id == 5 and hot.employer_done == 5
    assert not is_hot(proj(25, 5, "Парсинг данных"))
    assert not is_hot(proj(12, 1, "AI и машинное обучение"))
    assert not is_hot(proj(12, 5, "Разработка ботов"))
    assert card(hot).startswith("🔥 <b>")
    assert "у заказчика проектов: 5" in card(hot)
    weak = proj(60, 0, "Разработка ботов")
    assert card(weak).startswith("<b>")
    rep = card(weak, repeat=True)
    assert rep.startswith("🤝 <b>") and "Уже работали" in rep


def test_repeat_client_goes_into_prompt():
    llm = FakeLLM()
    p = parse_project(project_item())
    p.employer_id = 555
    cs = cases()
    cs[0].client_id = 555
    asyncio.run(Po(llm).write_bid(p, cs, repeat=True))
    assert "УЖЕ РАБОТАЛ С ФРИЛАНСЕРОМ" in llm.calls[0]["prompt"]
    assert "Разработка Telegram-бота для записи клиентов и оплаты" in llm.calls[0]["prompt"].split("КАТАЛОГ")[0]


def test_review_client_id_parsed():
    data = {"data": [{"id": 1, "attributes": {"comment": "ok", "from": {"id": 42}, "project": {"name": "X"}}}]}
    assert parse_reviews(data)[0].client_id == 42


def test_profile_message_with_stats():
    text = ui.profile_message({"data": {"attributes": {"first_name": "Г"}}}, 79, 31, 0, False, {"days": 30, "total": 20, "won": 3})
    assert "Ставки за 30 дней: 20, выиграно 3 (15%)" in text and "🔥" in text


def test_matcher_ignores_review_praise_and_keeps_1c():
    from po.catalog import Case

    cs = [
        Case("r1", "review", "Парсер для розетки", text="", review="Рекомендую, можна працювати, все супер"),
        Case("p1", "portfolio", "PIM-система", text="Каталог товаров, загрузка из 1С, аналитика цен"),
        Case("p2", "portfolio", "Лендинг", text="Сайт для школы"),
    ]
    top = best_matches("AI-агенти для аналітики звітів 1С, рекомендую можна працювати", cs, n=1, min_score=0.1)
    assert top[0].ref == "p1"


def test_big_price_requires_two_stages():
    from po.agent import review_bid

    one = {"price": 45000, "stages": []}
    assert any("2 этапа" in i for i in review_bid("Текст.", one, "UAH"))
    two = {"price": 37000, "stages": [{"title": "a", "price": 20000, "days": 7}, {"title": "b", "price": 17000, "days": 5}]}
    assert not any("этап" in i for i in review_bid("Текст.", two, "UAH"))
    assert not any("этап" in i for i in review_bid("Текст.", {"price": 20000, "stages": []}, "UAH"))
    assert not any("этап" in i for i in review_bid("Текст.", {"price": 900, "stages": []}, "USD"))


def test_stages_shown_in_bid_message():
    p = parse_project(project_item())
    bid = {"fit": "high", "cases": [], "bid": "Текст ставки.", "price": 37000, "days": 12, "note": "",
           "stages": [{"title": "основа", "price": 20000, "days": 7}, {"title": "доводка", "price": 17000, "days": 5}]}
    d = asyncio.run(Po(FakeLLM(bid=bid)).write_bid(p, cases()))
    text = ui.bid_message(p, d)
    assert "Этап 1: 20 000 UAH, 7 дн. · основа" in text and "Этап 2: 17 000 UAH, 5 дн. · доводка" in text


def test_assemble_terms_ru_uk_and_stages():
    from po.agent import assemble, plural_days

    assert [plural_days(n, True) for n in (1, 3, 5, 11, 22)] == ["день", "дні", "днів", "днів", "дні"]
    assert [plural_days(n, False) for n in (1, 2, 7)] == ["день", "дня", "дней"]
    ru = parse_project(project_item())
    t = assemble("Тело.", {"price": 4000, "days": 3, "start_today": True}, ru, "Пишите, обсудим детали.")
    assert t == "Тело.\n\nСрок: 3 дня\nБюджет: 4 000 грн\nНачинаю сегодня.\n\nПишите, обсудим детали."
    uk = parse_project(project_item(name="Створення AI-агентів", desc="Нас цікавить аналітика звітів 1С і підключення"))
    stages = [{"title": "основна частина.", "price": 20000, "days": 7}, {"title": "доводка", "price": 17000, "days": 5}]
    t = assemble("Тіло.", {"price": 37000, "days": 12, "stages": stages}, uk, "Пишіть.")
    assert "Етап 1 (основна частина): 20 000 грн, 7 днів\nЕтап 2 (доводка): 17 000 грн, 5 днів" in t
    assert "Бюджет" not in t and t.endswith("Пишіть.")


def test_assemble_drops_duplicated_closing():
    from po.agent import assemble

    p = parse_project(project_item())
    t = assemble("Тело. Как бот определяет профиль?", {"price": 1700, "days": 1}, p, "Как бот определяет профиль?")
    assert t.count("Как бот определяет профиль?") == 1 and t.startswith("Тело.\n\nСрок")
