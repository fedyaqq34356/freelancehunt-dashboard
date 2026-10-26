"""По: подбирает кейсы под проект и пишет ставку."""
import re
from dataclasses import dataclass, field
from typing import Optional

from . import humanizer
from .catalog import Case, render_for_prompt
from .llm import LLM
from .projects import Project
from .text import clip

PLAN_VERBS = re.compile(
    r"\b(сделаю|проверю|подключу|настрою|добавлю|реализую|разработаю|сверю|посмотрю|напишу|интегрирую|доработаю|"
    r"создам|соберу|внедрю|проанализирую|изучу|перепишу|оптимизирую|разберусь|перевірю|зроблю|додам|налаштую|підключу)\b",
    re.I,
)
GENERIC = re.compile(
    r"(есть|имею|маю)\s+(\w+\s+)?(опыт|досвід)|у меня есть (\w+\s+){0,2}(работ|проект|доработк)|делал похож|робив схож|каталог"
    r"|среди (моих )?работ нет|готово\w* .{0,30}нет|проблем (с реализацией )?не (будет|возникнет)",
    re.I,
)
HOURLY = re.compile(r"\$\s?\d+\s?/\s?ч|ставк\w* \$|\d+\s?(грн|uah|usd|eur|\$)?\s?(/|в)\s?(ч\b|час)", re.I)
REF = re.compile(r"[rp]\d+")
MAX_LEN = 700

BID_RULES = """Ты По. Пишешь ставку на Freelancehunt от первого лица фрилансера. Он делает на Python Telegram-ботов, парсеры, AI-агентов и автоматизацию, сайты, CRM, админки.
Цель: чтобы заказчик выбрал его или хотя бы написал.

Что известно из 306 его прошлых ставок:
- Почти все тексты ставок шаблонные («изучил ТЗ, имею большой опыт, пишите»), и у конкурентов так же. Выделяется ставка, по которой видно, что человек вник именно в эту задачу.
- Самая сильная его победа (52 конкурента): коротко описал, как будет устроено решение именно под это ТЗ (роли, статусы, оплата, особые случаи), и показал похожую готовую систему.
- Похожий готовый проект с конкретикой (что в нём уже работает) и ссылкой/вложением выигрывает чаще.
- Срок и бюджет прямо в тексте выигрывают чаще, чем без них. «Начинаю сегодня» на небольших задачах работает.
- Если заказчик уже работал с ним, это лучший аргумент: такие ставки не проигрывали.
Исследования площадок говорят то же: персонализированный текст повышает шанс найма, шаблонный снижает, а текст, который звучит как написанный нейросетью, перестаёт что-то значить для заказчика.

Структура (держи её, это его живой стиль, который выигрывал):
1. «Имя, добрый день.» (или «Добрий день» на украинском). Если заказчик уже работал с ним, сразу второй фразой: «Уже работали с вами» и что делали.
2. 1-3 предложения по сути ЕГО задачи: как будет устроено решение именно под это ТЗ, с 1-2 конкретными деталями из описания (роли, источники данных, интеграции, особые случаи). Это не план этапов, а короткое «как это будет работать», чтобы было видно, что он понял задачу лучше других.
3. Похожая готовая система из каталога: что в ней уже реализовано и почему это ускоряет его задачу. Если подходящая работа есть в портфолио ([p...]), можно сказать «в прикреплённом проекте уже реализовано ...». Если по похожему проекту есть сильный отзыв, одна короткая фраза о нём.
4. Отдельными строками: «Срок: ...» и «Бюджет: ...». Если задача маленькая и реально делается за день, добавь «Начинаю сегодня».
5. Закрытие «Пишите, обсудим детали.» Если в ТЗ не хватает ключевой детали, вместо этого один короткий вопрос по ней.

Правила:
- 300-650 знаков. Язык проекта (русский или украинский).
- Только факты из каталога и профиля. Готовой системе не приписывай того, чего про неё не написано. Почасовую ставку и условия заказчика не выдавай за свои.
- Не пиши «имею большой опыт», «у меня есть опыт», «проблем с реализацией не будет»: это есть у всех. Вместо этого конкретная система или конкретная деталь решения.
- Если похожего мало, не пиши, чего у тебя нет. Сильнее опирайся на пункт 2 и ближайшую реальную систему.
- Ref кейсов ([r...], [p...]) в текст не вставляй. Слово «каталог» не используй.
- Без markdown, эмодзи, восклицаний и длинных тире.

Как выбирать кейсы: по сути задачи (что система делает, с какими данными и сервисами работает). Кейсы с отзывом ([r...]) ценнее при равной похожести. 1-3 кейса, только ref из каталога.

Цена в валюте проекта. Если бюджет указан, ставь ровно бюджет: все его выигранные ставки были ровно по бюджету, ставки ниже бюджета не выиграли ни разу. Скидку не предлагай, готовая основа значит «быстрее и надёжнее», а не «дешевле». Без бюджета ориентируйся на бюджеты похожих кейсов. Срок реалистичный и короткий.
note: подсказка фрилансеру, не заказчику: риск, что уточнить, стоит ли браться.

Образцы его реальных выигравших ставок (имена заказчиков заменены). Факты в них про другие проекты, бери из них только тон и структуру.

Образец 1 (52 конкурента, выиграл):
Денисе, ТЗ прочитав повністю, логіка зрозуміла.
Бота напишу на Python з aiogram 3, база PostgreSQL. Три ролі через окремі FSM-стани, кожен бачить тільки свій інтерфейс. Статуси замовлень оновлюються у клієнта автоматично, коли кур'єр натискає кнопку. Нестандартні замовлення з фото йдуть окремим сценарієм, ціну призначає адмін.
У портфоліо є AI-рекрутинговий бот з реєстрацією, кількома ролями, адмін-панеллю та обробкою медіа. Структура дуже схожа, тому база і логіка ролей займуть значно менше часу.
Термін: 5 днів
Бюджет: 4200 грн
Пишіть

Образец 2 (выиграл):
Андрію, добрий день.
Є кейс AI-рекрутингового бота з обробкою медіа, реєстрацією та персоналізованими відповідями через ШІ.
Зроблю на Python: aiogram 3, Claude API, Whisper для транскрипції української та російської, Google Drive Service Account.
Термін: 2-3 дні
Бюджет: 4500 грн
Пишіть."""

BID_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fit": {"type": "string", "enum": ["high", "medium", "low"]},
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"ref": {"type": "string"}, "why": {"type": "string"}},
                "required": ["ref", "why"],
            },
        },
        "bid": {"type": "string"},
        "price": {"type": ["integer", "null"]},
        "days": {"type": ["integer", "null"]},
        "note": {"type": "string"},
    },
    "required": ["fit", "cases", "bid", "price", "days", "note"],
}

HUMAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"bid": {"type": "string"}},
    "required": ["bid"],
}

MAX_CASES_IN_PROMPT = 120


@dataclass
class Pick:
    case: Case
    why: str


@dataclass
class BidDraft:
    text: str
    fit: str
    picks: list[Pick] = field(default_factory=list)
    price: Optional[int] = None
    days: Optional[int] = None
    currency: str = ""
    note: str = ""


def render_project(p: Project) -> str:
    return "\n".join(
        [
            f"Название: {p.name}",
            f"Заказчик: {p.employer_name or 'имя неизвестно'} (завершённых проектов у него: {p.employer_done})",
            f"Бюджет: {p.budget}",
            f"Навыки: {', '.join(p.skills) or 'не указаны'}",
            f"Ставок уже: {p.bid_count}",
            "Описание:",
            clip(p.description, 3500) or "(пусто)",
        ]
    )


def review_bid(text: str) -> list[str]:
    """Проверка ставки без модели: план работ, общие слова, длина."""
    issues = []
    plan = PLAN_VERBS.findall(text)
    if len(plan) > 3:
        issues.append(f"слишком много обещаний сделать ({', '.join(plan)}), опиши, как будет устроено решение, а не список действий")
    if GENERIC.search(text):
        issues.append("общая фраза про опыт или слово «каталог», замени конкретной готовой системой")
    if HOURLY.search(text):
        issues.append("почасовая ставка, убери её, называй только цену за работу")
    if len(text) > MAX_LEN:
        issues.append(f"слишком длинно ({len(text)} знаков), нужно до 650")
    if re.search(r"\[[rp]\d+\]", text):
        issues.append("в тексте служебные ref, убери их")
    return issues


class Po:
    def __init__(self, llm: LLM):
        self.llm = llm

    async def write_bid(
        self, project: Project, cases: list[Case], facts: str = "", previous: Optional[str] = None, repeat: bool = False
    ) -> BidDraft:
        catalog = cases[:MAX_CASES_IN_PROMPT]
        past = [c for c in catalog if repeat and c.client_id and c.client_id == project.employer_id]
        prompt = f"ПРОЕКТ\n{render_project(project)}"
        if repeat:
            prompt += "\nЭТОТ ЗАКАЗЧИК УЖЕ РАБОТАЛ С ФРИЛАНСЕРОМ. Прошлые проекты с ним: " + (
                "; ".join(c.title for c in past) or "есть"
            )
        prompt += f"\n\nКАТАЛОГ МОИХ РАБОТ\n{render_for_prompt(catalog)}"
        if facts:
            prompt += f"\n\nФАКТЫ ПРОФИЛЯ\n{facts}"
        if previous:
            prompt += f"\n\nПРЕДЫДУЩИЙ ВАРИАНТ (не повторяй его, напиши по-другому, можно с другими кейсами):\n{previous}"
        raw = await self.llm.json(instructions=BID_RULES, prompt=prompt, schema=BID_SCHEMA, name="bid", effort="medium")
        first = raw
        for _ in range(2):
            issues = review_bid(raw.get("bid", ""))
            if not issues:
                break
            fix = f"{prompt}\n\nТВОЙ ЧЕРНОВИК\n{raw.get('bid', '')}\n\nПерепиши ставку. Проблемы: {'; '.join(issues)}."
            raw = await self.llm.json(instructions=BID_RULES, prompt=fix, schema=BID_SCHEMA, name="bid", effort="medium")
        if not raw.get("cases"):
            raw["cases"] = first.get("cases") or []

        by_ref = {c.ref: c for c in catalog}
        picks = []
        for item in raw.get("cases") or []:
            m = REF.search(str(item.get("ref", "")))
            case = by_ref.get(m.group(0)) if m else None
            if case and all(p.case.ref != case.ref for p in picks):
                picks.append(Pick(case, item.get("why", "")))
        text = await self.humanize(raw.get("bid", ""))
        return BidDraft(
            text=text,
            fit=raw.get("fit", "medium"),
            picks=picks[:3],
            price=raw.get("price"),
            days=raw.get("days"),
            currency=project.currency or "UAH",
            note=raw.get("note", ""),
        )

    async def humanize(self, text: str) -> str:
        """Humanizer: правка моделью, повтор с подсказкой, если признаки остались, и механическая чистка."""
        prompt = text
        for _ in range(2):
            out = await self.llm.json(
                instructions=humanizer.RULES, prompt=prompt, schema=HUMAN_SCHEMA, name="humanize", effort="none", max_tokens=800
            )
            text = out.get("bid") or text
            tells = humanizer.find_tells(text)
            if not tells:
                break
            prompt = f"{text}\n\nВ тексте остались признаки: {', '.join(tells)}. Исправь их."
        return humanizer.cleanup(text)
