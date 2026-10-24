// Browse… (D42): inside the desktop app, the system's folder picker fills the folder box. In a browser it isn't shown,
// since a web page can't read a folder's path.
import { Icons } from "./icons";

interface TauriCore { invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T> }

function tauri(): TauriCore | undefined {
  return (window as unknown as { __TAURI__?: { core?: TauriCore } }).__TAURI__?.core;
}

export function canPickFolder(): boolean {
  return typeof tauri()?.invoke === "function";
}

/** The folder picked, or null when the picker was closed. */
export async function pickFolder(): Promise<string | null> {
  const picked = await tauri()!.invoke<string | string[] | null>("plugin:dialog|open", { options: { directory: true, multiple: false } });
  return Array.isArray(picked) ? picked[0] ?? null : picked;
}

export function BrowseButton({ onPick, disabled }: { onPick: (path: string) => void; disabled?: boolean }) {
  if (!canPickFolder()) return null;
  return (
    <button type="button" className="btn" disabled={disabled}
      onClick={() => void pickFolder().then((path) => { if (path) onPick(path); }, () => {})}>
      {Icons.file(16)} Browse…
    </button>
  );
}
