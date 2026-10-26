"""По: подбирает кейсы под проект и пишет ставку."""
import re
from dataclasses import dataclass, field
from typing import Optional

from . import humanizer
from .catalog import Case, render_for_prompt
from .llm import LLM
from .projects import Project
from .text import clip, stems

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
LATIN_START = re.compile(r"^\s*[A-Za-z][a-z]+,")
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
1. «Имя, добрый день.» (или «Добрий день» на украинском). Имя всегда кириллицей на языке ставки, даже если в профиле латиница: Dima → Дима (Діма), Oleksandr → Олександр (Александр), Kostiantyn → Костянтин. Если имени нет, просто «Добрый день.» Если заказчик уже работал с ним, сразу второй фразой: «Уже работали с вами» и что делали.
2. 1-3 предложения, которых НЕТ в ТЗ. Не пересказывай ТЗ: заказчик знает свою задачу, а пересказ делают почти все конкуренты (часто нейросетью). Каждое предложение добавляет одно из: риск или подводный камень, о котором заказчик не подумал; как результат будет выглядеть для него на практике (запуск двойным кликом, файл с датой в названии, кнопка в боте); решение спорного места задачи. Пример хорошего хода: «Найризикованіше тут не парсинг, а зведення дублів: один артикул у різних постачальників пишеться по-різному».
3. На сайте к ставке прикладываются две вещи, выбери обе:
   - work_ref: «Пример работы» из портфолио ([p...]), самая точная по задаче.
   - project_ref: «Пример проекта», выполненный проект с отзывом ([r...]), только НЕ личный (у личных в каталоге пометка), самый похожий по задаче, а не просто с хорошим отзывом. Ссылка на него добавится к ставке автоматически.
   Похожим считается только то, что решает ту же задачу тем же механизмом (например, пересылка диалога клиент-менеджер, сведение прайсов, отчёты из 1С). Общая тема или «тоже Telegram-бот» не считается. Лучше пусто, чем притянуто.
   В тексте назови похожую систему явно и процитируй коротко отзыв по project_ref: «За схожий проєкт "Назва" замовник написав: "..."». Отзыв переводи на язык проекта. Если подходящего публичного проекта нет, project_ref пустой, опирайся на work_ref: «У прикріпленому прикладі "Назва" вже працює ...».
   Если по-настоящему похожего нет ни в работах, ни в проектах, оба поля пустые, cases пустой, и в ставке вообще не упоминай примеры и отзывы. Тогда ставка держится на понимании задачи, решении и рейтинге.
4. Строки «Срок», «Бюджет» и этапы добавятся к ставке автоматически из полей price, days, minutes и stages. В поле bid их не пиши. Если задача маленькая и реально делается за день, поставь start_today=true.
5. Поле closing: «Пишите, обсудим детали.» (на языке проекта) или, если в ТЗ не хватает ключевой детали, один короткий вопрос по ней. В поле bid этот вопрос не повторяй.

Правила:
- 300-650 знаков. Язык проекта (русский или украинский).
- Только факты из каталога и профиля. Готовой системе не приписывай того, чего про неё не написано. Почасовую ставку и условия заказчика не выдавай за свои.
- Не пиши «имею большой опыт», «у меня есть опыт», «проблем с реализацией не будет»: это есть у всех. Вместо этого конкретная система или конкретная деталь решения.
- Если похожего мало, не пиши, чего у тебя нет. Сильнее опирайся на пункт 2 и ближайшую реальную систему.
- Ref кейсов ([r...], [p...]) в текст не вставляй. Слово «каталог» не используй.
- Без markdown, эмодзи, восклицаний и длинных тире.

Как выбирать кейсы: по сути задачи (что система делает, с какими данными и сервисами работает), а не по теме. Первый кейс в cases самый точный по задаче, его фрилансер приложит к ставке. Кейсы с отзывом ([r...]) ценнее при равной похожести. 1-3 кейса, только ref из каталога.

Ставки конкурентов (если даны в блоке СТАВКИ КОНКУРЕНТОВ):
- Прочитай их и найди, что пишут все (обычно пересказ ТЗ, «маю досвід», одинаковые сроки). Этого не повторяй.
- Найди, чего ни у кого нет, и построй ставку на этом: риск, который никто не назвал, готовая похожая система, более короткий реальный срок, наглядный результат.
- Чужие идеи и формулировки не копируй: если деталь (риск, приём, фича) уже есть хоть у одного конкурента, она не твоё отличие, не используй её. Слабые и пустые ставки игнорируй.
- Срок не длиннее самого короткого у содержательных конкурентов, если задача реально делается так быстро. Для мелких задач лучше часы (minutes).
- rivals_note: одна-две фразы фрилансеру, что пишут конкуренты и чем его ставка отличается.

Рейтинг: если дан блок СИЛЬНЫЙ ФАКТ, вставь его одной короткой фразой в начало второго или третьего предложения, на языке проекта, без хвастовства (например «У рейтингу AI на Freelancehunt я на 3-му місці з 2 665»). Больше никаких цифр профиля не перечисляй.

Скрытие: hide=true, если в ставке есть своё решение или идея, которую конкуренты могут скопировать (у фрилансера Plus, ставку можно скрыть). hide_reason: коротко почему.

Цена и срок:
- Цена в валюте проекта. Если бюджет указан, ставь ровно бюджет: все его выигранные ставки были ровно по бюджету, ставки ниже бюджета не выиграли ни разу. Скидку не предлагай, готовая основа значит «быстрее и надёжнее», а не «дешевле».
- Если бюджета нет, цену бери по бюджетам его похожих проектов из каталога (например, AI-агенты у него стоили 11 800-19 000 грн, PIM 27 000 грн за этап, боты обычно 1 000-5 000 грн), а не по рыночным оценкам больших студий.
- Он работает быстро с современными инструментами разработки, поэтому сроки короче рыночных. Об инструментах заказчику не пиши.
- Мелкие задачи (скрипт, правка, небольшой бот, настройка) оценивай в минутах или часах: поле minutes (30, 60, 120, 240), days тогда null. Если реально делается за день или быстрее, minutes обязательно, и start_today=true. Срок короче, чем у конкурентов, часто решает выбор.
- Задачи крупнее: days, обычно 1-10 дней, minutes null.
- Если итоговая цена больше 27 000 грн, раздели работу на 2 этапа. Этап 1: основная техническая часть (подключения, данные, логика), примерно 55% суммы. Этап 2: доводка (удобство, оформление, дополнительные отчёты и сценарии), остальное. В поле stages два этапа: title коротко и на языке проекта (что входит, до 60 знаков), price, days. price = сумма этапов, days = сумма дней. Если цена до 27 000 грн, stages пустой.
- Сильный отзыв по похожему проекту обязательно процитируй коротко, переведя на язык проекта. Это самый сильный аргумент.
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
        "work_ref": {"type": "string"},
        "project_ref": {"type": "string"},
        "bid": {"type": "string"},
        "closing": {"type": "string"},
        "start_today": {"type": "boolean"},
        "price": {"type": ["integer", "null"]},
        "days": {"type": ["integer", "null"]},
        "minutes": {"type": ["integer", "null"]},
        "stages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"title": {"type": "string"}, "price": {"type": "integer"}, "days": {"type": "integer"}},
                "required": ["title", "price", "days"],
            },
        },
        "note": {"type": "string"},
        "hide": {"type": "boolean"},
        "hide_reason": {"type": "string"},
        "rivals_note": {"type": "string"},
    },
    "required": [
        "fit", "cases", "work_ref", "project_ref", "bid", "closing", "start_today", "price", "days", "minutes", "stages", "note",
        "hide", "hide_reason", "rivals_note",
    ],
}

STAGE_LIMIT_UAH = 27000

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
    stages: list[dict] = field(default_factory=list)
    minutes: Optional[int] = None
    hide: bool = False
    hide_reason: str = ""
    rivals_note: str = ""
    rivals_summary: str = ""
    cost: float = 0.0
    work: Optional[Case] = None
    example: Optional[Case] = None


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


def restated(text: str, project_text: str) -> int:
    """Сколько предложений ставки почти целиком состоят из слов ТЗ."""
    source = stems(project_text)
    count = 0
    for sentence in re.split(r"(?<=[.?!])\s+", text):
        st = stems(sentence)
        if len(st) >= 5 and len(st & source) / len(st) >= 0.6:
            count += 1
    return count


def review_bid(text: str, raw: Optional[dict] = None, currency: str = "UAH", project_text: str = "") -> list[str]:
    """Проверка ставки без модели: пересказ ТЗ, план работ, общие слова, длина, этапы для крупных сумм."""
    issues = []
    if LATIN_START.search(text) and re.search(r"[а-яіїє]", project_text, re.I):
        issues.append("имя заказчика латиницей, напиши его кириллицей (Dima → Дима)")
    if project_text and restated(text, project_text) >= 2:
        issues.append("предложения пересказывают ТЗ, замени их тем, чего в ТЗ нет: риск, наглядный результат, готовая система")
    raw = raw or {}
    price = raw.get("price") or sum(st.get("price", 0) for st in raw.get("stages") or [])
    if currency.upper() in ("UAH", "") and price and price > STAGE_LIMIT_UAH and len(raw.get("stages") or []) < 2:
        issues.append(f"сумма {price} грн больше {STAGE_LIMIT_UAH}, раздели на 2 этапа (основная часть и доводка) в тексте и в stages")
    plan = PLAN_VERBS.findall(text)
    if len(plan) > 3:
        issues.append(f"слишком много обещаний сделать ({', '.join(plan)}), опиши, как будет устроено решение, а не список действий")
    if GENERIC.search(text):
        issues.append("общая фраза про опыт или слово «каталог», замени конкретной готовой системой")
    low = raw.get("price")
    if currency.upper() in ("UAH", "") and low is not None and 0 < low < 300 and not raw.get("stages"):
        issues.append(f"цена {low} грн подозрительно низкая, это должна быть цена за всю работу")
    if HOURLY.search(text):
        issues.append("почасовая ставка, убери её, называй только цену за работу")
    if len(text) > MAX_LEN:
        issues.append(f"слишком длинно ({len(text)} знаков), нужно до 650")
    if re.search(r"\[[rp]\d+\]", text):
        issues.append("в тексте служебные ref, убери их")
    return issues


def is_ukrainian(text: str) -> bool:
    return len(re.findall(r"[іїєґ]", text.lower())) >= 3


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def plural_days(n: int, uk: bool) -> str:
    return _plural(n, "день", "дні", "днів") if uk else _plural(n, "день", "дня", "дней")


def duration(minutes: int, uk: bool) -> str:
    if minutes < 60:
        return f"{minutes} " + (_plural(minutes, "хвилина", "хвилини", "хвилин") if uk else _plural(minutes, "минута", "минуты", "минут"))
    hours = round(minutes / 60)
    return f"{hours} " + (_plural(hours, "година", "години", "годин") if uk else _plural(hours, "час", "часа", "часов"))


def money(n: int, currency: str) -> str:
    cur = "грн" if currency.upper() in ("UAH", "") else currency
    return f"{n:,}".replace(",", " ") + f" {cur}"


def assemble(body: str, raw: dict, project: Project, closing: str, example: Optional[Case] = None) -> str:
    """Тело ставки от модели + строки срока, бюджета или этапов + концовка."""
    uk = is_ukrainian(f"{project.name} {project.description} {body}")
    if closing and closing.strip() in body:
        body = body.replace(closing.strip(), "").strip()
    cur = project.currency or "UAH"
    lines = []
    stages = raw.get("stages") or []
    if len(stages) >= 2:
        for i, st in enumerate(stages, 1):
            word = "Етап" if uk else "Этап"
            lines.append(f"{word} {i} ({st['title'].strip().rstrip('.')}): {money(st['price'], cur)}, {st['days']} {plural_days(st['days'], uk)}")
    else:
        if raw.get("minutes"):
            lines.append(f"{'Термін' if uk else 'Срок'}: {duration(raw['minutes'], uk)}")
        elif raw.get("days"):
            lines.append(f"{'Термін' if uk else 'Срок'}: {raw['days']} {plural_days(raw['days'], uk)}")
        if raw.get("price"):
            lines.append(f"{'Бюджет'}: {money(raw['price'], cur)}")
    if raw.get("start_today"):
        lines.append("Починаю сьогодні." if uk else "Начинаю сегодня.")
    if example and example.public and example.url:
        body = f"{body.strip()}\n{example.url} - {'відгук замовника' if uk else 'отзыв заказчика'}"
    parts = [body.strip(), "\n".join(lines), closing.strip()]
    return "\n\n".join(p for p in parts if p)


class Po:
    def __init__(self, llm: LLM):
        self.llm = llm

    async def write_bid(
        self,
        project: Project,
        cases: list[Case],
        facts: str = "",
        previous: Optional[str] = None,
        repeat: bool = False,
        rivals: str = "",
        rivals_summary: str = "",
        rank: str = "",
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
        if rank:
            prompt += f"\n\nСИЛЬНЫЙ ФАКТ\n{rank}"
        if rivals:
            prompt += f"\n\nСТАВКИ КОНКУРЕНТОВ ({rivals_summary})\n{rivals}"
        if previous:
            prompt += f"\n\nПРЕДЫДУЩИЙ ВАРИАНТ (не повторяй его, напиши по-другому, можно с другими кейсами):\n{previous}"
        raw = await self.llm.json(instructions=BID_RULES, prompt=prompt, schema=BID_SCHEMA, name="bid", effort="medium", max_tokens=4000)
        first = raw
        for _ in range(2):
            issues = review_bid(raw.get("bid", ""), raw, project.currency, f"{project.name} {project.description}")
            if not issues:
                break
            fix = f"{prompt}\n\nТВОЙ ЧЕРНОВИК\n{raw.get('bid', '')}\n\nПерепиши ставку. Проблемы: {'; '.join(issues)}."
            raw = await self.llm.json(instructions=BID_RULES, prompt=fix, schema=BID_SCHEMA, name="bid", effort="medium", max_tokens=4000)
        if not raw.get("cases"):
            raw["cases"] = first.get("cases") or []

        by_ref = {c.ref: c for c in catalog}
        picks = []
        for item in raw.get("cases") or []:
            m = REF.search(str(item.get("ref", "")))
            case = by_ref.get(m.group(0)) if m else None
            if case and all(p.case.ref != case.ref for p in picks):
                picks.append(Pick(case, item.get("why", "")))
        def pick_ref(field: str, kind: str) -> Optional[Case]:
            m = REF.search(str(raw.get(field, "")))
            c = by_ref.get(m.group(0)) if m else None
            if not c or c.kind != kind or (kind == "review" and c.public is False):
                return None
            return c

        work = pick_ref("work_ref", "portfolio")
        example = pick_ref("project_ref", "review")
        body = await self.humanize(raw.get("bid", ""))
        closing = humanizer.cleanup(raw.get("closing") or "")
        text = assemble(body, raw, project, closing, example)
        return BidDraft(
            text=text,
            fit=raw.get("fit", "medium"),
            picks=picks[:3],
            price=raw.get("price"),
            days=raw.get("days"),
            currency=project.currency or "UAH",
            note=raw.get("note", ""),
            stages=raw.get("stages") or [],
            minutes=raw.get("minutes"),
            hide=bool(raw.get("hide")),
            hide_reason=raw.get("hide_reason", ""),
            rivals_note=raw.get("rivals_note", "") if rivals else "",
            rivals_summary=rivals_summary,
            work=work,
            example=example,
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

    async def write_nudge(self, subject: str, dialog: str) -> str:
        from .followup import NUDGE_RULES, NUDGE_SCHEMA

        out = await self.llm.json(
            instructions=NUDGE_RULES, prompt=f"Тема: {subject}\n\nПЕРЕПИСКА\n{dialog}", schema=NUDGE_SCHEMA,
            name="nudge", effort="low", max_tokens=1500,
        )
        return await self.humanize(out.get("text", ""))

    async def client_ideas(self, client_text: str, portfolio_text: str) -> dict:
        from .followup import IDEAS_RULES, IDEAS_SCHEMA

        out = await self.llm.json(
            instructions=IDEAS_RULES,
            prompt=f"{client_text}\n\nДРУГИЕ РАБОТЫ ФРИЛАНСЕРА (для идей)\n{portfolio_text}",
            schema=IDEAS_SCHEMA, name="ideas", effort="low", max_tokens=3000,
        )
        out["message"] = await self.humanize(out.get("message", ""))
        return out
