import { createBrowserRouter, Link } from "react-router-dom";
import { Shell } from "./components/Shell";
import { AddConnector } from "./pages/AddConnector";
import { ConnectorPage, ConnectorsList } from "./pages/Connector";
import { Approvals, PlanReview, Security } from "./pages/Later";
import { LiveRun, LiveRunLatest } from "./pages/LiveRun";
import { Overview } from "./pages/Overview";
import { RunHistory } from "./pages/RunHistory";

function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <p className="lede">That address isn't part of FlowForge. <Link to="/">Back to the overview</Link>.</p>
    </>
  );
}

export const routes = [
  {
    element: <Shell />,
    children: [
      { path: "/", element: <Overview /> },
      { path: "/connectors", element: <ConnectorsList /> },
      { path: "/connectors/new", element: <AddConnector /> },
      { path: "/connectors/:id", element: <ConnectorPage /> },
      { path: "/connectors/:id/edit", element: <AddConnector /> },
      { path: "/plans", element: <PlanReview /> },
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
