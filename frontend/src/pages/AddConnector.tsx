import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, useApi } from "../api/client";
import type { Connector, ConnectorType, Preset } from "../api/types";
import { BrandTile } from "../brand/BrandTile";
import { Icons } from "../components/icons";
import { CardSkeleton, ErrorBox } from "../components/ui";
import { COLORS, EMPTY, TYPES, fromConnector, initials, problems, slug, toConnector, type Form } from "./connectorForm";

const MAX_LOGO = 1024 * 1024;
const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"];

function Field({ label, error, hint, children }: { label: string; error?: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      {label}
      {children}
      {error ? <span className="error" role="alert">{error}</span> : hint ? <span className="hint">{hint}</span> : null}
    </label>
  );
}

export function AddConnector() {
  const { id: editId } = useParams();
  const editing = !!editId;
  const navigate = useNavigate();
  const existing = useApi<Connector>(editing ? `/connectors/${encodeURIComponent(editId)}` : null);
  const all = useApi<Connector[]>("/connectors");
  const presets = useApi<Preset[]>(editing ? null : "/presets");
  const [form, setForm] = useState<Form>(EMPTY);
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [submitted, setSubmitted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [logoPreview, setLogoPreview] = useState<string>();

  useEffect(() => {
    if (existing.data) setForm(fromConnector(existing.data));
  }, [existing.data]);
  useEffect(() => {
    if (!logoFile) return setLogoPreview(undefined);
    const url = URL.createObjectURL(logoFile);
    setLogoPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [logoFile]);

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setTouched((t) => new Set(t).add(key));
  };
  const issues = problems(form);
  const show = (key: keyof Form) => (submitted || touched.has(key) ? issues[key] : undefined);
  const saved = useMemo(() => toConnector(form, editing && existing.data?.style.logo.type === "upload" && form.logo === "upload"
    ? { file: (existing.data.style.logo as { file: string }).file } : null), [form, editing, existing.data]);
  const type = TYPES.find((t) => t.id === form.type)!;

  function usePreset(p: Preset) {
    const taken = new Set((all.data ?? []).map((c) => c.id));
    let id = p.id ?? "";
    for (let n = 2; id && taken.has(id); n++) id = `${p.id}-${n}`;
    setForm({ ...fromConnector({ ...p, id }, p.style?.color ?? COLORS[0]) });
    setTouched(new Set());
  }

  function pickLogo(file: File | undefined) {
    setError(undefined);
    if (!file) return;
    if (!LOGO_TYPES.includes(file.type)) return setError("Logos must be PNG, JPEG or WebP images.");
    if (file.size > MAX_LOGO) return setError("Logos must be 1 MB or smaller.");
    setLogoFile(file);
    set("logo", "upload");
  }

  async function submit() {
    setSubmitted(true);
    setError(undefined);
    if (Object.keys(issues).length) return;
    if (form.logo === "upload" && !logoFile && !(editing && existing.data?.style.logo.type === "upload")) {
      return setError("Choose an image for the logo, or pick Letters or Colour only.");
    }
    setSaving(true);
    try {
      const body = { ...saved, ...(form.logo === "upload" && logoFile ? { style: { color: form.color, logo: { type: "letters", text: "" } } } : {}) };
      const result = editing
        ? await api.put<Connector>(`/connectors/${encodeURIComponent(editId)}`, body)
        : await api.post<Connector>("/connectors", body);
      if (logoFile) {
        const data = new FormData();
        data.append("file", logoFile);
        await api.post(`/connectors/${encodeURIComponent(result.id)}/logo`, data);
      }
      navigate(`/connectors/${result.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (editing && existing.error) return <ErrorBox error={existing.error} what="this app" />;
  if (editing && !existing.data) return <CardSkeleton lines={6} />;
  if (editing && existing.data?.managed_by === "file") {
    return <div className="notice">This app comes from <code>connectors.json</code>; edit that file to change it.</div>;
  }

  const previewC = {
    id: saved.id as string || "new", type: form.type, name: form.name || "Your app",
    connection: saved.connection as Record<string, unknown>,
    style: saved.style as Connector["style"], logo_url: form.logo === "upload" ? logoPreview ?? existing.data?.logo_url : undefined,
  };

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="eyebrow">{editing ? `Edit ${existing.data?.name}` : "Add an app"}</span>
          <h1>Connect it, colour it, name it</h1>
          <span className="lede">Four ways to connect cover every app, MCP server and model.</span>
        </div>
      </header>

      {!editing && presets.data && (
        <section className="card" aria-labelledby="preset-title">
          <span className="eyebrow" id="preset-title">Start from a ready-made app</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {presets.data.filter((p) => !p.preset.startsWith("custom")).map((p) => (
              <button key={p.preset} type="button" className="btn" onClick={() => usePreset(p)}>
                <BrandTile c={{ id: p.preset, type: p.type, name: p.name ?? p.preset, style: p.style as Connector["style"], connection: p.connection }} size={24} />
                {p.name}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="card" aria-labelledby="type-title">
        <span className="eyebrow" id="type-title">1 · How does it connect?</span>
        <div className="grid" style={{ "--min": "200px" } as CSSProperties}>
          {TYPES.map((t) => (
            <button key={t.id} type="button" className="choice" aria-pressed={form.type === t.id} disabled={editing && form.type !== t.id}
              onClick={() => set("type", t.id as ConnectorType)}>
              <b>{t.label}</b><span>{t.desc}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="grid" style={{ "--min": "440px" } as CSSProperties}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="card" aria-labelledby="name-title">
            <span className="eyebrow" id="name-title">2 · Name it</span>
            <Field label="Name" error={show("name")}>
              <input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Image studio" autoComplete="off" />
            </Field>
            <Field label="What it does" error={show("role")}>
              <input value={form.role} onChange={(e) => set("role", e.target.value)} placeholder="makes product photos" autoComplete="off" />
            </Field>
            <Field label="Short name (used in plans)" error={show("id")} hint={editing ? "Short names can't be changed." : undefined}>
              <input value={form.id || slug(form.name)} onChange={(e) => set("id", e.target.value)} disabled={editing}
                className="mono" spellCheck={false} autoComplete="off" />
            </Field>
          </section>

          <section className="card" aria-labelledby="connect-title">
            <span className="eyebrow" id="connect-title">3 · Connect it · {type.label}</span>
            {form.type === "llm" && (
              <>
                <Field label="Provider">
                  <select value={form.provider} onChange={(e) => set("provider", e.target.value as Form["provider"])}>
                    <option value="openai_compatible">OpenAI-style API (NIM, Gemini, Ollama, OpenRouter…)</option>
                    <option value="anthropic">Anthropic (Claude)</option>
                  </select>
                </Field>
                {form.provider === "openai_compatible" && (
                  <Field label="Base URL" error={show("baseUrl")}>
                    <input value={form.baseUrl} onChange={(e) => set("baseUrl", e.target.value)} placeholder="https://api.example.com/v1" className="mono" autoComplete="off" />
                  </Field>
                )}
                <Field label="Model" error={show("model")}>
                  <input value={form.model} onChange={(e) => set("model", e.target.value)} placeholder="model-name" className="mono" autoComplete="off" />
                </Field>
              </>
            )}
            {form.type === "mcp" && (
              <>
                <Field label="Command" error={show("command")}>
                  <input value={form.command} onChange={(e) => set("command", e.target.value)} placeholder="npx" className="mono" autoComplete="off" />
                </Field>
                <Field label="Arguments" error={show("args")}>
                  <input value={form.args} onChange={(e) => set("args", e.target.value)} placeholder="my-image-mcp" className="mono" autoComplete="off" />
                </Field>
              </>
            )}
            {form.type === "http" && (
              <>
                <Field label="Base URL" error={show("baseUrl")} hint="The key is only ever sent to this address.">
                  <input value={form.baseUrl} onChange={(e) => set("baseUrl", e.target.value)} placeholder="https://api.example.com" className="mono" autoComplete="off" />
                </Field>
                <Field label="Auth header name" error={show("authHeader")}>
                  <input value={form.authHeader} onChange={(e) => set("authHeader", e.target.value)} placeholder="Authorization" autoComplete="off" />
                </Field>
                <Field label="Auth style">
                  <select value={form.authScheme} onChange={(e) => set("authScheme", e.target.value as Form["authScheme"])}>
                    <option value="bearer">Bearer token</option><option value="basic">Basic (id:secret)</option><option value="raw">The key as-is</option>
                  </select>
                </Field>
                <Field label="Mode">
                  <select value={form.mode} onChange={(e) => set("mode", e.target.value as Form["mode"])}>
                    <option value="">Not a payment app</option><option value="test">Test mode</option><option value="live">Live mode</option>
                  </select>
                </Field>
              </>
            )}
            {form.type === "local" && (
              <>
                <Field label="Command" error={show("command")} hint="Runs directly, never through a shell. .bat and .cmd files are refused.">
                  <input value={form.command} onChange={(e) => set("command", e.target.value)} placeholder="./scan.sh" className="mono" autoComplete="off" />
                </Field>
                <Field label="Run in folder" error={show("cwd")} hint="It can't reach files outside this folder.">
                  <input value={form.cwd} onChange={(e) => set("cwd", e.target.value)} placeholder="project/tools" className="mono" autoComplete="off" />
                </Field>
              </>
            )}
            <Field label={type.needsKey ? "Key: the name of the variable in your .env file" : "Key variable passed to the program (optional)"}
              error={show("keyVar")}
              hint={<>Put <code>{form.keyVar || "NAME"}=your-key</code> in <code>.env</code>. FlowForge saves only the name, never the key. The vault arrives in Phase 3.</>}>
              <input value={form.keyVar} onChange={(e) => set("keyVar", e.target.value.toUpperCase())} placeholder="GEMINI_API_KEY"
                className="mono" spellCheck={false} autoComplete="off" />
            </Field>
            <Field label="Rate limit (calls a minute, optional)" error={show("rpm")}>
              <input value={form.rpm} onChange={(e) => set("rpm", e.target.value)} inputMode="numeric" placeholder="no limit" autoComplete="off" />
            </Field>
          </section>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="card" aria-labelledby="style-title">
            <span className="eyebrow" id="style-title">4 · Style it</span>
            <span className="card-note" id="colour-label">Colour</span>
            <div role="radiogroup" aria-labelledby="colour-label" style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
              {COLORS.map((c) => (
                <button key={c} type="button" role="radio" aria-checked={form.color === c} aria-label={`Colour ${c}`}
                  onClick={() => set("color", c)} className="swatch" style={{ background: c, boxShadow: `0 0 0 2px ${form.color === c ? "var(--fg)" : "var(--line)"}` }} />
              ))}
              <label className="swatch custom" title="Pick any colour" style={{ background: COLORS.includes(form.color) ? "var(--surface-2)" : form.color }}>
                <span className="visually-hidden">Custom colour</span>
                <input type="color" value={form.color} onChange={(e) => set("color", e.target.value.toUpperCase())} />
                {COLORS.includes(form.color) && <span aria-hidden="true">+</span>}
              </label>
            </div>
            <span className="card-note" id="logo-label">Logo</span>
            <div role="radiogroup" aria-labelledby="logo-label" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {([["letters", "Letters"], ["upload", "Upload image"], ["none", "Colour only"]] as const).map(([v, l]) => (
                <button key={v} type="button" role="radio" aria-checked={form.logo === v} className="filter"
                  onClick={() => set("logo", v)}>{l}</button>
              ))}
            </div>
            {form.logo === "letters" && (
              <Field label="Letters" error={show("letters")}>
                <input value={form.letters} maxLength={2} onChange={(e) => set("letters", e.target.value)} placeholder={form.name ? initials(form.name) : "Is"} style={{ maxWidth: 120 }} />
              </Field>
            )}
            {form.logo === "upload" && (
              <Field label="Image" hint="PNG, JPEG or WebP, under 1 MB. SVG isn't accepted.">
                <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => pickLogo(e.target.files?.[0])} style={{ paddingTop: 10 }} />
              </Field>
            )}
          </section>

          <section className="card raised" aria-labelledby="preview-title">
            <span className="eyebrow" id="preview-title">Preview · on the map</span>
            <div className="hub-tile" style={{ boxShadow: "var(--shadow-1)" }}>
              <BrandTile c={previewC} size={44} />
              <span className="hub-text"><b>{form.name || "Your app"}</b><span>{form.role || "what it does"} · {type.label}</span></span>
              <span className="hub-dot tone-slate" aria-hidden="true" />
            </div>
            <span className="card-note">The dot turns green once it has run, or passed "Test connection" on its page.</span>
            <span className="eyebrow">What gets saved (no secrets)</span>
            <pre className="code" aria-label="What gets saved">{JSON.stringify(saved, null, 2)}</pre>
          </section>
        </div>
      </div>

      {error && <div className="error-box" role="alert"><b>Couldn't save it.</b> {error}</div>}
      {submitted && Object.keys(issues).length > 0 && <div className="notice" role="alert">Some answers need another look; they're marked above.</div>}
      <div className="actions">
        <button type="button" className="btn primary" onClick={submit} disabled={saving} style={{ minHeight: 48, padding: "0 22px" }}>
          {Icons.check(18)} {saving ? "Saving…" : editing ? "Save changes" : "Add to project"}
        </button>
        <Link to={editing ? `/connectors/${editId}` : "/"} className="btn" style={{ minHeight: 48 }}>Cancel</Link>
      </div>
      {!editing && <p className="card-note">After adding, open its page to test the connection.</p>}
    </>
  );
}
