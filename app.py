import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from freelancehunt.client import FreelancehuntClient, FreelancehuntError
from freelancehunt.surcharges import SurchargeScanner

load_dotenv()

DASH_USER = os.getenv("DASHBOARD_USER")
DASH_PASS = os.getenv("DASHBOARD_PASS")
if not DASH_USER or not DASH_PASS:
    raise RuntimeError("DASHBOARD_USER / DASHBOARD_PASS not set in .env")

SECRET_KEY = (os.getenv("SECRET_KEY") or "dev-insecure-key").encode()
COOKIE_NAME = "fh_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 90  # 90 days — "remember me"

client = FreelancehuntClient()
scanner = SurchargeScanner(client)
STATIC_DIR = Path(__file__).parent / "static"
EXTRAS_FILE = Path(__file__).parent / "income_extras.json"


# ---------- Stateless signed-cookie auth (survives restarts) ----------
def issue_token() -> str:
    payload = str(int(time.time()) + COOKIE_MAX_AGE)
    sig = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def valid_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(":", 1)
    except Exception:
        return False
    expected = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return int(payload) > time.time()
    except ValueError:
        return False


def load_extras() -> dict[str, float]:
    if EXTRAS_FILE.exists():
        try:
            return json.loads(EXTRAS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_extras(data: dict[str, float]) -> None:
    EXTRAS_FILE.write_text(json.dumps(data, ensure_ascii=False))


def load_extras() -> dict[str, float]:
    if EXTRAS_FILE.exists():
        try:
            return json.loads(EXTRAS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_extras(data: dict[str, float]) -> None:
    EXTRAS_FILE.write_text(json.dumps(data, ensure_ascii=False))

app = FastAPI(title="Freelancehunt Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_session(fh_session: Optional[str] = Cookie(default=None)):
    if not valid_token(fh_session):
        raise HTTPException(status_code=401, detail="Unauthorized")


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FreelancehuntError as e:
        raise HTTPException(status_code=e.status, detail=e.detail or e.title)


# ---------- Auth ----------
class LoginPayload(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(payload: LoginPayload, response: Response):
    user_ok = secrets.compare_digest(payload.username, DASH_USER)
    pass_ok = secrets.compare_digest(payload.password, DASH_PASS)
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    response.set_cookie(
        COOKIE_NAME, issue_token(), httponly=True, samesite="lax", max_age=COOKIE_MAX_AGE
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


# ---------- Profile ----------
@app.get("/api/profile", dependencies=[Depends(require_session)])
def get_profile():
    return call(client.my_profile)


@app.get("/api/portfolio", dependencies=[Depends(require_session)])
def get_portfolio():
    profile = call(client.my_profile)
    my_id = profile["data"]["id"]
    return call(client.portfolio, my_id)


@app.get("/api/income", dependencies=[Depends(require_session)])
def get_income():
    """Aggregate income from completed projects (freelancer reviews carry project budgets).

    Surcharges ("доплата") are not exposed by the API, so the user can record them
    manually per project; they are stored in income_extras.json and folded into totals.
    """
    profile = call(client.my_profile)
    my_id = profile["data"]["id"]
    extras = load_extras()

    by_month: dict[str, dict[str, float]] = {}
    projects: list[dict] = []
    total_by_currency: dict[str, float] = {}

    page = 1
    while page <= 20:  # safety cap
        payload = call(client.reviews, my_id, page)
        data = payload.get("data", [])
        if not data:
            break
        for rev in data:
            attrs = rev["attributes"]
            proj = attrs.get("project") or {}
            budget = proj.get("budget")
            published = attrs.get("published_at", "")
            if not budget:
                continue
            pid = proj.get("id")
            month = published[:7]
            cur = budget["currency"]
            base = budget["amount"]
            extra = float(extras.get(str(pid), 0) or 0)
            amount = base + extra
            by_month.setdefault(month, {}).setdefault(cur, 0)
            by_month[month][cur] += amount
            total_by_currency[cur] = total_by_currency.get(cur, 0) + amount
            projects.append(
                {
                    "project_id": pid,
                    "name": proj.get("name"),
                    "base": base,
                    "extra": extra,
                    "amount": amount,
                    "currency": cur,
                    "published_at": published,
                    "status": (proj.get("status") or {}).get("name"),
                }
            )
        if not payload.get("links", {}).get("next"):
            break
        page += 1

    # Fold in auto-detected surcharges from chat system messages.
    surcharges = scanner.get()
    surcharge_by_month = surcharges.get("by_month", {})
    surcharge_total = surcharges.get("total", {})
    for month, curs in surcharge_by_month.items():
        for cur, amt in curs.items():
            by_month.setdefault(month, {}).setdefault(cur, 0)
            by_month[month][cur] += amt
    for cur, amt in surcharge_total.items():
        total_by_currency[cur] = total_by_currency.get(cur, 0) + amt

    months_sorted = sorted(by_month.keys())
    return {
        "by_month": [{"month": m, "totals": by_month[m]} for m in months_sorted],
        "total_by_currency": total_by_currency,
        "projects_count": len(projects),
        "projects": sorted(projects, key=lambda p: p["published_at"], reverse=True),
        "surcharge_total": surcharge_total,
        "surcharge_items": surcharges.get("items", []),
    }


class ExtraPayload(BaseModel):
    project_id: int
    amount: float


@app.post("/api/income/extra", dependencies=[Depends(require_session)])
def set_income_extra(payload: ExtraPayload):
    extras = load_extras()
    if payload.amount:
        extras[str(payload.project_id)] = payload.amount
    else:
        extras.pop(str(payload.project_id), None)
    save_extras(extras)
    return {"ok": True}


# ---------- Projects ----------
@app.get("/api/projects", dependencies=[Depends(require_session)])
def get_projects(page: int = 1, skill_id: Optional[int] = None, budget_min: Optional[int] = None):
    filters = {}
    if skill_id:
        filters["skills"] = skill_id
    if budget_min:
        filters["budget_min"] = budget_min
    return call(client.projects, page=page, filters=filters or None)


@app.get("/api/projects/{project_id}", dependencies=[Depends(require_session)])
def get_project(project_id: int):
    return call(client.project, project_id)


@app.get("/api/projects/{project_id}/bids", dependencies=[Depends(require_session)])
def get_project_bids(project_id: int, status: Optional[str] = None):
    return call(client.project_bids, project_id, status)


class BidPayload(BaseModel):
    days: int
    amount: float
    currency: str = "UAH"
    comment: str
    safe_type: str = "employer"


@app.post("/api/projects/{project_id}/bids", dependencies=[Depends(require_session)])
def place_bid(project_id: int, payload: BidPayload):
    return call(
        client.place_bid,
        project_id,
        payload.days,
        payload.amount,
        payload.currency,
        payload.comment,
        payload.safe_type,
    )


@app.post("/api/projects/{project_id}/bids/{bid_id}/revoke", dependencies=[Depends(require_session)])
def revoke_bid(project_id: int, bid_id: int):
    return call(client.revoke_bid, project_id, bid_id)


@app.post("/api/projects/{project_id}/bids/{bid_id}/restore", dependencies=[Depends(require_session)])
def restore_bid(project_id: int, bid_id: int):
    return call(client.restore_bid, project_id, bid_id)


# ---------- My bids ----------
@app.get("/api/my/bids", dependencies=[Depends(require_session)])
def get_my_bids(status: Optional[str] = None):
    return call(client.my_bids, status)


# ---------- Threads ----------
@app.get("/api/threads", dependencies=[Depends(require_session)])
def get_threads(page: int = 1):
    return call(client.threads, page)


@app.get("/api/threads/{thread_id}", dependencies=[Depends(require_session)])
def get_thread_messages(thread_id: int, page: int = 1):
    return call(client.thread_messages, thread_id, page)


class ReplyPayload(BaseModel):
    message_html: str


@app.post("/api/threads/{thread_id}", dependencies=[Depends(require_session)])
def reply_thread(thread_id: int, payload: ReplyPayload):
    return call(client.reply_thread, thread_id, payload.message_html)


# ---------- Feed / notifications ----------
@app.get("/api/feed", dependencies=[Depends(require_session)])
def get_feed(page: int = 1):
    return call(client.feed, page)


@app.post("/api/feed/read", dependencies=[Depends(require_session)])
def read_feed():
    return call(client.feed_read)


# ---------- Reference ----------
@app.get("/api/skills", dependencies=[Depends(require_session)])
def get_skills():
    return call(client.skills)


# ---------- Static frontend ----------
@app.get("/assets/{filename}")
def assets(filename: str):
    path = (STATIC_DIR / filename).resolve()
    if STATIC_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/login")
def login_page():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/")
def index(fh_session: Optional[str] = Cookie(default=None)):
    if not valid_token(fh_session):
        return RedirectResponse("/login")
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
def _startup():
    scanner.start_background()
