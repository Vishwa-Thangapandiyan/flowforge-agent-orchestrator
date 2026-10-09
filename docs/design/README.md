# FlowForge design reference

- **flow-map-artboards/** is the current spec (D17, D18; approved 2026-10-09). It holds Claude Design source (`*.dc.html`, `canvas.json`). Open them in Claude Design, or read them as HTML source.
  - **Main:** the flow map (home): pan, drag, step panel, test-run replay.
  - **Planner:** how the Planner draws the map.
  - **Recheck:** the re-check diff.
  - **Catalog:** the connector catalog with mock test runs.
  - **Kinds:** blocks, lines, colours, the Flow JSON shape, and the Geist / Geist Mono type scale.

  Logos in them load from the canvas's uploaded simple-icons marks (`/_blob/...`); the app imports the same marks from the `simple-icons` package. All data is example data.
- **system-map.html:** the original six-view system map. Still the reference for the connector zoom, add-an-app, swap and security views. View 1 (hub map) and View 7 (plan-review list) are replaced by the flow map.
- **plan.html, swap-flow.html:** the roadmap and swap flow.
- **dashboard-artboards/:** the Phase 2 dashboard pages as Claude Design source. They are structure and wording references with example data, deliberately plain. Page map: Main=Overview (replaced by the flow map), Connector, AddConnector, PlanReview (replaced), Run, Approvals, History, Security.
