// The trip planner's flow, as Phase 6 reads it from examples/trip-planner/planner.py (D25), and one renderer
// that draws it in each candidate theme. Example data: latencies are the recorded checks (D24); "estimate" marks
// a per-kind default. Artboard code only: the app renders with React Flow.
const FLOW = {
  nodes: [
    { id: "start", kind: "start", title: "plan()", sub: "planner.py:48", x: 20, y: 360 },
    { id: "ip", kind: "api", title: "ip-api", sub: "where you are", ref: "planner.py:51", ms: 210, src: "measured", health: "warn", x: 200, y: 470 },
    { id: "nomc", kind: "api", title: "Nominatim", sub: "find the city", ref: "planner.py:52", ms: 420, src: "measured", health: "up", x: 200, y: 262 },
    { id: "d1", kind: "decision", title: "City not found?", cond: "place is None", ref: "planner.py:53", x: 410, y: 267 },
    { id: "stop", kind: "end", title: "Stop", sub: "no city, no plan", x: 455, y: 380 },
    { id: "d2", kind: "decision", title: "Sight given?", cond: "sight", ref: "planner.py:57", x: 600, y: 40 },
    { id: "noms", kind: "api", title: "Nominatim", sub: "find the sight", ref: "planner.py:58", ms: 420, src: "measured", health: "up", x: 790, y: 40 },
    { id: "osrm", kind: "api", title: "OSRM", sub: "route to the sight", ref: "planner.py:59", ms: 640, src: "measured", health: "up", x: 985, y: 40 },
    { id: "meteo", kind: "api", title: "Open-Meteo", sub: "today's weather", ref: "planner.py:60", ms: 180, src: "measured", health: "up", x: 600, y: 168 },
    { id: "d3", kind: "decision", title: "Forecast?", cond: "forecast", ref: "planner.py:63", x: 790, y: 168 },
    { id: "time", kind: "mcp", title: "time", sub: "local time", ref: "planner.py:64", ms: 1900, src: "measured", health: "up", x: 985, y: 130 },
    { id: "pack", kind: "local", title: "packing list", sub: "local script", ref: "planner.py:72", ms: 10, src: "estimate", health: "up", x: 985, y: 212 },
    { id: "fetch", kind: "mcp", title: "fetch", sub: "about the city", ref: "planner.py:66", ms: 6800, src: "measured", health: "warn", x: 600, y: 300 },
    { id: "wiki", kind: "api", title: "Wikipedia", sub: "through fetch", ref: "planner.py:67", health: "up", x: 790, y: 300, via: true },
    { id: "cur", kind: "mcp", title: "currency", sub: "rupee rate", ref: "planner.py:68", ms: 400, src: "measured", health: "down", x: 600, y: 420 },
    { id: "llm", kind: "llm", title: "Ollama", sub: "write the plan", ref: "planner.py:88", ms: 2000, src: "estimate", health: "up", x: 1180, y: 262 },
    { id: "d4", kind: "decision", title: "Plan written?", cond: "itinerary", ref: "planner.py:95", x: 1375, y: 262 },
    { id: "save", kind: "mcp", title: "files", sub: "save the plan", ref: "planner.py:98", ms: 2400, src: "measured", health: "up", side: true, x: 1560, y: 262 },
  ],
  edges: [
    ["start", "ip"], ["start", "nomc"], ["nomc", "d1"], ["d1", "stop", "yes"], ["d1", "d2", "no"], ["d1", "meteo", "no"],
    ["d1", "fetch", "no"], ["d1", "cur", "no"], ["d2", "noms", "yes"], ["noms", "osrm"], ["meteo", "d3"],
    ["d3", "time", "yes"], ["d3", "pack", "yes"], ["fetch", "wiki", "via"], ["ip", "llm"], ["osrm", "llm"],
    ["time", "llm"], ["pack", "llm"], ["fetch", "llm"], ["cur", "llm"], ["llm", "d4"], ["d4", "save", "yes"],
  ],
  critical: ["start", "nomc", "d1", "fetch", "llm", "d4", "save"],
  // the two pieces of advice, and the steps each covers
  advice: [["ip", "nomc"], ["noms", "meteo", "fetch", "cur"]],
  // when each block runs if every call starts as soon as its inputs are ready (ms): the "could be" schedule
  timing: { start: [0, 0], ip: [0, 210], nomc: [0, 420], d1: [420, 420], stop: [420, 420], d2: [420, 420],
    noms: [420, 840], osrm: [840, 1480], meteo: [420, 600], d3: [600, 600], time: [600, 2500], pack: [600, 610],
    fetch: [420, 7220], wiki: [420, 7220], cur: [420, 820], llm: [7220, 9220], d4: [9220, 9220], save: [9220, 11620] },
  total: 11620,
};

const KIND_WORD = { api: "API", mcp: "MCP", llm: "LLM", local: "Local" };
const took = (ms) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

// Each theme sizes its blocks and says where lines leave and arrive.
const SIZES = {
  studio: { w: 168, h: 54 }, boxed: { w: 156, h: 46 }, blueprint: { w: 160, h: 50 }, metro: { w: 0, h: 0 }, soft: { w: 168, h: 58 },
};

function box(n, theme) {
  const s = SIZES[theme];
  if (n.kind === "decision") return { w: 44, h: 44 };
  if (n.kind === "start" || n.kind === "end") return { w: theme === "metro" ? 0 : 120, h: theme === "metro" ? 0 : 40 };
  return s;
}

function anchor(n, theme, side) {
  const b = box(n, theme);
  if (theme === "metro") return { x: n.x + 60, y: n.y + 22 };
  const cy = n.y + (n.kind === "decision" ? 22 : b.h / 2);
  const cx = n.kind === "decision" ? n.x + 22 : n.x;
  if (side === "out") return { x: n.kind === "decision" ? n.x + 44 : n.x + b.w, y: cy };
  return { x: n.kind === "decision" ? n.x : cx, y: cy };
}

function curve(a, b) {
  const mx = (a.x + b.x) / 2;
  return `M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`;
}

function elbow(a, b) {
  const mx = Math.round((a.x + b.x) / 2);
  return `M${a.x},${a.y} H${mx} V${b.y} H${b.x}`;
}

function metroLine(a, b) {
  // transit style: horizontal, then a 45° turn, then horizontal
  const dy = b.y - a.y;
  const run = Math.min(Math.abs(dy), Math.max(0, b.x - a.x - 20));
  const x1 = a.x + (b.x - a.x - run) / 2;
  return `M${a.x},${a.y} H${x1} L${x1 + run},${a.y + Math.sign(dy) * run} V${b.y} H${b.x}`;
}

/** Draw FLOW into `svg` in `theme`. opts: { critical: bool, advice: index | null, selected: id | null } */
function drawFlow(svg, theme, opts = {}) {
  while (svg.firstChild) svg.firstChild.remove();
  const top = theme === "boxed" ? 52 : 0;   // Boxed keeps a row above the drawing for its containers' labels
  svg.setAttribute("viewBox", `0 0 1740 ${540 + top}`);
  svg.dataset.theme = theme;
  const byId = Object.fromEntries(FLOW.nodes.map((n) => [n.id, n]));
  const onPath = new Set(opts.critical ? FLOW.critical : []);
  const lit = new Set(opts.advice != null ? FLOW.advice[opts.advice] : []);
  const defs = el("defs");
  defs.innerHTML = `<marker id="arr-${theme}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker>
    <pattern id="grid-${theme}" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" class="gridline"/></pattern>`;
  svg.append(defs);
  if (theme === "blueprint") svg.append(el("rect", { x: 0, y: 0, width: 1740, height: 540, fill: `url(#grid-${theme})` }));
  const layer = el("g", { transform: `translate(0 ${top})` });

  if (theme === "boxed") {   // containers: what runs together, from the dependency graph
    const groups = [
      { x: 180, w: 196, label: "Start together", note: "0.4 s", ids: ["ip", "nomc"] },
      { x: 580, w: 380, label: "Then together, after the city check", note: "6.8 s, fetch is the slowest", ids: ["d2", "noms", "meteo", "d3", "fetch", "wiki", "cur"] },
      { x: 965, w: 200, label: "When their input is ready", note: "1.9 s", ids: ["osrm", "time", "pack"] },
      { x: 1160, w: 560, label: "Write, then save", note: "4.4 s", ids: ["llm", "d4", "save"] },
    ];
    for (const g of groups) {
      svg.append(el("rect", { x: g.x, y: 4, width: g.w, height: 584, rx: 18, class: "group" }));
      svg.append(el("text", { x: g.x + 16, y: 26, class: "group-label" }, g.label));
      svg.append(el("text", { x: g.x + 16, y: 43, class: "group-note" }, g.note));
    }
  }

  const labelled = new Set();
  for (const [s, t, label] of FLOW.edges) {
    const a = anchor(byId[s], theme, "out");
    const b = anchor(byId[t], theme, "in");
    const cp = onPath.has(s) && onPath.has(t);
    const d = theme === "metro" ? metroLine(a, b) : theme === "boxed" || theme === "blueprint" ? elbow(a, b) : curve(a, b);
    const kind = byId[t].kind;
    const cls = ["edge", cp && "cp", label === "via" && "via", label === "yes" || label === "no" ? "branch" : "", `to-${kind}`]
      .filter(Boolean).join(" ");
    const path = el("path", { d, class: cls, "data-s": s, "data-t": t, pathLength: 1 });
    path.style.setProperty("--draw-delay", `${(FLOW.timing[s]?.[1] ?? 0) / FLOW.total * 1.4}s`);
    if (theme !== "metro") path.setAttribute("marker-end", `url(#arr-${theme})`);
    layer.append(path);
    if ((label === "yes" || label === "no") && !labelled.has(`${s}:${label}`)) {
      labelled.add(`${s}:${label}`);
      const up = b.y < a.y - 4, down = b.y > a.y + 4;
      const lx = a.x + (up || down ? 6 : 12), ly = up ? a.y - 10 : down ? a.y + 18 : a.y - 7;
      layer.append(el("text", { x: lx, y: ly, class: "branch-label" }, label));
    }
  }

  for (const n of FLOW.nodes) {
    const g = el("g", { "data-id": n.id, class: ["node", `k-${n.kind}`, `h-${n.health || "none"}`, onPath.has(n.id) && "cp",
      lit.size && (lit.has(n.id) ? "lit" : "dim"), opts.selected === n.id && "sel"].filter(Boolean).join(" ") });
    const b = box(n, theme);
    if (theme === "metro") {
      const cx = n.x + 60, cy = n.y + 22;
      if (n.kind === "decision") g.append(el("rect", { x: cx - 8, y: cy - 8, width: 16, height: 16, transform: `rotate(45 ${cx} ${cy})`, class: "station dec" }));
      else g.append(el("circle", { cx, cy, r: n.kind === "llm" ? 13 : n.kind === "start" || n.kind === "end" ? 11 : 9, class: "station" }));
      g.append(el("text", { x: cx, y: cy - 20, class: "title", "text-anchor": "middle" }, n.title));
      const sub = n.ms ? took(n.ms) : n.cond ? n.cond : n.sub || "";
      g.append(el("text", { x: cx, y: cy + 30, class: "sub", "text-anchor": "middle" }, sub));
      if (n.health) g.append(el("circle", { cx: cx + 15, cy: cy - 12, r: 4, class: "hdot" }));
      layer.append(g);
      continue;
    }
    if (n.kind === "decision") {
      g.append(el("rect", { x: n.x + 7, y: n.y + 7, width: 30, height: 30, rx: theme === "soft" ? 8 : 4,
        transform: `rotate(45 ${n.x + 22} ${n.y + 22})`, class: "diamond" }));
      g.append(el("text", { x: n.x + 22, y: n.y - 8, class: "title", "text-anchor": "middle" }, n.title));
      g.append(el("text", { x: n.x + 22, y: n.y + 62, class: "code", "text-anchor": "middle" }, n.cond));
      layer.append(g);
      continue;
    }
    if (n.kind === "start" || n.kind === "end") {
      g.append(el("rect", { x: n.x, y: n.y, width: b.w, height: b.h, rx: theme === "blueprint" ? 2 : 20, class: "pill" }));
      g.append(el("text", { x: n.x + 16, y: n.y + 18, class: "title" }, n.title));
      g.append(el("text", { x: n.x + 16, y: n.y + 32, class: "sub" }, n.sub));
      layer.append(g);
      continue;
    }
    g.append(el("rect", { x: n.x, y: n.y, width: b.w, height: b.h, rx: { studio: 12, boxed: 8, blueprint: 2, soft: 18 }[theme], class: "card" }));
    if (theme === "studio") g.append(el("rect", { x: n.x, y: n.y + 9, width: 3, height: b.h - 18, rx: 1.5, class: "edgebar" }));
    const tile = theme === "blueprint" ? null : el("rect", { x: n.x + 10, y: n.y + (b.h - 28) / 2, width: 28, height: 28, rx: theme === "soft" ? 10 : 7, class: `tile t-${n.kind}` });
    if (tile) {
      g.append(tile);
      g.append(el("text", { x: n.x + 24, y: n.y + b.h / 2 + 4, class: "mono", "text-anchor": "middle" }, n.title.slice(0, 2)));
    }
    const tx = theme === "blueprint" ? n.x + 12 : n.x + 46;
    g.append(el("text", { x: tx, y: n.y + b.h / 2 - 3, class: "title" }, n.title));
    g.append(el("text", { x: tx, y: n.y + b.h / 2 + 12, class: "sub" }, n.sub));
    if (theme === "blueprint") g.append(el("text", { x: n.x + b.w - 10, y: n.y + 15, class: "kindtag", "text-anchor": "end" }, KIND_WORD[n.kind]));
    if (n.health) g.append(el("circle", { cx: n.x + b.w - 12, cy: theme === "blueprint" ? n.y + b.h - 12 : n.y + b.h / 2, r: 4.5, class: "hdot" }));
    if (n.ms) {
      if (theme === "blueprint") {   // timings as dimension lines
        const y = n.y + b.h + 12;
        g.append(el("path", { d: `M${n.x},${y - 4} V${y + 4} M${n.x},${y} H${n.x + b.w} M${n.x + b.w},${y - 4} V${y + 4}`, class: "dim" }));
        g.append(el("text", { x: n.x + b.w / 2, y: y + 14, class: "dimtext", "text-anchor": "middle" }, `${took(n.ms)}${n.src === "estimate" ? " est." : ""}`));
      } else {
        g.append(el("text", { x: n.x + 4, y: n.y + b.h + 15, class: `weight ${n.src}` }, `${n.ref}  ${took(n.ms)}${n.src === "estimate" ? " · estimate" : ""}`));
      }
    } else if (n.ref && theme !== "blueprint") {
      g.append(el("text", { x: n.x + 4, y: n.y + b.h + 15, class: "weight" }, n.ref));
    }
    layer.append(g);
  }
  svg.append(layer);
}


/** "Watch it run": trains travel each line while its call runs, blocks light up as they start and finish, all in
 * the "could be" schedule, squeezed into `seconds`. Respects reduced motion (it jumps to the end). Returns stop(). */
function playFlow(svg, { seconds = 7, onTick } = {}) {
  const layer = svg.querySelector("g[transform]") || svg;
  for (const t of layer.querySelectorAll(".train")) t.remove();
  const total = FLOW.total, scale = (seconds * 1000) / total;
  const trains = [];
  for (const path of layer.querySelectorAll("path.edge")) {
    const span = FLOW.timing[path.dataset.t];
    if (!span || span[1] === span[0]) continue;
    const train = el("circle", { r: 5, class: `train${path.classList.contains("cp") ? " cp" : ""}` });
    layer.append(train);
    trains.push({ path, train, span, len: path.getTotalLength() });
  }
  const nodes = [...layer.querySelectorAll(".node")];
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let raf = 0;
  const t0 = performance.now();
  const frame = (now) => {
    const t = reduced ? total : Math.min(total, (now - t0) / scale);
    for (const { path, train, span, len } of trains) {
      const [a, b] = span;
      const k = t <= a ? 0 : t >= b ? 1 : (t - a) / (b - a);
      const p = path.getPointAtLength(k * len);
      train.setAttribute("cx", p.x); train.setAttribute("cy", p.y);
      train.style.opacity = t < a ? 0 : t >= b ? 0 : 1;
      path.classList.toggle("live", t >= a && t < b);
    }
    for (const g of nodes) {
      const span = FLOW.timing[g.dataset.id];
      if (!span) continue;
      g.classList.toggle("running", t >= span[0] && t < span[1]);
      g.classList.toggle("done", t >= span[1]);
    }
    onTick?.(t);
    if (t < total) raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
  return () => cancelAnimationFrame(raf);
}

/** Hovering a block lights what it waits for and what waits for it. */
function traceOnHover(svg) {
  const up = {}, down = {};
  for (const [s, t] of FLOW.edges) { (up[t] ||= []).push(s); (down[s] ||= []).push(t); }
  const walk = (start, next) => { const seen = new Set([start]), stack = [start];
    while (stack.length) for (const n of next[stack.pop()] || []) if (!seen.has(n)) { seen.add(n); stack.push(n); }
    return seen; };
  svg.addEventListener("mouseover", (e) => {
    const g = e.target.closest?.(".node"); if (!g) return;
    const keep = new Set([...walk(g.dataset.id, up), ...walk(g.dataset.id, down)]);
    svg.classList.add("tracing");
    for (const n of svg.querySelectorAll(".node")) n.classList.toggle("on-trace", keep.has(n.dataset.id));
    for (const p of svg.querySelectorAll("path.edge")) p.classList.toggle("on-trace", keep.has(p.dataset.s) && keep.has(p.dataset.t));
  });
  svg.addEventListener("mouseleave", () => svg.classList.remove("tracing"));
}

/* ---------------------------------------------------------------------------------------------------------------
 * The MCP Map notation (a proposal): lanes by kind, time left to right, each call a bar as long as it takes,
 * one shape per kind so it reads in black and white, a title block and a legend. Made to be sent to someone.
 * ------------------------------------------------------------------------------------------------------------ */
const LANES = [
  { kind: "control", label: "Decisions" }, { kind: "llm", label: "LLMs" }, { kind: "mcp", label: "MCP servers" },
  { kind: "api", label: "APIs" }, { kind: "local", label: "Local programs" },
];

function shape(kind, x, y, r) {
  if (kind === "llm") return [el("circle", { cx: x, cy: y, r, class: "sym" }), el("circle", { cx: x, cy: y, r: r * 0.38, class: "sym-in" })];
  if (kind === "mcp") {
    const pts = [...Array(6)].map((_, i) => { const a = Math.PI / 3 * i + Math.PI / 6; return `${x + r * Math.cos(a)},${y + r * Math.sin(a)}`; });
    return [el("polygon", { points: pts.join(" "), class: "sym" })];
  }
  if (kind === "api") return [el("rect", { x: x - r * 0.88, y: y - r * 0.88, width: r * 1.76, height: r * 1.76, rx: r * 0.3, class: "sym" })];
  if (kind === "local") return [el("polygon", { points: `${x},${y - r} ${x + r},${y + r * 0.8} ${x - r},${y + r * 0.8}`, class: "sym" })];
  if (kind === "decision") return [el("rect", { x: x - r * 0.7, y: y - r * 0.7, width: r * 1.4, height: r * 1.4, transform: `rotate(45 ${x} ${y})`, class: "sym" })];
  if (kind === "start") return [el("circle", { cx: x, cy: y, r, class: "sym" }), el("circle", { cx: x, cy: y, r: r * 0.66, class: "sym" })];
  return [el("rect", { x: x - r * 0.7, y: y - r * 0.7, width: r * 1.4, height: r * 1.4, class: "sym stopsym" })];
}

function drawStandard(svg, opts = {}) {
  while (svg.firstChild) svg.firstChild.remove();
  const W = 1600, left = 230, right = 40, top = 100, rowH = 54, pad = 16, ms = (W - left - right) / 12000;
  const xAt = (t) => left + t * ms;
  // where each block sits: its lane, its start time, and a row of its own when it would collide with a neighbour
  const place = {}, rows = {};
  for (const n of FLOW.nodes) {
    if (n.kind === "start" || n.kind === "end") continue;
    const lane = n.kind === "decision" ? "control" : n.kind;
    const [a, b] = FLOW.timing[n.id];
    const used = (rows[lane] ||= []);
    let row = used.findIndex((end) => end <= a);
    if (row < 0) { row = used.length; used.push(0); }
    used[row] = Math.max(b, a + 1250);   // a name needs room even for a short call
    place[n.id] = { x: xAt(a), x2: xAt(b), lane, row };
  }
  const laneTop = {}, laneHeight = {};
  let y = top;
  for (const lane of LANES) {
    laneTop[lane.kind] = y;
    laneHeight[lane.kind] = Math.max(1, (rows[lane.kind] || []).length) * rowH + pad * 2;
    y += laneHeight[lane.kind];
  }
  const axisY = y, H = axisY + 60;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const defs = el("defs");
  defs.innerHTML = `<marker id="std-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker>`;
  svg.append(defs, el("rect", { x: 0, y: 0, width: W, height: H, class: "paper" }));
  svg.append(el("text", { x: 32, y: 44, class: "std-title" }, "trip-planner"));
  svg.append(el("text", { x: 32, y: 68, class: "std-sub" }, "MCP map, read from planner.py on 21 Oct 2026. 11 calls, 4 decisions, 11.6 s at best."));
  LANES.forEach((lane, i) => {
    svg.append(el("rect", { x: 0, y: laneTop[lane.kind], width: W, height: laneHeight[lane.kind], class: `lane ${i % 2 ? "odd" : ""}` }));
    svg.append(el("text", { x: 32, y: laneTop[lane.kind] + laneHeight[lane.kind] / 2 + 5, class: "lane-label" }, lane.label));
  });
  for (let t = 0; t <= 12000; t += 1000) {
    svg.append(el("line", { x1: xAt(t), y1: top, x2: xAt(t), y2: axisY + 6, class: `tick${t % 2000 ? " minor" : ""}` }));
    if (t % 2000 === 0) svg.append(el("text", { x: xAt(t), y: axisY + 24, class: "tick-label", "text-anchor": "middle" }, `${t / 1000} s`));
  }
  const rowY = (p) => laneTop[p.lane] + pad + rowH * p.row + rowH / 2 + 4;
  place.start = { x: 172, x2: 172, lane: "api", row: 0 };
  place.start.y = (top + axisY) / 2;
  const onPath = new Set(FLOW.critical);
  for (const [s, t, label] of FLOW.edges) {
    const a = place[s], b = place[t];
    if (!a || !b) continue;
    const ay = a.y ?? rowY(a), by = b.y ?? rowY(b);
    const ax = s === "start" ? a.x + 16 : a.x2 + (FLOW.nodes.find((n) => n.id === s).kind === "decision" ? 10 : 0);
    const bx = b.x - 15;
    const mx = Math.min(Math.max(ax + 10, bx - 14), bx - 4);
    const d = `M${ax},${ay} H${mx} V${by} H${bx}`;
    const cls = ["std-line", onPath.has(s) && onPath.has(t) && "cp", label === "via" && "via"].filter(Boolean).join(" ");
    svg.append(el("path", { d, class: cls, "marker-end": "url(#std-arrow)" }));
  }
  const byId = Object.fromEntries(FLOW.nodes.map((n) => [n.id, n]));
  for (const [id, p] of Object.entries(place)) {
    const n = byId[id], yy = p.y ?? rowY(p);
    const g = el("g", { class: `std-node k-${n.kind} h-${n.health || "none"}${onPath.has(id) ? " cp" : ""}` });
    if (p.x2 - p.x > 2) g.append(el("rect", { x: p.x, y: yy - 5, width: p.x2 - p.x, height: 10, rx: 5, class: `bar ${n.src === "estimate" ? "est" : ""}` }));
    for (const sh of shape(n.kind, p.x, yy, 13)) g.append(sh);
    const name = n.kind === "decision" ? n.cond : n.title;
    g.append(el("text", { x: p.x + 20, y: yy - 13, class: "std-name" }, name));
    const note = n.ms ? `${took(n.ms)}${n.src === "estimate" ? " est." : ""}${n.side ? "  ✎ writes" : ""}` : n.via ? "through fetch" : "";
    if (note) g.append(el("text", { x: p.x + 20, y: yy + 24, class: "std-ms" }, note));
    if (n.health) g.append(el("circle", { cx: p.x + 11, cy: yy - 11, r: 4, class: "hdot" }));
    svg.append(g);
  }
}
