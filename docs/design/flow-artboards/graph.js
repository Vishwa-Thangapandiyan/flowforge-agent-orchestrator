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
    const path = el("path", { d, class: cls });
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
    const g = el("g", { class: ["node", `k-${n.kind}`, `h-${n.health || "none"}`, onPath.has(n.id) && "cp",
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
