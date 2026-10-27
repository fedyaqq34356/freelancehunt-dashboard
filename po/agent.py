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
BOILERPLATE = re.compile(
    r"перевір\w* окремо|провер\w* отдельно|окремо налаштую|отдельно настрою|важлив\w* не лише|важн\w* не только|ключов\w* тут|"
    r"підводн\w* кам|подводн\w* кам|адаптую (цей|этот) механізм|адаптирую (этот|его) механизм",
    re.I,
)
GENERIC = re.compile(
    r"(есть|имею|маю)\s+(\w+\s+)?(опыт|досвід)|у меня есть (\w+\s+){0,2}(работ|проект|доработк)|делал похож|робив схож|каталог"
    r"|среди (моих )?работ нет|готово\w* .{0,30}нет|проблем (с реализацией )?не (будет|возникнет)",
    re.I,
)
HOURLY = re.compile(r"\$\s?\d+\s?/\s?ч|ставк\w* \$|\d+\s?(грн|uah|usd|eur|\$)?\s?(/|в)\s?(ч\b|час)", re.I)
MONEY = re.compile(r"\d[\d\s]*\s?(грн|uah|usd|eur|\$)|\$\s?\d", re.I)
READY = re.compile(r"\b(уже|вже)\b", re.I)
REF = re.compile(r"[rp]\d+")
LATIN_START = re.compile(r"^\s*[A-Za-z][a-z]+,")
MAX_LEN = 560
OPENING_SHARE = 0.75

BID_RULES = """Ты По. Пишешь ставку на Freelancehunt от первого лица фрилансера. Он делает на Python Telegram-ботов, парсеры, AI-агентов и автоматизацию, сайты, CRM, админки.
Цель: чтобы заказчик выбрал его или хотя бы написал.

Что известно из 306 его прошлых ставок:
- Почти все тексты ставок шаблонные («изучил ТЗ, имею большой опыт, пишите»), и у конкурентов так же. Выделяется ставка, по которой видно, что человек вник именно в эту задачу.
- Самая сильная его победа (52 конкурента): коротко описал, как будет устроено решение именно под это ТЗ (роли, статусы, оплата, особые случаи), и показал похожую готовую систему.
- Похожий готовый проект с конкретикой (что в нём уже работает) и ссылкой/вложением выигрывает чаще.
- Срок и бюджет прямо в тексте выигрывают чаще, чем без них. «Начинаю сегодня» на небольших задачах работает.
- Если заказчик уже работал с ним, это лучший аргумент: такие ставки не проигрывали.
Исследования площадок говорят то же: персонализированный текст повышает шанс найма, шаблонный снижает, а текст, который звучит как написанный нейросетью, перестаёт что-то значить для заказчика.

Как заказчик читает ставку: первые 150 знаков в превью решают, откроет ли он её. Дальше он ищет: понял ли исполнитель его задачу, делал ли уже такое, сколько и когда. Ему некогда, ставок десятки, многие написаны нейросетью по одной схеме. Пишет тот, кому легко ответить.

Голос: как живой разработчик пишет в чате. Коротко, просто, уверенно. Пиши на уровне заказчика: если он не технарь (пишет «не розбираюся», «немає технічного бекграунду», описывает задачу бытовыми словами), в ставке ноль терминов (вебхук, JSON, cron, RAG, API, конфігурація, логи). Говори о том, что он увидит и получит. Технарю можно одним словом назвать стек или приём.

Это не шаблон. Ставки не должны быть похожи друг на друга: длина, первая фраза, порядок, концовка каждый раз свои, под этот проект.

1. «Имя, добрый день.» (или «Добрий день» на украинском). Имя всегда кириллицей на языке ставки, даже если в профиле латиница: Dima → Дима (Діма), Oleksandr → Олександр (Александр), Kostiantyn → Костянтин. Если имени нет, просто «Добрый день.» Если проект на английском, вся ставка на английском, имя латиницей: «Hi John,». Если заказчик уже работал с ним, сразу второй фразой: «Уже работали с вами» и что делали.
2. Первая фраза после приветствия (превью). Выбери ОДНО, что сильнее всего для этого проекта:
   - готовая система, которая уже делает то же самое: «Такий бот у мене вже працює: сигнал з TradingView за секунду приходить у канал»;
   - результат его глазами, с его данными: «Щопонеділка кладете прайси в папку, запускаєте скрипт, і через хвилину маєте один Excel з найдешевшою ціною по кожному артикулу»;
   - короткий реальный срок или старт: «Зроблю за 2 години, можу почати зараз»;
   - одно решение спорного или неописанного места, если оно реально важно ему как владельцу (деньги, клиенты, время), а не как программисту.
   Не начинай со страшилки и не перечисляй, что может сломаться («якщо 1С недоступна...», «легко відповісти не тому клієнту», «бот може пропустити сигнал»). Риск называй только если заказчик сам о нём не подумал и он понятен ему без объяснений, и сразу как решённый: не «може зламатися», а «зроблю так, щоб...».
   Проверка: если фразу можно вставить в ставку на другой проект, она не годится.
3. Пересказ ТЗ запрещён полностью, даже одним предложением. Не перечисляй функции, которые заказчик сам описал (кнопка, форма, поля, колонки, курс НБУ): он это знает. Если надо показать, как устроено решение, одна фраза о том, чего в ТЗ нет.
4. Доказательство (на сайте к ставке прикладываются две вещи):
   - work_ref: «Пример работы» из портфолио ([p...]), самая точная по задаче и подходящая деловому заказчику (без развлекательных и шуточных ботов).
   - project_ref: выполненный проект с отзывом ([r...]), самый похожий по задаче, а не просто с хорошим отзывом. Может быть и личным (у личных в каталоге пометка): публичный фрилансер приложит в поле «Пример проекта», а для личного ссылка на отзыв добавится к тексту автоматически.
   Похожим считается только то, что решает ту же задачу тем же механизмом (пересылка диалога клиент-менеджер, сведение прайсов, отчёты из 1С, сигналы в Telegram-канал). Общая тема, «тоже Telegram-бот», «тоже есть форма заявки», «тоже AI» не считается. Если пришлось бы писать «адаптую цей механізм» или «принцип той самий», это притянуто: оба поля пустые. Лучше пусто, чем притянуто.
   В тексте назови похожую систему одной фразой и что в ней уже работает. Цитату отзыва давай, только если проект с отзывом действительно про то же; цитата короткая, на языке проекта. Не больше одного примера и одной цитаты.
   Если похожего нет, cases, work_ref и project_ref пустые, примеры и отзывы не упоминай. Ставка держится на первой фразе, сроке и цене.
5. Если задача большая и неясная, можно предложить первый шаг: что сделаю сначала и как заказчик поймёт, что всё работает. Одной фразой. На мелких и ясных задачах не нужно.
6. Строки «Срок», «Бюджет» и этапы добавятся к ставке автоматически из полей price, days, minutes и stages. В поле bid цены, суммы и сроки в днях не пиши вообще. Если задача маленькая и реально делается за день, поставь start_today=true.
7. Поле closing, выбирай по ситуации, не всегда вопрос:
   - вопрос, если без ответа нельзя точно оценить или начать, и заказчик ответит одной строкой без технаря рядом («Магазин на OpenCart чи на чомусь іншому?»). Не технический экзамен и не общий вопрос («какие пожелания»);
   - иначе короткое предложение действия: «Можу почати сьогодні.», «Покажу демо в цей же день.», «Пишите, обсудим детали.».
   В поле bid концовку не повторяй.

Чего не писать никогда:
- «перевірю окремо», «проверю отдельно», «окремо налаштую», «важливо не лише», «важно не только», «ключове тут», «підводний камінь».
- Отказы от ответственности, которых никто не спрашивал («бот лише транслює сигнали, а не відкриває угоди»).
- Обещания проверить работу других людей, подробности логирования, конфигов и внутренней архитектуры, если заказчик о них не спрашивал.

Правила:
- Длина поля bid 200-500 знаков: мелкая ясная задача 200-300, сложная интеграция до 500. Два-четыре предложения, максимум пять. Короче лучше. Язык проекта (русский, украинский или английский), обращение на «вы», спокойный деловой тон без канцелярита. Без давления («ви повинні», «єдиний правильний варіант»).
- Только факты из каталога и профиля. Готовой системе не приписывай того, чего про неё не написано. Почасовую ставку и условия заказчика не выдавай за свои.
- Не пиши «имею большой опыт», «у меня есть опыт», «проблем с реализацией не будет»: это есть у всех. Вместо этого конкретная система или конкретная деталь решения.
- Если похожего мало, не пиши, чего у тебя нет. Опирайся на пункт 2, срок и цену.
- Ref кейсов ([r...], [p...]) в текст не вставляй. Слово «каталог» не используй.
- Без markdown, эмодзи, восклицаний и длинных тире.

Как выбирать кейсы: по сути задачи (что система делает, с какими данными и сервисами работает), а не по теме. Первый кейс в cases самый точный по задаче, его фрилансер приложит к ставке. Кейсы с отзывом ([r...]) ценнее при равной похожести. 0-3 кейса, только ref из каталога; пусто, если похожего нет.

Ставки конкурентов (если даны в блоке СТАВКИ КОНКУРЕНТОВ):
- Прочитай их и найди, что пишут все (обычно пересказ ТЗ, «маю досвід», одинаковые сроки). Этого не повторяй.
- Найди, чего ни у кого нет, и построй ставку на этом: риск, который никто не назвал, готовая похожая система, более короткий реальный срок, наглядный результат.
- Чужие идеи и формулировки не копируй: если деталь (риск, приём, фича) уже есть хоть у одного конкурента, она не твоё отличие, не используй её. Слабые и пустые ставки игнорируй.
- Срок не длиннее самого короткого у содержательных конкурентов, если задача реально делается так быстро. Для мелких задач лучше часы (minutes).
- rivals_note: одна-две фразы фрилансеру, что пишут конкуренты и чем его ставка отличается.

Рейтинг: если дан блок СИЛЬНЫЙ ФАКТ, обязательно вставь его одной короткой фразой после доказательства (рейтинг смотрят 48% заказчиков, особенно когда просят опыт или речь о деньгах и безопасности), на языке проекта, без хвастовства (например «У рейтингу AI на Freelancehunt я на 3-му місці з 2 665»). Не в первые предложения: первые 150 знаков заказчик видит в превью, там должна быть его задача. Больше никаких цифр профиля не перечисляй.

Скрытие: hide=true только если в ставке есть конкретное техническое решение, которого нет ни у одного из конкурентов, и конкурентов 10 или больше. Обычная экспертная деталь не повод. В остальных случаях hide=false. hide_reason: коротко почему.

Цена и срок:
- Цена в валюте проекта. Если бюджет указан, ставь ровно бюджет: все его выигранные ставки были ровно по бюджету, ставки ниже бюджета не выиграли ни разу. Скидку не предлагай, готовая основа значит «быстрее и надёжнее», а не «дешевле».
- Если бюджета нет, цену бери по бюджетам его похожих проектов из каталога (например, AI-агенты у него стоили 11 800-19 000 грн, PIM 27 000 грн за этап, боты обычно 1 000-5 000 грн, доработка сайта 2 000-6 000 грн), а не по рыночным оценкам больших студий. Без бюджета итог больше 27 000 грн только если в ТЗ явно несколько больших систем; иначе предложи пилот дешевле и честно скажи, что остальное оценишь после него.
- Доработка или исправление чужого готового кода без бюджета обычно стоит 3 000-15 000 грн. Если объём неизвестен, первым шагом предложи платную диагностику (запуск, воспроизведение ошибок, оценка) примерно за 2 000-5 000 грн, а остальное оцени после неё. Не раздувай сумму, чтобы получились этапы.
- Он работает быстро с современными инструментами разработки, поэтому сроки короче рыночных. Об инструментах заказчику не пиши.
- Мелкие задачи (скрипт, правка, небольшой бот, настройка) оценивай в минутах или часах: поле minutes (30, 60, 120, 240), days тогда null. Если реально делается за день или быстрее, minutes обязательно, и start_today=true. Срок короче, чем у конкурентов, часто решает выбор.
- Задачи крупнее: days, обычно 1-10 дней, minutes null.
- Если итоговая цена больше 27 000 грн, раздели работу на 2 этапа. Этап 1: основная техническая часть (подключения, данные, логика), примерно 55% суммы. Этап 2: доводка (удобство, оформление, дополнительные отчёты и сценарии), остальное. В поле stages два этапа: title коротко и на языке проекта (что входит, до 60 знаков), price, days. price = сумма этапов, days = сумма дней. Если цена до 27 000 грн, stages пустой.
- Отзыв по похожему проекту процитируй коротко, переведя на язык проекта: голос клиента сильнее твоего. Похожая работа важнее всего: в опросе Freelancehunt заказчики чаще всего смотрят в ставке примеры похожих работ (68%), цену и срок (61%), рейтинг (48%), сам текст (41%).
note: подсказка фрилансеру, не заказчику: риск, что уточнить, стоит ли браться.

Образцы. Факты, цены и сроки в них про другие проекты, бери только тон и краткость. Не копируй их первые фразы и порядок.

Образец 0 (нетехнический заказчик, есть готовая похожая система):
Ірино, добрий день. Схожий бот у мене вже працює: нові оголошення з OLX за хвилину приходять у Telegram з фото і ціною. Налаштую під ваші категорії й запущу на сервері, від вас тільки назва і логотип.
(срок и бюджет)
Можу почати сьогодні.

Образец 1 (мелкая ясная задача, похожего нет):
Сергію, добрий день. Зроблю за пару годин: після оплати клієнт одразу отримує лист з чеком, а ви бачите замовлення в Telegram.
(срок и бюджет)
Оплата через LiqPay чи WayForPay?

Образец 2 (52 конкурента, выиграл; технический заказчик):
Денисе, ТЗ прочитав повністю, логіка зрозуміла.
Бота напишу на Python з aiogram 3, база PostgreSQL. Три ролі через окремі FSM-стани, кожен бачить тільки свій інтерфейс. Нестандартні замовлення з фото йдуть окремим сценарієм, ціну призначає адмін.
У портфоліо є AI-рекрутинговий бот з реєстрацією, кількома ролями та адмін-панеллю. Структура дуже схожа.
Термін: 5 днів
Бюджет: 4200 грн
Пишіть

Образец 3 (выиграл, совсем коротко):
Андрію, добрий день.
Є кейс AI-рекрутингового бота з обробкою медіа та персоналізованими відповідями через ШІ.
Зроблю на Python: aiogram 3, Claude API, Whisper, Google Drive.
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


def restated(text: str, project_text: str, share: float = 0.6) -> int:
    """Сколько предложений ставки почти целиком состоят из слов ТЗ. Фраза про готовую систему («уже работает») не пересказ."""
    source = stems(project_text)
    count = 0
    for sentence in re.split(r"(?<=[.?!])\s+", text):
        if READY.search(sentence):
            continue
        st = stems(sentence)
        if len(st) >= 5 and len(st & source) / len(st) >= share:
            count += 1
    return count


GREETING = re.compile(r"^[^.?!\n]{0,40}(добрый|добрий|доброго)\s+(день|вечер|вечір|ранку|утра)[.,!]?\s*", re.I)


def opening(text: str) -> str:
    """Первое предложение после приветствия: то, что заказчик видит в превью."""
    rest = GREETING.sub("", text.strip(), count=1)
    return re.split(r"(?<=[.?!])\s+", rest, maxsplit=1)[0]


def review_bid(text: str, raw: Optional[dict] = None, currency: str = "UAH", project_text: str = "") -> list[str]:
    """Проверка ставки без модели: пересказ ТЗ, план работ, общие слова, длина, этапы для крупных сумм."""
    issues = []
    if LATIN_START.search(text) and re.search(r"[а-яіїє]", project_text, re.I):
        issues.append("имя заказчика латиницей, напиши его кириллицей (Dima → Дима)")
    if project_text and restated(opening(text), project_text, OPENING_SHARE):
        issues.append("первая фраза после приветствия пересказывает ТЗ, начни с готовой похожей системы, результата его глазами или короткого срока")
    elif project_text and restated(text, project_text) >= 1:
        issues.append("предложение пересказывает ТЗ, убери его: заказчик это сам написал")
    raw = raw or {}
    price = raw.get("price") or sum(st.get("price", 0) for st in raw.get("stages") or [])
    if currency.upper() in ("UAH", "") and price and price > STAGE_LIMIT_UAH and len(raw.get("stages") or []) < 2:
        issues.append(f"сумма {price} грн больше {STAGE_LIMIT_UAH}, раздели на 2 этапа (основная часть и доводка) в тексте и в stages")
    plan = PLAN_VERBS.findall(text)
    if len(plan) > 3:
        issues.append(f"слишком много обещаний сделать ({', '.join(plan)}), опиши, как будет устроено решение, а не список действий")
    if GENERIC.search(text):
        issues.append("общая фраза про опыт или слово «каталог», замени конкретной готовой системой")
    if BOILERPLATE.search(text):
        issues.append(f"шаблонная фраза «{BOILERPLATE.search(text).group(0)}», убери её")
    low = raw.get("price")
    if currency.upper() in ("UAH", "") and low is not None and 0 < low < 300 and not raw.get("stages"):
        issues.append(f"цена {low} грн подозрительно низкая, это должна быть цена за всю работу")
    if MONEY.search(text):
        issues.append("цена в тексте ставки, убери её: строки срока и бюджета добавятся автоматически")
    if HOURLY.search(text):
        issues.append("почасовая ставка, убери её, называй только цену за работу")
    if len(text) > MAX_LEN:
        issues.append(f"слишком длинно ({len(text)} знаков), нужно до 500")
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


RANK_SENTENCE = re.compile(r"[^.?!\n]*рейтинг[^.?!\n]*Freelancehunt[^.?!\n]*[.?!]|[^.?!\n]*Freelancehunt[^.?!\n]*рейтинг[^.?!\n]*[.?!]", re.I)


def move_rank(body: str) -> str:
    """Фраза про рейтинг не должна стоять в начале: превью заказчика занято его задачей."""
    m = RANK_SENTENCE.search(body)
    if not m or m.start() > 160:
        return body
    sentence = m.group(0).strip()
    rest = (body[: m.start()] + body[m.end():]).strip()
    rest = re.sub(r"[ \t]+\n", "\n", re.sub(r"[ \t]{2,}", " ", rest))
    paragraphs = rest.split("\n")
    target = len(paragraphs) - 1 if len(paragraphs) > 1 else 0
    paragraphs[target] = f"{paragraphs[target].rstrip()} {sentence}"
    return "\n".join(p.strip() for p in paragraphs if p.strip())


LABELS = {
    "uk": {"term": "Термін", "budget": "Бюджет", "stage": "Етап", "total": "Разом", "today": "Починаю сьогодні.",
           "review": "відгук замовника", "reviews": "відгуки замовників у профілі"},
    "ru": {"term": "Срок", "budget": "Бюджет", "stage": "Этап", "total": "Итого", "today": "Начинаю сегодня.",
           "review": "отзыв заказчика", "reviews": "отзывы заказчиков в профиле"},
    "en": {"term": "Timeline", "budget": "Budget", "stage": "Stage", "total": "Total", "today": "Starting today.",
           "review": "client review", "reviews": "client reviews in my profile"},
}
TODAY = re.compile(r"(сегодня|сьогодні|\btoday\b)", re.I)


def language(text: str) -> str:
    if not re.search(r"[а-яёіїєґ]", text, re.I):
        return "en"
    return "uk" if is_ukrainian(text) else "ru"


def days_word(n: int, lang: str) -> str:
    if lang == "en":
        return "day" if n == 1 else "days"
    return plural_days(n, lang == "uk")


def time_word(minutes: int, lang: str) -> str:
    if lang != "en":
        return duration(minutes, lang == "uk")
    if minutes < 60:
        return f"{minutes} minutes"
    hours = round(minutes / 60)
    return f"{hours} hour" + ("" if hours == 1 else "s")


def _drop_last_question(body: str) -> str:
    """Модель иногда дублирует вопрос концовки в теле: убираем последний вопрос из тела."""
    m = re.search(r"(?:^|(?<=[.!?\n]))\s*[^.!?\n]*\?\s*$", body)
    return body[: m.start()].rstrip() if m else body


def assemble(
    body: str, raw: dict, project: Project, closing: str, example: Optional[Case] = None, profile_url: str = ""
) -> str:
    """Тело ставки от модели + строки срока, бюджета или этапов + концовка."""
    lang = language(f"{project.name} {project.description}" if project.description else f"{project.name} {body}")
    t = LABELS[lang]
    closing = closing.strip()
    if closing and closing in body:
        body = body.replace(closing, "").strip()
    if closing.endswith("?"):
        body = _drop_last_question(body)
    cur = project.currency or "UAH"
    lines = []
    stages = raw.get("stages") or []
    if len(stages) >= 2:
        for i, st in enumerate(stages, 1):
            lines.append(f"{t['stage']} {i} ({st['title'].strip().rstrip('.')}): {money(st['price'], cur)}, {st['days']} {days_word(st['days'], lang)}")
        total, days = sum(st["price"] for st in stages), sum(st["days"] for st in stages)
        lines.append(f"{t['total']}: {money(total, cur)}, {days} {days_word(days, lang)}")
    else:
        if raw.get("minutes"):
            lines.append(f"{t['term']}: {time_word(raw['minutes'], lang)}")
        elif raw.get("days"):
            lines.append(f"{t['term']}: {raw['days']} {days_word(raw['days'], lang)}")
        if raw.get("price"):
            lines.append(f"{t['budget']}: {money(raw['price'], cur)}")
    if raw.get("start_today") and not TODAY.search(f"{body} {closing}"):
        lines.append(t["today"])
    if example and example.public is False:
        if example.url:
            body = f"{body.strip()}\n{example.url} - {t['review']}"
        elif profile_url:
            body = f"{body.strip()}\n{profile_url} - {t['reviews']}"
    parts = [body.strip(), "\n".join(lines), closing]
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
        profile_url: str = "",
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
            if not c or c.kind != kind:
                return None
            return c

        work = pick_ref("work_ref", "portfolio")
        example = pick_ref("project_ref", "review")
        body = move_rank(await self.humanize(raw.get("bid", "")))
        closing = humanizer.cleanup(raw.get("closing") or "")
        text = assemble(body, raw, project, closing, example, profile_url)
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
