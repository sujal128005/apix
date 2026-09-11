/* APIx — shared page helpers.

   Deliberately dependency-free. The charts are hand-drawn SVG rather than a
   library: nothing to fetch from a CDN at demo time, and a statistical chart
   needs axis labelling that most libraries make harder rather than easier. */

const money = n => n === null || n === undefined ? "—"
  : "\u20b9" + Number(n).toLocaleString("en-IN", {maximumFractionDigits: 0});
const idx = (n, d = 3) => n === null || n === undefined ? "—" : Number(n).toFixed(d);
const pct = n => n === null || n === undefined ? "—"
  : (n >= 0 ? "+" : "") + Number(n).toFixed(2) + "%";
const esc = s => String(s ?? "—").replace(/[<>&"]/g, c =>
  ({"<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;"}[c]));

async function get(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(path + " → " + r.status);
  return r.json();
}

function provTag(p) {
  const cls = p === "SIMULATED_DEMO" ? "sim" : p === "OFFICIAL_STATISTIC" ? "off" : "live";
  return `<span class="tag ${cls}">${esc(p)}</span>`;
}

function table(cols, rows, rowClass) {
  if (!rows || !rows.length) return '<div class="empty">No records.</div>';
  const head = cols.map(c => `<th${c.num ? ' style="text-align:right"' : ""}>${c.label}</th>`).join("");
  const body = rows.map(r => {
    const cls = rowClass ? rowClass(r) : "";
    const cells = cols.map(c => `<td class="${c.num ? "num" : ""}">${c.render(r)}</td>`).join("");
    return `<tr class="${cls}">${cells}</tr>`;
  }).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

/* A line chart with a real y-axis.

   The y-axis deliberately does NOT start at zero. For an index series anchored
   near 100, a zero-based axis compresses every movement into a flat line and
   hides exactly what the chart exists to show. Bar charts of *levels* do start
   at zero, because there the bar length is the quantity. */
function lineChart(points, {height = 220, valueKey = "y", labelKey = "x", format = v => idx(v, 1)} = {}) {
  if (!points.length) return '<div class="empty">No data.</div>';

  const W = 900, H = height, padL = 58, padR = 16, padT = 14, padB = 34;
  const values = points.map(p => Number(p[valueKey]));
  let lo = Math.min(...values), hi = Math.max(...values);
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = hi - lo;
  lo -= span * 0.12; hi += span * 0.12;

  const x = i => padL + (i / Math.max(points.length - 1, 1)) * (W - padL - padR);
  const y = v => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);

  const ticks = 5;
  let grid = "", path = "", dots = "";
  for (let t = 0; t <= ticks; t++) {
    const v = lo + (hi - lo) * (t / ticks), yy = y(v);
    grid += `<line class="grid-line" x1="${padL}" y1="${yy}" x2="${W - padR}" y2="${yy}"/>`;
    grid += `<text x="${padL - 8}" y="${yy + 4}" text-anchor="end">${format(v)}</text>`;
  }
  points.forEach((p, i) => {
    const xx = x(i), yy = y(Number(p[valueKey]));
    path += (i ? " L" : "M") + xx + " " + yy;
    if (points.length <= 40) dots += `<circle class="point" cx="${xx}" cy="${yy}" r="2.5"/>`;
  });

  const every = Math.ceil(points.length / 8);
  const labels = points.map((p, i) => i % every === 0 || i === points.length - 1
    ? `<text x="${x(i)}" y="${H - 12}" text-anchor="middle">${esc(p[labelKey])}</text>` : "").join("");

  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img">
    ${grid}
    <line class="axis" x1="${padL}" y1="${padT}" x2="${padL}" y2="${H - padB}"/>
    <line class="axis" x1="${padL}" y1="${H - padB}" x2="${W - padR}" y2="${H - padB}"/>
    <path class="series" d="${path}"/>${dots}${labels}
  </svg></div>`;
}

/* A bar chart of levels. Starts at zero, because bar length is the quantity. */
function barChart(bars, {height = 240, valueKey = "y", labelKey = "x", format = money, highlight = () => false} = {}) {
  if (!bars.length) return '<div class="empty">No data.</div>';

  const W = 900, H = height, padL = 58, padR = 16, padT = 20, padB = 44;
  const hi = Math.max(...bars.map(b => Number(b[valueKey]))) * 1.12;
  const bandWidth = (W - padL - padR) / bars.length;
  const barWidth = Math.min(bandWidth * 0.55, 70);
  const y = v => padT + (1 - v / hi) * (H - padT - padB);

  let grid = "";
  for (let t = 0; t <= 4; t++) {
    const v = hi * (t / 4), yy = y(v);
    grid += `<line class="grid-line" x1="${padL}" y1="${yy}" x2="${W - padR}" y2="${yy}"/>`;
    grid += `<text x="${padL - 8}" y="${yy + 4}" text-anchor="end">${format(v)}</text>`;
  }

  const rects = bars.map((b, i) => {
    const v = Number(b[valueKey]);
    const cx = padL + bandWidth * i + bandWidth / 2;
    const yy = y(v);
    return `<rect class="bar${highlight(b) ? " cpi" : ""}" x="${cx - barWidth / 2}" y="${yy}"
              width="${barWidth}" height="${H - padB - yy}"/>
            <text class="value" x="${cx}" y="${yy - 6}" text-anchor="middle">${format(v)}</text>
            <text x="${cx}" y="${H - 26}" text-anchor="middle">${esc(b[labelKey])}</text>
            ${b.sub ? `<text x="${cx}" y="${H - 12}" text-anchor="middle">${esc(b.sub)}</text>` : ""}`;
  }).join("");

  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img">
    ${grid}
    <line class="axis" x1="${padL}" y1="${padT}" x2="${padL}" y2="${H - padB}"/>
    <line class="axis" x1="${padL}" y1="${H - padB}" x2="${W - padR}" y2="${H - padB}"/>
    ${rects}
  </svg></div>`;
}

function masthead(active) {
  const pages = [
    ["/", "Dashboard"], ["/routes", "Routes"], ["/lead-time", "Lead time"],
    ["/quality", "Data quality"], ["/api/v1/sources", "Sources"],
    ["/api/v1/backtest", "Validation"], ["/methodology", "Methodology"],
    ["/operations", "Operations"], ["/api/docs", "API"],
  ];
  return `<header class="masthead">
    <div class="org">Ministry of Statistics and Programme Implementation &middot;
      Data Informatics &amp; Innovation Division</div>
    <h1>APIx &mdash; Real-time Airfare Price Index</h1>
    <div class="sub">Daily airfare index for India, computed with the CPI 2024
      methodology &middot; Problem Statement 26056</div>
  </header>
  <nav>${pages.map(([href, label]) =>
    `<a href="${href}"${href === active ? ' class="active"' : ""}>${label}</a>`).join("")}</nav>`;
}
