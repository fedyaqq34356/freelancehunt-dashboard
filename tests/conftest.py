import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


SKILL_IDS = {"Разработка ботов": 180, "Розробка ботів": 180, "Парсинг данных": 169, "AI и машинное обучение": 175,
             "Веб-программирование": 99, "Python": 22}


def project_item(pid=101, name="Telegram-бот для записи клиентов", amount=5000, currency="UAH", desc=None, skills=("Разработка ботов",)):
    return {
        "id": pid,
        "type": "project",
        "attributes": {
            "name": name,
            "description": desc or "Нужен бот для записи клиентов в салон с оплатой картой и админкой для мастера.",
            "budget": {"amount": amount, "currency": currency} if amount else None,
            "bid_count": 3,
            "skills": [{"id": SKILL_IDS.get(s, 1000 + i), "name": s} for i, s in enumerate(skills)],
            "employer": {"login": "client1", "first_name": "Иван", "last_name": "П."},
            "is_only_for_plus": False,
            "status": {"id": 11, "name": "Прием ставок"},
        },
        "links": {"self": {"api": f"https://api.freelancehunt.com/v2/projects/{pid}", "web": f"https://freelancehunt.com/project/x/{pid}.html"}},
    }


PORTFOLIO = {
    "data": [
        {
            "id": 1,
            "attributes": {
                "name": "AI-агент обновления цен и наличия для интернет-магазина",
                "comment": "Собирает прайсы поставщиков из почты и файлов, сопоставляет с каталогом, пересчитывает цены.",
                "skill": {"id": 5, "name": "Python"},
            },
            "links": {"self": {"web": "https://freelancehunt.com/freelancer/x/portfolio/1.html"}},
        },
        {
            "id": 2,
            "attributes": {
                "name": "Телеграм бот для проведения розыгрышей",
                "description": "Розыгрыши в каналах, проверка подписки, случайный выбор победителя.",
                "skill": {"id": 6, "name": "Разработка ботов"},
            },
        },
        {"id": 3, "attributes": {"name": ""}},
    ]
}

REVIEWS = {
    "data": [
        {
            "id": 77,
            "attributes": {
                "comment": "Георгий сделал Telegram-бота быстро и с учетом всех пожеланий.",
                "grades": {"total": 5.0},
                "project": {
                    "id": 900,
                    "name": "Разработка Telegram-бота для записи клиентов и оплаты",
                    "budget": {"amount": 4200, "currency": "UAH"},
                },
            },
        }
    ],
    "links": {},
}


class FakeLLM:
    """Отвечает заготовками и запоминает вызовы."""

    def __init__(self, bid=None, human=None):
        self.calls = []
        self.bid = bid or {
            "fit": "high",
            "cases": [{"ref": "[r77]", "why": "тот же бот записи"}, {"ref": "p999", "why": "выдуманный"}, {"ref": "r77", "why": "дубль"}],
            "bid": "Здравствуйте! У меня уже работает бот записи — с оплатой и админкой.",
            "price": 4500,
            "days": 4,
            "note": "Уточнить платёжку",
        }
        self.human = list(human or ["У меня уже работает бот записи с оплатой и админкой. Сделаю за 4 дня."])

    async def json(self, *, instructions, prompt, schema, name, effort="low", max_tokens=1500):
        self.calls.append({"name": name, "prompt": prompt, "instructions": instructions})
        if name == "bid":
            return self.bid
        return {"bid": self.human.pop(0) if len(self.human) > 1 else self.human[0]}


@pytest.fixture
def fake_llm():
    return FakeLLM()
