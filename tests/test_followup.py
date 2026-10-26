from datetime import datetime, timedelta, timezone

from po import followup, ui
from po.catalog import Case
from po.competitors import Rival

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
ME, CLIENT = 1771211, 555


def msg(mid, sender, hours_ago, text="текст"):
    return {"id": mid, "attributes": {"posted_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "message_html": text, "participants": {"from": {"id": sender}}}}


def thread(visited_hours_ago):
    return {"id": 9, "attributes": {"subject": "Бот", "participants": {
        "from": {"id": CLIENT, "first_name": "Іван", "last_name": "П.", "visited_at": (NOW - timedelta(hours=visited_hours_ago)).isoformat()},
        "to": {"id": ME}}}}


def test_loss_project_id_from_feed():
    m = 'Роберт выбрал другого исполнителя проекта <a href="https://freelancehunt.com/project/skript/1661107.html#bids">X</a>'
    assert followup.loss_project_id(m) == 1661107
    assert followup.loss_project_id('Роберт добавил проект <a href="https://freelancehunt.com/project/x/1.html">') is None


def test_stale_thread_rules():
    msgs = [msg(1, CLIENT, 50), msg(2, ME, 30), msg(3, followup.SYSTEM_SENDER, 1)]
    s = followup.stale_thread(thread(visited_hours_ago=2), msgs, ME, NOW)
    assert s == {"thread_id": 9, "message_id": 2, "subject": "Бот", "client": "Іван П.", "hours": 30}
    assert followup.stale_thread(thread(visited_hours_ago=40), msgs, ME, NOW) is None
    assert followup.stale_thread(thread(2), [msg(1, ME, 5)], ME, NOW) is None
    assert followup.stale_thread(thread(2), [msg(1, ME, 30), msg(2, CLIENT, 3)], ME, NOW) is None
    assert followup.stale_thread(thread(2), [msg(1, ME, 24 * 20)], ME, NOW) is None


def test_render_dialog_skips_system_and_labels():
    d = followup.render_dialog([msg(1, CLIENT, 5, "Привет"), msg(2, followup.SYSTEM_SENDER, 4, "сист"), msg(3, ME, 3, "Ответ")], ME)
    assert "Заказчик" in d and "Я (" in d and "сист" not in d
    assert d.index("Привет") < d.index("Ответ")


def test_build_loss_and_message():
    project = {"id": 7, "attributes": {"name": "Скрипт", "bid_count": 66, "budget": {"amount": 4000, "currency": "UAH"},
               "freelancer": {"id": 3, "login": "val", "first_name": "Валерій", "last_name": "П."}}}
    winner = {"attributes": {"completed_projects": 6, "rating": 1349, "is_plus_active": True}}
    wbid = Rival(login="val", name="Валерій П.", amount=4000, days=1, hidden=True)
    mine = {"attributes": {"budget": {"amount": 4000}, "days": 2}}
    loss = followup.build_loss(project, winner, wbid, mine, 8183)
    text = followup.loss_message(loss)
    assert "Победил Валерій П.: 6 проектов, рейтинг 1349, Plus" in text
    assert "Его ставка: 4000 UAH, 1 дн. Текст скрыт." in text and "Твоя: 4000 UAH, 2 дн." in text
    assert "срок у него короче" in text and "решил не профиль" in text and "цена у него ниже" not in text


def test_weekly_digest_counts():
    losses = [
        {"date": "2026-10-25", "winner_projects": 6, "winner_rating": 1349, "my_rating": 8183, "winner_days": 1, "my_days": 2,
         "winner_amount": 4000, "my_amount": 4000, "winner_hidden": True},
        {"date": "2026-10-01", "winner_projects": 99},
    ]
    t = followup.weekly_digest(losses, {"total": 10, "won": 2}, NOW)
    assert "Ставок: 10, выиграно: 2" in t and "Проигрышей с известным победителем: 1" in t
    assert "Рейтинг ниже твоего: 1. Срок короче: 1. Цена ниже: 0. Ставка скрыта: 1." in t
    assert "Разборов проигрышей за неделю нет" in followup.weekly_digest([], {}, NOW)


def make_cases():
    return [
        Case("r1", "review", "Разработка сайта", budget="20 000 UAH", review="Сайт работает отлично", client_id=10, client_name="Vlad Y.", date="2026-06-01"),
        Case("r2", "review", "Доработка бота", budget="1 800 UAH", review="Быстро", client_id=10, client_name="Vlad Y.", date="2026-10-09"),
        Case("r3", "review", "PIM", budget="27 000 UAH", review="Стартуем второй этап", client_id=20, client_name="Виталий", date="2026-10-17"),
        Case("p1", "portfolio", "CRM"),
    ]


def test_past_clients_and_due_reminders():
    clients = followup.past_clients(make_cases())
    assert [c.name for c in clients] == ["Vlad Y.", "Виталий"]
    vlad = clients[0]
    assert vlad.total == 21800 and vlad.last_date == "2026-10-09"
    assert [c.name for c in followup.due_for_reminder(clients, "2026-11-05")] == ["Vlad Y."]
    text = followup.render_client(vlad)
    assert text.index("Разработка сайта") < text.index("Доработка бота") and "21800 грн" in text
    card = ui.client_card(vlad)
    assert "2 проектов, около 21 800 грн, последний 2026-10-09" in card
    assert ui.client_kb(10).inline_keyboard[0][0].callback_data == "idea:10"
    assert ui.nudge_kb(9).inline_keyboard[0][0].callback_data == "nudge:9"


def test_ideas_message():
    c = followup.past_clients(make_cases())[0]
    t = ui.ideas_message(c, {"ideas": ["Мониторинг", "Поддержка"], "message": "Влад, добрый день.", "price_hint": "4000 грн/мес"}, 0.001)
    assert "1. Мониторинг" in t and "<pre>Влад, добрый день.</pre>" in t and "Стоило $0.0010" in t


def test_new_project_id_from_feed():
    m = 'Євгеній добавил проект <a href="https://freelancehunt.com/project/parsing/1661200.html">Парсинг</a>'
    assert followup.new_project_id(m, {"project": "https://api.freelancehunt.com/v2/projects/1661200"}) == 1661200
    assert followup.new_project_id(m, {}) == 1661200
    assert followup.new_project_id("Ваш рейтинг вырос", {}) is None
