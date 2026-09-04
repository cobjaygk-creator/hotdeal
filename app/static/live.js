const configEl = document.getElementById("live-config");
const config = configEl ? JSON.parse(configEl.textContent) : { live: false };
const bodyEl = document.getElementById("deal-body");
const statusEl = document.getElementById("live-status");
const dot = document.getElementById("live-dot");
const chipRow = document.getElementById("source-chips");
const moreBtn = document.getElementById("more-btn");
const filterEmpty = document.getElementById("filter-empty");
const bookmarkChip = document.getElementById("bookmark-chip");
const STORAGE_KEY = "hotdeal.sourceChips";
const BOOKMARK_KEY = "hotdeal.bookmarks";
const sourceLabels = config.sourceLabels || {};
const seen = new Set(
  bodyEl ? [...bodyEl.querySelectorAll("[data-id]")].map((row) => row.dataset.id) : []
);

let selectedSources = null;
let bookmarkOnly = false;
let hasMore = !!config.hasMore;
let loadingMore = false;

function loadBookmarks() {
  try {
    return JSON.parse(localStorage.getItem(BOOKMARK_KEY) || "[]").map(String);
  } catch (e) {
    return [];
  }
}

function saveBookmarks(ids) {
  try {
    localStorage.setItem(BOOKMARK_KEY, JSON.stringify(ids.map((x) => Number(x))));
  } catch (e) {}
  scheduleBookmarkSync(ids);
}

let meLoggedIn = false;
let bookmarkTimer = null;

function scheduleBookmarkSync(ids) {
  if (!meLoggedIn) return;
  clearTimeout(bookmarkTimer);
  bookmarkTimer = setTimeout(() => {
    fetch("/api/me/bookmarks", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ids: ids.map((x) => Number(x)).filter((n) => n > 0).slice(0, 200),
      }),
    }).catch(() => {});
  }, 400);
}

async function syncBookmarksFromServer() {
  try {
    const me = await fetch("/api/me", { credentials: "same-origin" }).then((r) => r.json());
    meLoggedIn = !!(me && me.user);
    if (!meLoggedIn) return;
    const data = await fetch("/api/me/bookmarks", { credentials: "same-origin" }).then((r) => r.json());
    const remote = (data.ids || []).map(String);
    const merged = Array.from(new Set(loadBookmarks().concat(remote)));
    try {
      localStorage.setItem(BOOKMARK_KEY, JSON.stringify(merged.map((x) => Number(x))));
    } catch (e) {}
    paintBookmarkButtons();
    scheduleBookmarkSync(merged);
  } catch (e) {}
}

function isBookmarked(id) {
  return loadBookmarks().includes(String(id));
}

function toggleBookmark(id) {
  const ids = loadBookmarks();
  const sid = String(id);
  const next = ids.includes(sid) ? ids.filter((x) => x !== sid) : ids.concat(sid);
  saveBookmarks(next);
  document.querySelectorAll(`.bookmark-btn[data-deal-id="${sid}"]`).forEach((btn) => {
    btn.classList.toggle("on", next.includes(sid));
    btn.textContent = next.includes(sid) ? "★" : "☆";
  });
  if (bookmarkOnly) applySourceFilter();
  return next.includes(sid);
}

function paintBookmarkButtons() {
  const ids = new Set(loadBookmarks());
  document.querySelectorAll(".bookmark-btn[data-deal-id]").forEach((btn) => {
    const on = ids.has(btn.dataset.dealId);
    btn.classList.toggle("on", on);
    btn.textContent = on ? "★" : "☆";
  });
  if (bookmarkChip) bookmarkChip.classList.toggle("on", bookmarkOnly);
}

function kst(s) {
  if (!s) return "-";
  const iso = String(s).includes("T") ? String(s) : String(s).replace(" ", "T");
  const aware = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const d = new Date(aware);
  if (Number.isNaN(d.getTime())) return String(s);
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
    .format(d)
    .replace("T", " ");
}

window.relativeTime = relativeTime;
function relativeTime(s) {
  if (!s) return "-";
  const iso = String(s).includes("T") ? String(s) : String(s).replace(" ", "T");
  const aware = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const d = new Date(aware);
  if (Number.isNaN(d.getTime())) return String(s);
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 45) return "방금";
  if (secs < 3600) return Math.max(1, Math.floor(secs / 60)) + "분전";
  if (secs < 86400) return Math.floor(secs / 3600) + "시간전";
  if (secs < 86400 * 7) return Math.floor(secs / 86400) + "일전";
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

function clockTime(s) {
  if (!s) return "";
  const iso = String(s).includes("T") ? String(s) : String(s).replace(" ", "T");
  const aware = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const d = new Date(aware);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

function refreshTimes() {
  if (!bodyEl) return;
  bodyEl.querySelectorAll(".time-rel[data-ts]").forEach((el) => {
    el.textContent = relativeTime(el.dataset.ts);
  });
  bodyEl.querySelectorAll(".time-abs[data-ts]").forEach((el) => {
    el.textContent = clockTime(el.dataset.ts);
  });
}

function won(n) {
  return n == null ? "-" : Number(n).toLocaleString("ko-KR") + "원";
}

function priceHtml(n) {
  return n == null ? "-" : Number(n).toLocaleString("ko-KR") + '<span class="won">원</span>';
}

function offHtml(rate) {
  if (rate == null) return "";
  const pct = Math.round(-Number(rate) * 100);
  if (!(pct > 0)) return "";
  return `<span class="deal-off">-${pct}%</span>`;
}

function detailOffHtml(deal) {
  if (deal.discount_rate == null) return "";
  const pct = Math.round(-Number(deal.discount_rate) * 100);
  if (!(pct > 0)) return "";
  const g = deal.grade || "";
  const prefix = g.includes("초특가")
    ? "초특가 "
    : g.includes("특가")
      ? "특가 "
      : g.includes("핫딜")
        ? "핫딜 "
        : "";
  return `<span class="deal-off">${prefix}-${pct}%</span>`;
}

function strikeHtml(deal, hasBaseline, cheaper) {
  if (deal.discount_rate != null && deal.price) {
    const r = Number(deal.discount_rate);
    if (r < 0 && r > -0.95) {
      const orig = Math.round(Number(deal.price) / (1 + r));
      if (orig > Number(deal.price)) return `<span class="mkt-strike">${won(orig)}</span>`;
    }
  }
  if (hasBaseline && cheaper) return `<span class="mkt-strike">${won(deal.baseline_price)}</span>`;
  return "";
}

function lowestHtml(deal) {
  if (!deal.min_price || !deal.price || Number(deal.price) > Number(deal.min_price)) return "";
  return (
    '<span class="deal-lowest">' +
    '<svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M3 8.5l3 3 7-7"></path></svg>최저가' +
    "</span>"
  );
}

function pct(rate) {
  return rate == null ? "-" : (-rate * 100).toFixed(1) + "%";
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function sourceTokens(raw) {
  return String(raw || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function labelSources(raw) {
  const toks = sourceTokens(raw);
  if (!toks.length) return "-";
  return toks.map((s) => sourceLabels[s] || s).join(", ");
}

function tagsHtml(deal) {
  const parts = [];
  if (deal.category) {
    parts.push(`<span class="deal-tag">${esc(deal.category)}</span>`);
  }
  if (deal.seller) {
    parts.push(`<span class="deal-tag">${esc(deal.seller)}</span>`);
  }
  for (const key of sourceTokens(deal.sources)) {
    const label = sourceLabels[key] || key;
    const initial = label.slice(0, 1) || "?";
    parts.push(
      `<span class="deal-tag deal-tag-source" data-source="${esc(key)}"><span class="deal-tag-ico" aria-hidden="true">${esc(initial)}</span>${esc(label)}</span>`
    );
  }
  return `<div class="deal-tags">${parts.join("")}</div>`;
}

function matchesSources(raw) {
  if (!selectedSources || !selectedSources.length) return true;
  const toks = sourceTokens(raw);
  return selectedSources.some((s) => toks.includes(s));
}

function matchesFilter(deal) {
  if (config.grade && !(deal.grade || "").includes(config.grade)) return false;
  if (config.seller && deal.seller !== config.seller) return false;
  if (!matchesSources(deal.sources)) return false;
  return true;
}

function isHot(deal) {
  const g = deal.grade || "";
  return g.includes("핫딜") || g.includes("특가");
}

function gradeHtml(grade) {
  const g = grade || "-";
  if (g.includes("초특가")) return `<span class="grade-chip grade-super">${esc(g)}</span>`;
  if (g.includes("특가")) return `<span class="grade-chip grade-special">${esc(g)}</span>`;
  if (g.includes("핫딜")) return `<span class="grade-chip grade-hot">${esc(g)}</span>`;
  if (g === "관심") return `<span class="grade-chip grade-watch">${esc(g)}</span>`;
  return `<span class="grade-quiet">${esc(g)}</span>`;
}

function isPostUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url.trim());
}

function renderRow(deal, { fresh = false } = {}) {
  const li = document.createElement("li");
  li.className = "deal-card" + (fresh ? (isHot(deal) ? " fresh hot-fresh" : " fresh") : "");
  li.dataset.id = String(deal.id);
  li.dataset.sources = deal.sources || "";
  li.dataset.ts = deal.last_seen_at || "";
  li.dataset.category = deal.category || "";
  li.dataset.price = deal.price != null ? String(deal.price) : "";
  li.dataset.discount = deal.discount_rate != null ? String(deal.discount_rate) : "";
  li.dataset.comments = String((Number(deal.user_comments) || 0) + (Number(deal.comments) || 0));
  li.dataset.status = deal.status || "";
  if (deal.mall_url) li.dataset.mallUrl = deal.mall_url;
  const starred = isBookmarked(deal.id);
  const title = deal.product_name || "(제목 없음)";
  const thumb = deal.thumbnail_url
    ? `<img class="deal-thumb" src="${esc(deal.thumbnail_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="deal-thumb placeholder" aria-hidden="true"></div>`;
  const ts = deal.last_seen_at || "";
  const comments =
    deal.comments && Number(deal.comments) > 0
      ? `<span class="deal-comments" aria-label="원문 댓글 ${Number(deal.comments)}">댓글 ${Number(deal.comments)}</span>`
      : "";
  const userComments =
    deal.user_comments && Number(deal.user_comments) > 0
      ? `<span class="deal-user-comments" aria-label="댓글 ${Number(deal.user_comments)}">댓글 ${Number(deal.user_comments)}</span>`
      : "";
  const soldout = deal.status === "expired" ? `<span class="deal-soldout">품절</span>` : "";
  if (deal.status === "expired") li.classList.add("is-expired");
  li.innerHTML =
    `<a class="deal-row-main" href="/deal/${deal.id}" data-deal-id="${deal.id}">` +
    `<div class="deal-thumb-wrap">${thumb}</div>` +
    `<div class="deal-body">` +
    tagsHtml(deal) +
    `<span class="deal-title">${esc(title)}</span>` +
    `<div class="deal-price-row"><div class="deal-price">${priceHtml(deal.price)}</div>` +
    offHtml(deal.discount_rate) +
    lowestHtml(deal) +
    `<time class="time-rel" datetime="${esc(ts)}" data-ts="${esc(ts)}">${esc(relativeTime(ts))}</time>${comments}${userComments}${soldout}</div>` +
    `</div></a>` +
    `<div class="deal-row-side">` +
    (isPostUrl(deal.mall_url)
      ? `<a class="deal-buy-btn" href="${esc(deal.mall_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">구매하기</a>`
      : "") +
    `<button type="button" class="bookmark-btn${starred ? " on" : ""}" data-deal-id="${deal.id}" aria-label="북마크">${starred ? "★" : "☆"}</button>` +
    `<time class="time-abs" datetime="${esc(ts)}" data-ts="${esc(ts)}">${esc(clockTime(ts))}</time>` +
    `</div>`;
  applyChipClass(li);
  return li;
}

function applyChipClass(el) {
  const hideSource = !matchesSources(el.dataset.sources);
  const hideSaved = bookmarkOnly && !isBookmarked(el.dataset.id);
  el.classList.toggle("is-filtered-out", hideSource || hideSaved);
}

function visibleCount() {
  return [...bodyEl.querySelectorAll("[data-id]")].filter(
    (el) => !el.classList.contains("is-filtered-out")
  ).length;
}

function applySourceFilter() {
  if (!bodyEl) {
    paintBookmarkButtons();
    return;
  }
  bodyEl.querySelectorAll("[data-id]").forEach(applyChipClass);
  const cards = bodyEl.querySelectorAll("[data-id]").length;
  if (filterEmpty) {
    filterEmpty.hidden = !(cards && visibleCount() === 0);
  }
  paintChips();
  paintBookmarkButtons();
  setMoreVisible();
}

function paintChips() {
  if (!chipRow) return;
  const all = !selectedSources || !selectedSources.length;
  chipRow.querySelectorAll("[data-source]").forEach((btn) => {
    const src = btn.dataset.source;
    // Match UX Insight: only "전체" is filled when everything is selected.
    const on = src === "*" ? all : !all && selectedSources.includes(src);
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function persistSources() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(selectedSources || []));
  } catch (e) {}
}

function loadSavedSources() {
  const fromUrl = (config.source || "").trim();
  if (fromUrl) {
    selectedSources = [fromUrl];
    persistSources();
    return;
  }
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    if (Array.isArray(raw) && raw.length) selectedSources = raw;
    else selectedSources = null;
  } catch (e) {
    selectedSources = null;
  }
}

function setMoreVisible() {
  if (moreBtn) moreBtn.hidden = !hasMore || bookmarkOnly;
}

async function loadMore() {
  if (loadingMore || !hasMore) return 0;
  const last = [...bodyEl.querySelectorAll("[data-id]")].pop();
  if (!last) return 0;
  loadingMore = true;
  if (moreBtn) {
    moreBtn.disabled = true;
    moreBtn.textContent = "불러오는 중…";
  }
  try {
    const params = new URLSearchParams({
      limit: String(config.pageSize || 40),
      before_id: last.dataset.id,
    });
    if (config.grade) params.set("grade", config.grade);
    if (config.seller) params.set("seller", config.seller);
    if (config.category) params.set("cat", config.category);
    const res = await fetch("/api/deals?" + params.toString());
    const items = await res.json();
    if (!Array.isArray(items) || !items.length) {
      hasMore = false;
      setMoreVisible();
      return 0;
    }
    let added = 0;
    for (const deal of items) {
      const id = String(deal.id);
      if (seen.has(id)) continue;
      seen.add(id);
      bodyEl.append(renderRow(deal));
      added += 1;
    }
    if (items.length < (config.pageSize || 40)) hasMore = false;
    setMoreVisible();
    applySourceFilter();
    return added;
  } catch (e) {
    setLive(false, "더보기 실패");
    return 0;
  } finally {
    loadingMore = false;
    if (moreBtn) {
      moreBtn.disabled = false;
      moreBtn.textContent = "더보기";
    }
  }
}

async function ensureVisible(min) {
  let guard = 0;
  while (visibleCount() < min && hasMore && guard < 6) {
    guard += 1;
    const n = await loadMore();
    if (!n) break;
  }
  applySourceFilter();
}

function applyStats(stats) {
  if (!stats) return;
  const posts = document.getElementById("stat-posts");
  const hot = document.getElementById("stat-hot");
  const strong = document.getElementById("stat-strong");
  const last = document.getElementById("stat-last");
  if (posts) posts.textContent = stats.posts;
  if (hot) hot.textContent = stats.today_hot;
  if (strong) strong.textContent = stats.strong;
  if (last) last.textContent = kst(stats.last_collect_at);
}

function prefersReducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {
    return false;
  }
}

function flipPrepend(rows, { animate = false } = {}) {
  if (!bodyEl || !rows.length) return;
  if (!animate || prefersReducedMotion()) {
    for (const row of rows) bodyEl.prepend(row);
    return;
  }
  const prev = new Map();
  bodyEl.querySelectorAll(".deal-card[data-id]").forEach((el) => {
    prev.set(el.dataset.id, el.getBoundingClientRect());
  });
  for (const row of rows) bodyEl.prepend(row);
  requestAnimationFrame(() => {
    bodyEl.querySelectorAll(".deal-card[data-id]").forEach((el) => {
      const first = prev.get(el.dataset.id);
      if (!first) return;
      const last = el.getBoundingClientRect();
      const dx = first.left - last.left;
      const dy = first.top - last.top;
      if (!dx && !dy) return;
      el.style.transition = "none";
      el.style.transform = `translate(${dx}px, ${dy}px)`;
      requestAnimationFrame(() => {
        el.style.transition = "transform 0.9s cubic-bezier(0.22, 1, 0.36, 1)";
        el.style.transform = "";
        const clear = (ev) => {
          if (ev.propertyName && ev.propertyName !== "transform") return;
          el.style.transition = "";
          el.removeEventListener("transitionend", clear);
        };
        el.addEventListener("transitionend", clear);
      });
    });
  });
}

function patchRowMall(deal) {
  if (!bodyEl || !deal || !isPostUrl(deal.mall_url)) return;
  const li = bodyEl.querySelector(`[data-id="${deal.id}"]`);
  if (!li) return;
  li.dataset.mallUrl = deal.mall_url;
  const existing = li.querySelector(".deal-buy-btn");
  if (existing) {
    existing.href = deal.mall_url;
    return;
  }
  const side = li.querySelector(".deal-row-side");
  if (!side) return;
  const a = document.createElement("a");
  a.className = "deal-buy-btn";
  a.href = deal.mall_url;
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = "구매하기";
  a.addEventListener("click", (ev) => ev.stopPropagation());
  side.prepend(a);
}

function ingest(items, { animate = false, allowInsert = true } = {}) {
  if (!bodyEl || !items || !items.length) return;
  const rows = [];
  for (const deal of items) {
    const id = String(deal.id);
    if (seen.has(id)) {
      patchRowMall(deal);
      continue;
    }
    if (!allowInsert) continue;
    // Wait for shop-link enrichment before inserting a brand-new live card.
    if (!isPostUrl(deal.mall_url) && !deal.list_ready) continue;
    if (config.grade && !(deal.grade || "").includes(config.grade)) continue;
    if (config.seller && deal.seller !== config.seller) continue;
    if (config.category && deal.category !== config.category) continue;
    seen.add(id);
    rows.push(renderRow(deal, { fresh: animate }));
  }
  if (rows.length) {
    bodyEl.querySelector(".empty-row")?.remove();
    flipPrepend(rows, { animate });
    applySourceFilter();
  }
}

function setLive(ok, text) {
  if (!statusEl || !dot) return;
  statusEl.textContent = text;
  dot.classList.toggle("on", ok);
  dot.classList.toggle("off", !ok);
  const meta = document.getElementById("live-meta");
  if (meta) {
    meta.classList.toggle("live-ok", ok);
    meta.classList.toggle("live-off", !ok);
  }
}

function connect() {
  const es = new EventSource("/api/stream");
  es.onopen = () => setLive(true, "실시간 수신 중");
  es.onmessage = (ev) => {
    if (!ev.data) return;
    const data = JSON.parse(ev.data);
    const n = Number(data.new_posts) || 0;
    if (!n) {
      // Mall-link enrichment can publish existing cards with new_posts: 0.
      // Only update a card that is already on screen; do not refresh the list.
      ingest(data.items || [], { allowInsert: false });
      return;
    }
    applyStats(data.stats);
    setLive(true, `신규 ${n}건 반영`);
    ingest(data.items || [], { animate: true });
  };
  es.onerror = () => {
    setLive(false, "연결 끊김 · 재시도 중");
  };
}

async function loadMissingBookmarks() {
  if (!bodyEl) return;
  const missing = loadBookmarks().filter((id) => !seen.has(String(id)));
  if (!missing.length) return;
  try {
    const res = await fetch("/api/deals?ids=" + missing.join(","));
    const items = await res.json();
    if (!Array.isArray(items)) return;
    for (const deal of items) {
      const id = String(deal.id);
      if (seen.has(id)) continue;
      seen.add(id);
      bodyEl.append(renderRow(deal));
    }
  } catch (e) {}
}

document.getElementById("collect-btn")?.addEventListener("click", async (e) => {
  const btn = e.target;
  btn.disabled = true;
  btn.textContent = "수집 중...";
  try {
    const res = await fetch("/api/collect", { method: "POST" });
    const data = await res.json();
    const newPosts = Number(data.new_posts) || 0;
    ingest(data.new_deals || [], { animate: newPosts > 0, allowInsert: newPosts > 0 });
    setLive(true, `수동 수집 완료 · 신규 ${newPosts}건`);
  } catch (err) {
    setLive(false, "수집 실패");
  } finally {
    btn.disabled = false;
    btn.textContent = "지금 수집";
  }
});

if (chipRow) {
  chipRow.addEventListener("click", (e) => {
    if (e.target.closest("[data-bookmarks]")) return;
    const btn = e.target.closest("[data-source]");
    if (!btn) return;
    const src = btn.dataset.source;
    if (src === "*") {
      selectedSources = null;
    } else if (!selectedSources || !selectedSources.length) {
      selectedSources = [src];
    } else if (selectedSources.includes(src)) {
      selectedSources = selectedSources.filter((s) => s !== src);
      if (!selectedSources.length) selectedSources = null;
    } else {
      selectedSources = [...selectedSources, src];
    }
    persistSources();
    applySourceFilter();
    if (selectedSources && selectedSources.length) ensureVisible(12);
  });
}

if (bookmarkChip) {
  bookmarkChip.addEventListener("click", async () => {
    bookmarkOnly = !bookmarkOnly;
    if (bookmarkOnly) await loadMissingBookmarks();
    applySourceFilter();
  });
}

if (moreBtn) {
  moreBtn.addEventListener("click", () => loadMore());
}

if (bodyEl) {
  loadSavedSources();
  applySourceFilter();
  setMoreVisible();
  if (selectedSources && selectedSources.length) ensureVisible(12);
  refreshTimes();
  setInterval(refreshTimes, 30000);
  if (config.live !== false) connect();
} else {
  paintBookmarkButtons();
}
syncBookmarksFromServer();

const modal = document.getElementById("deal-modal");
const modalBody = document.getElementById("modal-body");
const modalCta = document.getElementById("modal-cta");
let chart;
let marketChart;
let modalPushed = false;
let modalOpenId = null;
let marketLoadedFor = null;

function specRow(label, value) {
  if (value == null || value === "" || value === "-") return "";
  return `<div class="dd-spec-row"><span>${esc(label)}</span><strong>${value}</strong></div>`;
}

function closeModal(opts) {
  const fromPop = opts && opts.fromPop;
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
  if (chart) {
    chart.destroy();
    chart = null;
  }
  if (marketChart) {
    marketChart.destroy();
    marketChart = null;
  }
  if (modalCta) {
    modalCta.innerHTML = "";
    modalCta.hidden = true;
  }
  marketLoadedFor = null;
  if (window.DealChatPin) window.DealChatPin.unbind();
  if (window.DealChat) window.DealChat.stop();
  const wasOpen = modalOpenId;
  modalOpenId = null;
  if (!fromPop && wasOpen && modalPushed) {
    modalPushed = false;
    window.history.back();
  } else if (!fromPop && wasOpen && location.pathname.startsWith("/deal/")) {
    window.history.replaceState({}, "", "/");
  }
}

async function fetchDealDetail(id) {
  let lastErr = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch("/api/deals/" + id, { cache: "no-store" });
      if (res.status === 404) {
        throw new Error("not found");
      }
      if (!res.ok) {
        lastErr = new Error("status " + res.status);
        await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
        continue;
      }
      return await res.json();
    } catch (err) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
    }
  }
  throw lastErr || new Error("deal fetch failed");
}

async function openModal(id, opts) {
  const fromHistory = opts && opts.fromHistory;
  if (!modal || !modalBody) return;
  modal.hidden = false;
  document.body.classList.add("modal-open");
  modalBody.innerHTML = "<p class='muted'>불러오는 중…</p>";
  if (!fromHistory && location.pathname !== "/deal/" + id) {
    window.history.pushState({ dealModal: Number(id) }, "", "/deal/" + id);
    modalPushed = true;
  }
  modalOpenId = Number(id);
  let deal;
  try {
    deal = await fetchDealDetail(id);
  } catch (err) {
    console.error(err);
    modalBody.innerHTML = "<p>상세를 불러오지 못했습니다.</p>";
    return;
  }
  if (modalOpenId !== Number(id)) return;
  const posts = deal.posts || [];
  const priceHistory = deal.history || [];
  const similar = deal.similar || [];
  const sampleCount = Number(deal.sample_count) || 0;
  const hasBaseline = sampleCount >= 3 && deal.baseline_price;
  const postHtml = posts.length
    ? posts
        .map(
          (p) =>
            `<li><a href="${esc(p.url)}" target="_blank" rel="noopener">[${esc(p.source)}] ${esc(p.title)}</a>` +
            `<div class="muted" style="margin-top:3px;font-size:var(--text-label)">${kst(p.posted_at || p.collected_at)} · 추천 ${p.votes || 0} · 조회 ${p.views || 0}</div></li>`
        )
        .join("")
    : "<li class='muted'>원문 없음</li>";
  const sourceBits = sourceTokens(deal.sources)
    .map((key) => {
      const label = sourceLabels[key] || key;
      return `<span class="deal-tag deal-tag-source" data-source="${esc(key)}"><span class="deal-tag-ico">${esc(label.slice(0, 1))}</span>${esc(label)}</span>`;
    })
    .join("");
  const thumb = `<div class="modal-thumb-wrap">${
    deal.thumbnail_url
      ? `<img class="modal-thumb" src="${esc(deal.thumbnail_url)}" alt="" referrerpolicy="no-referrer">`
      : ""
  }</div>`;
  const buyLabel = deal.seller
    ? `${esc(deal.seller)}에서 ${won(deal.price)} 구매`
    : `${won(deal.price)} 구매하기`;
  const starred = isBookmarked(id);
  const starBtn =
    `<button type="button" class="dd-cta-star bookmark-btn${starred ? " on" : ""}" data-deal-id="${id}" aria-label="북마크" title="북마크">${starred ? "★" : "☆"}</button>`;
  const ctaHtml =
    (isPostUrl(deal.mall_url)
      ? `<a class="btn dd-cta-buy" href="${esc(deal.mall_url)}" target="_blank" rel="noopener">${buyLabel}</a>`
      : "") +
    (isPostUrl(deal.deal_url)
      ? `<a class="btn-secondary dd-cta-source" href="${esc(deal.deal_url)}" target="_blank" rel="noopener">원문</a>`
      : "") +
    starBtn;
  const similarHtml = similar.length
    ? `<h2 class="dd-section">비슷한 핫딜</h2><ul class="dd-similar">${similar
        .map((s) => `<li><a href="/deal/${s.id}" data-deal-id="${s.id}">${esc(s.product_name)}${s.price ? " · " + won(s.price) : ""}</a></li>`)
        .join("")}</ul>`
    : "";
  const chartIsDemo = priceHistory.length < 2;
  const chartPoints = chartIsDemo
    ? (window.demoPricePoints
        ? window.demoPricePoints(deal.price, deal.baseline_price)
        : [])
    : priceHistory;
  const showChart = chartPoints.length >= 2;
  const cheaper =
    hasBaseline && deal.price && Number(deal.baseline_price) > Number(deal.price);
  const saveAmt = cheaper ? Number(deal.baseline_price) - Number(deal.price) : 0;
  const isLowest =
    hasBaseline && deal.min_price && deal.price && Number(deal.price) <= Number(deal.min_price);
  const checkSvg =
    `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 8.5l3 3 7-7"></path></svg>`;
  const verdictHtml = cheaper
    ? `<p class="dd-verdict">${checkSvg}` +
      `<strong>${isLowest ? "90일 최저가" : "평소보다 저렴"}</strong>` +
      `<span class="status-sep">·</span>` +
      `평소가(중앙값) ${won(deal.baseline_price)}보다 ${Number(saveAmt).toLocaleString("ko-KR")}원 저렴` +
      `</p>`
    : "";
  const chartSub = chartIsDemo
    ? `예시 데이터 · 실제 이력이 쌓이면 교체됩니다`
    : `딜 게시 가격 · 표본 ${priceHistory.length}건`;
  const chartHtml = showChart
    ? `<div class="dd-chart${chartIsDemo ? " is-demo" : ""}" id="dd-chart-root">` +
      `<div class="dd-chart-head">` +
      `<div><span class="dd-chart-title">가격 흐름${chartIsDemo ? ' <span class="dd-demo-badge">예시</span>' : ""}</span>` +
      `<span class="dd-chart-sub">${chartSub}</span></div>` +
      `<div class="seg-group dd-chart-range" role="tablist" aria-label="기간">` +
      `<button type="button" class="seg-chip" data-range="30" role="tab" aria-selected="false">30일</button>` +
      `<button type="button" class="seg-chip on" data-range="90" role="tab" aria-selected="true">90일</button>` +
      `<button type="button" class="seg-chip" data-range="all" role="tab" aria-selected="false">전체</button>` +
      `</div></div>` +
      `<div class="dd-chart-box"><canvas id="modal-chart"></canvas></div>` +
      `<div class="dd-chart-legend">` +
      `<span><span class="dd-legend-line"></span>딜 가격</span>` +
      (hasBaseline || chartIsDemo ? `<span><span class="dd-legend-dash"></span>평소가 중앙값</span>` : "") +
      `<span><span class="dd-legend-dot"></span>현재 딜</span>` +
      `</div></div>`
    : `<div class="dd-empty">같은 상품의 딜 가격 이력이 아직 부족해 가격 흐름을 그릴 수 없습니다.</div>`;
  const baselineRows = hasBaseline
    ? `${specRow("중앙값", won(deal.baseline_price))}${specRow("최저가", won(deal.min_price))}${specRow("표본", esc(sampleCount) + "건")}`
    : (sampleCount ? specRow("표본", esc(sampleCount) + "건") : "");
  modalBody.innerHTML = `
    <div class="dd-hero">
      ${thumb}
      <div class="dd-hero-body">
        <p class="dd-meta">
          ${sourceBits}
          ${deal.category ? `<span class="dd-meta-cat">${esc(deal.category)}</span>` : ""}
          <time>${esc(relativeTime(deal.last_seen_at))}</time>
          ${deal.status === "expired" ? `<span class="deal-soldout">품절</span>` : ""}
        </p>
        <h1 id="modal-title">${esc(deal.product_name)}</h1>
        <p class="modal-price">${priceHtml(deal.price)}${detailOffHtml(deal)}${strikeHtml(deal, hasBaseline, cheaper)}</p>
        ${verdictHtml}
      </div>
    </div>
    ${chartHtml}
    <h2 class="dd-section">쇼핑몰 시세 <span class="dd-section-sub">커뮤니티 기준</span></h2>
    <div class="dd-market">
      <p class="muted" id="market-status" style="font-size:var(--text-body-sm)">시세를 불러오는 중…</p>
      <div id="market-bars" class="mkt" hidden></div>
      <ul class="dd-market-list" id="market-list" hidden></ul>
      <p class="mkt-note" id="market-note" hidden></p>
    </div>
    <h2 class="dd-section">상품 정보</h2>
    <div class="dd-spec">
      ${specRow("쇼핑몰", esc(deal.seller || ""))}
      ${specRow("가격", won(deal.price))}
      ${deal.shipping_fee != null ? specRow("배송비", won(deal.shipping_fee)) : ""}
      ${deal.unit_price ? specRow("단가", won(deal.unit_price)) : ""}
      ${baselineRows}
      ${specRow("카테고리", esc(deal.category || ""))}
      ${deal.first_seen_at ? specRow("최초 확인", esc(kst(deal.first_seen_at))) : ""}
    </div>
    <h2 class="dd-section">원문 ${posts.length ? `<span class="dd-section-sub">${posts.length}건</span>` : ""}</h2>
    <ul class="dd-posts">${postHtml}</ul>
    <div class="dd-tags">
      ${deal.seller ? `<span class="dd-tag">#${esc(deal.seller)}</span>` : ""}
      ${deal.category ? `<span class="dd-tag">#${esc(deal.category)}</span>` : ""}
    </div>
    ${similarHtml}
    <p class="dd-share">
      <button type="button" class="btn-secondary btn-sm" data-copy-link>링크 복사</button>
      <button type="button" class="btn-secondary btn-sm" data-share-link>공유</button>
    </p>
  `;
  modalBody.querySelector("[data-copy-link]")?.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(location.href); } catch (e) {}
  });
  modalBody.querySelector("[data-share-link]")?.addEventListener("click", async () => {
    if (navigator.share) {
      try { await navigator.share({ title: deal.product_name, url: location.href }); } catch (e) {}
    } else {
      try { await navigator.clipboard.writeText(location.href); } catch (e) {}
    }
  });
  if (showChart) {
    const root = document.getElementById("dd-chart-root");
    const baseline =
      hasBaseline ? deal.baseline_price
        : chartIsDemo && deal.price ? Math.round(Number(deal.price) * 1.25)
        : null;
    if (window.bindPriceChartRange) {
      chart = window.bindPriceChartRange(root, "modal-chart", chartPoints, baseline, 90);
    } else if (window.renderPriceChart) {
      chart = window.renderPriceChart("modal-chart", chartPoints, baseline);
    }
  }
  if (modalCta) {
    modalCta.innerHTML = ctaHtml;
    modalCta.hidden = !ctaHtml;
    paintBookmarkButtons();
  }
  loadMarketCompare(id);
  if (window.DealChat) window.DealChat.open(id);
  if (window.DealChatPin) window.DealChatPin.bind();
  if (!isPostUrl(deal.mall_url)) {
    pollModalMall(id, deal);
  }
}

async function pollModalMall(id, deal) {
  const buyLabelBase = deal && deal.seller
    ? `${esc(deal.seller)}에서 ${won(deal.price)} 구매`
    : `${won(deal && deal.price)} 구매하기`;
  for (let i = 0; i < 6; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    if (modalOpenId !== Number(id)) return;
    try {
      const res = await fetch("/api/deals/" + id);
      if (!res.ok) continue;
      const fresh = await res.json();
      if (!isPostUrl(fresh.mall_url)) continue;
      patchRowMall(fresh);
      if (!modalCta || modalCta.querySelector(".dd-cta-buy")) return;
      const label = fresh.seller
        ? `${esc(fresh.seller)}에서 ${won(fresh.price)} 구매`
        : buyLabelBase;
      const a = document.createElement("a");
      a.className = "btn dd-cta-buy";
      a.href = fresh.mall_url;
      a.target = "_blank";
      a.rel = "noopener";
      a.innerHTML = label;
      modalCta.prepend(a);
      modalCta.hidden = false;
      return;
    } catch (err) {}
  }
}

function renderMarketBars(items) {
  const host = document.getElementById("market-bars");
  if (!host) return;
  const prices = items.map((x) => Number(x.price) || 0).filter(Boolean);
  const max = prices.length ? Math.max.apply(null, prices) : 1;
  host.innerHTML = items
    .map((item) => {
      const price = Number(item.price) || 0;
      const w = Math.max(8, Math.round((price / max) * 100));
      const priceInner = item.url
        ? `<a href="${esc(item.url)}" target="_blank" rel="noopener">${won(price)}</a>`
        : won(price);
      return (
        `<div class="mkt-row${item.is_deal ? " is-deal" : ""}">` +
        `<span class="mkt-mall">${esc(item.mall || "")}</span>` +
        `<span class="mkt-track"><span class="mkt-bar" style="width:${w}%"></span></span>` +
        `<span class="mkt-price">${priceInner}</span></div>`
      );
    })
    .join("");
  host.hidden = !items.length;
}

window.loadMarketCompare = loadMarketCompare;
async function loadMarketCompare(dealId) {
  if (marketLoadedFor === Number(dealId)) return;
  const status = document.getElementById("market-status");
  const note = document.getElementById("market-note");
  const bars = document.getElementById("market-bars");
  if (status) status.textContent = "시세를 불러오는 중…";
  if (bars) {
    bars.innerHTML = "";
    bars.hidden = true;
  }
  try {
    const res = await fetch("/api/deals/" + dealId + "/market");
    const data = await res.json();
    marketLoadedFor = Number(dealId);
    const items = data.items || [];
    if (!items.length) {
      if (status) status.textContent = data.note || "비교할 가격 이력이 아직 없습니다.";
      return;
    }
    if (status) status.textContent = "커뮤니티 딜 가격 · 판매처별 최저";
    renderMarketBars(items);
    if (note) {
      note.textContent = data.note || "";
      note.hidden = !data.note;
    }
  } catch (err) {
    console.error(err);
    if (status) status.textContent = "시세를 불러오지 못했습니다.";
  }
}

window.addEventListener("popstate", (e) => {
  const id = e.state && e.state.dealModal;
  if (id) openModal(id, { fromHistory: true });
  else if (modalOpenId) closeModal({ fromPop: true });
});

document.addEventListener("click", (e) => {
  const mark = e.target.closest(".bookmark-btn");
  if (mark) {
    e.preventDefault();
    e.stopPropagation();
    toggleBookmark(mark.dataset.dealId);
    return;
  }
  if (e.target.closest("[data-close]")) {
    closeModal();
    return;
  }
  const detail = e.target.closest(".detail-btn");
  if (detail) {
    e.preventDefault();
    openModal(detail.dataset.dealId);
    return;
  }
  const row = e.target.closest("a.deal-row-main[data-deal-id], .dd-similar a[data-deal-id]");
  if (row) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openModal(row.dataset.dealId);
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && modal && !modal.hidden) closeModal();
});
