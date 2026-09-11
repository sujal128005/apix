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
  // Wrapped so a wide statistical table scrolls on a narrow screen rather than
  // pushing the page sideways.
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead>` +
         `<tbody>${body}</tbody></table></div>`;
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
    ["/", "Home"], ["/routes", "Route Explorer"], ["/lead-time", "Lead Time"],
    ["/quality", "Data Quality"], ["/api/v1/backtest", "Validation"],
    ["/methodology", "Methodology"], ["/operations", "Operations"],
    ["/api/docs", "API"],
  ];

  return `
  <a class="skip-link" href="#main">Skip to main content</a>

  <div class="topbar">
    <span class="gov">भारत सरकार &nbsp;|&nbsp; GOVERNMENT OF INDIA</span>
    <span class="spacer"></span>
    <a href="#main">Skip to Main Content</a>
    <span class="sizer" role="group" aria-label="Text size">
      <button type="button" data-size="0.875" aria-pressed="false" title="Decrease text size">A-</button>
      <button type="button" data-size="1"     aria-pressed="true"  title="Normal text size">A</button>
      <button type="button" data-size="1.15"  aria-pressed="false" title="Increase text size">A+</button>
    </span>
    <a href="/api/docs">Screen Reader Access</a>
  </div>

  <header class="masthead">
    <div class="mark" aria-hidden="true">APIx</div>
    <div class="titles">
      <div class="hindi">सांख्यिकी और कार्यक्रम कार्यान्वयन मंत्रालय</div>
      <div class="english">Ministry of Statistics and Programme Implementation</div>
      <div class="division">Data Informatics &amp; Innovation Division &middot; National Statistical Office</div>
    </div>
    <div class="system">
      <div class="name">Real-time Airfare Price Index</div>
      <div class="ps">Problem Statement 26056 &middot; Smart India Hackathon 2026</div>
    </div>
  </header>

  <nav class="primary" aria-label="Primary">
    ${pages.map(([href, label]) =>
      `<a href="${href}"${href === active ? ' class="active" aria-current="page"' : ""}>${label}</a>`
    ).join("")}
  </nav>`;
}

function govFooter(lastUpdated) {
  /* Multi-column government-portal footer.

     The columns use APIx's own pages and the external references it genuinely
     relies on. No social accounts, no RTI or feedback links, no visitor
     counter - this project has none of those, and inventing them to fill the
     layout would be exactly the impersonation the design must avoid. */
  return `
  <div class="gov-footer">
    <div class="columns">
      <div>
        <h3>Statistics</h3>
        <ul>
          <li><a href="/">Airfare Price Index</a></li>
          <li><a href="/routes">Route Explorer</a></li>
          <li><a href="/lead-time">Lead-time Profile</a></li>
          <li><a href="/api/v1/benchmark">CPI Benchmark Series</a></li>
        </ul>
      </div>
      <div>
        <h3>Methodology</h3>
        <ul>
          <li><a href="/methodology">Index Methodology</a></li>
          <li><a href="/api/v1/backtest">Validation &amp; Limitations</a></li>
          <li><a href="/quality">Data Quality</a></li>
          <li><a href="/api/v1/methodology">Machine-readable Methodology</a></li>
        </ul>
      </div>
      <div>
        <h3>Developers</h3>
        <ul>
          <li><a href="/api/docs">API Documentation</a></li>
          <li><a href="/api/v1/openapi.json">OpenAPI Specification</a></li>
          <li><a href="/operations">System Status</a></li>
          <li><a href="/api/v1/health">Health Check</a></li>
        </ul>
      </div>
      <div>
        <h3>Data Sources</h3>
        <p>Consumer Price Index data is retrieved from the MoSPI open API.</p>
        <ul>
          <li><a href="https://www.mospi.gov.in/" rel="noopener noreferrer"
                 target="_blank">MoSPI (external reference)</a></li>
          <li><a href="https://esankhyiki.mospi.gov.in/" rel="noopener noreferrer"
                 target="_blank">eSankhyiki (external reference)</a></li>
        </ul>
      </div>
    </div>

    <div class="links">
      <a href="/methodology">Methodology</a>
      <a href="/quality">Data Quality</a>
      <a href="/api/v1/backtest">Limitations</a>
      <a href="/operations">System Status</a>
      <a href="/api/docs">API</a>
    </div>

    <div class="attribution">
      <div class="row"><strong>Prototype.</strong> Built for Smart India Hackathon 2026
        against Problem Statement 26056. This is a student project. It is
        <strong>not</strong> an official publication of the Ministry of Statistics and
        Programme Implementation, and not a source of official statistics.</div>
      <div class="row">Consumer Price Index data is retrieved from MoSPI's open API at
        <code>api.mospi.gov.in</code> and remains Government of India official statistics.
        APIx stores it with its source URL and retrieval timestamp.</div>
      <div class="row">Every figure on this site is traceable to an individual fare quote,
        its source and its collection timestamp.</div>
    </div>

    <div class="disclaimer">
      Last updated: ${esc(lastUpdated || "—")} &nbsp;|&nbsp;
      Index methodology follows MoSPI CPI 2024 (Expert Group Report, January 2026)
    </div>
  </div>`;
}

/* Text resizing. A GoI accessibility bar that does not resize anything would be
   worse than not having one, so this is wired to a CSS custom property that the
   whole page scales from. */
function initTextSizer() {
  const stored = sessionStorage.getItem("apix-font-scale");
  if (stored) document.documentElement.style.setProperty("--font-scale", stored);

  document.querySelectorAll(".topbar .sizer button").forEach(button => {
    button.addEventListener("click", () => {
      const scale = button.dataset.size;
      document.documentElement.style.setProperty("--font-scale", scale);
      sessionStorage.setItem("apix-font-scale", scale);
      document.querySelectorAll(".topbar .sizer button").forEach(b =>
        b.setAttribute("aria-pressed", String(b === button)));
    });
  });
}

/* Call once per page, after the chrome is injected. */
function initChrome(active, lastUpdated) {
  document.getElementById("chrome").innerHTML = masthead(active);
  const foot = document.getElementById("gov-footer");
  if (foot) foot.innerHTML = govFooter(lastUpdated);
  initTextSizer();
}
