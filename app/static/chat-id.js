/* ============================================================
   chat-id.js — 익명 식별자 자동 발급
   · 닉네임: 대문자+숫자 6자 (혼동 문자 제외), 브라우저에 고정
   · PIN: 삭제 권한용 4자리, 사용자에게 보이지 않음
   comments.js는 #chat-nick / #chat-pin 의 value만 읽으므로
   해당 파일을 수정하지 않습니다.
   ============================================================ */
(function () {
  var ID_KEY = "hotdeal.anonId";
  var PIN_KEY = "hotdeal.anonPin";
  var ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // I,O,0,1 제외

  function randFrom(set, len) {
    var out = "";
    if (window.crypto && window.crypto.getRandomValues) {
      var buf = new Uint32Array(len);
      window.crypto.getRandomValues(buf);
      for (var i = 0; i < len; i++) out += set[buf[i] % set.length];
    } else {
      for (var j = 0; j < len; j++) out += set[Math.floor(Math.random() * set.length)];
    }
    return out;
  }

  function store(key, make) {
    var v = null;
    try { v = localStorage.getItem(key); } catch (e) {}
    if (!v) {
      v = make();
      try { localStorage.setItem(key, v); } catch (e) {}
    }
    return v;
  }

  var anonId = store(ID_KEY, function () { return randFrom(ALPHABET, 6); });
  var anonPin = store(PIN_KEY, function () { return randFrom("0123456789", 4); });

  function apply() {
    var nick = document.getElementById("chat-nick");
    var pin = document.getElementById("chat-pin");
    if (nick && nick.value !== anonId) nick.value = anonId;
    if (pin && pin.value !== anonPin) pin.value = anonPin;

    var badge = document.getElementById("chat-me");
    if (badge && badge.textContent !== anonId) badge.textContent = anonId;

    var foot = document.getElementById("chat-foot-id");
    if (foot && !foot.textContent) foot.textContent = anonId + " 으로 작성";
  }

  apply();
  document.addEventListener("DOMContentLoaded", apply);
  new MutationObserver(apply).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
