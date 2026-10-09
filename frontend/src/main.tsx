import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@xyflow/react/dist/base.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/motion.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./routes";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
