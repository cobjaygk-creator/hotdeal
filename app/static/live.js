const config = JSON.parse(document.getElementById("live-config").textContent);
const bodyEl = document.getElementById("deal-body");
const ticker = document.getElementById("ticker");
const statusEl = document.getElementById("live-status");
const dot = document.getElementById("live-dot");
const chipRow = document.getElementById("source-chips");
const moreBtn = document.getElementById("more-btn");
const filterEmpty = document.getElementById("filter-empty");
const STORAGE_KEY = "hotdeal.sourceChips";
const sourceLabels = config.sourceLabels || {};
const seen = new Set(
  [...bodyEl.querySelectorAll("[data-id]")].map((row) => row.dataset.id)
);

let selectedSources = null;
let hasMore = !!config.hasMore;
let loadingMore = false;

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
  if (secs < 3600) return Math.max(1, Math.floor(secs / 60)) + "분 전";
  if (secs < 86400) return Math.floor(secs / 3600) + "시간 전";
  if (secs < 86400 * 7) return Math.floor(secs / 86400) + "일 전";
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

function refreshTimes() {
  bodyEl.querySelectorAll(".time-rel[data-ts]").forEach((el) => {
    el.textContent = relativeTime(el.dataset.ts);
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
  const title = deal.product_name || "(제목 없음)";
  const titleHtml = `<a class="deal-title" href="/deal/${deal.id}" data-deal-id="${deal.id}">${esc(title)}</a>`;
  let drop = "";
  if (deal.discount_rate != null) {
    const cls = deal.discount_rate >= 0.15 ? "down" : "";
    drop = `<span class="${cls}">${pct(deal.discount_rate)}</span>`;
  }
  const base =
    deal.baseline_price != null
      ? `<span class="muted">중앙 ${won(deal.baseline_price)}</span>`
      : "";
  const thumb = deal.thumbnail_url
    ? `<img class="deal-thumb" src="${esc(deal.thumbnail_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="deal-thumb placeholder" aria-hidden="true"></div>`;
  const ts = deal.last_seen_at || "";
  li.innerHTML =
    thumb +
    `<div class="deal-price">${won(deal.price)}</div>` +
    `<div class="deal-main">${titleHtml}` +
    `<div class="deal-meta">` +
    `<time class="time-rel" datetime="${esc(ts)}" data-ts="${esc(ts)}">${esc(relativeTime(ts))}</time>` +
    `<span>${esc(deal.seller || "-")}</span>` +
    `<span>${esc(labelSources(deal.sources))}</span>` +
    drop +
    gradeHtml(deal.grade) +
    base +
    `</div></div>` +
    `<button type="button" class="detail-btn" data-deal-id="${deal.id}">상세</button>`;
  applyChipClass(li);
  return li;
}

function applyChipClass(el) {
  el.classList.toggle("is-filtered-out", !matchesSources(el.dataset.sources));
}

function visibleCount() {
  return [...bodyEl.querySelectorAll("[data-id]")].filter(
    (el) => !el.classList.contains("is-filtered-out")
  ).length;
}

function applySourceFilter() {
  bodyEl.querySelectorAll("[data-id]").forEach(applyChipClass);
  const cards = bodyEl.querySelectorAll("[data-id]").length;
  if (filterEmpty) {
    filterEmpty.hidden = !(cards && visibleCount() === 0);
  }
  paintChips();
}

function paintChips() {
  if (!chipRow) return;
  const all = !selectedSources || !selectedSources.length;
  chipRow.querySelectorAll("[data-source]").forEach((btn) => {
    const src = btn.dataset.source;
    const on = src === "*" ? all : all || selectedSources.includes(src);
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
  if (moreBtn) moreBtn.hidden = !hasMore;
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

function pushTicker(deal) {
  if (!ticker) return;
  const item = document.createElement("span");
  item.className = "ticker-item";
  const flag = isHot(deal) ? " " + (deal.grade || "") : "";
  item.textContent = `${won(deal.price)} ${deal.product_name || ""}${flag}`;
  ticker.prepend(item);
  while (ticker.children.length > 6) ticker.removeChild(ticker.lastChild);
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

function ingest(items) {
  if (!items || !items.length) return;
  const empty = bodyEl.querySelector(".empty-row");
  if (empty) empty.remove();
  for (const deal of items) {
    const id = String(deal.id);
    if (seen.has(id)) continue;
    if (config.grade && !(deal.grade || "").includes(config.grade)) continue;
    if (config.seller && deal.seller !== config.seller) continue;
    seen.add(id);
    bodyEl.prepend(renderRow(deal));
    if (matchesSources(deal.sources)) pushTicker(deal);
  }
  applySourceFilter();
}

function setLive(ok, text) {
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

document.getElementById("collect-btn").addEventListener("click", async (e) => {
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

if (moreBtn) {
  moreBtn.addEventListener("click", () => loadMore());
}

loadSavedSources();
applySourceFilter();
setMoreVisible();
if (selectedSources && selectedSources.length) ensureVisible(12);
refreshTimes();
setInterval(refreshTimes, 30000);
connect();

const modal = document.getElementById("deal-modal");
const modalBody = document.getElementById("modal-body");
let chart;

function closeModal() {
  modal.hidden = true;
  document.body.classList.remove("modal-open");
  if (chart) {
    chart.destroy();
    chart = null;
  }
}

async function openModal(id) {
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
  const title = e.target.closest("a.deal-title[data-deal-id]");
  if (title) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openModal(title.dataset.dealId);
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modal.hidden) closeModal();
});
