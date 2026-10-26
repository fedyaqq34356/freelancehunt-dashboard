# Freelancehunt Dashboard

Self-hosted web dashboard + Telegram bot for managing a [Freelancehunt](https://freelancehunt.com) freelancer account through the [API v2](https://apidocs.freelancehunt.com). Built with FastAPI and vanilla JS — no build step, single dependency install, runs anywhere.

## Features

### Web dashboard
- **Dashboard** — rating, ranking, completed projects, success rate and other profile stats at a glance.
- **Projects** — live project feed with instant client-side search and budget filter; publish date and skill tags.
- **My bids** — all your bids with status, comment and winner marker.
- **Income** — earnings reconstructed from completed projects (review budgets), with a smooth per-month line chart and month drill-down. Surcharges are detected automatically from chat system messages (multi-language) and folded into the totals; manual per-project adjustments are also supported.
- **Messaging** — conversations grouped by client, then by project. Attachments (images, files, video, archives) from clients are rendered inline. Reply directly. Read receipts (has the client read your message) and client "last seen / online" status.
- **Notifications** — activity feed with unread badges and polling.
- **Portfolio** — gallery of your portfolio snippets with a lightbox.
- **Profile** — full profile view (contacts, verification, skills, bio).
- Signed-cookie "remember me" auth, responsive mobile layout, dark theme.

### Telegram bot «По» (aiogram)
- New projects in your specializations (filtered by your profile skills), each with two buttons: **Open** and **✍️ Bid**.
- **✍️ Bid** asks the AI agent По to write a bid: it picks the closest work from your portfolio and reviewed projects, builds the bid around a system you already shipped (so it is faster and cheaper for the client), adds one expert remark and ends with an easy question. A rule-based critic and a humanizer pass remove plan-of-work filler, generic claims and AI-style writing. Tokens are spent only when you press the button.
- Bid comes back as a reply to the project card: tap-to-copy text, price, deadline and which portfolio works to attach. **🔄 Another version** writes a different one.
- Client messages (with photos and files) and notifications are forwarded; reply to a forwarded message to answer the client.
- Menu: fresh projects, pause, minimum budget, profile.

## API limitations (upstream, not bugs)

Freelancehunt's API v2 is read-mostly. These are **not** possible through the API and are handled by linking out to the website:

- Placing / editing / revoking bids — deprecated (HTTP 410).
- Editing the profile or portfolio — not allowed (HTTP 405 / read-only).
- Seeing other freelancers' bids on a project — visible only to the project owner.
- Uploading files into a chat — only text replies are supported.

Messaging replies, reading the feed, and marking it read still work.

## Stack

- **Backend:** FastAPI + Uvicorn, `requests` for the Freelancehunt API.
- **Frontend:** static HTML/CSS/JS (no framework, no bundler).
- **Bot:** aiogram v3.

## Setup

```bash
git clone <repo-url>
cd freelancehunt-dashboard
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # fill in your token and credentials
```

Generate a secret for the auth cookie:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Run the dashboard

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` and log in with `DASHBOARD_USER` / `DASHBOARD_PASS`.

### Run the Telegram bot

```bash
python -m po.bot
```

Needs `TELEGRAM_BOT_TOKEN`, `FREELANCEHUNT_TOKEN` and `OPENAI_API_KEY` in `.env`. A systemd unit is in `deploy/po-fh.service`.

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

Send `/start` to your bot once to bind it to your chat.

## Project layout

```
app.py                    FastAPI app: auth, API proxy routes, income aggregation
bot.py                    aiogram Telegram bot
freelancehunt/
  client.py               thin Freelancehunt API v2 client
  surcharges.py           auto-detect surcharge payments from chat messages
static/
  index.html              dashboard shell
  login.html              login page
  style.css               styles
  app.js                  frontend logic
requirements.txt
.env.example
```

## Security notes

- Secrets live only in `.env` (gitignored) — never commit it.
- The dashboard is protected by a single login; run it behind HTTPS (e.g. a reverse proxy with a Let's Encrypt certificate) before exposing it publicly, since the login is sent as plain credentials over the connection.

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
