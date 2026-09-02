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
      ? `<span class="deal-comments" aria-label="댓글 ${Number(deal.comments)}">💬 ${Number(deal.comments)}</span>`
      : "";
  li.innerHTML =
    `<a class="deal-row-main" href="/deal/${deal.id}" data-deal-id="${deal.id}">` +
    `<div class="deal-thumb-wrap">${thumb}</div>` +
    `<div class="deal-body">` +
    tagsHtml(deal) +
    `<span class="deal-title">${esc(title)}</span>` +
    `<div class="deal-price-row"><div class="deal-price">${won(deal.price)}</div>` +
    `<time class="time-rel" datetime="${esc(ts)}" data-ts="${esc(ts)}">${esc(relativeTime(ts))}</time>${comments}</div>` +
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
        el.style.transition = "transform 0.4s cubic-bezier(0.22, 1, 0.36, 1)";
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

function closeModal() {
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
  if (chart) {
    chart.destroy();
    chart = null;
  }
}

async function openModal(id) {
  if (!modal || !modalBody) return;
  modal.hidden = false;
  document.body.classList.add("modal-open");
  modalBody.innerHTML = "<p class='muted'>불러오는 중…</p>";
  const res = await fetch("/api/deals/" + id);
  if (!res.ok) {
    modalBody.innerHTML = "<p>상세를 불러오지 못했습니다.</p>";
    return;
  }
  const deal = await res.json();
  const posts = deal.posts || [];
  const history = deal.history || [];
  const postHtml = posts.length
    ? posts
        .map(
          (p) =>
            `<li><a href="${esc(p.url)}" target="_blank" rel="noopener">[${esc(p.source)}] ${esc(p.title)}</a> ` +
            `<span class="muted">${kst(p.posted_at || p.collected_at)} · 추천 ${p.votes || 0} · 조회 ${p.views || 0}</span></li>`
        )
        .join("")
    : "<li class='muted'>원문 없음</li>";
  const linkBtns = [
    deal.mall_url
      ? `<a class="btn" href="${esc(deal.mall_url)}" target="_blank" rel="noopener">구매하기</a>`
      : "",
    isPostUrl(deal.deal_url)
      ? `<a class="btn ghost" href="${esc(deal.deal_url)}" target="_blank" rel="noopener">원문 보기</a>`
      : "",
  ]
    .filter(Boolean)
    .join(" ");
  const thumb = deal.thumbnail_url
    ? `<div class="modal-thumb-wrap"><img class="modal-thumb" src="${esc(deal.thumbnail_url)}" alt="" referrerpolicy="no-referrer"></div>`
    : "";
  modalBody.innerHTML = `
    ${thumb}
    <p class="modal-price">${won(deal.price)} <span class="muted">${pct(deal.discount_rate)} · ${gradeHtml(deal.grade)}</span></p>
    <h1 id="modal-title">${esc(deal.product_name)}</h1>
    <p class="muted">${esc(deal.seller || "판매처 미상")} · 표본 ${deal.sample_count || 0}건 · ${kst(deal.last_seen_at)}</p>
    <p class="modal-meta">중앙값 ${won(deal.baseline_price)} · 최저 ${won(deal.min_price)}</p>
    ${linkBtns ? `<p class="modal-actions">${linkBtns}</p>` : ""}
    <h2>가격 이력</h2>
    <canvas id="modal-chart" height="120"></canvas>
    <h2>원문</h2>
    <ul class="modal-posts">${postHtml}</ul>
  `;
  const canvas = document.getElementById("modal-chart");
  if (canvas && history.length && window.Chart) {
    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: history.map((h) => h.observed_at),
        datasets: [
          {
            label: "딜 게시 가격",
            data: history.map((h) => h.price),
            showLine: true,
            pointRadius: 4,
            borderWidth: 2,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          y: { ticks: { callback: (v) => Number(v).toLocaleString("ko-KR") + "원" } },
        },
      },
    });
  }
}

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
  const row = e.target.closest("a.deal-row-main[data-deal-id]");
  if (row) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openModal(row.dataset.dealId);
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && modal && !modal.hidden) closeModal();
});
