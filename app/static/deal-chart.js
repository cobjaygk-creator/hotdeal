/* 가격 흐름 차트 — 커뮤니티 딜 게시 가격
   호출: window.renderPriceChart("chart", points, baseline)
   기간: window.filterPricePoints(points, days)  days=0 → 전체   */
(function () {
  var charts = {};

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function parseDate(raw) {
    if (!raw) return null;
    var d = new Date(String(raw).replace(" ", "T"));
    return isNaN(d.getTime()) ? null : d;
  }

  window.filterPricePoints = function (points, days) {
    if (!points || !points.length) return [];
    var n = Number(days) || 0;
    if (n <= 0) return points.slice();
    var cutoff = Date.now() - n * 86400000;
    var filtered = points.filter(function (p) {
      var d = parseDate(p.observed_at);
      return d && d.getTime() >= cutoff;
    });
    return filtered.length >= 2 ? filtered : points.slice();
  };

  /* 실제 이력이 부족할 때 쓰는 임시 예시 곡선 (현재가 기준 하향) */
  window.demoPricePoints = function (dealPrice, baseline) {
    var end = Number(dealPrice) || Number(baseline) || 30000;
    if (!(end > 0)) end = 30000;
    var start = Number(baseline) > end ? Number(baseline) * 1.12 : end * 1.45;
    var mid = (start + end) / 2;
    var factors = [1, 0.97, 0.94, 0.96, 0.91, 0.9, 0.88, 0.86, 0.84, 0.82, 0.78, 0.74, 0.7, 0.66];
    var now = Date.now();
    var span = 90 * 86400000;
    var points = factors.map(function (f, i) {
      var t = now - span + (span * i) / (factors.length - 1);
      var wobble = ((i % 3) - 1) * end * 0.012;
      var price = Math.round(start * f + wobble * 0.2);
      if (i === factors.length - 1) price = Math.round(end);
      if (i === Math.floor(factors.length / 2)) price = Math.round(mid);
      var d = new Date(t);
      var y = d.getFullYear();
      var m = String(d.getMonth() + 1).padStart(2, "0");
      var day = String(d.getDate()).padStart(2, "0");
      return { observed_at: y + "-" + m + "-" + day + " 12:00:00", price: price, demo: true };
    });
    return points;
  };

  window.renderPriceChart = function (canvasId, points, baseline) {
    var el = document.getElementById(canvasId);
    if (!el || !window.Chart || !points || points.length < 2) return null;

    if (charts[canvasId]) {
      try { charts[canvasId].destroy(); } catch (e) {}
      charts[canvasId] = null;
    }

    var ink = cssVar("--ink", "#16181d");
    var faint = cssVar("--ink-faint", "#8b94a3");
    var accent = cssVar("--accent", "#0052cc");
    var border = cssVar("--border", "#e4e7ec");
    var borderStrong = cssVar("--border-strong", "#cdd2da");
    var danger = cssVar("--danger", "#c81e1e");
    var surface = cssVar("--surface", "#ffffff");
    var font = "Pretendard Variable, Pretendard, sans-serif";

    var prices = points.map(function (p) { return p.price; });
    var labels = points.map(function (p) {
      var d = parseDate(p.observed_at);
      return d ? (d.getMonth() + 1) + "/" + d.getDate() : String(p.observed_at).slice(5, 10);
    });
    var last = prices.length - 1;

    var ctx = el.getContext("2d");
    var grad = ctx.createLinearGradient(0, 0, 0, el.clientHeight || 230);
    grad.addColorStop(0, accent + "1F");
    grad.addColorStop(1, accent + "00");

    var datasets = [{
      label: "딜 가격",
      data: prices,
      borderColor: accent,
      borderWidth: 2,
      fill: true,
      backgroundColor: grad,
      tension: 0.34,
      pointRadius: prices.map(function (_, i) { return i === last ? 5 : 0; }),
      pointBackgroundColor: danger,
      pointBorderColor: surface,
      pointBorderWidth: 2,
      pointHoverRadius: 5
    }];

    if (baseline) {
      datasets.push({
        label: "평소가",
        data: prices.map(function () { return baseline; }),
        borderColor: borderStrong,
        borderWidth: 1.5,
        borderDash: [5, 5],
        pointRadius: 0,
        fill: false,
        tension: 0
      });
    }

    var chart = new window.Chart(ctx, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { top: 10, right: 6 } },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: ink,
            padding: 10,
            cornerRadius: 8,
            displayColors: false,
            titleFont: { family: font, size: 11, weight: "600" },
            titleColor: faint,
            bodyFont: { family: font, size: 13, weight: "700" },
            callbacks: {
              label: function (c) {
                var head = c.datasetIndex === 1 ? "평소가 " : "";
                return head + Number(c.parsed.y).toLocaleString("ko-KR") + "원";
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: border },
            ticks: { color: faint, font: { family: font, size: 11 }, maxRotation: 0, autoSkipPadding: 18 }
          },
          y: {
            grid: { color: border, drawTicks: false },
            border: { display: false },
            ticks: {
              color: faint,
              font: { family: font, size: 11 },
              padding: 8,
              maxTicksLimit: 5,
              callback: function (v) {
                return v >= 10000 ? (v / 10000).toFixed(1) + "만" : Number(v).toLocaleString("ko-KR");
              }
            }
          }
        }
      }
    });
    charts[canvasId] = chart;
    return chart;
  };

  window.bindPriceChartRange = function (root, canvasId, allPoints, baseline, defaultDays) {
    if (!root) return null;
    var days = defaultDays == null ? 90 : Number(defaultDays);
    function paint() {
      var pts = window.filterPricePoints(allPoints, days);
      var sub = root.querySelector(".dd-chart-sub");
      if (sub) sub.textContent = "딜 게시 가격 · 표본 " + pts.length + "건";
      return window.renderPriceChart(canvasId, pts, baseline);
    }
    root.querySelectorAll("[data-range]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var raw = btn.getAttribute("data-range") || "all";
        days = raw === "all" ? 0 : Number(raw) || 0;
        root.querySelectorAll("[data-range]").forEach(function (b) {
          var on = b === btn;
          b.classList.toggle("on", on);
          b.setAttribute("aria-selected", on ? "true" : "false");
        });
        paint();
      });
    });
    return paint();
  };
})();
