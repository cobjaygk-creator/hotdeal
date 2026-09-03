/* ============================================================
   market.js — 상세/모달 후처리 (live.js 수정 없이 동작)
   1) 쇼핑몰 시세를 HTML 바로 다시 렌더
   2) 시세 섹션을 '상품 정보'보다 위로 이동
   3) 표본 부족 시 중앙값·최저가·최저가배지 제거 + 안내 문구
   4) 네이버 최저가 기준 판정 문장 생성
   base.html에서 live.js보다 뒤에(defer) 로드하세요.
   ============================================================ */
(function () {
  var MIN_SAMPLE = 3;

  function num(text) {
    var m = String(text || "").replace(/[^0-9]/g, "");
    return m ? Number(m) : null;
  }

  function fmt(n) {
    return Number(n).toLocaleString("ko-KR") + "원";
  }

  function scope(node) {
    return node.closest(".dd-main") || document;
  }

  function headingByText(root, text) {
    var hs = root.querySelectorAll("h2.dd-section");
    for (var i = 0; i < hs.length; i++) {
      if (hs[i].textContent.indexOf(text) !== -1) return hs[i];
    }
    return null;
  }

  /* ---------- 시세 리스트 → HTML 바 ---------- */
  function renderBars(list) {
    var rows = Array.prototype.map.call(list.querySelectorAll("li"), function (li) {
      var mallEl = li.querySelector(".dd-market-mall");
      var priceEl = li.querySelector(".dd-market-price");
      if (!mallEl || !priceEl) return null;
      var link = priceEl.querySelector("a");
      return {
        mall: mallEl.textContent.trim(),
        price: num(priceEl.textContent),
        url: link ? link.getAttribute("href") : "",
        isDeal: li.classList.contains("is-deal"),
      };
    }).filter(function (r) { return r && r.price; });

    if (!rows.length) return null;

    var max = Math.max.apply(null, rows.map(function (r) { return r.price; }));
    var wrap = document.createElement("div");
    wrap.className = "mkt";
    rows.forEach(function (r) {
      var w = Math.max(8, Math.round((r.price / max) * 100));
      var row = document.createElement("div");
      row.className = "mkt-row" + (r.isDeal ? " is-deal" : "");
      var priceInner = r.url
        ? '<a href="' + r.url + '" target="_blank" rel="noopener">' + fmt(r.price) + "</a>"
        : fmt(r.price);
      row.innerHTML =
        '<span class="mkt-mall">' + r.mall + "</span>" +
        '<span class="mkt-track"><span class="mkt-bar" style="width:' + w + '%"></span></span>' +
        '<span class="mkt-price">' + priceInner + "</span>";
      wrap.appendChild(row);
    });

    var old = list.parentNode.querySelector(".mkt");
    if (old) old.remove();
    list.parentNode.appendChild(wrap);
    list.hidden = true;
    return rows;
  }

  /* ---------- 판정 문장 ---------- */
  function setVerdict(root, rows) {
    var hero = root.querySelector(".dd-hero > div:last-child") || root.querySelector(".dd-hero");
    if (!hero) return;

    var priceEl = root.querySelector(".modal-price");
    var dealPrice = priceEl ? num(priceEl.textContent) : null;
    if (!dealPrice) return;

    var others = (rows || []).filter(function (r) { return !r.isDeal; });
    var line = hero.querySelector(".dd-verdict");

    // live.js/Jinja가 이미 이력 기반 판정을 넣었으면 존중
    if (line && line.textContent.indexOf("평소가") !== -1) return;

    if (!others.length) return;
    var min = Math.min.apply(null, others.map(function (r) { return r.price; }));

    if (!line) {
      line = document.createElement("p");
      line.className = "dd-verdict";
      hero.appendChild(line);
    }

    if (dealPrice < min) {
      line.className = "dd-verdict";
      line.innerHTML =
        '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 8.5l3 3 7-7"></path></svg>' +
        "<strong>쇼핑몰 최저가보다 저렴</strong>" +
        '<span class="status-sep">·</span>' +
        "네이버 최저 " + fmt(min) + "보다 " + fmt(min - dealPrice) + " 낮음";
    } else if (dealPrice === min) {
      line.className = "dd-verdict";
      line.innerHTML =
        '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 8.5l3 3 7-7"></path></svg>' +
        "<strong>쇼핑몰 최저가와 동일</strong>";
    } else {
      line.className = "dd-verdict is-unknown";
      line.textContent = "네이버 최저 " + fmt(min) + "이 " + fmt(dealPrice - min) + " 더 저렴합니다";
    }
  }

  /* ---------- 시세 섹션을 상품 정보 위로 ---------- */
  function reorder(root) {
    var mktHead = headingByText(root, "쇼핑몰 시세");
    var specHead = headingByText(root, "상품 정보");
    if (!mktHead || !specHead) return;
    var block = root.querySelector(".dd-market");
    if (!block || mktHead.dataset.moved) return;
    mktHead.dataset.moved = "1";
    specHead.parentNode.insertBefore(mktHead, specHead);
    specHead.parentNode.insertBefore(block, specHead);
  }

  /* ---------- 표본 부족 처리 ---------- */
  function guardSample(root) {
    if (root.dataset && root.dataset.sampleGuarded) return;
    var rows = root.querySelectorAll(".dd-spec-row");
    var sample = null;
    rows.forEach(function (r) {
      var k = r.querySelector("span");
      if (k && k.textContent.trim() === "표본") sample = num(r.textContent);
    });
    if (sample === null) sample = 1;
    if (root.dataset) root.dataset.sampleGuarded = "1";
    if (sample >= MIN_SAMPLE) return;

    rows.forEach(function (r) {
      var k = r.querySelector("span");
      if (!k) return;
      var key = k.textContent.trim();
      if (key === "중앙값" || key === "최저가") r.remove();
    });
    var badge = root.querySelector(".deal-lowest");
    if (badge) badge.remove();

    var v = root.querySelector(".dd-verdict");
    if (v && !v.textContent.trim()) v.remove();
  }

  /* ---------- 채팅 빈 상태 ---------- */
  function guardChat() {
    var chat = document.querySelector(".dd-chat");
    if (!chat) return;
    var hasMsg = !!chat.querySelector(".chat-row");
    chat.classList.toggle("is-empty", !hasMsg);
    var bar = document.getElementById("chat-reply-bar");
    if (bar && !bar.hidden) {
      var t = bar.querySelector(".chat-reply-target, span");
      if (!t || !t.textContent.trim()) bar.hidden = true;
    }
  }

  /* ---------- 관측 ---------- */
  function process(list) {
    var root = scope(list);
    guardSample(root);
    reorder(root);
    var rows = renderBars(list);
    if (rows) setVerdict(root, rows);
    guardChat();
  }

  var pending = null;
  new MutationObserver(function () {
    var list = document.getElementById("market-list");
    if (list && list.querySelector("li")) {
      clearTimeout(pending);
      pending = setTimeout(function () { process(list); }, 60);
    }
    var main = document.querySelector(".dd-main");
    if (main) {
      guardSample(main);
      reorder(main);
    }
    guardChat();
  }).observe(document.body, { childList: true, subtree: true });

  document.addEventListener("DOMContentLoaded", function () {
    var main = document.querySelector(".dd-main");
    if (main) {
      guardSample(main);
      reorder(main);
    }
    var list = document.getElementById("market-list");
    if (list && list.querySelector("li")) process(list);
    guardChat();
  });
})();
