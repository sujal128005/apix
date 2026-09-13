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
    ["/", "Home"], ["/routes", "Route Explorer"], ["/heatmap", "Heatmap"],
    ["/lead-time", "Lead Time"],
    ["/scenario", "Scenarios"], ["/quality", "Data Quality"], ["/api/v1/backtest", "Validation"],
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


/* --- Route network map ---------------------------------------------------

   Cities positioned by their real coordinates; corridors drawn as arcs between
   them. **No national outline is drawn**, and that is deliberate rather than a
   shortcut.

   Depicting India's boundaries is legally sensitive: Government of India
   requires maps to follow the Survey of India's official depiction, including
   Jammu & Kashmir and Ladakh. Open datasets - Natural Earth, OpenStreetMap
   extracts - generally do not match that depiction, and a hand-drawn outline
   matches nothing at all. On a page styled to resemble a ministry portal, an
   incorrect boundary would be a serious error, and it would be entirely
   gratuitous: a fare index has no need to assert where a border runs.

   A graticule gives the same orientation an outline would, without making any
   claim. If an official Survey of India basemap is licensed for this project
   later, it drops in here and nothing else changes.

   No tile server either: a government statistics page should not route its
   readers' requests to a third party, and a demo should not fail because a tile
   host is slow. */

const MAP_BOUNDS = {lonMin: 67.0, lonMax: 98.5, latMin: 6.5, latMax: 37.5};

/* India outline, following the official Government of India depiction: Jammu &
   Kashmir and Ladakh shown in full as Indian territory.

   A **schematic locator**, not a survey product. It is traced at roughly 130
   points, which is enough to orient a reader and nowhere near enough to be a
   cartographic authority - and it is not offered as one. Depicting India's
   boundaries carries legal requirements, so the depiction follows the official
   position; if the ministry licenses a Survey of India basemap it replaces this
   path and nothing else on the page changes.

   Coordinates are (longitude, latitude) and are projected by the same function
   as the city nodes, so outline and airports cannot drift apart. */
const INDIA_PATH = "M 76.8,36.5 L 77.8,35.9 L 78.3,35.5 L 78.9,34.9 L 79.5,34.5 L 79.2,33.5 L 78.8,33.0 L 79.2,32.6 L 78.7,32.2 L 78.4,31.8 L 79.1,31.4 L 79.9,30.9 L 80.3,30.3 L 80.9,29.9 L 81.0,30.2 L 81.9,30.3 L 82.7,30.1 L 83.6,29.5 L 84.6,29.3 L 85.5,28.7 L 86.4,28.1 L 87.2,27.8 L 88.1,27.9 L 88.2,27.3 L 88.8,27.4 L 89.6,28.1 L 90.4,28.1 L 91.6,27.8 L 92.1,27.5 L 92.7,27.9 L 93.7,28.6 L 94.7,29.3 L 95.4,29.0 L 96.4,29.4 L 97.1,28.5 L 97.4,28.2 L 96.9,27.5 L 97.1,27.1 L 96.5,26.4 L 95.7,26.0 L 95.1,26.6 L 94.6,25.5 L 94.3,24.4 L 93.9,24.0 L 93.4,23.1 L 93.1,22.3 L 92.6,21.9 L 92.2,23.7 L 91.6,22.9 L 91.3,23.7 L 91.0,24.4 L 90.5,24.9 L 89.9,25.3 L 89.3,26.0 L 88.6,26.4 L 88.2,25.2 L 88.7,24.3 L 88.0,23.5 L 88.6,22.6 L 88.9,21.7 L 87.5,21.5 L 86.9,20.8 L 86.4,20.1 L 85.1,19.6 L 84.2,19.0 L 83.3,18.3 L 82.3,17.1 L 81.3,16.4 L 80.5,15.9 L 80.3,15.2 L 80.2,14.4 L 80.1,13.5 L 79.9,12.4 L 79.8,11.4 L 79.4,10.6 L 79.0,10.2 L 78.5,9.4 L 78.1,9.1 L 77.6,8.3 L 77.1,8.3 L 76.8,8.8 L 76.4,9.5 L 76.0,10.3 L 75.6,11.2 L 75.2,12.1 L 74.8,13.0 L 74.5,14.0 L 74.0,15.0 L 73.7,15.9 L 73.3,16.9 L 73.0,17.8 L 72.8,18.8 L 72.7,19.7 L 72.6,20.6 L 72.9,21.4 L 72.5,21.8 L 71.6,21.0 L 70.8,20.9 L 70.0,21.4 L 69.1,22.0 L 68.9,22.6 L 68.2,23.5 L 68.7,23.9 L 69.6,24.1 L 70.4,24.4 L 70.9,24.7 L 71.0,25.4 L 70.6,26.0 L 71.1,27.0 L 72.2,27.7 L 73.0,28.4 L 73.8,29.2 L 74.4,30.0 L 74.6,30.8 L 74.9,31.5 L 75.3,32.1 L 74.6,32.6 L 74.3,33.2 L 73.9,33.8 L 74.2,34.3 L 73.9,34.9 L 74.6,35.4 L 75.4,35.9 L 76.1,36.3 L 76.8,36.5 Z";

function projectIndia(lat, lon, width, height, pad) {
  const {lonMin, lonMax, latMin, latMax} = MAP_BOUNDS;
  const x = pad + ((lon - lonMin) / (lonMax - lonMin)) * (width - pad * 2);
  const y = pad + ((latMax - lat) / (latMax - latMin)) * (height - pad * 2);
  return [x, y];
}

const BAND_COLOUR = {
  SHARP_RISE: "var(--stop)",
  RISE:       "var(--saffron)",
  STABLE:     "var(--ink-faint)",
  FALL:       "var(--navy-500)",
  SHARP_FALL: "var(--ok)",
};

function indiaOutline(width, height, pad) {
  /* Re-project every vertex through the same function the city nodes use. */
  const projected = INDIA_PATH.replace(/([\d.]+),([\d.]+)/g, (_, lon, lat) => {
    const [x, y] = projectIndia(parseFloat(lat), parseFloat(lon), width, height, pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return `<path d="${projected}" class="map-outline"/>`;
}

function graticule(width, height, pad) {
  /* Meridians and parallels every 5 degrees, labelled. Orientation without a
     boundary claim. */
  let out = "";
  for (let lon = 70; lon <= 95; lon += 5) {
    const [x] = projectIndia(MAP_BOUNDS.latMin, lon, width, height, pad);
    const [, yTop] = projectIndia(MAP_BOUNDS.latMax, lon, width, height, pad);
    const [, yBot] = projectIndia(MAP_BOUNDS.latMin, lon, width, height, pad);
    out += `<line class="graticule" x1="${x}" y1="${yTop}" x2="${x}" y2="${yBot}"/>`;
    out += `<text class="graticule-label" x="${x}" y="${yBot + 14}" text-anchor="middle">${lon}°E</text>`;
  }
  for (let lat = 10; lat <= 30; lat += 5) {
    const [xL, y] = projectIndia(lat, MAP_BOUNDS.lonMin, width, height, pad);
    const [xR] = projectIndia(lat, MAP_BOUNDS.lonMax, width, height, pad);
    out += `<line class="graticule" x1="${xL}" y1="${y}" x2="${xR}" y2="${y}"/>`;
    out += `<text class="graticule-label" x="${xL - 6}" y="${y + 3}" text-anchor="end">${lat}°N</text>`;
  }
  return out;
}

function routeMap(routes, {width = 860, height = 620} = {}) {
  if (!routes.length) {
    return '<div class="empty">No corridor is measurable on both dates.</div>';
  }

  const pad = 46;
  const P = (lat, lon) => projectIndia(lat, lon, width, height, pad);

  /* A city takes the colour of the largest absolute movement touching it, so a
     reader's eye lands on where something happened rather than on the busiest
     airport. */
  const nodes = new Map();
  for (const r of routes) {
    for (const end of [r.origin, r.destination]) {
      const existing = nodes.get(end.iata);
      const magnitude = Math.abs(r.change_pct);
      if (!existing || magnitude > existing.magnitude) {
        nodes.set(end.iata, {...end, magnitude, band: r.band, change: r.change_pct});
      }
    }
  }

  /* Arcs, not straight lines: DEL-BOM and BOM-DEL are different corridors with
     different indices, and drawn straight they would overprint. */
  const arcs = routes.map(r => {
    const [x1, y1] = P(r.origin.lat, r.origin.lon);
    const [x2, y2] = P(r.destination.lat, r.destination.lon);
    const dx = x2 - x1, dy = y2 - y1;
    const distance = Math.hypot(dx, dy) || 1;
    const bow = Math.min(distance * 0.18, 52);
    const cx = (x1 + x2) / 2 - (dy / distance) * bow;
    const cy = (y1 + y2) / 2 + (dx / distance) * bow;
    const weight = Math.min(1 + Math.abs(r.change_pct) * 0.3, 5.5);
    const move = (r.change_pct >= 0 ? "+" : "") + r.change_pct.toFixed(2);
    return `<path d="M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}" fill="none"
              stroke="${BAND_COLOUR[r.band]}" stroke-width="${weight}"
              stroke-linecap="round" opacity="0.5">
              <title>${esc(r.route)} · ${move}% · index ${idx(r.index_value, 2)}</title>
            </path>`;
  }).join("");

  const points = [...nodes.values()].map(n => {
    const [x, y] = P(n.lat, n.lon);
    const radius = 4 + Math.min(n.magnitude * 0.5, 7);
    const move = (n.change >= 0 ? "+" : "") + n.change.toFixed(2);
    return `<circle cx="${x}" cy="${y}" r="${radius + 6}" fill="${BAND_COLOUR[n.band]}" opacity="0.13"/>
            <circle cx="${x}" cy="${y}" r="${radius}" fill="${BAND_COLOUR[n.band]}"
                    stroke="#fff" stroke-width="1.5">
              <title>${esc(n.city)} (${esc(n.iata)}) · largest move ${move}%</title>
            </circle>
            <text x="${x + radius + 6}" y="${y + 4}" class="map-label">${esc(n.iata)}</text>`;
  }).join("");

  return `<div class="chart map"><svg viewBox="0 0 ${width} ${height}" role="img"
      aria-label="Airfare movement between Indian cities, positioned by coordinate">
      ${indiaOutline(width, height, pad)}${graticule(width, height, pad)}${arcs}${points}
    </svg></div>`;
}

function movementLegend() {
  const bands = [
    ["SHARP_RISE", "Sharp rise", "5% or more"],
    ["RISE", "Rise", "1% to 5%"],
    ["STABLE", "Stable", "within 1%"],
    ["FALL", "Fall", "-1% to -5%"],
    ["SHARP_FALL", "Sharp fall", "-5% or less"],
  ];
  return `<div class="legend">${bands.map(([band, label, range]) =>
    `<span class="legend-item"><span class="legend-dot" style="background:${BAND_COLOUR[band]}"></span>
     ${label} <span class="legend-range">${range}</span></span>`).join("")}</div>`;
}
