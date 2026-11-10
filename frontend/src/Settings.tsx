import { useState } from "react";
import { Link } from "react-router-dom";
import {
  CalendarDays,
  Database,
  Download,
  HardDrive,
  Layers3,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { base, human, useAction, useData } from "./api";
import { ErrorBox, Loading, Modal, PageHead, Pill } from "./ui";
import type { Job, Settings } from "./types";

function ConfigForm({ settings: s }: { settings: Settings }) {
  const save = useAction<Settings>(),
    [draft, setDraft] = useState(s),
    [saved, setSaved] = useState(false);
  function field<K extends keyof Settings>(k: K, v: Settings[K]) {
    setDraft((d) => ({ ...d, [k]: v }));
    setSaved(false);
  }
  function submit() {
    const {
      timezone,
      max_messages,
      max_tokens,
      window_hours,
      reflection_threshold,
      require_confirmation,
      auto_explicit,
    } = draft;
    save.mutate(
      {
        path: "/settings",
        method: "PATCH",
        body: {
          timezone,
          max_messages,
          max_tokens,
          window_hours,
          reflection_threshold,
          require_confirmation,
          auto_explicit,
        },
      },
      { onSuccess: () => setSaved(true) },
    );
  }
  return (
    <form
      className="panel settings-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="rail-head">
        <SlidersHorizontal size={17} />
        <h2>Workspace preferences</h2>
      </div>
      <div className="settings-fields">
        <label>
          Timezone
          <input
            required
            value={draft.timezone}
            onChange={(e) => field("timezone", e.target.value)}
          />
          <small>IANA timezone, such as Asia/Kolkata.</small>
        </label>
        <div className="form-pair">
          <label>
            Recent message limit
            <input
              type="number"
              min={1}
              max={100}
              value={draft.max_messages}
              onChange={(e) => field("max_messages", Number(e.target.value))}
            />
          </label>
          <label>
            Context token budget
            <input
              type="number"
              min={32}
              max={16000}
              value={draft.max_tokens}
              onChange={(e) => field("max_tokens", Number(e.target.value))}
            />
          </label>
        </div>
        <div className="form-pair">
          <label>
            Working window (hours)
            <input
              type="number"
              min={1}
              max={720}
              value={draft.window_hours}
              onChange={(e) => field("window_hours", Number(e.target.value))}
            />
          </label>
          <label>
            Reflect after how many turns?
            <input
              type="number"
              min={1}
              max={100}
              value={draft.reflection_threshold}
              onChange={(e) =>
                field("reflection_threshold", Number(e.target.value))
              }
            />
          </label>
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.require_confirmation}
            onChange={(e) => field("require_confirmation", e.target.checked)}
          />
          Review passively detected academic dates
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.auto_explicit}
            onChange={(e) => field("auto_explicit", e.target.checked)}
          />
          Auto-confirm unambiguous “add to calendar” commands
        </label>
        <ErrorBox error={save.error} />
        <div className="inline">
          <button className="primary" disabled={save.isPending}>
            Save preferences
          </button>
          {saved && <span role="status">Preferences saved.</span>}
        </div>
      </div>
    </form>
  );
}
export function SettingsPage() {
  const cfg = useData<Settings>("/settings", true, 6000),
    jobs = useData<Job[]>("/jobs", true, 3000),
    action = useAction(),
    [modal, setModal] = useState(false),
    [confirm, setConfirm] = useState(""),
    [status, setStatus] = useState("");
  function run(path: string, body: unknown, note: string) {
    action.mutate({ path, body }, { onSuccess: () => setStatus(note) });
  }
  return (
    <div className="page">
      <PageHead
        title="Settings"
        actions={
          <Link className="secondary" to="/settings/sources">
            Data sources
          </Link>
        }
        description="Manage local storage, memory processing, and calendar preferences."
      />
      <ErrorBox error={cfg.error || jobs.error || action.error} />
      {cfg.isPending ? (
        <Loading />
      ) : (
        cfg.data && (
          <>
            <div className="status-cards">
              <div className="panel status-card">
                <ShieldCheck size={19} />
                <small>Inference</small>
                <strong>
                  {cfg.data.mode === "offline"
                    ? "Offline mode"
                    : cfg.data.model}
                </strong>
                <p>
                  {cfg.data.mode === "offline"
                    ? "Deterministic extraction and source-based replies."
                    : "Selected conversation content is sent to the configured provider."}
                </p>
              </div>
              <div className="panel status-card">
                <Database size={19} />
                <small>Retrieval</small>
                <strong>
                  {cfg.data.vector_status === "ready"
                    ? "Chroma + SQLite"
                    : "SQLite lexical search"}
                </strong>
                <p>Vector index · {cfg.data.vector_status}</p>
              </div>
              <div className="panel status-card">
                <HardDrive size={19} />
                <small>Calendar storage</small>
                <strong>Local SQLite</strong>
                <p>{cfg.data.timezone}</p>
              </div>
            </div>
            <ConfigForm settings={cfg.data} />
          </>
        )
      )}
      <div className="settings-grid">
        <section className="panel">
          <div className="rail-head">
            <Layers3 size={17} />
            <h2>Memory processing</h2>
          </div>
          <div className="settings-actions">
            <button
              className="secondary"
              disabled={action.isPending}
              onClick={() =>
                run(
                  "/memory/reflect",
                  {},
                  "Reflection request processed. Check the jobs below.",
                )
              }
            >
              <RefreshCw size={14} />
              Reflect now
            </button>
            <button
              className="secondary"
              disabled={action.isPending}
              onClick={() =>
                run(
                  "/memory/rebuild",
                  { history: false },
                  "Index repair requested.",
                )
              }
            >
              <Database size={14} />
              Rebuild index
            </button>
            <button
              className="secondary"
              disabled={action.isPending}
              onClick={() =>
                run(
                  "/memory/rebuild",
                  { history: true },
                  "Saved conversations queued for reprocessing.",
                )
              }
            >
              Reprocess history
            </button>
          </div>
        </section>
        <section className="panel">
          <div className="rail-head">
            <HardDrive size={17} />
            <h2>Local data</h2>
          </div>
          <div className="settings-actions">
            <a href={base + "/data/export"} download className="secondary">
              <Download size={14} />
              Export workspace JSON
            </a>
            <a
              href={base + "/calendar/export.ics"}
              download
              className="secondary"
            >
              <CalendarDays size={14} />
              Export calendar ICS
            </a>
            <button className="danger" onClick={() => setModal(true)}>
              <Trash2 size={14} />
              Erase local data
            </button>
          </div>
        </section>
      </div>
      {status && (
        <p className="notice" role="status">
          {status}
        </p>
      )}
      <section className="panel jobs">
        <div className="rail-head">
          <RefreshCw size={16} />
          <h2>Processing jobs</h2>
        </div>
        {jobs.data?.length ? (
          jobs.data.slice(0, 20).map((j) => (
            <div key={j.id} className="job">
              <span>{human(j.kind)}</span>
              <Pill tone={j.status === "done" ? "green" : "peach"}>
                {j.status}
              </Pill>
              {j.error && <small>{j.error}</small>}
              {j.status === "failed" && (
                <button
                  className="text-button"
                  onClick={() =>
                    run("/jobs/" + j.id + "/retry", {}, "Job queued.")
                  }
                >
                  Retry
                </button>
              )}
            </div>
          ))
        ) : (
          <p className="section-empty">No processing jobs yet.</p>
        )}
      </section>
      {modal && (
        <Modal title="Erase local data?" close={() => setModal(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action.mutate(
                { path: "/data?confirm=DELETE", method: "DELETE" },
                {
                  onSuccess: () => {
                    setModal(false);
                    setConfirm("");
                    setStatus("Local workspace data erased.");
                  },
                },
              );
            }}
          >
            <p>
              This permanently removes conversations, derived memories, calendar
              entries, and their local index records.
            </p>
            <label>
              Type DELETE to confirm
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </label>
            <ErrorBox error={action.error} />
            <button
              className="danger"
              disabled={confirm !== "DELETE" || action.isPending}
            >
              Erase data
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}
