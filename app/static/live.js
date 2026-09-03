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

function renderRow(deal) {
  const li = document.createElement("li");
  li.className = "deal-card" + (isHot(deal) ? " fresh hot-fresh" : " fresh");
  li.dataset.id = String(deal.id);
  li.dataset.sources = deal.sources || "";
  li.dataset.ts = deal.last_seen_at || "";
  li.dataset.category = deal.category || "";
  const starred = isBookmarked(deal.id);
  const title = deal.product_name || "(제목 없음)";
  const thumb = deal.thumbnail_url
    ? `<img class="deal-thumb" src="${esc(deal.thumbnail_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="deal-thumb placeholder" aria-hidden="true"></div>`;
  const ts = deal.last_seen_at || "";
  const comments =
    deal.comments && Number(deal.comments) > 0
      ? `<span class="deal-comments" aria-label="원문 댓글 ${Number(deal.comments)}">💬 ${Number(deal.comments)}</span>`
      : "";
  const userComments =
    deal.user_comments && Number(deal.user_comments) > 0
      ? `<span class="deal-user-comments" aria-label="댓글 ${Number(deal.user_comments)}">💬 ${Number(deal.user_comments)}</span>`
      : "";
  const soldout = deal.status === "expired" ? `<span class="deal-soldout">품절</span>` : "";
  if (deal.status === "expired") li.classList.add("is-expired");
  li.innerHTML =
    `<a class="deal-row-main" href="/deal/${deal.id}" data-deal-id="${deal.id}">` +
    `<div class="deal-thumb-wrap">${thumb}</div>` +
    `<div class="deal-body">` +
    tagsHtml(deal) +
    `<span class="deal-title">${esc(title)}</span>` +
    `<div class="deal-price-row"><div class="deal-price">${won(deal.price)}</div>` +
    `<time class="time-rel" datetime="${esc(ts)}" data-ts="${esc(ts)}">${esc(relativeTime(ts))}</time>${comments}${userComments}${soldout}</div>` +
    `</div></a>` +
    `<div class="deal-row-side">` +
    `<time class="time-abs" datetime="${esc(ts)}" data-ts="${esc(ts)}">${esc(clockTime(ts))}</time>` +
    `<button type="button" class="bookmark-btn${starred ? " on" : ""}" data-deal-id="${deal.id}" aria-label="북마크">${starred ? "★" : "☆"}</button>` +
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

function flipPrepend(rows) {
  if (!bodyEl || !rows.length) return;
  if (prefersReducedMotion()) {
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

function ingest(items) {
  if (!bodyEl || !items || !items.length) return;
  const empty = bodyEl.querySelector(".empty-row");
  if (empty) empty.remove();
  const rows = [];
  for (const deal of items) {
    const id = String(deal.id);
    if (seen.has(id)) continue;
    if (config.grade && !(deal.grade || "").includes(config.grade)) continue;
    if (config.seller && deal.seller !== config.seller) continue;
    if (config.category && deal.category !== config.category) continue;
    seen.add(id);
    rows.push(renderRow(deal));
  }
  if (rows.length) flipPrepend(rows);
  applySourceFilter();
}

function setLive(ok, text) {
  if (!statusEl || !dot) return;
  statusEl.textContent = text;
  dot.classList.toggle("on", ok);
  dot.classList.toggle("off", !ok);
}

function connect() {
  const es = new EventSource("/api/stream");
  es.onopen = () => setLive(true, "실시간 수신 중");
  es.onmessage = (ev) => {
    if (!ev.data) return;
    const data = JSON.parse(ev.data);
    applyStats(data.stats);
    const n = data.new_posts || 0;
    if (n) {
      setLive(true, `신규 ${n}건 반영`);
    } else if (data.stats && data.stats.last_collect_at) {
      setLive(true, "실시간 · " + kst(data.stats.last_collect_at));
    }
    ingest(data.items || []);
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
    ingest(data.new_deals || []);
    setLive(true, `수동 수집 완료 · 신규 ${data.new_posts || 0}건`);
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
  marketLoadedFor = null;
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
    const res = await fetch("/api/deals/" + id);
    if (!res.ok) {
      modalBody.innerHTML = "<p>상세를 불러오지 못했습니다.</p>";
      return;
    }
    deal = await res.json();
  } catch (err) {
    console.error(err);
    modalBody.innerHTML = "<p>상세를 불러오지 못했습니다.</p>";
    return;
  }
  const posts = deal.posts || [];
  const priceHistory = deal.history || [];
  const similar = deal.similar || [];
  const postHtml = posts.length
    ? posts
        .map(
          (p) =>
            `<li><a href="${esc(p.url)}" target="_blank" rel="noopener">[${esc(p.source)}] ${esc(p.title)}</a> ` +
            `<span class="muted">${kst(p.posted_at || p.collected_at)} · 추천 ${p.votes || 0} · 조회 ${p.views || 0}</span></li>`
        )
        .join("")
    : "<li class='muted'>원문 없음</li>";
  const sourceBits = sourceTokens(deal.sources)
    .map((key) => {
      const label = sourceLabels[key] || key;
      return `<span class="deal-tag deal-tag-source" data-source="${esc(key)}"><span class="deal-tag-ico">${esc(label.slice(0, 1))}</span>${esc(label)}</span>`;
    })
    .join("");
  const thumb = deal.thumbnail_url
    ? `<div class="modal-thumb-wrap"><img class="modal-thumb" src="${esc(deal.thumbnail_url)}" alt="" referrerpolicy="no-referrer"></div>`
    : "";
  const cta = deal.mall_url
    ? `<a class="btn" href="${esc(deal.mall_url)}" target="_blank" rel="noopener">${esc(deal.seller || "")} ${won(deal.price)} 구매하기</a>`
    : isPostUrl(deal.deal_url)
      ? `<a class="btn ghost" href="${esc(deal.deal_url)}" target="_blank" rel="noopener">원문에서 확인</a>`
      : "";
  const similarHtml = similar.length
    ? `<h2 class="dd-section">비슷한 핫딜</h2><ul class="dd-similar">${similar
        .map((s) => `<li><a href="/deal/${s.id}" data-deal-id="${s.id}">${esc(s.product_name)}${s.price ? " · " + won(s.price) : ""}</a></li>`)
        .join("")}</ul>`
    : "";
  const showChart = priceHistory.length >= 2;
  modalBody.innerHTML = `
    <p class="dd-meta">
      ${deal.category ? `<span>${esc(deal.category)}</span>` : ""}
      <time>${esc(relativeTime(deal.last_seen_at))}</time>
      ${sourceBits}
      ${isPostUrl(deal.deal_url) ? `<a href="${esc(deal.deal_url)}" target="_blank" rel="noopener">원본글</a>` : ""}
      <button type="button" class="dd-report-btn" data-open-report>🚨 신고</button>
      ${deal.status === "expired" ? `<span class="deal-soldout">품절</span>` : ""}
    </p>
    <div class="dd-hero">
      ${thumb}
      <div>
        <h1 id="modal-title">${esc(deal.product_name)}</h1>
        <p class="modal-price">${won(deal.price)} <span class="muted">${pct(deal.discount_rate)} · ${gradeHtml(deal.grade)}</span></p>
      </div>
    </div>
    <div class="seg-group dd-inner-tabs" role="tablist">
      <button type="button" class="seg-chip on" data-inner-tab="spec">상품 정보</button>
      <button type="button" class="seg-chip" data-inner-tab="market">가격 비교</button>
      ${showChart ? `<button type="button" class="seg-chip" data-inner-tab="chart">가격 흐름</button>` : ""}
      <button type="button" class="seg-chip" data-inner-tab="posts">원문</button>
    </div>
    <div class="dd-spec" data-inner-pane="spec">
      ${specRow("쇼핑몰", esc(deal.seller || ""))}
      ${specRow("가격", won(deal.price))}
      ${deal.shipping_fee != null ? specRow("배송비", won(deal.shipping_fee)) : ""}
      ${deal.unit_price ? specRow("단가", won(deal.unit_price)) : ""}
      ${specRow("중앙값", won(deal.baseline_price))}
      ${specRow("최저가", won(deal.min_price))}
      ${deal.sample_count ? specRow("표본", esc(deal.sample_count) + "건") : ""}
      ${specRow("카테고리", esc(deal.category || ""))}
      ${deal.first_seen_at ? specRow("최초 확인", esc(kst(deal.first_seen_at))) : ""}
    </div>
    <div class="dd-market" data-inner-pane="market" hidden>
      <p class="muted" id="market-status">시세를 불러오는 중…</p>
      <div class="dd-market-chart-wrap"><canvas id="market-chart" height="180"></canvas></div>
      <ul class="dd-market-list" id="market-list"></ul>
    </div>
    ${showChart ? `<div class="dd-chart" data-inner-pane="chart" hidden><canvas id="modal-chart" height="120"></canvas></div>` : ""}
    <ul class="dd-posts" data-inner-pane="posts" hidden>${postHtml}</ul>
    <div class="dd-tags">
      ${deal.seller ? `<span class="dd-tag">#${esc(deal.seller)}</span>` : ""}
      ${deal.category ? `<span class="dd-tag">#${esc(deal.category)}</span>` : ""}
    </div>
    ${similarHtml}
    <p class="dd-share">
      <button type="button" class="btn-secondary" data-copy-link>링크 복사</button>
      <button type="button" class="btn-secondary" data-share-link>공유</button>
    </p>
    <div class="dd-cta">${cta}</div>
    <form class="dd-report" id="dd-report" hidden>
      <p>신고하기</p>
      <select name="reason">
        <option value="price">가격 정보가 이상해요</option>
        <option value="link">구매 링크가 이상해요</option>
        <option value="spam">스팸 같아요</option>
        <option value="soldout">품절·종료된 게시물</option>
        <option value="illegal">불법/유해 내용</option>
        <option value="other">기타</option>
      </select>
      <textarea name="detail" maxlength="2000" placeholder="내용 (기타는 필수)"></textarea>
      <div class="dd-report-actions">
        <button type="submit" class="btn">보내기</button>
        <button type="button" class="btn-secondary" data-close-report>닫기</button>
      </div>
    </form>
  `;
  modalBody.querySelectorAll("[data-inner-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.innerTab;
      modalBody.querySelectorAll("[data-inner-tab]").forEach((b) => b.classList.toggle("on", b === btn));
      modalBody.querySelectorAll("[data-inner-pane]").forEach((p) => {
        p.hidden = p.dataset.innerPane !== tab;
      });
      if (tab === "market") loadMarketCompare(id);
    });
  });
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
  modalBody.querySelector("[data-open-report]")?.addEventListener("click", () => {
    const form = document.getElementById("dd-report");
    if (form) form.hidden = !form.hidden;
  });
  modalBody.querySelector("[data-close-report]")?.addEventListener("click", () => {
    const form = document.getElementById("dd-report");
    if (form) form.hidden = true;
  });
  document.getElementById("dd-report")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const res = await fetch("/api/deals/" + id + "/report", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: form.reason.value, detail: form.detail.value }),
    });
    if (res.ok) form.hidden = true;
    else window.alert("신고를 보내지 못했습니다.");
  });
  const canvas = document.getElementById("modal-chart");
  if (canvas && priceHistory.length && window.Chart) {
    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: priceHistory.map((h) => h.observed_at),
        datasets: [{ label: "딜 게시 가격", data: priceHistory.map((h) => h.price), showLine: true, pointRadius: 4, borderWidth: 2 }],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: (v) => Number(v).toLocaleString("ko-KR") + "원" } } },
      },
    });
  }
  if (window.DealChat) window.DealChat.open(id);
}

window.loadMarketCompare = loadMarketCompare;
async function loadMarketCompare(dealId) {
  if (marketLoadedFor === Number(dealId)) return;
  const status = document.getElementById("market-status");
  const list = document.getElementById("market-list");
  const canvas = document.getElementById("market-chart");
  if (status) status.textContent = "시세를 불러오는 중…";
  if (list) list.innerHTML = "";
  try {
    const res = await fetch("/api/deals/" + dealId + "/market");
    const data = await res.json();
    marketLoadedFor = Number(dealId);
    if (!data.enabled) {
      if (status) status.textContent = data.note || "시세 비교를 사용할 수 없습니다.";
      if (canvas) canvas.hidden = true;
      return;
    }
    const items = data.items || [];
    if (!items.length) {
      if (status) status.textContent = data.note || "비슷한 상품 시세를 찾지 못했습니다.";
      if (canvas) canvas.hidden = true;
      return;
    }
    if (status) {
      status.textContent = data.fetched_at
        ? `네이버 쇼핑 시세 · ${kst(data.fetched_at)} 기준`
        : "네이버 쇼핑 시세";
    }
    if (list) {
      list.innerHTML = items
        .map((item) => {
          const label = item.is_deal ? `${esc(item.mall)} · 현재 딜` : esc(item.mall);
          const link = item.url
            ? `<a href="${esc(item.url)}" target="_blank" rel="noopener">${won(item.price)}</a>`
            : won(item.price);
          return `<li class="${item.is_deal ? "is-deal" : ""}"><span class="dd-market-mall">${label}</span><span class="dd-market-price">${link}</span></li>`;
        })
        .join("");
    }
    if (canvas && window.Chart) {
      canvas.hidden = false;
      if (marketChart) {
        marketChart.destroy();
        marketChart = null;
      }
      const labels = items.map((x) => x.mall);
      const prices = items.map((x) => x.price);
      const colors = items.map((x) => (x.is_deal ? "#e11d48" : "#2f80ed"));
      marketChart = new Chart(canvas, {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              label: "가격",
              data: prices,
              backgroundColor: colors,
              borderRadius: 6,
              maxBarThickness: 28,
            },
          ],
        },
        options: {
          indexAxis: "y",
          plugins: { legend: { display: false } },
          scales: {
            x: {
              ticks: { callback: (v) => Number(v).toLocaleString("ko-KR") + "원" },
            },
          },
        },
      });
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
