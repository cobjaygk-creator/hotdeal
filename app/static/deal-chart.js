/* 가격 흐름 차트 — 스타일 규칙을 한곳에 모음.
   호출: window.renderPriceChart("chart", points, baseline)
   points: [{observed_at, price}, ...]                            */
(function () {
  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  window.renderPriceChart = function (canvasId, points, baseline) {
    var el = document.getElementById(canvasId);
    if (!el || !window.Chart || !points || points.length < 2) return null;

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
      var d = new Date(p.observed_at);
      return isNaN(d) ? String(p.observed_at).slice(5, 10) : (d.getMonth() + 1) + "/" + d.getDate();
    });
    var last = prices.length - 1;

    var ctx = el.getContext("2d");
    var grad = ctx.createLinearGradient(0, 0, 0, el.clientHeight || 230);
    grad.addColorStop(0, accent + "24");
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

    return new window.Chart(ctx, {
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
  };
})();
