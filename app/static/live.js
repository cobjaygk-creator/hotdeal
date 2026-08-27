const config = JSON.parse(document.getElementById("live-config").textContent);
const bodyEl = document.getElementById("deal-body");
const ticker = document.getElementById("ticker");
const statusEl = document.getElementById("live-status");
const dot = document.getElementById("live-dot");
const seen = new Set(
  [...bodyEl.querySelectorAll("tr[data-id]")].map((row) => row.dataset.id)
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
  }).format(d).replace("T", " ");
}

function won(n) {
  return n == null ? "-" : Number(n).toLocaleString("ko-KR") + "원";
}

function pct(rate) {
  return rate == null ? "-" : (-rate * 100).toFixed(1) + "%";
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

function renderRow(deal) {
  const tr = document.createElement("tr");
  tr.dataset.id = String(deal.id);
  tr.className = isHot(deal) ? "fresh hot-fresh" : "fresh";
  const down = deal.discount_rate != null && deal.discount_rate >= 0.15 ? " down" : "";
  tr.innerHTML =
    `<td class="num col-price"></td>` +
    `<td class="col-name"><a class="deal-link" href="/deal/${deal.id}"></a></td>` +
    `<td class="col-seller"></td>` +
    `<td class="num col-base"></td>` +
    `<td class="num col-drop${down}"></td>` +
    `<td class="col-grade"></td>` +
    `<td class="muted col-src"></td>`;
  const cells = tr.children;
  cells[0].textContent = won(deal.price);
  cells[1].querySelector("a").textContent = deal.product_name || "(제목 없음)";
  cells[2].textContent = deal.seller || "-";
  cells[3].textContent = won(deal.baseline_price);
  cells[4].textContent = pct(deal.discount_rate);
  cells[5].textContent = deal.grade || "-";
  cells[6].textContent = deal.sources || "-";
  return tr;
}

function pushTicker(deal) {
  const item = document.createElement("span");
  item.className = "ticker-item";
  const flag = isHot(deal) ? " " + (deal.grade || "") : "";
  item.textContent = `${won(deal.price)} ${deal.product_name || ""}${flag}`;
  ticker.prepend(item);
  while (ticker.children.length > 8) ticker.removeChild(ticker.lastChild);
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
  while (bodyEl.querySelectorAll("tr[data-id]").length > 200) {
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
  es.onopen = () => setLive(true, "실시간 수신 중 · 뽐뿌 1분");
  es.onmessage = (ev) => {
    if (!ev.data) return;
    const data = JSON.parse(ev.data);
    applyStats(data.stats);
    const n = data.new_posts || 0;
    if (n) {
      setLive(true, `신규 ${n}건 반영`);
    } else if (data.stats && data.stats.last_collect_at) {
      setLive(true, "실시간 수신 중 · " + kst(data.stats.last_collect_at));
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
    btn.textContent = "지금 전체 수집";
  }
});

connect();

const modal = document.getElementById("deal-modal");
const modalBody = document.getElementById("modal-body");
let chart;

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

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
  modalBody.innerHTML = `
    <h1 id="modal-title">${esc(deal.product_name)}</h1>
    <p class="muted">${esc(deal.seller || "판매처 미상")} · ${esc(deal.grade)} · ${esc(deal.status)}</p>
    <section class="stats">
      <div class="stat"><div class="label">현재 가격</div><div class="value">${won(deal.price)}</div></div>
      <div class="stat"><div class="label">90일 중앙값</div><div class="value">${won(deal.baseline_price)}</div></div>
      <div class="stat"><div class="label">90일 최저가</div><div class="value">${won(deal.min_price)}</div></div>
      <div class="stat"><div class="label">하락률</div><div class="value">${pct(deal.discount_rate)}</div></div>
    </section>
    <p class="modal-meta">단위가격: ${deal.unit_price != null ? esc(deal.unit_price) : "-"}
     · 표본 ${deal.sample_count || 0}건
     · 최종 수집 ${kst(deal.last_seen_at)}</p>
    ${deal.deal_url ? `<p><a href="${esc(deal.deal_url)}" target="_blank" rel="noopener">대표 게시글 열기</a></p>` : ""}
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
        datasets: [{
          label: "딜 게시 가격",
          data: history.map((h) => h.price),
          showLine: true,
          pointRadius: 4,
          borderWidth: 2,
        }],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { ticks: { callback: (v) => Number(v).toLocaleString("ko-KR") + "원" } } },
      },
    });
  }
}

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-close]")) {
    closeModal();
    return;
  }
  const link = e.target.closest("a.deal-link");
  if (!link) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  const id = link.getAttribute("href").split("/").pop();
  openModal(id);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modal.hidden) closeModal();
});

