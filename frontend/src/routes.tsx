import { type ComponentType, lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";
import { Link, Navigate } from "./projects/links";
import { NewProjectPage, ProjectsPage, ToDefaultProject } from "./projects/ProjectsPage";
import { Shell } from "./components/Shell";

// Each page loads when it is opened: the first screen (your projects) doesn't wait for the map's React Flow and
// dagre, or for pages you may never open. The app frame and the projects home load up front.
function page<T extends Record<string, unknown>>(load: () => Promise<T>, name: keyof T) {
  const Page = lazy(async () => ({ default: (await load())[name] as ComponentType }));
  return function Loaded() {
    return <Suspense fallback={<div className="page-loading" aria-busy="true" />}><Page /></Suspense>;
  };
}

const FlowMapPage = page(() => import("./flowmap/FlowMapPage"), "FlowMapPage");
const HowDrawn = page(() => import("./flowmap/HowDrawn"), "HowDrawn");
const Recheck = page(() => import("./flowmap/Recheck"), "Recheck");
const ExportPage = page(() => import("./mcpmap/ExportPage"), "ExportPage");
const AddConnector = page(() => import("./pages/AddConnector"), "AddConnector");
const Catalog = page(() => import("./pages/Catalog"), "Catalog");
const ConnectorPage = page(() => import("./pages/Connector"), "ConnectorPage");
const Approvals = page(() => import("./pages/Later"), "Approvals");
const LiveRun = page(() => import("./pages/LiveRun"), "LiveRun");
const LiveRunLatest = page(() => import("./pages/LiveRun"), "LiveRunLatest");
const RunHistory = page(() => import("./pages/RunHistory"), "RunHistory");
const IssuesPage = page(() => import("./security/IssuesPage"), "IssuesPage");
const KeysPage = page(() => import("./security/KeysPage"), "KeysPage");
const VaultPage = page(() => import("./security/VaultPage"), "VaultPage");
const SettingsPage = page(() => import("./settings/SettingsPage"), "SettingsPage");
const ConnectAgent = page(() => import("./agent/ConnectAgent"), "ConnectAgent");
const ChecksPage = page(() => import("./checks/ChecksPage"), "ChecksPage");

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
  { path: "settings", element: <SettingsPage /> },   // for every project (D40), shown inside the open one
  { path: "*", element: <NotFound /> },
];

export const routes = [
  {
    element: <Shell />,
    children: [
      { path: "/", element: <ProjectsPage /> },
      { path: "/projects/new", element: <NewProjectPage /> },
      { path: "/settings", element: <SettingsPage /> },
      { path: "/p/:pid", children: projectPages },
      { path: "*", element: <ToDefaultProject /> },   // an address from before projects: the default project's page
    ],
  },
];

export const router = createBrowserRouter(routes);
