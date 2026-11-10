import { useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Upload, FolderOpen, RefreshCw, Trash2, Download } from "lucide-react";
import { base, human, useAction, useData } from "./api";
import { Empty, ErrorBox, Loading, Modal, PageHead, Pill } from "./ui";

type Source = {
  id: string;
  filename: string;
  kind: string;
  status: string;
  version: number;
  warnings: string[];
};
type Item = {
  id: string;
  field: string;
  locator: string;
  relation: string;
  value: {
    raw: unknown;
    programme?: string;
    semester?: string;
    grade?: string;
    credits?: number;
    title?: string;
    meaning?: string;
  };
  status: string;
  excerpt: string;
  provenance: string;
  version: number;
};
type Detail = Source & {
  items: Item[];
  pages: { page: number; text: string; review: boolean }[];
  schema_fields: string[];
  conflicts: { relation: string; values: string[] }[];
  report: Record<string, number>;
};
const kinds = [
  "auto",
  "survey_json",
  "academic_transcript",
  "curriculum_template",
  "academic_notice",
  "general_academic_document",
];
function Survey({ doc }: { doc: Detail }) {
  const rows = doc.items.filter((x) => x.status !== "superseded"),
    [draft, setDraft] = useState<Record<string, string>>({}),
    [selected, setSelected] = useState<string[]>([]),
    action = useAction();
  const missing = doc.schema_fields.filter(
    (k) => !rows.some((r) => r.field === k),
  );
  function field(
    pointer: string,
    label: string,
    value: unknown,
    provenance: string,
  ) {
    const checked = selected.includes(pointer);
    return (
      <div className="survey-field" key={pointer}>
        <label className="check">
          <input
            aria-label={"Select " + label}
            type="checkbox"
            checked={checked}
            onChange={() =>
              setSelected(
                checked
                  ? selected.filter((p) => p !== pointer)
                  : [...selected, pointer],
              )
            }
          />
          {human(label)}
        </label>
        <label>
          <span className="sr-only">{pointer}</span>
          {typeof value === "boolean" ? (
            <select
              value={draft[pointer] ?? String(value)}
              onChange={(e) =>
                setDraft({ ...draft, [pointer]: e.target.value })
              }
            >
              <option>true</option>
              <option>false</option>
            </select>
          ) : (
            <input
              aria-label={pointer}
              value={draft[pointer] ?? String(value ?? "")}
              maxLength={600}
              onChange={(e) =>
                setDraft({ ...draft, [pointer]: e.target.value })
              }
            />
          )}
        </label>
        <small>
          {provenance} · {pointer}
        </small>
      </div>
    );
  }
  return (
    <section className="panel source-panel">
      <h2>Survey review</h2>
      <p>
        Select fields you can confirm. A confirmed skill level is recorded as a
        self-report.
      </p>
      {rows.map((r) =>
        field(r.locator, r.field, r.value.raw, human(r.provenance)),
      )}
      <details>
        <summary>Additional fields ({missing.length})</summary>
        {missing.map((k) => field("/" + k, k, "", "Missing"))}
      </details>
      <ErrorBox error={action.error} />
      <button
        className="primary"
        disabled={!selected.length || action.isPending}
        onClick={() => {
          const fields = selected.map((pointer) => {
            const old = rows.find((r) => r.locator === pointer)?.value.raw;
            const raw = draft[pointer];
            return {
              pointer,
              value:
                raw === undefined
                  ? (old ?? null)
                  : typeof old === "boolean"
                    ? raw === "true"
                    : typeof old === "number" && raw.trim() !== ""
                      ? Number(raw)
                      : raw,
            };
          });
          action.mutate(
            {
              path: "/sources/" + doc.id + "/confirm",
              body: { version: doc.version, fields },
            },
            {
              onSuccess: () => {
                setSelected([]);
                setDraft({});
              },
            },
          );
        }}
      >
        Confirm selected fields
      </button>
    </section>
  );
}
export function DataSources() {
  const { id } = useParams(),
    nav = useNavigate(),
    cache = useQueryClient(),
    list = useData<Source[]>("/sources", true, 3000),
    detail = useData<Detail>("/sources/" + id, !!id, 3000),
    graph = useData<{ state: string; pending: number }>(
      "/graph/status",
      true,
      5000,
    ),
    act = useAction();
  const [file, setFile] = useState<File | null>(null),
    [kind, setKind] = useState("auto"),
    [error, setError] = useState<Error | null>(null),
    [busy, setBusy] = useState(false),
    [erase, setErase] = useState(false),
    [filter, setFilter] = useState("");
  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      if (file.size > 16 * 1024 * 1024)
        throw Error("Choose a file smaller than 16 MiB.");
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      const res = await fetch(base + "/sources/upload", {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const err = await res.json();
        throw Error(
          typeof err.detail === "string" ? err.detail : "Invalid upload",
        );
      }
      const d: Source = await res.json();
      await cache.invalidateQueries();
      nav("/settings/sources/" + d.id);
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }
  const d = detail.data,
    items = d?.items.filter((i) => i.status !== "superseded") ?? [];
  const variants = Array.from(
    new Set(items.map((i) => i.value.programme).filter(Boolean)),
  ) as string[];
  return (
    <div className="page">
      <PageHead
        title="Data sources"
        description="Review local survey fields and academic documents."
        actions={
          <Link className="secondary" to="/settings">
            Settings
          </Link>
        }
      />
      <ErrorBox
        error={error || act.error || list.error || (id ? detail.error : null)}
      />
      <form
        className="panel source-panel"
        onSubmit={(e) => {
          e.preventDefault();
          void upload();
        }}
      >
        <label>
          Academic file
          <input
            aria-label="Academic file"
            type="file"
            required
            accept=".pdf,.json"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          Document type
          <select
            aria-label="Document type"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            {kinds.map((k) => (
              <option key={k} value={k}>
                {human(k)}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" disabled={!file || busy}>
          <Upload size={15} />
          Upload locally
        </button>
      </form>
      <div className="source-list">
        {list.data?.map((s) => (
          <Link
            className="secondary"
            key={s.id}
            to={"/settings/sources/" + s.id}
            onClick={() => setFilter("")}
          >
            <FolderOpen size={14} />
            {s.filename} · {s.status}
          </Link>
        ))}
      </div>
      {graph.data && (
        <p className="muted">
          {graph.data.state} · {graph.data.pending} pending graph updates{" "}
          <button
            className="text-button"
            onClick={() => act.mutate({ path: "/graph/reindex" })}
          >
            Reindex graph
          </button>
        </p>
      )}
      {id && detail.isPending ? (
        <Loading />
      ) : d ? (
        <>
          <section className="panel source-panel">
            <div className="section-title">
              <h2>{d.filename}</h2>
              <Pill>{d.status}</Pill>
            </div>
            <p>
              {human(d.kind)} · Revision {d.version}
            </p>
            <div className="inline">
              <a
                className="secondary"
                href={base + "/sources/" + id + "/original"}
                download={d.filename}
              >
                <Download size={14} />
                Original file
              </a>
              <button
                className="secondary"
                disabled={d.status === "queued" || d.status === "processing"}
                onClick={() =>
                  act.mutate({
                    path: "/sources/" + id + "/reprocess",
                    body: { kind },
                  })
                }
              >
                <RefreshCw size={14} />
                Reprocess as {human(kind)}
              </button>
              <button className="danger" onClick={() => setErase(true)}>
                <Trash2 size={14} />
                Delete source
              </button>
            </div>
            {d.conflicts.map((c) => (
              <p className="notice" key={c.relation}>
                {human(c.relation.toLowerCase())} · Conflicting values:{" "}
                {c.values.join(" / ")}
              </p>
            ))}
            {d.warnings.map((w, i) => (
              <p className="notice" key={i}>
                {w}
              </p>
            ))}
            <div className="inline">
              {Object.entries(d.report).map(([k, v]) => (
                <Pill key={k}>
                  {human(k)} · {v}
                </Pill>
              ))}
            </div>
          </section>
          {d.kind === "survey_json" && d.status === "ready" && (
            <Survey key={d.id} doc={d} />
          )}
          {d.kind !== "survey_json" && (
            <section className="panel source-panel">
              <h2>
                {d.kind === "curriculum_template"
                  ? "Programme reference"
                  : "Extracted academic records"}
              </h2>
              {variants.length > 0 && (
                <label>
                  Programme variant
                  <select
                    aria-label="Programme variant"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  >
                    <option value="">All variants</option>
                    {variants.map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </label>
              )}
              {items
                .filter((i) => !filter || i.value.programme === filter)
                .map((i) => (
                  <div className="source-row" key={i.id}>
                    <b>
                      {human(i.field)} · {String(i.value.raw)}
                    </b>
                    <p>{i.excerpt}</p>
                    <small>
                      {i.locator} · {i.status}
                      {i.value.semester
                        ? " · Semester " + i.value.semester
                        : ""}
                    </small>
                    {i.status === "review" && (
                      <div className="inline">
                        {["confirm", "reject"].map((decision) => (
                          <button
                            className="secondary"
                            key={decision}
                            onClick={() =>
                              act.mutate({
                                path:
                                  "/sources/" +
                                  d.id +
                                  "/rows/" +
                                  i.id +
                                  "/review",
                                body: { version: d.version, decision },
                              })
                            }
                          >
                            {human(decision)} row
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
            </section>
          )}
          <details className="panel source-panel">
            <summary>Source pages and revision history</summary>
            {d.pages.map((p) => (
              <details key={p.page}>
                <summary>Page {p.page}</summary>
                <pre>{p.text}</pre>
              </details>
            ))}
            {d.items.map((i) => (
              <p key={i.id}>
                v{i.version} · {i.locator} · {i.excerpt} · {i.status}
              </p>
            ))}
          </details>
        </>
      ) : (
        !list.data?.length && (
          <Empty title="No uploaded sources">
            Upload a survey JSON or academic PDF to begin.
          </Empty>
        )
      )}
      {erase && d && (
        <Modal title="Delete source?" close={() => setErase(false)}>
          <p>
            Remove the original file and its derived evidence from this
            workspace.
          </p>
          <button
            className="danger"
            onClick={() =>
              act.mutate(
                { path: "/sources/" + id, method: "DELETE" },
                {
                  onSuccess: () => {
                    setErase(false);
                    nav("/settings/sources");
                  },
                },
              )
            }
          >
            Delete file and evidence
          </button>
        </Modal>
      )}
    </div>
  );
}
export function PathInspector() {
  const [query, setQuery] = useState(""),
    action = useAction<{
      query: string;
      intent: string;
      normalized_query: string;
      direct: string[];
      semantic: string[];
      graph: string[];
      expansion: string[];
      rrf: { id: string; score: number }[];
      selected: {
        value: string;
        evidence: {
          filename?: string;
          location?: string;
          source_type: string;
        }[];
      }[];
      answer: string;
      graph_status: string;
      vector_status: string;
    }>();
  return (
    <details className="panel source-panel">
      <summary>Multi-source retrieval trace</summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          action.mutate({ path: "/retrieval/debug", body: { query } });
        }}
      >
        <label>
          Source query
          <input
            required
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <button className="secondary">Trace retrieval</button>
      </form>
      <ErrorBox error={action.error} />
      {action.data && (
        <>
          <h3>{action.data.intent}</h3>
          <p>{action.data.answer}</p>
          <small>
            {action.data.graph_status} · vectors {action.data.vector_status}
          </small>
          <pre>{JSON.stringify(action.data, null, 2)}</pre>
        </>
      )}
    </details>
  );
}
