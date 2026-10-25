import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { BrowseButton } from "./FolderPicker";

afterEach(() => { delete (window as unknown as { __TAURI__?: unknown }).__TAURI__; });

test("in a browser there is no Browse button (a page can't read a folder's path)", () => {
  render(<BrowseButton onPick={() => {}} />);
  expect(screen.queryByRole("button", { name: /Browse/ })).not.toBeInTheDocument();
});

test("in the desktop app, Browse opens the system's folder picker and fills the box (D42)", async () => {
  const invoke = vi.fn(async () => "/home/me/code/shop");
  (window as unknown as { __TAURI__: unknown }).__TAURI__ = { core: { invoke } };
  const picked: string[] = [];
  render(<BrowseButton onPick={(p) => picked.push(p)} />);
  await userEvent.click(screen.getByRole("button", { name: /Browse/ }));
  expect(invoke).toHaveBeenCalledWith("plugin:dialog|open", { options: { directory: true, multiple: false } });
  expect(picked).toEqual(["/home/me/code/shop"]);
});

test("closing the picker changes nothing", async () => {
  (window as unknown as { __TAURI__: unknown }).__TAURI__ = { core: { invoke: vi.fn(async () => null) } };
  const picked: string[] = [];
  render(<BrowseButton onPick={(p) => picked.push(p)} />);
  await userEvent.click(screen.getByRole("button", { name: /Browse/ }));
  expect(picked).toEqual([]);
});
