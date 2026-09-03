/* ============================================================
   market.js v2 — 상세/모달 후처리 (live.js 수정 없이 동작)
   · 렌더 토큰 기반이라 딜을 바꿔도 매번 다시 적용됩니다
   · #modal-body 가 빈 채로 먼저 존재하는 문제 해결 (v1 버그)
   base.html에서 live.js보다 뒤에(defer) 로드하세요.
   ============================================================ */
(function () {
  var MIN_SAMPLE = 3;

  function num(t) {
    var s = String(t == null ? "" : t).replace(/[^0-9]/g, "");
    return s ? Number(s) : null;
  }
  function fmt(n) { return Number(n).toLocaleString("ko-KR") + "원"; }

  function root() {
    return document.querySelector("#modal-body, .dd-page.is-detail .dd-main");
  }

  function heading(r, text) {
    var hs = r.querySelectorAll("h2.dd-section");
    for (var i = 0; i < hs.length; i++) {
      if (hs[i].textContent.indexOf(text) !== -1) return hs[i];
    }
    return null;
  }

  function specRows(r) {
    return Array.prototype.slice.call(r.querySelectorAll(".dd-spec-row"));
  }

  function readSample(r) {
    var found = null;
    specRows(r).forEach(function (row) {
      var k = row.querySelector("span");
      if (k && k.textContent.trim() === "표본") found = num(row.textContent);
    });
    return found;
  }

  /* ---------- A. 상세 본문 1회 처리 ---------- */
  function applyDetail() {
    var r = root();
    if (!r) return;

    var title = r.querySelector("#modal-title");
    if (!title || !title.textContent.trim()) return;      // 아직 렌더 전
    var token = title.textContent.trim() + "|" + specRows(r).length;
    if (r.dataset.mktToken === token) return;
    r.dataset.mktToken = token;

    /* 1) 시세 섹션을 상품 정보 위로 */
    var mktHead = heading(r, "쇼핑몰 시세");
    var specHead = heading(r, "상품 정보");
    var mktBlock = r.querySelector(".dd-market");
    if (mktHead && specHead && mktBlock) {
      specHead.parentNode.insertBefore(mktHead, specHead);
      specHead.parentNode.insertBefore(mktBlock, specHead);
    }

    /* 2) 표본 부족 → 중앙값·최저가 행과 최저가 배지 제거 */
    var sample = readSample(r);
    if (sample === null) sample = 1;
    if (sample < MIN_SAMPLE) {
      specRows(r).forEach(function (row) {
        var k = row.querySelector("span");
        if (!k) return;
        var key = k.textContent.trim();
        if (key === "중앙값" || key === "최저가") row.remove();
      });
      var badge = r.querySelector(".deal-lowest");
      if (badge) badge.remove();
      var v = r.querySelector(".dd-verdict");
      if (v && !v.textContent.trim()) v.remove();

      /* 가격 흐름 섹션이 비어 있으면 숨김 */
      var chartBox = r.querySelector(".dd-chart");
      if (chartBox && !chartBox.querySelector("canvas")) chartBox.remove();
    }
  }

  /* ---------- B. 시세 리스트 → HTML 바 + 상단 파생 ---------- */
  function applyMarket() {
    var r = root();
    if (!r) return;
    var list = r.querySelector("#market-list") || document.getElementById("market-list");
    if (!list) return;

    var items = list.querySelectorAll("li");
    if (!items.length) return;

    var token = items.length + "|" + (items[0].textContent || "").trim();
    if (list.dataset.mktToken === token) return;
    list.dataset.mktToken = token;

    var rows = Array.prototype.map.call(items, function (li) {
      var mallEl = li.querySelector(".dd-market-mall");
      var priceEl = li.querySelector(".dd-market-price");
      if (!mallEl || !priceEl) return null;
      var a = priceEl.querySelector("a");
      return {
        mall: mallEl.textContent.trim(),
        price: num(priceEl.textContent),
        url: a ? a.getAttribute("href") : "",
        isDeal: li.classList.contains("is-deal")
      };
    }).filter(function (x) { return x && x.price; });

    if (!rows.length) return;

    /* 바 렌더 */
    var max = Math.max.apply(null, rows.map(function (x) { return x.price; }));
    var wrap = document.createElement("div");
    wrap.className = "mkt";
    rows.forEach(function (x) {
      var w = Math.max(8, Math.round((x.price / max) * 100));
      var row = document.createElement("div");
      row.className = "mkt-row" + (x.isDeal ? " is-deal" : "");
      var p = x.url
        ? '<a href="' + x.url + '" target="_blank" rel="noopener">' + fmt(x.price) + "</a>"
        : fmt(x.price);
      row.innerHTML =
        '<span class="mkt-mall">' + x.mall + "</span>" +
        '<span class="mkt-track"><span class="mkt-bar" style="width:' + w + '%"></span></span>' +
        '<span class="mkt-price">' + p + "</span>";
      wrap.appendChild(row);
    });
    var old = list.parentNode.querySelector(".mkt");
    if (old) old.remove();
    list.parentNode.appendChild(wrap);
    list.hidden = true;

    /* 상단 가격 블록 파생: 취소선 + 할인율 배지 + 판정 문장 */
    var priceEl = r.querySelector(".modal-price");
    if (!priceEl) return;
    var dealPrice = num(priceEl.textContent);
    if (!dealPrice) return;

    var others = rows.filter(function (x) { return !x.isDeal; });
    if (!others.length) return;
    var minOther = Math.min.apply(null, others.map(function (x) { return x.price; }));
    var maxOther = Math.max.apply(null, others.map(function (x) { return x.price; }));

    /* 이미 이력 기반 배지/취소선이 있으면 건드리지 않는다 */
    if (!priceEl.querySelector(".deal-off") && maxOther > dealPrice) {
      var off = Math.round((1 - dealPrice / maxOther) * 100);
      if (off >= 5) {
        var b = document.createElement("span");
        b.className = "deal-off";
        b.textContent = "-" + off + "%";
        priceEl.appendChild(b);
      }
    }
    if (!priceEl.querySelector(".mkt-strike") && maxOther > dealPrice) {
      var s = document.createElement("span");
      s.className = "mkt-strike";
      s.textContent = fmt(maxOther);
      priceEl.appendChild(s);
    }

    var hero = r.querySelector(".dd-hero > div:last-child") || r.querySelector(".dd-hero");
    if (!hero) return;
    var line = hero.querySelector(".dd-verdict");
    if (line && line.textContent.indexOf("평소가") !== -1) return;   // 이력 판정 존중
    if (!line) {
      line = document.createElement("p");
      line.className = "dd-verdict";
      hero.appendChild(line);
    }
    var check =
      '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 8.5l3 3 7-7"></path></svg>';
    if (dealPrice < minOther) {
      line.className = "dd-verdict";
      line.innerHTML =
        check + "<strong>쇼핑몰 최저가보다 저렴</strong>" +
        '<span class="status-sep">·</span>네이버 최저 ' + fmt(minOther) +
        "보다 " + fmt(minOther - dealPrice) + " 낮음";
    } else if (dealPrice === minOther) {
      line.className = "dd-verdict";
      line.innerHTML = check + "<strong>쇼핑몰 최저가와 동일</strong>";
    } else {
      line.className = "dd-verdict is-unknown";
      line.textContent =
        "네이버 최저 " + fmt(minOther) + "이 " + fmt(dealPrice - minOther) + " 더 저렴합니다";
    }
  }

  /* ---------- C. 채팅 빈 상태 ---------- */
  function applyChat() {
    var chat = document.querySelector(".dd-chat");
    if (chat) chat.classList.toggle("is-empty", !chat.querySelector(".chat-row"));
    var bar = document.getElementById("chat-reply-bar");
    var label = document.getElementById("chat-reply-label");
    if (bar && !bar.hidden && label && !label.textContent.trim()) bar.hidden = true;
  }

  function tick() {
    try { applyDetail(); } catch (e) { console.warn("[market.js] detail", e); }
    try { applyMarket(); } catch (e) { console.warn("[market.js] market", e); }
    try { applyChat(); } catch (e) { console.warn("[market.js] chat", e); }
  }

  var timer = null;
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(tick, 50);
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true,
    subtree: true
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tick);
  } else {
    tick();
  }
  window.__marketFix = tick;   // 콘솔에서 수동 실행: __marketFix()
})();
