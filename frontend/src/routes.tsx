import { createBrowserRouter } from "react-router-dom";
import { Link, Navigate } from "./projects/links";
import { NewProjectPage, ProjectsPage, ToDefaultProject } from "./projects/ProjectsPage";
import { ConnectAgent } from "./agent/ConnectAgent";
import { ChecksPage } from "./checks/ChecksPage";
import { Shell } from "./components/Shell";
import { FlowMapPage } from "./flowmap/FlowMapPage";
import { HowDrawn } from "./flowmap/HowDrawn";
import { Recheck } from "./flowmap/Recheck";
import { ExportPage } from "./mcpmap/ExportPage";
import { AddConnector } from "./pages/AddConnector";
import { Catalog } from "./pages/Catalog";
import { ConnectorPage } from "./pages/Connector";
import { Approvals } from "./pages/Later";
import { LiveRun, LiveRunLatest } from "./pages/LiveRun";
import { RunHistory } from "./pages/RunHistory";
import { IssuesPage } from "./security/IssuesPage";
import { KeysPage } from "./security/KeysPage";
import { VaultPage } from "./security/VaultPage";

function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <p className="lede">That address isn't part of FlowForge. <Link to="/">Back to the map</Link>.</p>
    </>
  );
}

// A project's pages (D39), under /p/:pid. Their links stay "/keys", "/issues"…: projects/links.tsx adds the prefix.
const projectPages = [
  { index: true, element: <FlowMapPage />, handle: { bleed: true } },
  { path: "map/how", element: <HowDrawn /> },
  { path: "map/recheck", element: <Recheck /> },
  { path: "map/export", element: <ExportPage /> },
  { path: "connectors", element: <Catalog /> },
  { path: "connectors/new", element: <AddConnector /> },
  { path: "connectors/:id", element: <ConnectorPage /> },
  { path: "connectors/:id/edit", element: <AddConnector /> },
  { path: "plans", element: <Navigate to="/" replace /> },  // the plan is the map now (D17)
  { path: "checks", element: <ChecksPage /> },
  { path: "connect", element: <ConnectAgent /> },
  { path: "live", element: <LiveRunLatest /> },
  { path: "runs", element: <RunHistory /> },
  { path: "runs/:id", element: <LiveRun /> },
  { path: "approvals", element: <Approvals /> },
  { path: "issues", element: <IssuesPage /> },
  { path: "keys", element: <KeysPage /> },
  { path: "vault", element: <VaultPage /> },
  { path: "security", element: <Navigate to="/issues" replace /> },  // the Issues page (D37)
  { path: "*", element: <NotFound /> },
];

export const routes = [
  {
    element: <Shell />,
    children: [
      { path: "/", element: <ProjectsPage /> },
      { path: "/projects/new", element: <NewProjectPage /> },
      { path: "/p/:pid", children: projectPages },
      { path: "*", element: <ToDefaultProject /> },   // an address from before projects: the default project's page
    ],
  },
];

export const router = createBrowserRouter(routes);
