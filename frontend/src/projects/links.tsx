// Links inside a project (D39): a page writes `to="/keys"` and, in project "shop", it goes to "/p/shop/keys". Outside
// a project (the home page) paths are left as they are. "/projects…" and "/p/…" are never prefixed.
import { forwardRef } from "react";
import {
  Link as RouterLink, type LinkProps, Navigate as RouterNavigate, type NavigateOptions, type NavigateProps, type To,
  useMatch, useNavigate as useRouterNavigate,
} from "react-router-dom";

export function useProjectId(): string | undefined {
  const deep = useMatch("/p/:pid/*");
  const top = useMatch("/p/:pid");
  return deep?.params.pid ?? top?.params.pid;
}

export function inProject(pid: string | undefined, to: To): To {
  if (!pid || typeof to !== "string" || !to.startsWith("/")) return to;
  if (to.startsWith("/p/") || to === "/projects" || to.startsWith("/projects/")) return to;
  return `/p/${encodeURIComponent(pid)}${to === "/" ? "" : to}`;
}

export const Link = forwardRef<HTMLAnchorElement, LinkProps>(function Link({ to, ...rest }, ref) {
  return <RouterLink ref={ref} to={inProject(useProjectId(), to)} {...rest} />;
});

export function Navigate({ to, ...rest }: NavigateProps) {
  return <RouterNavigate to={inProject(useProjectId(), to)} {...rest} />;
}

export function useNavigate() {
  const go = useRouterNavigate();
  const pid = useProjectId();
  return (to: To | number, options?: NavigateOptions) =>
    typeof to === "number" ? go(to) : go(inProject(pid, to), options);
}
