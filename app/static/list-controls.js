/* 불러온 목록 내 정렬 + 품절 숨기기 (클라이언트 전용) */
(function () {
  var list = document.getElementById("deal-body");
  var group = document.getElementById("sort-group");
  var hide = document.getElementById("hide-soldout");
  if (!list) return;

  var mode = "recent";
  try { mode = localStorage.getItem("deal-sort") || "recent"; } catch (e) {}
  var hideSoldout = false;
  try { hideSoldout = localStorage.getItem("deal-hide-soldout") === "1"; } catch (e) {}
  var busy = false;
  var timer = null;

  function num(li, attr) {
    var v = parseFloat(li.getAttribute(attr) || "");
    return isNaN(v) ? null : v;
  }

  function compare(a, b) {
    if (mode === "price-asc") {
      var pa = num(a, "data-price"), pb = num(b, "data-price");
      if (pa === null && pb === null) return 0;
      if (pa === null) return 1;
      if (pb === null) return -1;
      return pa - pb;
    }
    if (mode === "discount") {
      var da = num(a, "data-discount"), db = num(b, "data-discount");
      if (da === null && db === null) return 0;
      if (da === null) return 1;
      if (db === null) return -1;
      // discount_rate는 음수(더 할인일수록 작음) → 오름차순
      return da - db;
    }
    if (mode === "comments") {
      return (num(b, "data-comments") || 0) - (num(a, "data-comments") || 0);
    }
    return String(b.getAttribute("data-ts") || "").localeCompare(String(a.getAttribute("data-ts") || ""));
  }

  function applySort() {
    var items = Array.prototype.slice.call(list.querySelectorAll("li.deal-card"));
    if (!items.length) return;
    var sorted = items.slice().sort(compare);
    var unchanged = sorted.every(function (el, i) { return el === items[i]; });
    if (unchanged) return;

    busy = true;
    sorted.forEach(function (li) { list.appendChild(li); });
    // MutationObserver는 동기 블록 이후에 돌아가므로 busy를 마이크로태스크에서 해제
    Promise.resolve().then(function () { busy = false; });
  }

  function applyHide() {
    collapseSourceDupes();
    list.querySelectorAll('li.deal-card[data-status="expired"]').forEach(function (li) {
      if (li.hidden) return;
      li.style.display = hideSoldout ? "none" : "";
    });
  }

  function normTitle(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/\s+\d[\d,]*\s*원/g, " ")
      .replace(/기타정보|인기정보/g, " ")
      .replace(/[^0-9a-z가-힣]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function sourceRank(src) {
    var keys = String(src || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    if (keys.some(function (k) { return k && k !== "ppomppu"; })) return 0;
    return 1;
  }

  function collapseSourceDupes() {
    var cards = Array.prototype.slice.call(list.querySelectorAll("li.deal-card"));
    var kept = [];
    cards.forEach(function (li) {
      var price = li.getAttribute("data-price") || "";
      var title = normTitle((li.querySelector(".deal-title") || {}).textContent || "");
      var src = li.getAttribute("data-sources") || "";
      var dup = null;
      for (var i = 0; i < kept.length; i++) {
        if (kept[i].price === price && kept[i].title === title) {
          dup = kept[i];
          break;
        }
      }
      if (!dup) {
        li.hidden = false;
        kept.push({ li: li, price: price, title: title, src: src });
        return;
      }
      if (sourceRank(src) < sourceRank(dup.src)) {
        dup.li.hidden = true;
        li.hidden = false;
        dup.li = li;
        dup.src = src;
      } else {
        li.hidden = true;
      }
    });
  }

  function syncSortChips() {
    if (!group) return;
    group.querySelectorAll("[data-sort]").forEach(function (b) {
      var on = b.dataset.sort === mode;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  function syncHideChip() {
    if (!hide) return;
    hide.classList.toggle("on", hideSoldout);
    hide.setAttribute("aria-pressed", hideSoldout ? "true" : "false");
  }

  if (group) {
    group.addEventListener("click", function (e) {
      var hideBtn = e.target.closest("#hide-soldout");
      if (hideBtn) {
        hideSoldout = !hideSoldout;
        try { localStorage.setItem("deal-hide-soldout", hideSoldout ? "1" : "0"); } catch (err) {}
        syncHideChip();
        applyHide();
        return;
      }
      var btn = e.target.closest("[data-sort]");
      if (!btn) return;
      mode = btn.dataset.sort;
      try { localStorage.setItem("deal-sort", mode); } catch (err) {}
      syncSortChips();
      applySort();
      applyHide();
    });
  }

  new MutationObserver(function () {
    if (busy) return;
    clearTimeout(timer);
    timer = setTimeout(function () {
      applySort();
      applyHide();
    }, 120);
  }).observe(list, { childList: true });

  syncSortChips();
  syncHideChip();
  if (mode !== "recent") applySort();
  applyHide();
  collapseSourceDupes();
})();
