import { createBrowserRouter, Link, Navigate } from "react-router-dom";
import { Shell } from "./components/Shell";
import { FlowMapPage } from "./flowmap/FlowMapPage";
import { HowDrawn } from "./flowmap/HowDrawn";
import { Recheck } from "./flowmap/Recheck";
import { AddConnector } from "./pages/AddConnector";
import { Catalog } from "./pages/Catalog";
import { ConnectorPage } from "./pages/Connector";
import { Approvals, Security } from "./pages/Later";
import { LiveRun, LiveRunLatest } from "./pages/LiveRun";
import { RunHistory } from "./pages/RunHistory";

function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <p className="lede">That address isn't part of FlowForge. <Link to="/">Back to the map</Link>.</p>
    </>
  );
}

export const routes = [
  {
    element: <Shell />,
    children: [
      { path: "/", element: <FlowMapPage />, handle: { bleed: true } },
      { path: "/map/how", element: <HowDrawn /> },
      { path: "/map/recheck", element: <Recheck /> },
      { path: "/connectors", element: <Catalog /> },
      { path: "/connectors/new", element: <AddConnector /> },
      { path: "/connectors/:id", element: <ConnectorPage /> },
      { path: "/connectors/:id/edit", element: <AddConnector /> },
      { path: "/plans", element: <Navigate to="/" replace /> },  // the plan is the map now (D17)
      { path: "/live", element: <LiveRunLatest /> },
      { path: "/runs", element: <RunHistory /> },
      { path: "/runs/:id", element: <LiveRun /> },
      { path: "/approvals", element: <Approvals /> },
      { path: "/security", element: <Security /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
