"""Auto-detect surcharge ("доплата") payments from thread system messages.

Freelancehunt posts a system message (sender id 4) whenever an employer adds a
surcharge to the safe deal, e.g.:
    "Заказчик внес доплату за работу над проектом в сумме 750 UAH."
These are the only place surcharges are exposed, so we scan threads, extract the
amount + currency, and bucket them by month. Results are cached with a TTL because
scanning every thread is a lot of API calls.
"""
import re
import threading
import time

# Keyword gate across ru / uk / en / pl so a change of interface language still matches.
KEYWORDS = re.compile(r"(доплат|надбав|surcharge|extra\s+payment|dopła|доплачен)", re.I)
# Amount + currency. Narrow/no-break spaces ( ,  ) appear as thousands separators.
AMOUNT = re.compile(r"(\d[\d\s  .,]*?)\s*(UAH|RUB|₴|PLN|zł|USD|EUR)", re.I)

CUR_NORMALIZE = {"₴": "UAH", "zł": "PLN"}


def _parse_amount(raw: str) -> float:
    cleaned = raw.replace(" ", "").replace(" ", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    # Drop a trailing decimal like ".00" but keep integers robust.
    try:
        return float(cleaned)
    except ValueError:
        digits = re.sub(r"[^\d.]", "", cleaned)
        return float(digits) if digits else 0.0


def extract_surcharge(text: str):
    """Return (amount, currency) if the text is a surcharge notice, else None."""
    if not text or not KEYWORDS.search(text):
        return None
    m = AMOUNT.search(text)
    if not m:
        return None
    amount = _parse_amount(m.group(1))
    if amount <= 0:
        return None
    cur = m.group(2).upper()
    cur = CUR_NORMALIZE.get(m.group(2), cur)
    return amount, cur


class SurchargeScanner:
    def __init__(self, client, ttl: int = 600):
        self.client = client
        self.ttl = ttl
        self._lock = threading.Lock()
        self._cache = {"by_month": {}, "total": {}, "items": [], "ts": 0}

    def _scan(self) -> dict:
        by_month: dict[str, dict[str, float]] = {}
        total: dict[str, float] = {}
        items = []
        try:
            threads = self.client.threads().get("data", [])
        except Exception:
            return self._cache
        for t in threads:
            if not t["attributes"].get("is_project_working_area"):
                # Surcharge notices live in project working-area threads.
                continue
            try:
                msgs = self.client.thread_messages(t["id"]).get("data", [])
            except Exception:
                continue
            for msg in msgs:
                a = msg["attributes"]
                res = extract_surcharge(a.get("message_text") or "")
                if not res:
                    continue
                amount, cur = res
                month = (a.get("posted_at") or "")[:7]
                by_month.setdefault(month, {}).setdefault(cur, 0)
                by_month[month][cur] += amount
                total[cur] = total.get(cur, 0) + amount
                items.append(
                    {
                        "thread_id": t["id"],
                        "subject": t["attributes"].get("subject"),
                        "amount": amount,
                        "currency": cur,
                        "posted_at": a.get("posted_at"),
                    }
                )
        return {"by_month": by_month, "total": total, "items": items, "ts": time.time()}

    def get(self, force: bool = False) -> dict:
        with self._lock:
            fresh = (time.time() - self._cache["ts"]) < self.ttl
            if self._cache["ts"] and fresh and not force:
                return self._cache
        result = self._scan()
        with self._lock:
            self._cache = result
        return result

    def start_background(self):
        def loop():
            while True:
                try:
                    self.get(force=True)
                except Exception:
                    pass
                time.sleep(self.ttl)

        threading.Thread(target=loop, daemon=True).start()
