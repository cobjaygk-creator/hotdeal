(function () {
  const QUICK = ["샀어요", "품절됐어요", "더 싼 곳 있어요", "가격 실화?"];
  const REASONS = {
    like: "🔥 좋아요",
    meh: "🤔 글쎄",
    bought: "💸 샀어요",
    soldout: "⛔ 품절",
  };
  const NICK_KEY = "hotdeal.chatNick";
  const PIN_KEY = "hotdeal.chatPin";

  let dealId = 0;
  let lastId = 0;
  let pollTimer = null;
  let parentId = null;
  let parentNick = "";
  let isAdmin = false;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }
  function $$(sel, root) {
    return [...(root || document).querySelectorAll(sel)];
  }
  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function rel(ts) {
    if (window.relativeTime) return window.relativeTime(ts);
    return ts || "";
  }

  function loadId() {
    const nick = $("#chat-nick");
    const pin = $("#chat-pin");
    try {
      if (nick) nick.value = localStorage.getItem(NICK_KEY) || "";
      if (pin) pin.value = localStorage.getItem(PIN_KEY) || "";
    } catch (e) {}
  }
  function saveId() {
    try {
      localStorage.setItem(NICK_KEY, ($("#chat-nick") || {}).value || "");
      localStorage.setItem(PIN_KEY, ($("#chat-pin") || {}).value || "");
    } catch (e) {}
  }

  function setCounts(n) {
    $$("[data-chat-count]").forEach((el) => {
      el.textContent = n > 0 ? String(n) : "";
    });
  }

  function emptyHtml() {
    return (
      `<div class="chat-empty"><p>첫 댓글을 남겨 보세요.</p><div class="chat-quick">` +
      QUICK.map((t) => `<button type="button" class="chat-quick-btn" data-quick="${esc(t)}">${esc(t)}</button>`).join("") +
      `</div></div>`
    );
  }

  function bubbleHtml(item) {
    const mine = item.mine ? " is-mine" : "";
    const quote =
      item.parent_nickname
        ? `<div class="chat-quote">@${esc(item.parent_nickname)} ${esc((item.parent_body || "").slice(0, 40))}</div>`
        : "";
    const del = item.can_delete
      ? `<button type="button" class="chat-del" data-del="${item.id}">삭제</button>`
      : "";
    const reply = item.deleted
      ? ""
      : `<button type="button" class="chat-reply" data-reply="${item.id}" data-nick="${esc(item.nickname)}">답글</button>`;
    return `<article class="chat-row${mine}" data-cid="${item.id}">
      <div class="chat-nick">${esc(item.nickname)}</div>
      <div class="chat-bubble">${quote}<div class="chat-body">${esc(item.body)}</div></div>
      <div class="chat-meta"><time>${esc(rel(item.created_at))}</time>${reply}${del}</div>
    </article>`;
  }

  function renderList(items, replace) {
    const log = $("#chat-log");
    if (!log) return;
    if (replace) {
      log.innerHTML = items.length ? items.map(bubbleHtml).join("") : emptyHtml();
    } else {
      const empty = log.querySelector(".chat-empty");
      if (empty) empty.remove();
      items.forEach((item) => {
        if (log.querySelector(`[data-cid="${item.id}"]`)) return;
        log.insertAdjacentHTML("beforeend", bubbleHtml(item));
      });
    }
    if (items.length) log.scrollTop = log.scrollHeight;
    items.forEach((item) => {
      if (item.id > lastId) lastId = item.id;
    });
  }

  function paintReactions(snap) {
    if (!snap) return;
    $$(".chat-react").forEach((btn) => {
      const kind = btn.dataset.kind;
      const count = (snap.counts && snap.counts[kind]) || 0;
      const span = btn.querySelector("[data-count]");
      if (span) span.textContent = count;
      btn.classList.toggle("on", (snap.mine || []).includes(kind));
    });
  }

  async function load(after) {
    if (!dealId) return;
    const res = await fetch(`/api/deals/${dealId}/comments?after=${after || 0}`, {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    const data = await res.json();
    isAdmin = !!data.is_admin;
    setCounts(data.count || 0);
    paintReactions(data.reactions);
    renderList(data.items || [], !after);
  }

  async function send(body) {
    const nick = ($("#chat-nick") || {}).value || "";
    const pin = ($("#chat-pin") || {}).value || "";
    const text = (body || ($("#chat-input") || {}).value || "").trim();
    if (text.length < 2) return;
    if (!/^\d{4}$/.test(pin)) {
      window.alert("삭제용 숫자 4자리 PIN을 입력해 주세요.");
      return;
    }
    saveId();
    const payload = { nickname: nick, pin, body: text, parent_id: parentId };
    try {
      const res = await fetch(`/api/deals/${dealId}/comments`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        window.alert(data.detail || "댓글을 남기지 못했습니다.");
        return;
      }
      const input = $("#chat-input");
      if (input) input.value = "";
      updateLen();
      clearReply();
      renderList([data], false);
      const countEl = $$("[data-chat-count]");
      const n = Number((countEl[0] && countEl[0].textContent) || 0) + 1;
      setCounts(n);
    } catch (e) {
      window.alert("댓글을 남기지 못했습니다.");
    }
  }

  async function remove(id) {
    const pin = ($("#chat-pin") || {}).value || "";
    if (!isAdmin && !/^\d{4}$/.test(pin)) {
      window.alert("PIN이 필요합니다.");
      return;
    }
    const res = await fetch(`/api/comments/${id}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      window.alert(data.detail || "삭제하지 못했습니다.");
      return;
    }
    const row = document.querySelector(`[data-cid="${id}"] .chat-body`);
    if (row) row.textContent = "삭제된 댓글입니다";
  }

  async function react(kind) {
    const res = await fetch(`/api/deals/${dealId}/reactions`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    });
    if (!res.ok) return;
    paintReactions(await res.json());
  }

  function setReply(id, nick) {
    parentId = id;
    parentNick = nick;
    const bar = $("#chat-reply-bar");
    const label = $("#chat-reply-label");
    if (bar) bar.hidden = false;
    if (label) label.textContent = `@${nick}에게 답글`;
    $("#chat-input")?.focus();
  }
  function clearReply() {
    parentId = null;
    parentNick = "";
    const bar = $("#chat-reply-bar");
    if (bar) bar.hidden = true;
  }

  function updateLen() {
    const el = $("#chat-len");
    const input = $("#chat-input");
    if (el && input) el.textContent = `${input.value.length}/300`;
  }

  function setPane(name) {
    const split = document.querySelector(".dd-split") || document.querySelector(".dd-page");
    if (split) split.dataset.pane = name;
    $$("[data-dd-pane]").forEach((btn) => {
      const on = btn.dataset.ddPane === name;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  function bindOnce() {
    if (document.body.dataset.chatBound) return;
    document.body.dataset.chatBound = "1";
    document.addEventListener("click", (e) => {
      const pane = e.target.closest("[data-dd-pane]");
      if (pane) {
        setPane(pane.dataset.ddPane);
        return;
      }
      const quick = e.target.closest("[data-quick]");
      if (quick) {
        send(quick.dataset.quick);
        return;
      }
      const reactBtn = e.target.closest(".chat-react");
      if (reactBtn && dealId) {
        react(reactBtn.dataset.kind);
        return;
      }
      const reply = e.target.closest("[data-reply]");
      if (reply) {
        setReply(Number(reply.dataset.reply), reply.dataset.nick || "");
        return;
      }
      const del = e.target.closest("[data-del]");
      if (del) {
        remove(Number(del.dataset.del));
        return;
      }
      if (e.target.closest("#chat-reply-cancel")) clearReply();
      if (e.target.closest("#chat-send")) send();
    });
    $("#chat-input")?.addEventListener("input", updateLen);
    $("#chat-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });
  }

  function stop() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    dealId = 0;
    lastId = 0;
    clearReply();
  }

  async function open(id) {
    bindOnce();
    loadId();
    dealId = Number(id);
    lastId = 0;
    const chat = $("#dd-chat");
    if (chat) chat.dataset.dealId = String(id);
    setPane("info");
    await load(0);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      if (dealId) load(lastId);
    }, 8000);
  }

  window.DealChat = { open, stop, setPane };
})();
