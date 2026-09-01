const config = JSON.parse(document.getElementById("live-config").textContent);
const bodyEl = document.getElementById("deal-body");
const ticker = document.getElementById("ticker");
const statusEl = document.getElementById("live-status");
const dot = document.getElementById("live-dot");
const seen = new Set(
  [...bodyEl.querySelectorAll("[data-id]")].map((row) => row.dataset.id)
);

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

function matchesFilter(deal) {
  if (config.grade && !(deal.grade || "").includes(config.grade)) return false;
  if (config.seller && deal.seller !== config.seller) return false;
  if (config.source && !(deal.sources || "").includes(config.source)) return false;
  return true;
}

function isHot(deal) {
  const g = deal.grade || "";
  return g.includes("핫딜") || g.includes("특가");
}

function gradeHtml(grade) {
  const g = grade || "-";
  if (g.includes("핫딜") || g.includes("특가")) {
    return `<span class="grade-chip">${esc(g)}</span>`;
  }
  return `<span class="muted">${esc(g)}</span>`;
}

function renderRow(deal) {
  const li = document.createElement("li");
  li.className = "deal-card" + (isHot(deal) ? " fresh hot-fresh" : " fresh");
  li.dataset.id = String(deal.id);
  li.dataset.mallUrl = deal.mall_url || "";
  const mall = deal.mall_url;
  const title = deal.product_name || "(제목 없음)";
  const titleHtml = mall
    ? `<a class="deal-title" href="${esc(mall)}" target="_blank" rel="noopener">${esc(title)}</a>`
    : `<a class="deal-title deal-title-fallback" href="/deal/${deal.id}" data-deal-id="${deal.id}">${esc(title)}</a>`;
  let drop = "";
  if (deal.discount_rate != null) {
    const cls = deal.discount_rate >= 0.15 ? "down" : "";
    drop = `<span class="${cls}">${pct(deal.discount_rate)}</span>`;
  }
  const base =
    deal.baseline_price != null
      ? `<span class="muted">중앙 ${won(deal.baseline_price)}</span>`
      : "";
  li.innerHTML =
    `<div class="deal-price">${won(deal.price)}</div>` +
    `<div class="deal-main">${titleHtml}` +
    `<div class="deal-meta">` +
    `<span>${esc(deal.seller || "-")}</span>` +
    `<span>${esc(deal.sources || "-")}</span>` +
    drop +
    gradeHtml(deal.grade) +
    base +
    `</div></div>` +
    `<button type="button" class="detail-btn" data-deal-id="${deal.id}">상세</button>`;
  return li;
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
    if (!matchesFilter(deal)) continue;
    seen.add(id);
    bodyEl.prepend(renderRow(deal));
    pushTicker(deal);
  }
  while (bodyEl.querySelectorAll("[data-id]").length > 200) {
    bodyEl.removeChild(bodyEl.lastElementChild);
  }
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
  const mallBtn = deal.mall_url
    ? `<p><a class="btn" href="${esc(deal.mall_url)}" target="_blank" rel="noopener">쇼핑몰 열기</a></p>`
    : "";
  modalBody.innerHTML = `
    <p class="modal-price">${won(deal.price)} <span class="muted">${pct(deal.discount_rate)} · ${esc(deal.grade || "-")}</span></p>
    <h1 id="modal-title">${esc(deal.product_name)}</h1>
    <p class="muted">${esc(deal.seller || "판매처 미상")} · 표본 ${deal.sample_count || 0}건 · ${kst(deal.last_seen_at)}</p>
    <p class="modal-meta">중앙값 ${won(deal.baseline_price)} · 최저 ${won(deal.min_price)}</p>
    ${mallBtn}
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
  const fallback = e.target.closest("a.deal-title-fallback");
  if (fallback) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openModal(fallback.dataset.dealId);
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modal.hidden) closeModal();
});
