import html
import re

_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-zа-яёіїєґ0-9]+", re.I)

STOP = {
    "для", "что", "как", "это", "или", "все", "так", "его", "нам", "нас", "вам", "вас", "при", "без",
    "уже", "еще", "ещё", "был", "есть", "надо", "нужно", "нужен", "нужна", "потрібно", "який", "яка",
    "the", "and", "for", "with", "from", "that", "this", "you", "your", "are", "will", "can",
    "проект", "проекта", "работа", "работы", "задача", "задачи", "сделать", "можно", "будет", "который",
    "которая", "которые", "також", "щоб", "або", "так", "але", "вже", "один", "одна", "очень", "через",
}


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>", "\n", s or "", flags=re.I)
    return html.unescape(_TAG.sub("", s)).strip()


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def clip(s: str, n: int) -> str:
    s = squash(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def stems(s: str) -> set[str]:
    """Грубые основы слов: первые 5 букв, без стоп-слов и коротких слов."""
    out = set()
    for w in _WORD.findall((s or "").lower()):
        if len(w) < 3 or w in STOP:
            continue
        out.add(w[:5])
    return out
