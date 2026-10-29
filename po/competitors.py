import asyncio
"""Ставки конкурентов со страницы проекта: headless-браузер без входа в аккаунт, только чтение."""
import html
import logging
import os
import re
import statistics
import time
from dataclasses import dataclass
from typing import Optional

from .text import clip

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
MIN_TEXT = 200
MAX_IN_PROMPT = 12


@dataclass
class Rival:
    login: str
    name: str
    rating: int = 0
    plus: bool = False
    amount: Optional[int] = None
    days: Optional[int] = None
    projects: Optional[int] = None
    text: str = ""
    hidden: bool = False


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else ""


def _int(s: str) -> Optional[int]:
    digits = re.sub(r"\D", "", s or "")
    return int(digits) if digits else None


def _text(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>|</p>", "\n", fragment, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return "\n".join(" ".join(line.split()) for line in t.split("\n") if line.strip())


def parse(page: str, my_login: str = "") -> list[Rival]:
    rivals = []
    for art in re.findall(r"<article\b[^>]*\bbid\b.*?</article>", page, flags=re.S):
        open_tag = art[: art.find(">") + 1]
        m = re.search(r'/freelancer/([A-Za-z0-9_\-]+)\.html', art)
        login = m.group(1) if m else ""
        if not login or login == my_login:
            continue
        name = re.search(r'alt="([^"]*)"', art)
        projects = re.search(r"(?:Проєкти|Проекты)</span>.*?<span class=\"text-desktop-h6\">([^<]*)</span>", art, flags=re.S)
        comment = re.search(
            r'class="[^"]*\bbid-comment\b[^"]*"[^>]*>\s*<span[^>]*>\s*<span>(.*?)</span>', art, flags=re.S
        )
        hidden = "Деталі ставки приховані" in art or "Детали ставки скрыты" in art
        rivals.append(
            Rival(
                login=login,
                name=html.unescape(name.group(1)) if name else login,
                rating=_int(_attr(open_tag, "data-rating")) or 0,
                plus=_attr(open_tag, "data-hasplus") == "1",
                amount=_int(_attr(open_tag, "data-amount")),
                days=_int(_attr(open_tag, "data-days")),
                projects=_int(projects.group(1)) if projects else None,
                text="" if hidden else _text(comment.group(1)) if comment else "",
                hidden=hidden,
            )
        )
    return rivals


def hidden_note(page: str) -> bool:
    return "не показані ставки, приховані" in page or "не показаны ставки, скрытые" in page


def render_for_prompt(rivals: list[Rival]) -> str:
    """Только содержательные ставки: короткие «готов сделать» не учат ничему."""
    strong = sorted((r for r in rivals if len(r.text) >= MIN_TEXT), key=lambda r: -r.rating)[:MAX_IN_PROMPT]
    lines = []
    for i, r in enumerate(strong, 1):
        lines.append(f"{i}. проектов {r.projects or 0}, {r.amount or '?'} за {r.days or '?'} дн.: {clip(r.text, 600)}")
    return "\n".join(lines)


def summary(rivals: list[Rival], bid_count: int) -> str:
    """Короткая сводка для фрилансера: сколько видно, цены, сроки."""
    if not rivals and not bid_count:
        return ""
    amounts = [r.amount for r in rivals if r.amount]
    days = [r.days for r in rivals if r.days]
    parts = [f"видно {len(rivals)} из {bid_count}"]
    if amounts:
        parts.append(f"цены {min(amounts)}-{max(amounts)}, медиана {int(statistics.median(amounts))}")
    if days:
        parts.append(f"сроки {min(days)}-{max(days)} дн.")
    strong = sum(1 for r in rivals if len(r.text) >= MIN_TEXT)
    parts.append(f"содержательных {strong}")
    return ", ".join(parts)


async def fetch_html(url: str, timeout_ms: int = 10000, wait_s: float = 6.0) -> str:
    """Страница проекта браузером. Ждём ставки или проверку Cloudflare, что придёт раньше, не дольше wait_s."""
    from playwright.async_api import async_playwright

    exe = os.getenv("CHROMIUM_PATH") or None
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=exe, args=["--no-sandbox", "--disable-gpu"])
        try:
            page = await browser.new_page(user_agent=UA)
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            for _ in range(int(wait_s / 0.5)):
                html = await page.content()
                if blocked(html) or "article" in html and 'class="bid' in html:
                    return html
                await asyncio.sleep(0.5)
            return await page.content()
        finally:
            await browser.close()


def blocked(page: str) -> bool:
    return "<title>Just a moment" in page or "cf-chl" in page


BLOCK_COOLDOWN = 30 * 60
LOAD_TIMEOUT = 12
_blocked_at = 0.0


async def load(url: str, my_login: str = "") -> Optional[list[Rival]]:
    """Список ставок или None, если страницу не отдали (ошибка, защита сайта, таймаут).
    После проверки от ботов полчаса не пробуем: она держится долго, а каждая попытка задерживает ставку."""
    global _blocked_at
    if time.monotonic() - _blocked_at < BLOCK_COOLDOWN:
        return None
    try:
        page = await asyncio.wait_for(fetch_html(url), LOAD_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        log.warning("ставки конкурентов недоступны: %s", e or type(e).__name__)
        return None
    if blocked(page):
        _blocked_at = time.monotonic()
        log.warning("ставки конкурентов: сайт показал проверку от ботов, пропускаю 30 мин")
        return None
    return parse(page, my_login)
