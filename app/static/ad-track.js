(() => {
  const device = matchMedia("(max-width: 700px)").matches ? "mobile" : "pc";
  document.querySelectorAll(".adsbygoogle").forEach((el, index) => {
    const placement = el.closest("[aria-label='광고']")?.className || ("ad-" + index);
    fetch("/api/ads/event", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({event_type:"impression", placement, device})}).catch(() => {});
    el.addEventListener("click", () => fetch("/api/ads/event", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({event_type:"click", placement, device})}).catch(() => {}), {once:true});
  });
})();
