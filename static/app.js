const state = {
  projectsPage: 1,
  activeThreadId: null,
  myId: null,
  projectsRaw: [],
};

const TAB_TITLES = {
  dashboard: "Дашборд", projects: "Проекты", bids: "Мои ставки",
  income: "Доходы", threads: "Переписка", feed: "Уведомления", portfolio: "Портфолио",
};

// ---------- Helpers ----------
function toast(message, type = "success") {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `toast ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (res.status === 401) { window.location.href = "/login"; throw new Error("unauthorized"); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { const m = body.detail || `Ошибка ${res.status}`; toast(m, "error"); throw new Error(m); }
  return body;
}

function esc(s) {
  return (s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// Strip HTML tags to plain text (for feed notifications that arrive as HTML).
function stripHtml(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html || "";
  return (tmp.textContent || tmp.innerText || "").trim();
}

// Collapse 3+ newlines into a single blank line (fixes broken CV spacing).
function tidyText(s) {
  return (s || "").replace(/\n{3,}/g, "\n\n").trim();
}

function fmtDate(iso, withYear = false) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const t = { hour: "2-digit", minute: "2-digit" };
  if (d.toDateString() === now.toDateString()) return "сегодня " + d.toLocaleTimeString("ru-RU", t);
  const opts = withYear ? { day: "2-digit", month: "2-digit", year: "2-digit" } : { day: "2-digit", month: "2-digit" };
  return d.toLocaleDateString("ru-RU", opts) + " " + d.toLocaleTimeString("ru-RU", t);
}

function fmtDay(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "long", year: "numeric" });
}

function fmtMoney(b) { return b ? `${Number(b.amount).toLocaleString("ru-RU")} ${b.currency}` : ""; }
function fmtNum(n) { return Number(n).toLocaleString("ru-RU"); }

function timeAgo(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
}

const MONTH_NAMES = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"];
function monthLabel(ym) { const [y, m] = ym.split("-"); return `${MONTH_NAMES[+m - 1]} ${y.slice(2)}`; }

// ---------- Navigation ----------
function switchTab(tab) {
  document.querySelectorAll(".nav-item[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.getElementById(`tab-${tab}`).classList.add("active");
  document.getElementById("topbarTitle").textContent = TAB_TITLES[tab] || "";
  closeSidebar();
  if (tab === "projects") loadProjects();
  if (tab === "bids") loadBids();
  if (tab === "income") loadIncome();
  if (tab === "threads") loadThreads();
  if (tab === "feed") loadFeed();
  if (tab === "portfolio") loadPortfolio();
  if (tab === "profile") renderProfileTab();
}

function initNav() {
  document.querySelectorAll(".nav-item[data-tab]").forEach((btn) => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));
  document.getElementById("menuToggle").addEventListener("click", openSidebar);
  document.getElementById("scrim").addEventListener("click", closeSidebar);
  document.getElementById("logoutBtn").addEventListener("click", async () => {
    await api("/logout", { method: "POST" }).catch(() => {});
    window.location.href = "/login";
  });
}
function openSidebar() { document.getElementById("sidebar").classList.add("open"); document.getElementById("scrim").classList.add("show"); }
function closeSidebar() { document.getElementById("sidebar").classList.remove("open"); document.getElementById("scrim").classList.remove("show"); }

// ---------- Dashboard ----------
async function loadProfile() {
  const { data } = await api("/profile");
  state.myId = data.id;
  const a = data.attributes;
  state.profile = a;
  const avatarUrl = a.avatar?.small?.url || "";
  document.getElementById("avatar").src = avatarUrl;
  document.getElementById("topbarAvatar").src = avatarUrl;
  document.getElementById("profileName").textContent = `${a.first_name} ${a.last_name}`;
  document.getElementById("profileStatus").textContent = a.status?.name || "";
  document.getElementById("profileCv").textContent = tidyText(a.cv) || "Описание не заполнено";

  const stats = [
    ["Рейтинг", fmtNum(a.rating)], ["Позиция", `#${a.rating_position}`],
    ["Завершено", a.completed_projects], ["Успешность", `${a.success_rate}%`],
    ["Оценка", a.average_grade], ["Активные", a.active_projects],
    ["Отзывы +", a.positive_reviews], ["Просмотры", a.view_count],
  ];
  document.getElementById("statsGrid").innerHTML = stats
    .map(([l, v]) => `<div class="stat"><div class="stat-value">${v ?? "—"}</div><div class="stat-label">${l}</div></div>`).join("");
}

// ---------- Profile tab ----------
function renderProfileTab() {
  const a = state.profile;
  if (!a) return;
  const v = a.verification || {};
  const verifyItems = [
    ["Личность", v.identity], ["Телефон", v.phone], ["Email", v.email],
    ["Дата рожд.", v.birth_date], ["Сайт", v.website],
  ].filter(([, ok]) => ok).map(([l]) => `<span class="verify-badge">✓ ${l}</span>`).join("");

  const loc = a.location || {};
  const contacts = a.contacts || {};
  const info = [
    ["Локация", [loc.city?.name, loc.country?.name].filter(Boolean).join(", ")],
    ["Телефон", contacts.phone],
    ["Email", contacts.email],
    ["Сайт", contacts.website],
    ["На сайте с", a.created_at ? fmtDay(a.created_at) : ""],
    ["Был онлайн", a.visited_at ? fmtDate(a.visited_at, true) : ""],
    ["Freelancehunt Plus", a.is_plus_active ? "активен" : "нет"],
  ].filter(([, val]) => val).map(([k, val]) => `<div class="info-row"><span class="k">${k}</span><span class="v">${esc(String(val))}</span></div>`).join("");

  const skills = (a.skills || []).map((s) => `<span class="skill-chip">${esc(s.name)}</span>`).join("") || '<span class="client-sub">Навыки не указаны</span>';

  document.getElementById("profileView").innerHTML = `
    <div class="profile-hero">
      <img class="avatar" src="${a.avatar?.large?.url || a.avatar?.small?.url || ""}" alt="">
      <div class="profile-hero-info">
        <div class="profile-hero-name">${esc(a.first_name)} ${esc(a.last_name)}</div>
        <div class="profile-hero-login">@${esc(a.login)} · ${esc(a.status?.name || "")}</div>
        <div class="profile-hero-badges">${verifyItems}</div>
      </div>
    </div>
    <div class="profile-grid">
      <div class="card"><h2>Контакты и данные</h2>${info}</div>
      <div class="card"><h2>Навыки</h2><div class="skill-chips">${skills}</div></div>
    </div>
    <div class="card"><h2>О себе</h2><p class="cv-text">${esc(tidyText(a.cv)) || "Описание не заполнено"}</p></div>`;
}

// ---------- Projects (with working client-side filter) ----------
async function loadProjects() {
  const { data } = await api(`/projects?page=${state.projectsPage}`);
  state.projectsRaw = data;
  document.getElementById("projectsPage").textContent = state.projectsPage;
  renderProjects();
}

function renderProjects() {
  const q = (document.getElementById("searchFilter").value || "").toLowerCase().trim();
  const minB = Number(document.getElementById("budgetFilter").value) || 0;
  let items = state.projectsRaw;
  if (q) items = items.filter((p) => p.attributes.name.toLowerCase().includes(q));
  if (minB) items = items.filter((p) => (p.attributes.budget?.amount || 0) >= minB);

  document.getElementById("projectsList").innerHTML =
    items.map((p) => {
      const a = p.attributes;
      const skills = (a.skills || []).map((s) => `<span class="tag">${esc(s.name)}</span>`).join("");
      return `<div class="list-item">
        <div class="list-item-title">${esc(a.name)}</div>
        <div class="proj-tags">${skills}</div>
        <div class="list-item-meta">
          <span class="money">${fmtMoney(a.budget) || "Бюджет не указан"}</span>
          <span>${a.bid_count ?? 0} ставок</span>
          <span title="Опубликован">🕐 ${timeAgo(a.published_at)}</span>
        </div>
        <div class="list-item-actions">
          <a class="btn" href="https://freelancehunt.com/project/x/${p.id}.html" target="_blank" rel="noopener">Открыть и поставить ставку ↗</a>
        </div>
      </div>`;
    }).join("") || `<div class="empty-state">Ничего не найдено</div>`;
}

document.getElementById("searchFilter")?.addEventListener("input", renderProjects);
document.getElementById("budgetFilter")?.addEventListener("input", renderProjects);
document.getElementById("clearFilters")?.addEventListener("click", () => {
  document.getElementById("searchFilter").value = "";
  document.getElementById("budgetFilter").value = "";
  renderProjects();
});
document.getElementById("projectsPrev")?.addEventListener("click", () => { if (state.projectsPage > 1) { state.projectsPage--; loadProjects(); } });
document.getElementById("projectsNext")?.addEventListener("click", () => { state.projectsPage++; loadProjects(); });

// ---------- My bids (view-only: bid editing is API-deprecated) ----------
async function loadBids() {
  const { data } = await api("/my/bids");
  document.getElementById("bidsList").innerHTML =
    data.map((b) => {
      const a = b.attributes;
      const status = a.status?.name || "";
      const isRevoked = /отозв/i.test(status);
      const pid = a.project?.id;
      const isWinner = a.is_winner;
      return `<div class="list-item">
        <div class="list-item-title">${isWinner ? "🏆 " : ""}${esc(a.project?.name || "Проект")}</div>
        ${a.comment ? `<div class="bid-comment">${esc(a.comment)}</div>` : ""}
        <div class="list-item-meta">
          <span class="money">${fmtMoney(a.budget)}</span>
          <span class="pill ${isWinner ? "active" : isRevoked ? "revoked" : ""}">${esc(status)}</span>
          <span>${a.days} дн.</span>
          <span>${fmtDate(a.published_at)}</span>
        </div>
        <div class="list-item-actions">
          <a class="btn-ghost" href="https://freelancehunt.com/project/x/${pid}.html" target="_blank" rel="noopener">Открыть проект ↗</a>
        </div>
      </div>`;
    }).join("") || `<div class="empty-state">Ставок пока нет</div>`;
}

// ---------- Income ----------
let incomeData = null;
let monthFilter = null; // "YYYY-MM" or null for all

async function loadIncome() {
  incomeData = await api("/income");
  renderIncomeSummary();
  renderIncomeChart();
  renderMonthChips();
  renderIncomeProjects();
}

function renderIncomeSummary() {
  const totals = Object.entries(incomeData.total_by_currency);
  const surTotal = Object.entries(incomeData.surcharge_total || {});
  document.getElementById("incomeSummary").innerHTML = [
    ...totals.map(([cur, amt]) => `<div class="stat accent"><div class="stat-value money">${fmtNum(amt)} ${cur}</div><div class="stat-label">Всего заработано</div></div>`),
    `<div class="stat"><div class="stat-value">${incomeData.projects_count}</div><div class="stat-label">Оплаченных проектов</div></div>`,
    surTotal.length ? `<div class="stat"><div class="stat-value">${surTotal.map(([c, a]) => `+${fmtNum(a)}`).join(" ")}</div><div class="stat-label">Доплаты из чата (авто)</div></div>` : "",
  ].join("");
}

// Smooth SVG line/area chart with gridlines and collision-safe labels.
function renderIncomeChart() {
  const months = incomeData.by_month;
  const box = document.getElementById("incomeChart");
  if (!months.length) { box.innerHTML = `<div class="empty-state">Пока нет данных</div>`; return; }

  const W = Math.max(560, months.length * 92), H = 300;
  const padL = 22, padR = 22, padT = 58, padB = 40;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const vals = months.map((m) => Object.values(m.totals).reduce((a, b) => a + b, 0));
  const maxVal = Math.max(...vals) * 1.1 || 1;
  const x = (i) => padL + (months.length === 1 ? innerW / 2 : (i / (months.length - 1)) * innerW);
  const y = (v) => padT + innerH - (v / maxVal) * innerH;
  const pts = vals.map((v, i) => [x(i), y(v)]);

  // Catmull-Rom → cubic bezier for a smooth curve.
  const smooth = (p) => {
    if (p.length < 2) return p.length ? `M${p[0][0]},${p[0][1]}` : "";
    let d = `M${p[0][0].toFixed(1)},${p[0][1].toFixed(1)}`;
    for (let i = 0; i < p.length - 1; i++) {
      const p0 = p[i - 1] || p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] || p2;
      const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
    }
    return d;
  };
  const linePath = smooth(pts);
  const areaPath = `${linePath} L${x(months.length - 1).toFixed(1)},${(padT + innerH).toFixed(1)} L${x(0).toFixed(1)},${(padT + innerH).toFixed(1)} Z`;

  // Horizontal gridlines
  const grid = [0, 0.5, 1].map((f) => {
    const gy = (padT + innerH - f * innerH).toFixed(1);
    return `<line class="chart-grid" x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}"/>`;
  }).join("");

  const dots = pts.map((p, i) => {
    // Place value label above; if the point sits high, drop it below to avoid clipping.
    const labelAbove = p[1] > padT + 22;
    const ly = labelAbove ? p[1] - 15 : p[1] + 22;
    return `
      <text class="chart-val" x="${p[0].toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle">${fmtNum(vals[i])}</text>
      <circle class="chart-dot ${months[i].month === monthFilter ? "sel" : ""}" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="5.5" data-month="${months[i].month}"></circle>
      <text class="chart-xlabel" x="${p[0].toFixed(1)}" y="${(H - 12).toFixed(1)}" text-anchor="middle">${monthLabel(months[i].month)}</text>`;
  }).join("");

  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMinYMid meet" class="income-svg">
    <defs>
      <linearGradient id="incGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.30"/>
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>
      </linearGradient>
      <linearGradient id="incLine" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="var(--accent)"/>
        <stop offset="100%" stop-color="var(--accent-2)"/>
      </linearGradient>
    </defs>
    ${grid}
    <path d="${areaPath}" fill="url(#incGrad)"/>
    <path d="${linePath}" fill="none" stroke="url(#incLine)" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
    ${dots}
  </svg>`;
  document.getElementById("incomeHint").textContent = "клик по точке — месяц";
  box.querySelectorAll(".chart-dot").forEach((d) => d.addEventListener("click", () => {
    const m = d.getAttribute("data-month");
    monthFilter = monthFilter === m ? null : m;
    renderIncomeChart(); renderMonthChips(); renderIncomeProjects();
  }));
}

function renderMonthChips() {
  const chips = document.getElementById("monthChips");
  const months = [...incomeData.by_month].reverse();
  chips.innerHTML =
    `<button class="chip ${!monthFilter ? "on" : ""}" data-m="">Все</button>` +
    months.map((m) => `<button class="chip ${monthFilter === m.month ? "on" : ""}" data-m="${m.month}">${monthLabel(m.month)}</button>`).join("");
  chips.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    monthFilter = c.getAttribute("data-m") || null;
    renderIncomeChart(); renderMonthChips(); renderIncomeProjects();
  }));
}

function renderIncomeProjects() {
  // Unified timeline: completed projects (+ manual extra) and auto-detected surcharges.
  const projectEntries = incomeData.projects.map((p) => ({
    type: "project", name: p.name, amount: p.amount, base: p.base, extra: p.extra,
    currency: p.currency, date: p.published_at, project_id: p.project_id,
  }));
  const surchargeEntries = (incomeData.surcharge_items || []).map((s) => ({
    type: "surcharge",
    name: "Доплата · " + (s.subject || "").replace(/^Рабочая область проекта\s*/i, ""),
    amount: s.amount, currency: s.currency, date: s.posted_at,
  }));
  let entries = [...projectEntries, ...surchargeEntries];
  if (monthFilter) entries = entries.filter((e) => (e.date || "").slice(0, 7) === monthFilter);
  entries.sort((a, b) => (b.date || "").localeCompare(a.date || ""));

  const title = document.getElementById("incomeProjectsTitle");
  if (monthFilter) {
    const byCur = {};
    entries.forEach((e) => { byCur[e.currency] = (byCur[e.currency] || 0) + e.amount; });
    const sumStr = Object.entries(byCur).map(([c, a]) => `${fmtNum(a)} ${c}`).join(" + ");
    title.textContent = `${monthLabel(monthFilter)} — ${sumStr || "0"}`;
  } else {
    title.textContent = "Все поступления";
  }

  document.getElementById("incomeProjects").innerHTML =
    entries.map((e) => {
      if (e.type === "surcharge") {
        return `<div class="income-row surcharge-row">
          <div class="income-main">
            <div class="income-name">💰 ${esc(e.name)}</div>
            <div class="income-date">${fmtDay(e.date)}</div>
          </div>
          <div class="income-amounts"><span class="money">+${fmtNum(e.amount)} ${e.currency}</span></div>
          <div class="income-extra-edit"><span class="income-extra-badge">авто из чата</span></div>
        </div>`;
      }
      return `<div class="income-row">
        <div class="income-main">
          <div class="income-name">${esc(e.name)}</div>
          <div class="income-date">${fmtDay(e.date)}</div>
        </div>
        <div class="income-amounts">
          <span class="money">${fmtNum(e.amount)} ${e.currency}</span>
          ${e.extra ? `<span class="income-extra-badge">база ${fmtNum(e.base)} + доплата ${fmtNum(e.extra)}</span>` : ""}
        </div>
        <div class="income-extra-edit">
          <input type="number" class="extra-input" placeholder="доплата" value="${e.extra || ""}"
            onchange="saveExtra(${e.project_id}, this.value)">
        </div>
      </div>`;
    }).join("") || `<div class="empty-state">Нет поступлений</div>`;
}

window.saveExtra = async (projectId, value) => {
  const amount = Number(value) || 0;
  await api("/income/extra", { method: "POST", body: JSON.stringify({ project_id: projectId, amount }) });
  toast("Доплата сохранена");
  incomeData = await api("/income");
  renderIncomeSummary(); renderIncomeChart(); renderIncomeProjects();
};

// ---------- Threads (grouped by client → threads → conversation) ----------
let threadsRaw = [];
let clientsMap = {};   // clientId -> {info, threads:[]}
let navMode = "clients"; // "clients" | "threads"
let activeClientId = null;

function otherParty(a) {
  return a.participants?.from?.id === state.myId ? a.participants?.to : a.participants?.from;
}
function fullName(p) { return p ? `${p.first_name || ""} ${p.last_name || ""}`.trim() : "Заказчик"; }

// "online" if seen within 5 minutes, else a human "был(а) в сети …" label.
function lastSeenLabel(visitedAt) {
  if (!visitedAt) return { online: false, text: "" };
  const diff = (Date.now() - new Date(visitedAt)) / 1000;
  if (diff < 300) return { online: true, text: "в сети" };
  return { online: false, text: "был(а) в сети " + timeAgo(visitedAt) };
}

async function loadThreads() {
  const { data } = await api("/threads");
  threadsRaw = data;
  updateBadge("threadsBadge", data.filter((t) => t.attributes.is_unread).length);

  clientsMap = {};
  for (const t of data) {
    const a = t.attributes;
    const other = otherParty(a);
    if (!other) continue;
    const id = other.id;
    if (!clientsMap[id]) clientsMap[id] = { info: other, threads: [] };
    clientsMap[id].threads.push(t);
  }
  renderNav();
}

function renderNav() {
  const q = (document.getElementById("clientSearch").value || "").toLowerCase().trim();
  if (navMode === "clients") {
    document.getElementById("navTitle").textContent = "Заказчики";
    let clients = Object.values(clientsMap);
    if (q) clients = clients.filter((c) => fullName(c.info).toLowerCase().includes(q) || (c.info.login || "").toLowerCase().includes(q));
    clients.sort((a, b) => {
      const la = Math.max(...a.threads.map((t) => new Date(t.attributes.last_post_at)));
      const lb = Math.max(...b.threads.map((t) => new Date(t.attributes.last_post_at)));
      return lb - la;
    });
    document.getElementById("navList").innerHTML =
      clients.map((c) => {
        const unread = c.threads.filter((t) => t.attributes.is_unread).length;
        const last = c.threads.reduce((m, t) => t.attributes.last_post_at > m ? t.attributes.last_post_at : m, "");
        const av = c.info.avatar?.small?.url || "";
        const seen = lastSeenLabel(c.info.visited_at);
        return `<div class="client-item" onclick="openClient(${c.info.id})">
          <div class="chat-av-wrap">
            <img class="client-av" src="${av}" alt="" loading="lazy">
            ${seen.online ? '<span class="online-dot"></span>' : ""}
          </div>
          <div class="client-main">
            <div class="client-name">${esc(fullName(c.info))}</div>
            <div class="client-sub">${c.threads.length} диалог(ов) · ${seen.online ? "в сети" : fmtDate(last)}</div>
          </div>
          ${unread ? `<span class="badge">${unread}</span>` : ""}
        </div>`;
      }).join("") || `<div class="empty-state">Пусто</div>`;
  } else {
    const c = clientsMap[activeClientId];
    document.getElementById("navTitle").innerHTML = `<button class="nav-back" onclick="backToClients()">‹</button> ${esc(fullName(c.info))}`;
    let threads = [...c.threads].sort((a, b) => (b.attributes.last_post_at > a.attributes.last_post_at ? 1 : -1));
    if (q) threads = threads.filter((t) => t.attributes.subject.toLowerCase().includes(q));
    document.getElementById("navList").innerHTML =
      threads.map((t) => {
        const a = t.attributes;
        return `<div class="thread-item ${t.id === state.activeThreadId ? "selected" : ""}" onclick="openThread(${t.id})">
          <div class="subject">${a.is_unread ? '<span class="dot"></span>' : ""}${esc(a.subject.replace(/^Рабочая область проекта\s*/i, ""))}</div>
          <div class="snippet-meta">${fmtDate(a.last_post_at)} · ${a.messages_count} сообщ.${a.has_attachments ? " 📎" : ""}</div>
        </div>`;
      }).join("") || `<div class="empty-state">Нет диалогов</div>`;
  }
}

window.openClient = (clientId) => {
  activeClientId = clientId;
  navMode = "threads";
  document.getElementById("clientSearch").value = "";
  renderNav();
  // Auto-open the client's most recent thread for convenience.
  const c = clientsMap[clientId];
  const recent = [...c.threads].sort((a, b) => (b.attributes.last_post_at > a.attributes.last_post_at ? 1 : -1))[0];
  if (recent) openThread(recent.id);
};
window.backToClients = () => {
  navMode = "clients";
  document.getElementById("clientSearch").value = "";
  renderNav();
};
document.getElementById("clientSearch")?.addEventListener("input", renderNav);

function renderAttachments(list) {
  if (!list || !list.length) return "";
  return `<div class="attach-wrap">` + list.map((at) => {
    if (at.file_type === "image") {
      return `<a class="attach-img" href="${at.url}" target="_blank" rel="noopener"><img src="${at.thumbnail_url || at.url}" alt="${esc(at.name)}" loading="lazy"></a>`;
    }
    const kb = at.size ? ` · ${(at.size / 1024).toFixed(0)} КБ` : "";
    const icon = at.file_type === "video" ? "🎬" : /\.(zip|rar|7z|tar|gz)$/i.test(at.name) ? "🗜" : /\.py$/i.test(at.name) ? "🐍" : "📄";
    return `<a class="attach-file" href="${at.url}" target="_blank" rel="noopener" download>${icon} <span>${esc(at.name)}</span><small>${kb}</small></a>`;
  }).join("") + `</div>`;
}

const SURCHARGE_RE = /(доплат|надбав|surcharge|extra\s+payment|dopła)/i;

window.openThread = async (threadId) => {
  state.activeThreadId = threadId;
  const thread = threadsRaw.find((t) => t.id === threadId);
  const ta = thread ? thread.attributes : {};
  const other = otherParty(ta) || {};
  const subject = (ta.subject || "Переписка").replace(/^Рабочая область проекта\s*/i, "");
  const av = other.avatar?.small?.url || "";

  document.getElementById("threadsLayout").classList.add("viewing");
  renderNav(); // update selected state
  const view = document.getElementById("threadView");
  const seen = lastSeenLabel(other.visited_at);
  const header = `<div class="thread-view-header">
    <div class="chat-av-wrap">
      <img class="chat-av" src="${av}" alt="">
      ${seen.online ? '<span class="online-dot"></span>' : ""}
    </div>
    <button class="thread-back" onclick="backToThreadsList()">‹</button>
    <div class="chat-head-info">
      <div class="chat-head-name">${esc(fullName(other))}</div>
      <div class="chat-head-sub">${seen.text}</div>
    </div>
    <a class="btn-ghost chat-open" href="https://freelancehunt.com/mailbox/read/thread/${threadId}" target="_blank" rel="noopener">↗</a>
  </div>`;
  view.innerHTML = header + `<div class="messages"><div class="empty-state">Загрузка…</div></div>`;

  const { data } = await api(`/threads/${threadId}`);
  const messages = [...data].reverse();
  const html = messages.map((m) => {
    const a = m.attributes;
    const mine = a.participants?.from?.id === state.myId;
    const text = a.message_text || "";
    const isSys = a.participants?.from?.id === 4 || SURCHARGE_RE.test(text);
    const isSurcharge = SURCHARGE_RE.test(text) && /\d/.test(text);
    if (isSurcharge) {
      return `<div class="sys-msg surcharge">💰 ${esc(text)}<div class="message-time">${fmtDate(a.posted_at)}</div></div>`;
    }
    if (isSys) {
      return `<div class="sys-msg">${esc(text)}<div class="message-time">${fmtDate(a.posted_at)}</div></div>`;
    }
    const body = a.message_html || `<p>${esc(text)}</p>`;
    // For my messages, is_unread reflects whether the CLIENT has read it yet.
    const tick = mine
      ? `<span class="read-tick ${a.is_unread ? "" : "read"}" title="${a.is_unread ? "Не прочитано" : "Прочитано"}">${a.is_unread ? "✓" : "✓✓"}</span>`
      : "";
    return `<div class="message ${mine ? "mine" : ""}">
      <div class="msg-body">${body}</div>
      ${renderAttachments(a.attachments)}
      <div class="message-time">${fmtDate(a.posted_at)}${tick}</div>
    </div>`;
  }).join("");

  view.innerHTML = header + `
    <div class="messages" id="messagesBox">${html || '<div class="empty-state">Нет сообщений</div>'}</div>
    <div class="reply-box">
      <textarea id="replyText" rows="2" placeholder="Сообщение… (Ctrl+Enter — отправить)"></textarea>
      <button class="btn reply-send" onclick="sendReply(${threadId})">➤</button>
    </div>`;
  const box = document.getElementById("messagesBox");
  box.scrollTop = box.scrollHeight;
  document.getElementById("replyText").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendReply(threadId);
  });
};
// On mobile, "back" from a conversation returns to the thread/client list.
window.backToThreadsList = () => {
  state.activeThreadId = null;
  document.getElementById("threadsLayout").classList.remove("viewing");
  renderNav();
};
window.sendReply = async (threadId) => {
  const input = document.getElementById("replyText");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  const html = text.split("\n").map((l) => `<p>${esc(l)}</p>`).join("");
  await api(`/threads/${threadId}`, { method: "POST", body: JSON.stringify({ message_html: html }) });
  openThread(threadId);
};

// ---------- Feed (fixed formatting) ----------
async function loadFeed() {
  const { data } = await api("/feed");
  updateBadge("feedBadge", data.filter((m) => m.attributes.is_new).length);
  document.getElementById("feedList").innerHTML =
    data.map((m) => {
      const a = m.attributes;
      const from = a.from ? `${a.from.first_name || ""} ${a.from.last_name || ""}`.trim() : "";
      const text = stripHtml(a.message) || from || "Уведомление"; // message arrives as HTML
      return `<div class="list-item">
        <div class="list-item-title">${a.is_new ? '<span class="dot"></span>' : ""}${esc(text)}</div>
        <div class="list-item-meta">
          ${a.is_new ? '<span class="pill new">Новое</span>' : ""}
          ${from ? `<span>${esc(from)}</span>` : ""}
          <span>${fmtDate(a.created_at)}</span>
        </div>
      </div>`;
    }).join("") || `<div class="empty-state">Уведомлений нет</div>`;
}
document.getElementById("markReadBtn").addEventListener("click", async () => {
  await api("/feed/read", { method: "POST" });
  toast("Отмечено прочитанным");
  loadFeed();
});

// ---------- Portfolio ----------
let pfItems = [];
async function loadPortfolio() {
  const grid = document.getElementById("portfolioGrid");
  grid.innerHTML = `<div class="empty-state">Загрузка…</div>`;
  const { data } = await api("/portfolio");
  pfItems = data;
  grid.innerHTML =
    data.map((s, i) => {
      const a = s.attributes;
      const thumb = a.image?.small?.url || "";
      return `<div class="pf-card" onclick="openPf(${i})">
        ${thumb ? `<img class="pf-thumb" src="${thumb}" alt="" loading="lazy">` : `<div class="pf-thumb"></div>`}
        <div class="pf-body"><div class="pf-name">${esc(a.name)}</div><div class="pf-skill">${esc(a.skill?.name || "")}</div></div>
      </div>`;
    }).join("") || `<div class="empty-state">Портфолио пусто</div>`;
}
window.openPf = (i) => {
  const a = pfItems[i].attributes;
  document.getElementById("pfImage").src = a.image?.large?.url || a.image?.small?.url || "";
  document.getElementById("pfTitle").textContent = a.name;
  document.getElementById("pfSkill").textContent = a.skill?.name || "";
  document.getElementById("pfComment").textContent = tidyText(a.comment);
  const link = document.getElementById("pfLink");
  if (a.url) { link.href = a.url; link.classList.remove("hidden"); } else { link.classList.add("hidden"); }
  document.getElementById("pfModal").classList.remove("hidden");
};
document.getElementById("pfClose").addEventListener("click", () => document.getElementById("pfModal").classList.add("hidden"));

// ---------- Badges & polling ----------
function updateBadge(id, count) {
  const badge = document.getElementById(id);
  if (count > 0) { badge.textContent = count; badge.classList.remove("hidden"); } else badge.classList.add("hidden");
}
async function poll() {
  try {
    const [feed, threads] = await Promise.all([api("/feed"), api("/threads")]);
    updateBadge("feedBadge", feed.data.filter((m) => m.attributes.is_new).length);
    updateBadge("threadsBadge", threads.data.filter((t) => t.attributes.is_unread).length);
  } catch (e) { /* ignore */ }
}

document.querySelectorAll(".modal").forEach((m) => m.addEventListener("click", (e) => { if (e.target === m) m.classList.add("hidden"); }));

// ---------- Init ----------
(async function init() {
  initNav();
  document.getElementById("topbarTitle").textContent = "Дашборд";
  await loadProfile();
  await poll();
  setInterval(poll, 45000);
})();
