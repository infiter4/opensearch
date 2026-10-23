import { useEffect, useRef, useState } from "react";
import { useChat, type WorkspaceInfo } from "../state/chat";

const ACCEPT =
  ".txt,.md,.markdown,.rst,.pdf,.py,.js,.ts,.tsx,.jsx,.go,.rs,.java,.c,.h,.cpp,.cs,.rb,.php,.swift,.kt,.sh,.sql,.json,.yaml,.yml";

/** The corpus control: choose whether a run researches the open web or one of your ingested
 *  workspaces, create/delete workspaces, and drop files in to ingest them. Only rendered when the
 *  backend has a store configured (SUPABASE_DB_URL). */
export function Workspaces() {
  const workspaces = useChat((s) => s.workspaces);
  const activeWorkspace = useChat((s) => s.activeWorkspace);
  const storeEnabled = useChat((s) => s.storeEnabled);
  const loadWorkspaces = useChat((s) => s.loadWorkspaces);
  const createWorkspace = useChat((s) => s.createWorkspace);
  const setActiveWorkspace = useChat((s) => s.setActiveWorkspace);
  const deleteWorkspace = useChat((s) => s.deleteWorkspace);
  const ingestFiles = useChat((s) => s.ingestFiles);

  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { void loadWorkspaces(); }, [loadWorkspaces]);

  if (!storeEnabled) return null;

  const active = workspaces.find((w) => w.slug === activeWorkspace) ?? null;

  const submitNew = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = title.trim();
    if (!t) return;
    setTitle(""); setCreating(false);
    const slug = await createWorkspace(t);
    setNote(slug ? `“${t}” created — drop files in to ingest` : "could not create workspace");
  };

  const onFiles = async (list: FileList | File[] | null) => {
    const files = list ? Array.from(list) : [];
    if (!files.length) return;
    setIngesting(true); setNote(null);
    const s = await ingestFiles(files);
    setIngesting(false);
    setNote(s
      ? `ingested ${s.documents} doc${s.documents === 1 ? "" : "s"}, ${s.chunks} chunk${s.chunks === 1 ? "" : "s"}${s.skipped ? ` · ${s.skipped} skipped` : ""}`
      : "ingestion failed");
    if (fileRef.current) fileRef.current.value = "";
  };

  const removeActive = async () => {
    if (!active) return;
    if (!window.confirm(`Delete workspace “${active.title}” and all its documents?`)) return;
    await deleteWorkspace(active.slug);
    setNote(null);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1 flex-wrap">
        <span className="label !text-faint mr-2">corpus</span>

        <Pill
          label="Web"
          active={!activeWorkspace}
          onClick={() => setActiveWorkspace(null)}
          note="research the open web — the default"
        />
        {workspaces.map((w) => (
          <Pill
            key={w.slug}
            label={w.title}
            count={w.n_documents}
            active={activeWorkspace === w.slug}
            onClick={() => setActiveWorkspace(w.slug)}
            note={`${w.n_documents ?? 0} document${w.n_documents === 1 ? "" : "s"} · ${w.n_chunks ?? 0} chunks · researched instead of the web`}
          />
        ))}

        {creating ? (
          <form onSubmit={submitNew} className="flex items-center gap-1 ml-1">
            <input
              autoFocus
              value={title}
              placeholder="workspace name"
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Escape") { setCreating(false); setTitle(""); } }}
              className="bg-transparent outline-none border-b border-signal text-ink font-mono text-[11px] py-0.5 w-36"
            />
            <button type="submit" className="text-signal hover:opacity-70 px-1" data-note="create">✓</button>
            <button type="button" onClick={() => { setCreating(false); setTitle(""); }}
                    className="text-faint hover:text-ink px-1" data-note="cancel">×</button>
          </form>
        ) : (
          <button
            onClick={() => setCreating(true)}
            className="font-mono text-[11px] text-mute hover:text-ink px-2 py-1 transition-colors"
            data-note="create a workspace to research your own documents"
          >
            + new
          </button>
        )}

        {!workspaces.length && !creating && (
          <span className="text-faint text-[13px] italic ml-1 hidden sm:inline">
            research your own documents: text, code, PDFs
          </span>
        )}
      </div>

      {/* Ingest zone — only for an active workspace. Click or drag files in. */}
      {active && (
        <label
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); void onFiles(e.dataTransfer.files); }}
          className={`group flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 rounded-[3px] border border-dashed cursor-pointer transition-colors ${
            dragOver ? "border-signal bg-[var(--sel)] text-ink" : "border-line-2 text-mute hover:border-ink/40 hover:text-ink"
          }`}
        >
          <input ref={fileRef} type="file" multiple hidden accept={ACCEPT}
                 onChange={(e) => void onFiles(e.target.files)} />
          <span className="font-mono text-[10.5px] flex items-center gap-2 min-w-0">
            <span className={`w-1.5 h-1.5 rounded-full bg-signal ${ingesting ? "live-dot" : ""}`} />
            <span className="truncate">
              {ingesting ? "ingesting…" : dragOver ? "release to ingest" : `drop files into “${active.title}” or click`}
            </span>
          </span>
          <span className="flex items-center gap-3 shrink-0">
            {note && <span className="font-mono text-[10px] text-mute">{note}</span>}
            <span className="font-mono text-[10px] text-faint">
              {active.n_documents ?? 0} docs · {active.n_chunks ?? 0} chunks
            </span>
            <button
              type="button"
              onClick={(e) => { e.preventDefault(); void removeActive(); }}
              className="font-mono text-[12px] text-faint hover:text-signal transition-colors"
              data-note="delete this workspace and its documents"
            >
              ×
            </button>
          </span>
        </label>
      )}
    </div>
  );
}

function Pill({ label, count, active, onClick, note }: {
  label: string; count?: number; active: boolean; onClick: () => void; note: string;
}) {
  return (
    <button
      onClick={onClick}
      data-note={note}
      className={`flex items-center gap-1.5 font-mono text-[11px] px-2.5 py-1 rounded-full border transition-colors ${
        active ? "border-ink text-ink" : "border-transparent text-mute hover:text-ink"
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${active ? "bg-signal" : "border border-faint"}`} />
      {label}
      {count != null && <span className="text-faint">{count}</span>}
    </button>
  );
}

export type { WorkspaceInfo };
