/* news2048 — 靜態新聞儀表板
 *
 * 架構：
 *   data/dashboard.json  →  一次 fetch  →  依 module.type 派給對應 renderer
 *   新增模組不需要動這支檔案，除非要新增「型別」。
 */

(function () {
  "use strict";

  // ---------------------------------------------------------------- helpers

  /** 建立 DOM 元素。h('div', {class:'x'}, '文字', h('b', {}, '粗')) */
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  function svg(tag, attrs) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    return el;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /** 極簡行內標記：先跳脫再套用，因此可安全放進 innerHTML。 */
  function inline(s) {
    return escapeHtml(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
               '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }

  function fmt(n) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    const opts = Number.isInteger(n)
      ? { maximumFractionDigits: 0 }
      : { minimumFractionDigits: 1, maximumFractionDigits: 2 };
    return n.toLocaleString("zh-TW", opts);
  }

  function signed(n, digits) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    const sign = n > 0 ? "+" : n < 0 ? "−" : "±";
    const abs = Math.abs(n);
    return sign + abs.toLocaleString("zh-TW", {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
  }

  // ------------------------------------------------------- 方向與語意配色
  //
  // 這裡是整個平台唯一決定「漲跌用什麼顏色」的地方。
  // 模組自己宣告 scheme / polarity，前端只查表，不預設任何文化慣例。

  function direction(diff) {
    if (!isFinite(diff) || Math.abs(diff) < 1e-9) return "flat";
    return diff > 0 ? "up" : "down";
  }

  const SCHEMES = {
    "market-tw": { up: "dir-up", down: "dir-down" },      // 台灣股市：紅漲綠跌
    "market-us": { up: "dir-good", down: "dir-bad" },     // 歐美慣例：綠漲紅跌
    thermal:     { up: "dir-hot", down: "dir-cold" },     // 溫度：暖／冷
    plain:       { up: "dir-neutral", down: "dir-neutral" },
  };

  function dirClass(dir, scheme, polarity) {
    if (dir === "flat") return "dir-flat";
    if (scheme === "semantic") {
      const badIsUp = polarity !== "higher-is-good";
      if (dir === "up") return badIsUp ? "dir-bad" : "dir-good";
      return badIsUp ? "dir-good" : "dir-bad";
    }
    return (SCHEMES[scheme] || SCHEMES.plain)[dir];
  }

  const ARROW = { up: "▲", down: "▼", flat: "—" };
  const COMPARISON_MARK = { up: "△", down: "▽", flat: "—" };
  const EPIDEMIC_MODULE_IDS = new Set(["cdc-covid-weekly", "cdc-flu-severe-weekly"]);
  const LOTTERY_MODULE_ID = "lottery-jackpots";
  const AUTO_UPDATED_MODULE_IDS = new Set([
    "weather-taipei",
    "twse-index",
    "cdc-covid-weekly",
    "cdc-flu-severe-weekly",
    "lottery-jackpots",
  ]);
  const ANALYSIS_FILES = {
    "fu-kunchi-absence": "analysis/2026-08-12-fu-kunchi-agenda-setting.md",
    "universal-cash-media-framing": "analysis/2026-08-18-universal-cash-media-framing.md",
  };

  /** 小數位數：跟著原始資料的精度走，避免 44.67 的差被截成 +22.3。 */
  function decimalsOf(n) {
    if (typeof n !== "number" || Number.isInteger(n)) return 0;
    const i = String(n).indexOf(".");
    return i < 0 ? 0 : Math.min(String(n).length - i - 1, 2);
  }

  /** 今天的變化，相對於近期日常波動算不算大？（回答「漲多了還是跌多了」）
   *
   *  只有當比較基準就是序列的前一點時，這個比值才有意義：series 的逐期落差
   *  是「一期對一期」的尺度，若模組拿「前三週平均」當基準，兩者不可比，寧可不顯示。
   */
  function magnitudeHint(series, diff, baselineIsPrevPoint) {
    if (!baselineIsPrevPoint) return null;
    if (!Array.isArray(series) || series.length < 4) return null;
    const steps = [];
    for (let i = 1; i < series.length - 1; i++) {
      steps.push(Math.abs(series[i] - series[i - 1]));
    }
    const avg = steps.reduce((a, b) => a + b, 0) / steps.length;
    if (!avg) return null;
    const ratio = Math.abs(diff) / avg;
    if (ratio >= 1.5) return `幅度是近期平均波動的 ${ratio.toFixed(1)} 倍`;
    if (ratio <= 0.5) return `幅度只有近期平均波動的 ${ratio.toFixed(1)} 倍`;
    return null;
  }

  function sparkline(series, cls) {
    const W = 200, H = 30, PAD = 3;
    const min = Math.min(...series), max = Math.max(...series);
    const span = max - min || 1;
    const x = (i) => (i / (series.length - 1)) * W;
    const y = (v) => H - PAD - ((v - min) / span) * (H - PAD * 2);

    const node = svg("svg", {
      class: "metric-spark " + cls, width: "100%", height: H,
      viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none",
      role: "img", "aria-label": "近期趨勢",
    });
    node.appendChild(svg("polyline", {
      points: series.map((v, i) => `${x(i)},${y(v)}`).join(" "),
      fill: "none", stroke: "currentColor", "stroke-width": "1.5",
      "vector-effect": "non-scaling-stroke",
    }));
    // 末端垂直短線標示最新值（在 preserveAspectRatio=none 下不會被拉扁）
    const last = series.length - 1;
    node.appendChild(svg("line", {
      x1: x(last), x2: x(last), y1: y(series[last]) - 4, y2: y(series[last]) + 4,
      stroke: "currentColor", "stroke-width": "2",
      "vector-effect": "non-scaling-stroke",
    }));
    return node;
  }

  // ------------------------------------------------------------- renderers

  const renderers = {};

  renderers.delta = function (d) {
    const box = h("div", {});
    for (const m of d.metrics || []) {
      const diff = m.current - m.previous;
      const dir = direction(diff);
      const cls = dirClass(dir, d.scheme, d.polarity);
      const pct = m.previous ? (diff / Math.abs(m.previous)) * 100 : NaN;
      const decimals = Math.max(decimalsOf(m.current), decimalsOf(m.previous));

      const primary = m.mode === "percent" ? signed(pct, 2) + "%" : signed(diff, decimals);
      const secondary = m.mode === "percent"
        ? `(${signed(diff, decimals)}${d.unit || ""})`
        : (isFinite(pct) ? `(${signed(pct, 1)}%)` : "");

      // 比較基準是不是就是序列的前一點？（例如「前三週平均」就不是）
      const n = Array.isArray(m.series) ? m.series.length : 0;
      const prevPoint = n >= 2 ? m.series[n - 2] : null;
      const baselineIsPrevPoint = prevPoint !== null &&
        Math.abs(prevPoint - m.previous) <= Math.abs(m.previous) * 1e-6 + 1e-9;

      const hint = magnitudeHint(m.series, diff, baselineIsPrevPoint);

      // 基準不是前一期時，另外補上逐期變化，讓讀者同時看到兩種讀法
      let stepLine = null;
      if (n >= 2 && !baselineIsPrevPoint) {
        const sDiff = m.current - prevPoint;
        const sPct = prevPoint ? (sDiff / Math.abs(prevPoint)) * 100 : NaN;
        const sCls = dirClass(direction(sDiff), d.scheme, d.polarity);
        // 逐期變化的精度跟著序列本身，不要被基準值（如 44.67）的小數位污染
        const sDec = Math.max(decimalsOf(m.current), decimalsOf(prevPoint));
        stepLine = h("div", { class: "metric-step" },
          `較${m.period_label || "前一期"} ${fmt(prevPoint)}`,
          h("span", { class: sCls },
            ` ${ARROW[direction(sDiff)]} ${signed(sDiff, sDec)}`
            + (isFinite(sPct) ? `（${signed(sPct, 1)}%）` : "")));
      }

      box.appendChild(h("div", { class: "metric" },
        h("div", { class: "metric-label" }, m.label),
        h("div", { class: "metric-main" },
          h("div", { class: "metric-value" },
            fmt(m.current),
            d.unit ? h("span", { class: "metric-unit" }, d.unit) : null),
          h("div", { class: "metric-delta " + cls },
            ARROW[dir] + " " + primary + " ",
            secondary ? h("span", { class: "secondary" }, secondary) : null),
          h("div", { class: "metric-prev" },
            `${m.previous_label || "前期"} ${fmt(m.previous)}`)),
        stepLine,
        hint ? h("div", { class: "metric-hint " + cls }, hint) : null,
        n > 1 ? sparkline(m.series, cls) : null));
    }
    if (Array.isArray(d.context) && d.context.length) {
      const context = h("div", { class: "metric-context" });
      for (const line of d.context) context.appendChild(h("p", {}, line));
      box.appendChild(context);
    }
    return box;
  };

  renderers.compare = function (d) {
    const box = h("div", {});
    if (d.question) box.appendChild(h("p", { class: "q" }, d.question));

    const subjects = d.subjects || [];
    const table = h("table", { class: "cmp" });

    const headRow = h("tr", {}, h("th", {}, ""));
    for (const s of subjects) {
      headRow.appendChild(h("th", {},
        h("span", { class: "subject-name" },
          h("span", { class: "tone tone-" + (s.tone || "neutral"),
                      title: "立場標記：" + (s.tone || "neutral") }),
          s.url
            ? h("a", { href: s.url, target: "_blank", rel: "noopener" }, s.name)
            : s.name)));
    }
    table.appendChild(h("thead", {}, headRow));

    const body = h("tbody", {});
    for (const ax of d.axes || []) {
      const row = h("tr", {}, h("th", {}, ax.label));
      for (const s of subjects) {
        row.appendChild(h("td", { html: inline((s.fields || {})[ax.key] || "—") }));
      }
      body.appendChild(row);
    }
    table.appendChild(body);
    box.appendChild(h("div", { class: "cmp-scroll" }, table));

    if (d.takeaway) {
      box.appendChild(h("div", { class: "takeaway", html: "<b>觀察：</b>" + inline(d.takeaway) }));
    }
    return box;
  };

  renderers.list = function (d) {
    const box = h("div", {});
    if (d.question) box.appendChild(h("p", { class: "q" }, d.question));

    const cols = h("div", { class: "cols" });
    for (const c of d.columns || []) {
      const ol = h("ol", {});
      for (const it of c.items || []) {
        ol.appendChild(h("li", {},
          h("span", { html: inline(it.text || "") }),
          it.meta ? h("span", { class: "item-meta" }, it.meta) : null));
      }
      cols.appendChild(h("div", { class: "col" },
        h("div", { class: "col-head" },
          c.url ? h("a", { href: c.url, target: "_blank", rel: "noopener" }, c.name) : c.name),
        ol));
    }
    box.appendChild(cols);

    if (d.takeaway) {
      box.appendChild(h("div", { class: "takeaway", html: "<b>觀察：</b>" + inline(d.takeaway) }));
    }
    return box;
  };

  renderers.note = function (d) {
    const box = h("div", { class: "note-body" });
    for (const p of d.body || []) box.appendChild(h("p", { html: inline(p) }));
    if (d.image) {
      box.appendChild(h("img", { src: d.image, alt: d.image_caption || "" }));
      if (d.image_caption) box.appendChild(h("p", { class: "note-caption" }, d.image_caption));
    }
    return box;
  };

  function parseLocalDate(dateText) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateText || "");
    if (!match) return null;
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }

  function lotteryDrawLabel(dateText, now = new Date()) {
    const drawDate = parseLocalDate(dateText);
    if (!drawDate) return { text: "開獎日待確認", today: false };

    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const dayMs = 24 * 60 * 60 * 1000;
    const daysUntil = Math.round((drawDate - today) / dayMs);
    const dateLabel = `${drawDate.getMonth() + 1}/${drawDate.getDate()}`;

    if (daysUntil === 0) return { text: `今日開獎${dateLabel}`, today: true };
    if (daysUntil === 1) return { text: `明日開獎${dateLabel}`, today: false };
    if (daysUntil > 1) return { text: `下次開獎${dateLabel}`, today: false };
    return { text: `資料待更新（原定${dateLabel}開獎）`, today: false };
  }

  function lotteryAmount(amount, decimals) {
    if (typeof amount !== "number" || !isFinite(amount)) return "—";
    const digits = Number.isInteger(decimals) ? decimals : 1;
    return (amount / 100000000).toLocaleString("zh-TW", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }) + "億";
  }

  function currentDateLabel(now = new Date()) {
    const parts = new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei",
      month: "numeric",
      day: "numeric",
      weekday: "long",
    }).formatToParts(now);
    const value = (type) => parts.find((part) => part.type === type)?.value || "";
    return `${value("month")}月${value("day")}日 ${value("weekday")}`;
  }

  renderers.lottery = function (d) {
    const box = h("div", { class: "lottery-list" });
    for (const game of d.games || []) {
      const draw = lotteryDrawLabel(game.next_draw_date);
      box.appendChild(h("div", { class: "lottery-row" },
        h("p", { class: "lottery-summary" },
          h("span", { class: "lottery-name" }, game.name || "彩券"),
          "獎金累計",
          h("strong", { class: "lottery-amount" },
            lotteryAmount(game.amount, game.amount_decimals))),
        h("p", {
          class: "lottery-draw" + (draw.today ? " lottery-draw-today" : ""),
        }, `（${draw.text}）`)));
    }
    return box;
  };

  // ----------------------------------------------------------- card 外殼

  function markdownDocument(text) {
    const box = h("div", { class: "analysis-document" });
    const lines = text.replace(/\r/g, "").split("\n");
    let i = 0;

    const cells = (line) => line.trim().replace(/^\||\|$/g, "")
      .split("|").map((cell) => cell.trim());

    while (i < lines.length) {
      const line = lines[i].trim();
      if (!line) { i++; continue; }
      if (/^-{3,}$/.test(line)) { box.appendChild(h("hr", {})); i++; continue; }

      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        box.appendChild(h(heading[1].length === 1 ? "h3" : "h4", { html: inline(heading[2]) }));
        i++; continue;
      }

      if (line.startsWith("|")) {
        const rows = [];
        while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
        const table = h("table", { class: "analysis-table" });
        const hasHeader = rows.length > 1 && rows[1].every((cell) => /^:?-{3,}:?$/.test(cell));
        const dataRows = hasHeader ? rows.slice(2) : rows;
        if (hasHeader) {
          const headerCells = rows[0].map((cell) => h("th", { html: inline(cell) }));
          table.appendChild(h("thead", {}, h("tr", {}, headerCells)));
        }
        const dataNodes = dataRows.map((row) => {
          const rowCells = row.map((cell) => h("td", { html: inline(cell) }));
          return h("tr", {}, rowCells);
        });
        table.appendChild(h("tbody", {}, dataNodes));
        box.appendChild(h("div", { class: "analysis-table-scroll" }, table));
        continue;
      }

      if (/^-\s+/.test(line)) {
        const list = h("ul", {});
        while (i < lines.length && /^-\s+/.test(lines[i].trim())) {
          list.appendChild(h("li", { html: inline(lines[i].trim().replace(/^-\s+/, "")) }));
          i++;
        }
        box.appendChild(list);
        continue;
      }

      box.appendChild(h("p", { html: inline(line) }));
      i++;
    }
    return box;
  }

  function newsSourceDocument(manifest) {
    const box = h("div", { class: "news-source-document" });
    const articles = Array.isArray(manifest.articles) ? manifest.articles : [];
    const grouped = new Map();

    for (const article of articles) {
      const period = article.period || "未分期";
      const outlet = article.outlet || "未標示媒體";
      if (!grouped.has(period)) grouped.set(period, new Map());
      const outlets = grouped.get(period);
      if (!outlets.has(outlet)) outlets.set(outlet, []);
      outlets.get(outlet).push(article);
    }

    if (manifest.method) box.appendChild(h("p", {}, manifest.method));
    for (const [period, outlets] of grouped) {
      const periodCount = [...outlets.values()].reduce((sum, rows) => sum + rows.length, 0);
      const periodDetails = h("details", {},
        h("summary", {}, `${period}（${periodCount} 則）`));

      for (const [outlet, rows] of outlets) {
        const outletDetails = h("details", {},
          h("summary", {}, `${outlet}（${rows.length} 則）`));
        const list = h("ul", {});
        for (const article of rows) {
          const label = article.date ? `${article.date}｜${article.title}` : article.title;
          list.appendChild(h("li", {},
            article.url
              ? h("a", { href: article.url, target: "_blank", rel: "noopener" }, label)
              : label,
            article.url_kind ? `（${article.url_kind}）` : null));
        }
        outletDetails.appendChild(list);
        periodDetails.appendChild(outletDetails);
      }
      box.appendChild(periodDetails);
    }
    return box;
  }

  function makeInteractive(article, mod) {
    article.classList.add("card-openable");
    article.tabIndex = 0;
    article.setAttribute("role", "button");
    article.setAttribute("aria-label", `開啟${mod.title}詳細閱讀`);
    article.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      openDetail(mod);
    });
    article.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDetail(mod);
      }
    });
    return article;
  }

  /** 疫情卡片的管理檢視：不另存資料，直接從既有 delta schema 濃縮摘要。 */
  function compactEpidemicCard(mod) {
    const d = mod.data || {};
    const m = (d.metrics || [])[0];
    if (!m) return card(mod);

    const diff = m.current - m.previous;
    const dir = direction(diff);
    const cls = dirClass(dir, d.scheme, d.polarity);
    const pct = m.previous ? (diff / Math.abs(m.previous)) * 100 : NaN;
    const n = Array.isArray(m.series) ? m.series.length : 0;
    const prevPoint = n >= 2 ? m.series[n - 2] : null;
    const stepDiff = prevPoint === null ? NaN : m.current - prevPoint;
    const stepDir = direction(stepDiff);
    const stepPct = prevPoint ? (stepDiff / Math.abs(prevPoint)) * 100 : NaN;
    const stepDecimals = Math.max(decimalsOf(m.current), decimalsOf(prevPoint));
    const unitLabel = m.label && m.label.includes("病例") ? "病例" : (d.unit || "");

    const summary = h("p", { class: "compact-epidemic-summary" },
      `上週新增 ${fmt(m.current)} ${unitLabel}，較${m.previous_label || "前期"} `,
      h("span", { class: cls },
        `${COMPARISON_MARK[dir]}${fmt(Math.abs(diff))}`
        + (isFinite(pct) ? `（${signed(pct, 1)}%）` : "")),
      prevPoint === null ? null : [
        `，較${m.period_label || "前一期"} `,
        h("span", { class: dirClass(stepDir, d.scheme, d.polarity) },
          `${ARROW[stepDir]} ${signed(stepDiff, stepDecimals)}`
          + (isFinite(stepPct) ? `（${signed(stepPct, 1)}%）` : "")),
      ]);

    return makeInteractive(h("article", { class: "card compact-epidemic-card", "data-id": mod.id },
      h("div", { class: "compact-epidemic-body" },
        h("h2", { class: "card-title" }, mod.title),
        summary)), mod);
  }

  /** 樂透卡片的主畫面精簡檢視；完整資料仍可點開詳細閱讀。 */
  function compactLotteryCard(mod) {
    const body = h("div", { class: "compact-lottery-body" });
    for (const game of (mod.data || {}).games || []) {
      const draw = lotteryDrawLabel(game.next_draw_date);
      body.appendChild(h("p", { class: "compact-lottery-summary" },
        `${game.name || "彩券"}獎金累計`,
        h("strong", { class: "compact-lottery-amount" },
          lotteryAmount(game.amount, game.amount_decimals)),
        "（",
        h("span", {
          class: draw.today ? "compact-lottery-draw-today" : "compact-lottery-draw",
        }, draw.text),
        "）"));
    }
    return makeInteractive(h("article", {
      class: "card compact-lottery-card", "data-id": mod.id,
    }, body), mod);
  }

  function plainSummaryText(text, maxLength = 120) {
    const plain = String(text || "")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/\*\*|`/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (plain.length <= maxLength) return plain;
    return plain.slice(0, maxLength).trimEnd() + "…";
  }

  function compactDeltaSummary(mod) {
    const d = mod.data || {};
    const box = h("div", { class: "compact-card-lines" });
    for (const metric of d.metrics || []) {
      const diff = metric.current - metric.previous;
      const dir = direction(diff);
      const pct = metric.previous ? (diff / Math.abs(metric.previous)) * 100 : NaN;
      const decimals = Math.max(decimalsOf(metric.current), decimalsOf(metric.previous));
      const change = metric.mode === "percent"
        ? `${signed(pct, 2)}%（${signed(diff, decimals)}）`
        : `${signed(diff, decimals)}${isFinite(pct) ? `（${signed(pct, 1)}%）` : ""}`;
      box.appendChild(h("p", { class: "compact-card-summary" },
        `${metric.label || "指標"} `,
        h("strong", { class: "compact-card-value" }, `${fmt(metric.current)}${d.unit || ""}`),
        `，較${metric.previous_label || "前期"} `,
        h("span", { class: dirClass(dir, d.scheme, d.polarity) }, `${ARROW[dir]} ${change}`)));
    }
    for (const line of Array.isArray(d.context) ? d.context : []) {
      box.appendChild(h("p", { class: "compact-card-summary" }, line));
    }
    return box;
  }

  function compactGenericBody(mod) {
    const d = mod.data || {};
    if (mod.type === "delta") return compactDeltaSummary(mod);

    let text = mod.subtitle || "";
    if (mod.type === "compare") text = d.takeaway || d.question || text;
    if (mod.type === "list") text = d.question || d.takeaway || text;
    if (mod.type === "note") text = (d.body || [])[0] || text;

    return h("p", { class: "compact-card-summary" }, plainSummaryText(text));
  }

  /** 所有一般模組的主畫面摘要；完整 renderer 僅在詳細閱讀或關閉簡要模式時使用。 */
  function compactCard(mod) {
    if (EPIDEMIC_MODULE_IDS.has(mod.id)) return compactEpidemicCard(mod);
    if (mod.id === LOTTERY_MODULE_ID) return compactLotteryCard(mod);

    return makeInteractive(h("article", {
      class: "card compact-card", "data-id": mod.id,
    }, h("div", { class: "compact-card-body" },
      h("h2", { class: "card-title" }, mod.title),
      compactGenericBody(mod))), mod);
  }

  function card(mod, interactive = true, context = "grid") {
    const render = renderers[mod.type];
    const body = render
      ? render(mod.data || {})
      : h("p", { class: "error" }, `未知的模組型別：${mod.type}`);

    const reviewed = mod.review && mod.review.reviewed;
    const badges = h("div", { class: "card-badges" },
      mod.sample ? h("span", { class: "badge sample" }, "範例資料") : null,
      reviewed
        ? h("span", { class: "badge reviewed", title: `${mod.review.by} 於 ${mod.review.at} 核閱` }, "已人工核閱")
        : (mod.sample ? null : h("span", { class: "badge pending" }, "待核閱")),
      (mod.tags || []).map((t) => h("span", { class: "badge tag" }, t)),
      h("span", { class: "badge date" }, mod.updated));

    const src = mod.source && mod.source.name
      ? (mod.source.url
          ? h("a", { href: mod.source.url, target: "_blank", rel: "noopener" }, "來源：" + mod.source.name)
          : h("span", {}, "來源：" + mod.source.name))
      : null;

    const article = h("article", {
      class: context === "detail" ? "card detail-reading-card" : "card",
      "data-size": mod.size || "m",
      "data-id": context === "grid" ? mod.id : null,
      "data-detail-id": context === "detail" ? mod.id : null,
    },
      h("div", { class: "card-head" },
        h("div", { class: "card-titles" },
          h("h2", { class: "card-title" }, mod.title),
          mod.subtitle ? h("span", { class: "card-subtitle" }, mod.subtitle) : null),
        badges),
      h("div", { class: "card-body" }, body),
      (mod.note || src || mod.fetched_at)
        ? h("div", { class: "card-foot" },
            mod.note ? h("p", { class: "card-note" }, mod.note) : null,
            h("span", { class: "foot-right" },
              mod.fetched_at ? h("span", { class: "fetched" }, "抓取於 " + mod.fetched_at) : null,
              src))
        : null);
    return interactive ? makeInteractive(article, mod) : article;
  }

  // --------------------------------------------------------------- 主流程

  const state = {
    modules: [], tag: null, hideSample: false,
    compactAll: true,
  };
  const grid = document.getElementById("grid");
  const emptyMsg = document.getElementById("empty");
  const detailModal = document.getElementById("detail-modal");
  const detailContent = document.getElementById("detail-modal-content");
  const detailTitle = document.getElementById("detail-modal-title");
  let lastTrigger = null;

  function closeDetail() {
    detailModal.hidden = true;
    detailContent.replaceChildren();
    if (lastTrigger) lastTrigger.focus();
    lastTrigger = null;
  }

  function openDetail(mod) {
    lastTrigger = document.activeElement;
    detailTitle.textContent = mod.title;
    detailContent.replaceChildren(card(mod, false, "detail"));
    detailModal.hidden = false;
    detailModal.querySelector(".detail-modal-close").focus();

    const analysisFile = ANALYSIS_FILES[mod.id];
    if (analysisFile) {
      const analysis = h("section", { class: "analysis-reading" },
        h("h3", {}, "完整分析底稿"),
        h("p", { class: "analysis-status" }, "載入分析底稿…"));
      detailContent.appendChild(analysis);
      fetch(analysisFile, { cache: "no-cache" })
        .then((response) => {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.text();
        })
        .then((text) => analysis.replaceChildren(h("h3", {}, "完整分析底稿"), markdownDocument(text)))
        .catch(() => analysis.replaceChildren(
          h("h3", {}, "完整分析底稿"),
          h("p", { class: "analysis-status" }, "分析底稿暫時無法載入。")));
    }

    const sourceManifest = mod.source_manifest;
    if (sourceManifest && sourceManifest.path) {
      const sources = h("section", { class: "analysis-reading" },
        h("h3", {}, `逐則新聞來源（${sourceManifest.count || "—"} 則）`),
        h("p", { class: "analysis-status" }, "載入逐則鏈結…"));
      detailContent.appendChild(sources);
      fetch(sourceManifest.path, { cache: "no-cache" })
        .then((response) => {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        })
        .then((manifest) => sources.replaceChildren(
          h("h3", {}, `逐則新聞來源（${manifest.count || 0} 則）`),
          newsSourceDocument(manifest)))
        .catch(() => sources.replaceChildren(
          h("h3", {}, "逐則新聞來源"),
          h("p", { class: "analysis-status" }, "逐則新聞鏈結暫時無法載入。")));
    }
  }

  function visible() {
    return state.modules.filter((m) => {
      if (state.tag && !(m.tags || []).includes(state.tag)) return false;
      if (state.hideSample && m.sample) return false;
      return true;
    });
  }

  function channelLabel(title, count, className) {
    return h("div", { class: `channel-label ${className}` },
      h("span", { class: "channel-title" }, title),
      h("span", { class: "channel-count" }, `${count} 個模組`));
  }

  function dashboardColumn(className, label) {
    return h("section", {
      class: `dashboard-column ${className}`,
      "aria-label": label,
    });
  }

  function renderModule(mod) {
    return state.compactAll ? compactCard(mod) : card(mod);
  }

  function appendToShorterColumn(node, columns) {
    const target = columns.reduce((shorter, column) =>
      column.getBoundingClientRect().height < shorter.getBoundingClientRect().height
        ? column
        : shorter);
    target.appendChild(node);
  }

  function paint() {
    // 顯示模式或篩選條件改變時，舊的 detail view 不應與新 renderer 並存。
    if (!detailModal.hidden) closeDetail();

    const list = visible();
    const renderedIds = new Set();
    const liveModules = [];
    const otherModules = [];

    for (const mod of list) {
      // dashboard.json 理論上不會重複 id；前端仍 fail closed，確保一個 id 只渲染一次。
      if (renderedIds.has(mod.id)) continue;
      renderedIds.add(mod.id);

      (AUTO_UPDATED_MODULE_IDS.has(mod.id) ? liveModules : otherModules).push(mod);
    }

    if (!list.length) {
      grid.replaceChildren();
      emptyMsg.hidden = false;
      return;
    }

    const liveColumn = dashboardColumn("dashboard-column-live", "即時更新資料");
    const otherColumnA = dashboardColumn("dashboard-column-other-a", "其他資料頻道一");
    const otherColumnB = dashboardColumn("dashboard-column-other-b", "其他資料頻道二");
    grid.replaceChildren(
      channelLabel("即時更新", liveModules.length, "channel-label-live"),
      channelLabel("其他頻道", otherModules.length, "channel-label-other"),
      liveColumn,
      otherColumnA,
      otherColumnB,
    );

    for (const mod of liveModules) liveColumn.appendChild(renderModule(mod));
    for (const mod of otherModules) {
      appendToShorterColumn(renderModule(mod), [otherColumnA, otherColumnB]);
    }

    emptyMsg.hidden = list.length > 0;
  }

  function buildFilters() {
    const tags = [...new Set(state.modules.flatMap((m) => m.tags || []))].sort();
    const bar = document.getElementById("tag-filters");
    const mk = (label, value) =>
      h("button", {
        class: "chip", type: "button",
        "aria-pressed": String(state.tag === value),
        onclick: () => {
          state.tag = value;
          bar.querySelectorAll(".chip").forEach((b) =>
            b.setAttribute("aria-pressed", String(b.dataset.value === (value || ""))));
          paint();
        },
        "data-value": value || "",
      }, label);

    bar.replaceChildren(mk("全部", null), ...tags.map((t) => mk(t, t)));
  }

  function showError(title, detail) {
    grid.replaceChildren(h("div", { class: "error", style: "grid-column: 1 / -1" },
      h("b", {}, title), h("p", {}, detail)));
  }

  fetch("data/dashboard.json", { cache: "no-cache" })
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((payload) => {
      state.modules = payload.modules || [];
      document.getElementById("build-time").textContent = "建置於 " + (payload.generated_at || "—");
      document.getElementById("build-count").textContent = state.modules.length + " 個模組";
      buildFilters();
      paint();
    })
    .catch((err) => {
      if (location.protocol === "file:") {
        showError("需要以 HTTP 開啟",
          "瀏覽器不允許 file:// 讀取 JSON。請在專案目錄執行 python3 -m http.server 8000，" +
          "再開啟 http://localhost:8000/");
      } else {
        showError("載入 data/dashboard.json 失敗",
          err.message + "。請先執行 python3 tools/build.py 產生資料檔。");
      }
    });

  document.getElementById("current-date").textContent = currentDateLabel();

  document.getElementById("hide-sample").addEventListener("change", (e) => {
    state.hideSample = e.target.checked;
    paint();
  });

  document.getElementById("compact-all").addEventListener("change", (e) => {
    state.compactAll = e.target.checked;
    paint();
  });

  detailModal.addEventListener("click", (event) => {
    if (event.target.matches("[data-close-modal]")) closeDetail();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !detailModal.hidden) closeDetail();
  });
})();
