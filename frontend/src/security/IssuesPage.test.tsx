import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { META, mockApi, renderAt } from "../test/api";
import { ISSUES, KEY_FINDING, KEY_PREVIEW } from "../test/securityFixture";

afterEach(() => vi.unstubAllGlobals());

const KEY = `/issues/${KEY_FINDING.id}`;
const HTTP = `/issues/${ISSUES.issues[1].id}`;

/** An /issues that remembers what was fixed and sent, and every call it got. */
function issuesApi(preview: object = KEY_PREVIEW, example = false) {
  const fixed = new Set<string>();
  const sent = new Set<string>();
  const calls = mockApi({
    "/meta": { ...META, example }, "/keys": { repo: "trip", example, summary: {}, keys: [] },
    "/issues": () => ({ ...ISSUES, example, issues: ISSUES.issues.map((i) => fixed.has(i.id)
      ? { ...i, state: "fixed", branch: "flowforge/fix-google-static-maps-key" } : sent.has(i.id) ? { ...i, state: "sent" } : i) }),
    [`${KEY}/preview`]: { ...preview },
    [`${KEY}/fix`]: () => { fixed.add(KEY_FINDING.id); return { id: KEY_FINDING.id, branch: "flowforge/fix-google-static-maps-key" }; },
    [`${HTTP}/send`]: () => { sent.add(ISSUES.issues[1].id); return { id: ISSUES.issues[1].id, state: "sent" }; },
  });
  return calls;
}

const card = (title: string) => screen.getByText(title).closest("li")!;

test("issues come in two groups: what FlowForge fixes, and what goes to your agent", async () => {
  issuesApi();
  renderAt("/issues");
  const fixes = await screen.findByRole("region", { name: "FlowForge fixes" });
  expect(within(fixes).getByText(KEY_FINDING.title)).toBeInTheDocument();
  expect(within(fixes).getByRole("button", { name: /Fix/ })).toBeInTheDocument();
  const agent = screen.getByRole("region", { name: "For your agent" });
  expect(within(agent).getByRole("button", { name: /Send to agent/ })).toBeInTheDocument();
  expect(screen.getByText("1 high")).toBeInTheDocument();
});

test("Fix shows the change with the key masked, and Approve makes it on a new branch", async () => {
  const calls = issuesApi();
  renderAt("/issues");
  await userEvent.click(await within(await screen.findByRole("region", { name: "FlowForge fixes" })).findByRole("button", { name: /Fix/ }));
  const diff = await screen.findByRole("region", { name: "The change to config.py" });
  expect(diff).toHaveTextContent('-23GOOGLE_STATIC_MAPS_KEY = "[REDACTED]"');
  expect(diff).toHaveTextContent('+23GOOGLE_STATIC_MAPS_KEY = os.environ["GOOGLE_STATIC_MAPS_KEY"]');
  expect(screen.getByText("flowforge/fix-google-static-maps-key")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
  expect(calls.find((c) => c.url === `${KEY}/fix`)?.init?.method).toBe("POST");
  expect(await within(card(KEY_FINDING.title)).findByText(/On branch flowforge\/fix-google-static-maps-key/)).toBeInTheDocument();
  expect(within(card(KEY_FINDING.title)).getByText(/older commits still hold it/)).toBeInTheDocument();
});

test("a fix that can't be made says why and offers your agent instead", async () => {
  issuesApi({ ...KEY_PREVIEW, can_apply: false, why_not: "config.py has uncommitted changes: commit or stash them first." });
  renderAt("/issues");
  await userEvent.click(await within(await screen.findByRole("region", { name: "FlowForge fixes" })).findByRole("button", { name: /Fix/ }));
  expect(await screen.findByText(/uncommitted changes/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Approve/ })).toBeDisabled();
  expect(within(card(KEY_FINDING.title)).getByRole("button", { name: /Send to agent/ })).toBeInTheDocument();
});

test("example data shows the change but Approve stays off", async () => {
  issuesApi({ ...KEY_PREVIEW, can_apply: false, why_not: "Example data: FlowForge shows the change but makes none." }, true);
  renderAt("/issues");
  await userEvent.click(await within(await screen.findByRole("region", { name: "FlowForge fixes" })).findByRole("button", { name: /Fix/ }));
  expect(await screen.findByRole("button", { name: /Approve/ })).toBeDisabled();
  expect(within(card(KEY_FINDING.title)).queryByRole("button", { name: /Send to agent/ })).not.toBeInTheDocument();
});

test("Send to agent queues it and says what to tell your agent", async () => {
  const calls = issuesApi();
  renderAt("/issues");
  await userEvent.click(await within(await screen.findByRole("region", { name: "For your agent" })).findByRole("button", { name: /Send to agent/ }));
  expect(calls.find((c) => c.url === `${HTTP}/send`)?.init?.method).toBe("POST");
  expect(await screen.findByText(/do the FlowForge fixes/)).toBeInTheDocument();
});

test("nothing to fix says so", async () => {
  mockApi({ "/meta": META, "/keys": { repo: "trip", example: false, summary: {}, keys: [] },
    "/issues": { ...ISSUES, summary: {}, issues: [] } });
  renderAt("/issues");
  expect(await screen.findByText("Nothing to fix")).toBeInTheDocument();
});

test("the counts are read again when you move to another page (Codex review: no stale counts after a scan)", async () => {
  const calls = issuesApi();
  renderAt("/issues");
  await screen.findByRole("region", { name: "FlowForge fixes" });
  const before = calls.filter((c) => c.url === "/issues").length;
  await userEvent.click(screen.getByRole("link", { name: /^Keys/ }));
  await vi.waitFor(() => expect(calls.filter((c) => c.url === "/issues").length).toBeGreaterThan(before));
});
