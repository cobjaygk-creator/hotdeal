/* 불러온 목록 내 정렬 + 품절 숨기기 (클라이언트 전용) */
(function () {
  var list = document.getElementById("deal-body");
  var group = document.getElementById("sort-group");
  var hide = document.getElementById("hide-soldout");
  if (!list) return;

  var mode = "recent";
  try { mode = localStorage.getItem("deal-sort") || "recent"; } catch (e) {}
  var busy = false;

  function num(li, attr) {
    var v = parseFloat(li.getAttribute(attr) || "");
    return isNaN(v) ? null : v;
  }

  function apply() {
    var items = Array.prototype.slice.call(list.querySelectorAll("li.deal-card"));
    if (!items.length) return;
    items.sort(function (a, b) {
      if (mode === "price-asc") {
        var pa = num(a, "data-price"), pb = num(b, "data-price");
        if (pa === null && pb === null) return 0;
        if (pa === null) return 1;
        if (pb === null) return -1;
        return pa - pb;
      }
      if (mode === "comments") {
        return (num(b, "data-comments") || 0) - (num(a, "data-comments") || 0);
      }
      return String(b.getAttribute("data-ts") || "").localeCompare(String(a.getAttribute("data-ts") || ""));
    });
    busy = true;
    items.forEach(function (li) { list.appendChild(li); });
    busy = false;
  }

  function syncChips() {
    if (!group) return;
    group.querySelectorAll("[data-sort]").forEach(function (b) {
      var on = b.dataset.sort === mode;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  if (group) {
    group.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-sort]");
      if (!btn) return;
      mode = btn.dataset.sort;
      try { localStorage.setItem("deal-sort", mode); } catch (err) {}
      syncChips();
      apply();
    });
  }

  if (hide) {
    try { hide.checked = localStorage.getItem("deal-hide-soldout") === "1"; } catch (e) {}
    var toggle = function () {
      list.querySelectorAll('li.deal-card[data-status="expired"]').forEach(function (li) {
        li.style.display = hide.checked ? "none" : "";
      });
      try { localStorage.setItem("deal-hide-soldout", hide.checked ? "1" : "0"); } catch (e) {}
    };
    hide.addEventListener("change", toggle);
    toggle();
  }

  // live.js가 새 딜을 붙이면 다시 정렬
  var timer = null;
  new MutationObserver(function () {
    if (busy) return;
    clearTimeout(timer);
    timer = setTimeout(function () {
      apply();
      if (hide && hide.checked) {
        list.querySelectorAll('li.deal-card[data-status="expired"]').forEach(function (li) { li.style.display = "none"; });
      }
    }, 120);
  }).observe(list, { childList: true });

  syncChips();
  if (mode !== "recent") apply();
})();
