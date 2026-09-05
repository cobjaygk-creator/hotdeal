(function () {
  function urlB64ToUint8Array(base64) {
    const pad = "=".repeat((4 - (base64.length % 4)) % 4);
    const b64 = (base64 + pad).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(b64);
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  const meta = document.getElementById("push-config");
  const publicKey = meta ? meta.dataset.key : "";
  const supported =
    "serviceWorker" in navigator && "PushManager" in window && !!publicKey;

  async function reg() {
    return navigator.serviceWorker.register("/sw.js");
  }

  if ("serviceWorker" in navigator) {
    reg().catch(() => {});
  }

  async function currentSub() {
    if (!supported) return null;
    const r = await reg();
    return r.pushManager.getSubscription();
  }

  async function subscribe() {
    const r = await reg();
    const perm = await Notification.requestPermission();
    if (perm !== "granted") throw new Error("permission denied");
    const sub = await r.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(publicKey),
    });
    await fetch("/api/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sub.toJSON()),
    });
  }

  async function unsubscribe() {
    const sub = await currentSub();
    if (!sub) return;
    await fetch("/api/push/unsubscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: sub.endpoint }),
    });
    await sub.unsubscribe();
  }

  const btn = document.getElementById("push-toggle");
  if (btn) {
    if (!supported) {
      btn.disabled = true;
      btn.textContent = "이 브라우저는 웹 푸시를 지원하지 않습니다";
    } else {
      currentSub().then((s) => {
        btn.textContent = s ? "이 기기 알림 해제" : "이 기기에서 알림 받기";
        btn.dataset.on = s ? "1" : "";
      });
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          if (btn.dataset.on) {
            await unsubscribe();
            btn.textContent = "이 기기에서 알림 받기";
            btn.dataset.on = "";
          } else {
            await subscribe();
            btn.textContent = "이 기기 알림 해제";
            btn.dataset.on = "1";
          }
        } catch (e) {
          alert("알림 설정에 실패했습니다: " + e.message);
        } finally {
          btn.disabled = false;
        }
      });
    }
  }

  // In-app inbox dropdown (present on every page for logged-in users).
  const inbox = document.getElementById("inbox-menu");
  if (inbox) {
    const badge = inbox.querySelector(".inbox-badge");
    const list = inbox.querySelector(".inbox-list");
    async function load() {
      try {
        const res = await fetch("/api/me/notifications");
        if (!res.ok) return;
        const data = await res.json();
        if (badge) {
          badge.textContent = data.unread > 9 ? "9+" : String(data.unread || "");
          badge.hidden = !data.unread;
        }
        if (list) {
          list.innerHTML = (data.items || [])
            .map(
              (n) =>
                '<a href="/deal/' +
                n.deal_id +
                '"><strong>' +
                (n.product_name || "핫딜") +
                "</strong><span>" +
                (n.keyword || "") +
                "</span></a>"
            )
            .join("") || '<p class="inbox-empty">알림이 없습니다.</p>';
        }
      } catch (e) {}
    }
    inbox.addEventListener("toggle", () => {
      if (inbox.open) {
        load();
        fetch("/api/me/notifications/read", { method: "POST" }).then(() => {
          if (badge) badge.hidden = true;
        });
      }
    });
    load();
  }
})();
