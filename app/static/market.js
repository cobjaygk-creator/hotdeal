/* market.js — 상세 보조 (채팅 빈 상태 등). 시세 바는 live.js가 직접 렌더합니다. */
(function () {
  function applyChat() {
    var chat = document.querySelector(".dd-chat");
    if (chat) chat.classList.toggle("is-empty", !chat.querySelector(".chat-row"));
    var bar = document.getElementById("chat-reply-bar");
    var label = document.getElementById("chat-reply-label");
    if (bar && !bar.hidden && label && !label.textContent.trim()) bar.hidden = true;
  }

  function tick() {
    try { applyChat(); } catch (e) {}
  }

  var timer = null;
  new MutationObserver(function () {
    clearTimeout(timer);
    timer = setTimeout(tick, 50);
  }).observe(document.documentElement, { childList: true, subtree: true });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tick);
  } else {
    tick();
  }
})();
