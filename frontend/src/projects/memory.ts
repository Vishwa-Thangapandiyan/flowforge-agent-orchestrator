// What the picker remembers (D39): which projects you have open, and where you were in each, so switching brings you
// back to the same page, map view and open block. Viewer conveniences: kept in this browser only, never on the server.
const OPEN_KEY = "flowforge.openProjects";

function read(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function write(ids: string[]): void {
  try { localStorage.setItem(OPEN_KEY, JSON.stringify(ids)); } catch { /* private window: not remembered */ }
}

/** The projects you have open, most recent first. */
export function openProjects(): string[] {
  return read();
}

/** Opening a project puts it first in the open list. */
export function markOpen(id: string): void {
  write([id, ...read().filter((x) => x !== id)]);
}

/** × in the picker: out of the open list; the project itself stays (D39). */
export function closeProject(id: string): void {
  write(read().filter((x) => x !== id));
  places.delete(id);
  views.delete(id);
}

const places = new Map<string, string>();   // project → the page you were on (path + query)

export function rememberPlace(id: string, path: string): void {
  places.set(id, path);
}

/** Where opening a project takes you: the page you left it on, else its map. */
export function placeOf(id: string): string {
  return places.get(id) ?? `/p/${encodeURIComponent(id)}`;
}

export interface MapView { x: number; y: number; zoom: number; selected: string | null }
const views = new Map<string, MapView>();   // project → its map's viewport and open block

export function rememberView(id: string, view: MapView): void {
  views.set(id, view);
}

export function viewOf(id: string): MapView | undefined {
  return views.get(id);
}
