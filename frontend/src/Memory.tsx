import { useState } from "react";
import { PathInspector } from "./DataSources";
import {
  Check,
  CircleUserRound,
  FileClock,
  Filter,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { displayDate, human, useAction, useData } from "./api";
import type {
  Memory,
  Message,
  Profile,
  Retrieval,
  Revision,
  Settings,
} from "./types";
import {
  Empty,
  ErrorBox,
  layers,
  Loading,
  Modal,
  PageHead,
  Pill,
  Sources,
} from "./ui";

const sections: Record<string, string> = {
  identity: "Identity",
  academic_profile: "Academic background",
  learning_preferences: "Learning preferences",
  goals: "Goals",
  behavioral_patterns: "Behavioral observations",
  interests: "Interests",
  constraints: "Constraints",
};
function MemoryCard({ item, zone }: { item: Memory; zone: string }) {
  const [editor, setEditor] = useState(""),
    [value, setValue] = useState(item.value ?? ""),
    [expanded, setExpanded] = useState(false);
  const change = useAction();
  const status =
    item.status === "active" &&
    item.valid_until &&
    new Date(item.valid_until) <= new Date()
      ? "expired"
      : item.status;
  const history = useData<Revision[]>(
    "/persona/history?assertion_id=" + item.id,
    expanded && item.layer === "persona",
  );
  function act(path: string, method: string, body?: unknown) {
    change.mutate({ path, method, body }, { onSuccess: () => setEditor("") });
  }
  function edit() {
    if (item.layer === "persona")
      act("/persona", "PATCH", {
        path: item.path,
        operation: "REPLACE",
        target_id: item.id,
        value,
        scope: item.scope,
      });
    else act("/memory/semantic/" + item.id, "PATCH", { value });
  }
  return (
    <article className="memory-card">
      <div className="card-top">
        <div className="pills">
          <Pill
            tone={
              status === "active"
                ? "green"
                : status === "pending"
                  ? "peach"
                  : "neutral"
            }
          >
            {human(status)}
          </Pill>
          <Pill>
            {item.manual
              ? "Learner confirmed"
              : human(item.basis ?? item.origin)}
          </Pill>
          {item.synthetic && <Pill tone="purple">Synthetic demo</Pill>}
        </div>
        <small>{displayDate(item.created_at, zone)}</small>
      </div>
      <h3>{item.layer === "persona" ? item.value : item.content}</h3>
      <p className="muted">
        {item.path
          ? human(item.path.split(".")[1])
          : item.category
            ? human(item.category)
            : "Learning episode"}
        {item.scope ? " · " + item.scope : ""} · Evidence score{" "}
        {item.confidence.toFixed(2)}
      </p>
      <Sources items={item.evidence} zone={zone} />
      <div className="card-actions">
        {item.layer !== "episodic" && (
          <button
            onClick={() => {
              setValue(item.value ?? "");
              setEditor("edit");
            }}
          >
            <Pencil size={13} />
            Edit
          </button>
        )}
        {item.layer === "persona" && (
          <>
            {(item.status !== "active" || !item.manual) && (
              <button
                disabled={change.isPending}
                onClick={() =>
                  act("/persona/assertions/" + item.id + "/confirm", "POST")
                }
              >
                <Check size={13} />
                Confirm
              </button>
            )}
            {item.status !== "rejected" && (
              <button
                disabled={change.isPending}
                onClick={() =>
                  act("/persona/assertions/" + item.id + "/reject", "POST")
                }
              >
                <X size={13} />
                Reject
              </button>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              aria-expanded={expanded}
            >
              <FileClock size={13} />
              History
            </button>
          </>
        )}
        {item.layer === "semantic" && (
          <>
            {item.status === "pending" && (
              <button
                onClick={() =>
                  act("/memory/semantic/" + item.id, "PATCH", {
                    status: "active",
                  })
                }
              >
                Confirm
              </button>
            )}
            {item.status !== "rejected" && (
              <button
                onClick={() =>
                  act("/memory/semantic/" + item.id, "PATCH", {
                    status: "rejected",
                  })
                }
              >
                Reject
              </button>
            )}
            <button onClick={() => setEditor("delete")}>
              <Trash2 size={13} />
              Forget
            </button>
          </>
        )}
      </div>
      {expanded && (
        <div className="revisions">
          <ErrorBox error={history.error} />
          {history.data?.map((r) => (
            <div key={r.id}>
              <b>{human(r.operation.toLowerCase())}</b> · {r.detail.value}
              <small>
                {r.detail.reason} · {displayDate(r.created_at, zone, true)}
              </small>
            </div>
          ))}
        </div>
      )}
      <ErrorBox error={change.error} />
      {editor && (
        <Modal
          title={editor === "edit" ? "Edit memory" : "Forget this memory?"}
          close={() => setEditor("")}
        >
          {editor === "edit" ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                edit();
              }}
            >
              <label>
                Value
                <textarea
                  aria-label="Value"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  required
                  maxLength={600}
                />
              </label>
              <button className="primary" disabled={change.isPending}>
                Save correction
              </button>
            </form>
          ) : (
            <>
              <p>
                The fact, its persona assertion, and its index entry will be
                removed. The original conversation stays in your history.
              </p>
              <button
                className="danger"
                onClick={() => act("/memory/semantic/" + item.id, "DELETE")}
              >
                Forget memory
              </button>
            </>
          )}
          <ErrorBox error={change.error} />
        </Modal>
      )}
    </article>
  );
}
function Inspector({ zone }: { zone: string }) {
  const [q, setQ] = useState(""),
    action = useAction<Retrieval>();
  return (
    <div className="panel inspector">
      <div className="rail-head">
        <SlidersHorizontal size={17} />
        <h2>Retrieval inspector</h2>
      </div>
      <form
        className="search-row"
        onSubmit={(e) => {
          e.preventDefault();
          action.mutate({ path: "/memory/search", body: { query: q } });
        }}
      >
        <label className="grow">
          Query
          <input
            placeholder="What do I remember about probability?"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            required
          />
        </label>
        <button className="primary" disabled={action.isPending}>
          Inspect
        </button>
      </form>
      <ErrorBox error={action.error} />
      {action.data && (
        <div className="inspector-results">
          <b>
            {action.data.tokens} / {action.data.budget} estimated tokens
          </b>
          {action.data.selected.length === 0 && (
            <p>No relevant memories in this context.</p>
          )}
          {action.data.selected.map((h) => (
            <div key={h.id}>
              <Pill tone="purple">{h.layer}</Pill> <b>{h.score.toFixed(2)}</b>
              <p>{h.content}</p>
              <small>
                {h.id} · {h.reasons.join(" · ")}
              </small>
              <Sources items={h.evidence} zone={zone} />
            </div>
          ))}
          <details>
            <summary>Excluded records ({action.data.excluded.length})</summary>
            {action.data.excluded.map((e) => (
              <p key={e.id}>
                {e.id} · {e.reason}
              </p>
            ))}
          </details>
        </div>
      )}
    </div>
  );
}
export function MemoryPage() {
  const [params, setParams] = useSearchParams(),
    key = params.get("layer") ?? "working";
  const [q, setQ] = useState(""),
    [status, setStatus] = useState(""),
    [inspect, setInspect] = useState(false);
  const settings = useData<Settings>("/settings"),
    zone = settings.data?.timezone ?? "Asia/Kolkata";
  const layer = layers.find((l) => l.key === key) ?? layers[0];
  const w = useData<Message[]>("/memory/short-term", key === "working"),
    p = useData<Profile>("/persona", key === "persona");
  const long = useData<Memory[]>(
    key === "episodic" ? "/memory/episodes" : "/memory/semantic",
    key === "episodic" || key === "semantic",
  );
  const req = key === "working" ? w : key === "persona" ? p : long;
  const memories =
    (key === "persona" ? p.data?.assertions : long.data)?.filter(
      (m) =>
        (!status || m.status === status) &&
        m.content.toLowerCase().includes(q.toLowerCase()),
    ) ?? [];
  const messages =
    w.data?.filter((m) => m.content.toLowerCase().includes(q.toLowerCase())) ??
    [];
  return (
    <div className="page">
      <PageHead
        title="Memory Explorer"
        description="Trace what your workspace remembers back to its source."
        actions={
          <button
            className="secondary"
            onClick={() => setInspect(!inspect)}
            aria-expanded={inspect}
          >
            <SlidersHorizontal size={15} />
            Inspect retrieval
          </button>
        }
      />
      {inspect && (
        <>
          <Inspector zone={zone} />
          <PathInspector />
        </>
      )}
      <div className="layer-tabs">
        {layers.map(({ key: k, label, color, Icon }) => (
          <button
            key={k}
            className={key === k ? "selected" : ""}
            onClick={() => setParams({ layer: k })}
          >
            <span className={"tile " + color}>
              <Icon size={17} />
            </span>
            {label}
          </button>
        ))}
      </div>
      <div className="filter-bar">
        <label className="search-box">
          <Search size={15} />
          <input
            aria-label="Search memories"
            placeholder="Search memories"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        {key !== "working" && (
          <label className="filter">
            <Filter size={14} />
            <select
              aria-label="Memory status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">All statuses</option>
              {["active", "pending", "superseded", "rejected", "archived"].map(
                (x) => (
                  <option key={x}>{x}</option>
                ),
              )}
            </select>
          </label>
        )}
      </div>
      <ErrorBox error={req.error} />
      {req.isPending ? (
        <Loading />
      ) : key === "working" ? (
        messages.length ? (
          messages.map((m) => (
            <article className="memory-card" key={m.id}>
              <Pill tone="peach">{human(m.role)} turn</Pill>
              {m.details.synthetic && <Pill tone="purple">Synthetic demo</Pill>}
              <p>{m.content}</p>
              <small>
                {m.status} · {displayDate(m.created_at, zone, true)}
              </small>
              <Sources
                items={[
                  {
                    message_id: m.id,
                    conversation_id: m.conversation_id,
                    timestamp: m.created_at,
                  },
                ]}
                zone={zone}
              />
            </article>
          ))
        ) : (
          <Empty icon="layers" title="No recent turns">
            Messages within the working-memory window appear here.
          </Empty>
        )
      ) : memories.length ? (
        memories.map((m) => <MemoryCard key={m.id} item={m} zone={zone} />)
      ) : (
        <Empty icon="layers" title={"No matching " + layer.label.toLowerCase()}>
          Try a different filter or add evidence through a conversation.
        </Empty>
      )}
    </div>
  );
}
export function PersonaPage() {
  const data = useData<Profile>("/persona", true, 4000),
    settings = useData<Settings>("/settings"),
    reflect = useAction<{ jobs: string[] }>(),
    edit = useAction();
  const [modal, setModal] = useState(false),
    [path, setPath] = useState("identity.name"),
    [val, setVal] = useState(""),
    [scope, setScope] = useState(""),
    [showHistory, setShowHistory] = useState(false);
  const zone = settings.data?.timezone ?? "Asia/Kolkata";
  function add() {
    edit.mutate(
      {
        path: "/persona",
        method: "PATCH",
        body: { operation: "ADD", path, value: val, scope },
      },
      {
        onSuccess: () => {
          setModal(false);
          setVal("");
          setScope("");
        },
      },
    );
  }
  return (
    <div className="page">
      <PageHead
        title="Learner Persona"
        description="An evidence-linked profile of your studies and preferences."
        actions={
          <button
            className="secondary"
            disabled={reflect.isPending}
            onClick={() => reflect.mutate({ path: "/persona/reflect" })}
          >
            <RefreshCw size={15} />
            Reflect on recent conversations
          </button>
        }
      />
      <ErrorBox error={data.error || reflect.error} />
      {reflect.isSuccess && (
        <p className="notice" role="status">
          {reflect.data.jobs.length
            ? "Reflection queued. Track progress in Settings."
            : "There are no conversations to reflect on."}
        </p>
      )}
      <div className="persona-summary">
        <span className="profile-avatar">
          <CircleUserRound size={30} />
        </span>
        <div>
          <h2>
            {typeof data.data?.profile.identity.name === "string"
              ? data.data.profile.identity.name
              : "Learner profile"}
          </h2>
          <p>
            {data.data?.assertions.filter(
              (a) =>
                a.status === "active" &&
                (!a.valid_until || new Date(a.valid_until) > new Date()),
            ).length ?? 0}{" "}
            current assertions
          </p>
        </div>
        <button className="secondary" onClick={() => setModal(true)}>
          <Plus size={15} />
          Add assertion
        </button>
      </div>
      <div className="filter-bar">
        <label className="check">
          <input
            type="checkbox"
            checked={showHistory}
            onChange={(e) => setShowHistory(e.target.checked)}
          />
          Include historical assertions
        </label>
      </div>
      {data.isPending ? (
        <Loading />
      ) : (
        data.data && (
          <div className="persona-grid">
            {Object.entries(sections).map(([k, title]) => {
              const items = data.data.assertions.filter(
                (a) =>
                  a.path?.startsWith(k + ".") &&
                  (showHistory ||
                    a.status === "pending" ||
                    (a.status === "active" &&
                      (!a.valid_until ||
                        new Date(a.valid_until) > new Date()))),
              );
              return (
                <section className="persona-section" key={k}>
                  <div className="section-title">
                    <h2>{title}</h2>
                    <button
                      className="icon-button"
                      aria-label={"Add " + title}
                      onClick={() => {
                        setPath(k + "." + Object.keys(data.data.profile[k])[0]);
                        setModal(true);
                      }}
                    >
                      <Plus size={15} />
                    </button>
                  </div>
                  {items.length ? (
                    items.map((a) => (
                      <MemoryCard item={a} key={a.id} zone={zone} />
                    ))
                  ) : (
                    <p className="section-empty">No recorded assertions.</p>
                  )}
                </section>
              );
            })}
          </div>
        )
      )}
      {modal && (
        <Modal title="Add persona assertion" close={() => setModal(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              add();
            }}
          >
            <label>
              Profile field
              <select value={path} onChange={(e) => setPath(e.target.value)}>
                {data.data &&
                  Object.entries(data.data.profile).map(([group, fields]) => (
                    <optgroup key={group} label={sections[group]}>
                      {Object.keys(fields).map((k) => (
                        <option key={k} value={group + "." + k}>
                          {human(k)}
                        </option>
                      ))}
                    </optgroup>
                  ))}
              </select>
            </label>
            <label>
              Value
              <textarea
                value={val}
                onChange={(e) => setVal(e.target.value)}
                required
                maxLength={600}
              />
            </label>
            <label>
              Applies to (optional)
              <input
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                maxLength={90}
              />
            </label>
            <ErrorBox error={edit.error} />
            <button className="primary" disabled={edit.isPending}>
              Save assertion
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}
