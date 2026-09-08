/* 상세 스크롤 시 상품 요약을 우측 댓글 상단으로 이어지듯 이동 */
(function () {
  var observer = null;
  var scroller = null;
  var hero = null;
  var chat = null;
  var pin = null;
  var pinned = false;
  var animating = false;
  var flyEl = null;
  var collapseTimer = null;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function reduceMotion() {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (e) {
      return false;
    }
  }

  function isDesktopSplit() {
    try {
      return window.matchMedia("(min-width: 960px)").matches;
    } catch (e) {
      return true;
    }
  }

  function syncFromHero() {
    if (!hero || !pin) return;
    var title = ($("#modal-title", hero) || $("h1", hero));
    var price = $(".modal-price", hero);
    var img = $(".modal-thumb", hero);
    var t = $("#dd-chat-pin-title", pin);
    var p = $("#dd-chat-pin-price", pin);
    var thumb = $("#dd-chat-pin-thumb", pin);
    if (t) t.textContent = title ? title.textContent.trim() : "";
    if (p) p.textContent = price ? price.textContent.replace(/\s+/g, " ").trim() : "";
    if (thumb) {
      if (img && img.getAttribute("src")) {
        thumb.innerHTML =
          '<img src="' +
          img.getAttribute("src") +
          '" alt="" referrerpolicy="no-referrer">';
      } else {
        thumb.innerHTML = "";
      }
    }
  }

  function clearFly() {
    if (flyEl && flyEl.parentNode) flyEl.parentNode.removeChild(flyEl);
    flyEl = null;
  }

  function makeFlyCard(rect) {
    var card = document.createElement("div");
    card.className = "dd-chat-pin-fly";
    card.setAttribute("aria-hidden", "true");
    var title = ($("#dd-chat-pin-title", pin) || {}).textContent || "";
    var price = ($("#dd-chat-pin-price", pin) || {}).textContent || "";
    var thumbHtml = ($("#dd-chat-pin-thumb", pin) || {}).innerHTML || "";
    card.innerHTML =
      '<span class="dd-chat-pin-thumb">' +
      thumbHtml +
      "</span>" +
      '<span class="dd-chat-pin-body">' +
      '<span class="dd-chat-pin-title"></span>' +
      '<span class="dd-chat-pin-price"></span>' +
      "</span>";
    var ft = $(".dd-chat-pin-title", card);
    var fp = $(".dd-chat-pin-price", card);
    if (ft) ft.textContent = title;
    if (fp) fp.textContent = price;
    var w = Math.max(180, Math.min(rect.width, 380));
    var h = Math.max(72, Math.min(rect.height, 120));
    Object.assign(card.style, {
      left: rect.left + "px",
      top: Math.max(8, rect.top) + "px",
      width: w + "px",
      height: h + "px",
    });
    document.body.appendChild(card);
    flyEl = card;
    return card;
  }

  function showPinnedInstant() {
    if (!chat || !pin) return;
    pin.hidden = false;
    pin.setAttribute("aria-hidden", "false");
    chat.classList.add("is-pinned");
    chat.classList.remove("is-pin-leaving");
  }

  function hidePinnedInstant() {
    if (!chat || !pin) return;
    chat.classList.remove("is-pinned", "is-pin-leaving");
    pin.hidden = true;
    pin.setAttribute("aria-hidden", "true");
  }

  function flyIn(done) {
    if (!hero || !pin || !chat) {
      if (done) done();
      return;
    }
    syncFromHero();
    var first = hero.getBoundingClientRect();
    pin.hidden = false;
    pin.setAttribute("aria-hidden", "false");
    chat.classList.add("is-pinned", "is-pin-arriving");
    chat.classList.remove("is-pin-leaving");

    requestAnimationFrame(function () {
      var inner = $(".dd-chat-pin-inner", pin);
      var last = inner ? inner.getBoundingClientRect() : pin.getBoundingClientRect();
      if (last.width < 8 || last.height < 8 || first.width < 8) {
        chat.classList.remove("is-pin-arriving");
        showPinnedInstant();
        if (done) done();
        return;
      }
      var ghost = makeFlyCard(first);
      void ghost.offsetWidth;
      ghost.style.left = last.left + "px";
      ghost.style.top = last.top + "px";
      ghost.style.width = last.width + "px";
      ghost.style.height = last.height + "px";
      ghost.style.opacity = "0";
      ghost.style.borderRadius = "14px";
      ghost.style.boxShadow = "0 4px 14px rgba(22, 24, 29, 0.08)";

      var finished = false;
      function finish() {
        if (finished) return;
        finished = true;
        clearFly();
        chat.classList.remove("is-pin-arriving");
        if (done) done();
      }
      ghost.addEventListener("transitionend", finish);
      setTimeout(finish, 580);
    });
  }

  function flyOut(done) {
    if (!hero || !pin || !chat || pin.hidden) {
      hidePinnedInstant();
      if (done) done();
      return;
    }
    var inner = $(".dd-chat-pin-inner", pin);
    var first = inner ? inner.getBoundingClientRect() : pin.getBoundingClientRect();
    var last = hero.getBoundingClientRect();
    chat.classList.add("is-pin-leaving");
    chat.classList.remove("is-pin-arriving");

    var ghost = makeFlyCard(first);
    void ghost.offsetWidth;
    ghost.style.left = Math.max(8, last.left) + "px";
    ghost.style.top = Math.max(8, last.top) + "px";
    ghost.style.width = Math.min(last.width, 320) + "px";
    ghost.style.height = "88px";
    ghost.style.opacity = "0";

    clearTimeout(collapseTimer);
    collapseTimer = setTimeout(function () {
      clearFly();
      hidePinnedInstant();
      if (done) done();
    }, 450);

    requestAnimationFrame(function () {
      chat.classList.remove("is-pinned");
    });
  }

  function setPinned(on) {
    if (!chat || !pin) return;
    if (on === pinned) return;

    // 진행 중이면 비행 카드만 정리하고 즉시 상태 맞춤
    if (animating) {
      clearTimeout(collapseTimer);
      clearFly();
      animating = false;
      if (on) showPinnedInstant();
      else hidePinnedInstant();
      pinned = on;
      return;
    }

    pinned = on;

    if (!isDesktopSplit() || reduceMotion()) {
      if (on) showPinnedInstant();
      else hidePinnedInstant();
      return;
    }

    animating = true;
    if (on) {
      flyIn(function () {
        animating = false;
      });
    } else {
      flyOut(function () {
        animating = false;
      });
    }
  }

  function onIntersect(entries) {
    var entry = entries[0];
    if (!entry) return;
    var rootTop = entry.rootBounds ? entry.rootBounds.top : 0;
    var above = entry.boundingClientRect.bottom <= rootTop + 4;
    if (above) setPinned(true);
    else if (entry.isIntersecting) setPinned(false);
  }

  function unbind() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    clearTimeout(collapseTimer);
    clearFly();
    pinned = false;
    animating = false;
    hidePinnedInstant();
    scroller = null;
    hero = null;
  }

  function bind() {
    // 스크롤 시 상품정보가 우측 댓글 상단으로 날아가는 핀 애니메이션은 사용하지
    // 않는다 — 핀을 비활성화하고 숨긴 상태로만 둔다. API는 live.js 호환을 위해 유지.
    chat = $("#dd-chat");
    pin = $("#dd-chat-pin");
    hidePinnedInstant();
  }

  window.DealChatPin = { bind: bind, unbind: unbind };
})();
