# FlowForge design reference

- **flow-map-artboards/** is the current spec (D17, D18; approved 2026-10-09). It holds Claude Design source (`*.dc.html`, `canvas.json`). Open them in Claude Design, or read them as HTML source.
  - **Main:** the flow map (home): pan, drag, step panel, test-run replay.
  - **Planner:** how the Planner draws the map.
  - **Recheck:** the re-check diff.
  - **Catalog:** the connector catalog with mock test runs.
  - **Kinds:** blocks, lines, colours, the Flow JSON shape, and the Geist / Geist Mono type scale.

  Logos in them load from the canvas's uploaded simple-icons marks (`/_blob/...`); the app imports the same marks from the `simple-icons` package. All data is example data.
- **flow-artboards/** (Phase 6, D25; awaiting approval): `flow.html` is the flow read from code, with the Faster panel (as written versus could be, and the advice) and a clicked decision. `themes.html` shows the same flow in five graph themes (Studio, Boxed, Blueprint, Metro, Soft; approved), with motion: lines draw in, "Watch it run" sends trains along each call, hovering traces a block's path. `standard.html` proposes the MCP Map notation (lanes by kind, time left to right, a shape per kind) with SVG, PNG, Mermaid and Flow JSON export. All draw from `graph.js`; open them in a browser.
- **issues-keys/issues-keys.html** (D37; awaiting approval): the Issues page (Fix with a masked diff, Send to agent), the Keys page (paste once, move from .env), the locked key view (password + authenticator code) and its set-up. Plain HTML, fake keys; the top-right button switches light and dark.
- **checks-artboards/checks.html** (Phase 5, D24; awaiting approval): the map with health dots, the first "Check now" confirmation, the step panel's Health section and the Checks page. Plain HTML with the same tokens (no Claude Design runtime): open it in a browser; the button at the top right switches light and dark. Example data: the trip planner.
- **system-map.html:** the original six-view system map. Still the reference for the connector zoom, add-an-app, swap and security views. View 1 (hub map) and View 7 (plan-review list) are replaced by the flow map.
- **plan.html, swap-flow.html:** the roadmap and swap flow.
- **dashboard-artboards/:** the Phase 2 dashboard pages as Claude Design source. They are structure and wording references with example data, deliberately plain. Page map: Main=Overview (replaced by the flow map), Connector, AddConnector, PlanReview (replaced), Run, Approvals, History, Security.
