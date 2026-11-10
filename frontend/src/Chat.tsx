import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUp,
  BookOpen,
  CalendarDays,
  ChevronRight,
  Clock3,
  CornerDownLeft,
  Feather,
  Fingerprint,
  History,
  Layers3,
  ListChecks,
  MoreHorizontal,
  Pencil,
  Sparkles,
  Trash2,
} from "lucide-react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, displayDate, useAction, useData } from "./api";
import {
  ErrorBox,
  layers,
  Loading,
  Modal,
  PageHead,
  Pill,
  Sources,
} from "./ui";
import type {
  CalendarItem,
  Memory,
  Message,
  Profile,
  Settings,
  Thread,
} from "./types";

const prompts = [
  {
    Icon: History,
    title: "Recall a study session",
    text: "What topics did I struggle with last week?",
  },
  {
    Icon: CalendarDays,
    title: "Check my deadlines",
    text: "Which assignments do I have this week?",
  },
  {
    Icon: Fingerprint,
    title: "Recall my preferences",
    text: "What do you remember about my study preferences?",
  },
];
function MemoryArt() {
  return (
    <div className="memory-art" aria-hidden="true">
      <div className="orbit o1" />
      <div className="orbit o2" />
      <div className="orbit o3" />
      <div className="paper-stack">
        <i />
        <i />
        <span>
          <i />
          <i />
          <i />
          <b />
        </span>
      </div>
      <span className="star s1">✦</span>
      <span className="star s2">✧</span>
      <span className="star s3">✧</span>
    </div>
  );
}
function ContextRail({ zone, cid }: { zone: string; cid?: string }) {
  const semantic = useData<Memory[]>("/memory/semantic?status=active"),
    eps = useData<Memory[]>("/memory/episodes?status=active"),
    p = useData<Profile>("/persona"),
    w = useData<Message[]>(
      "/memory/short-term" + (cid ? "?conversation_id=" + cid : ""),
    ),
    events = useData<CalendarItem[]>("/calendar/upcoming");
  const counts = [
    w.data?.length,
    eps.data?.length,
    semantic.data?.length,
    p.data?.assertions.filter(
      (a) =>
        a.status === "active" &&
        (!a.valid_until || new Date(a.valid_until) > new Date()),
    ).length,
  ];
  return (
    <aside className="context-rail">
      <section className="panel">
        <div className="rail-head">
          <Layers3 size={17} />
          <h2>Memory overview</h2>
        </div>
        <div className="layer-list">
          {layers.map(({ key, label, Icon, color }, i) => (
            <Link to={"/memory?layer=" + key} key={key}>
              <span className={"tile " + color}>
                <Icon size={15} />
              </span>
              <span>{label}</span>
              <b>{counts[i] ?? "–"}</b>
            </Link>
          ))}
        </div>
        <ErrorBox error={w.error || eps.error || semantic.error || p.error} />
        <Link className="panel-link" to="/memory">
          Explore memory
          <ArrowRight size={13} />
        </Link>
      </section>
      <section className="panel">
        <div className="rail-head">
          <CalendarDays size={17} />
          <h2>Upcoming deadlines</h2>
        </div>
        <ErrorBox error={events.error} />
        {events.isPending ? (
          <Loading />
        ) : events.data?.length ? (
          <div className="mini-events">
            {events.data.slice(0, 3).map((e) => (
              <Link key={e.id} to={"/calendar?event=" + e.id}>
                <b>{e.title}</b>
                <small>
                  {e.start_utc
                    ? displayDate(e.start_utc, zone, true)
                    : e.local_date}
                </small>
              </Link>
            ))}
          </div>
        ) : (
          <div className="rail-empty">
            <span className="calendar-tile">
              <CalendarDays size={21} />
            </span>
            <strong>No upcoming deadlines</strong>
            <p>Confirmed events appear here.</p>
          </div>
        )}
        <Link className="panel-link" to="/calendar">
          Open calendar
          <ArrowRight size={13} />
        </Link>
      </section>
    </aside>
  );
}
export function ChatPage() {
  const { cid } = useParams(),
    nav = useNavigate(),
    location = useLocation(),
    client = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, string>>({}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<Error | null>(null),
    [menu, setMenu] = useState(false),
    [modal, setModal] = useState(""),
    [title, setTitle] = useState("");
  const draftKey = cid ?? "new",
    draft = drafts[draftKey] ?? "";
  const setDraft = (text: string) =>
    setDrafts((old) => ({ ...old, [draftKey]: text }));
  const input = useRef<HTMLTextAreaElement>(null),
    bottom = useRef<HTMLDivElement>(null),
    request = useRef<{ cid: string; content: string; key: string } | null>(
      null,
    );
  const thread = useData<Thread>("/conversations/" + cid, !!cid),
    history = useData<Message[]>(
      "/conversations/" + cid + "/messages",
      !!cid,
      cid ? 3000 : undefined,
    ),
    config = useData<Settings>("/settings"),
    action = useAction();
  const zone = config.data?.timezone ?? "Asia/Kolkata",
    list = history.data ?? [],
    closed = thread.data?.closed;
  useEffect(() => {
    setMenu(false);
    setModal("");
    setError(null);
  }, [cid]);
  useEffect(() => {
    if (location.hash) {
      const el = document.getElementById(location.hash.slice(1));
      el?.scrollIntoView?.({ block: "center" });
    } else if (list.length) {
      bottom.current?.scrollIntoView?.({ block: "nearest" });
    }
  }, [cid, list.length, location.hash]);
  async function send() {
    const content = draft.trim();
    if (!content || busy) return;
    setBusy(true);
    setError(null);
    setDraft("");
    let id = cid;
    try {
      if (!id) {
        const t = await api<Thread>("/conversations", "POST", {});
        id = t.id;
        nav("/chat/" + id);
      }
      if (request.current?.cid !== id || request.current.content !== content)
        request.current = { cid: id, content, key: crypto.randomUUID() };
      await api("/chat", "POST", {
        conversation_id: id,
        content,
        request_key: request.current.key,
      });
      request.current = null;
      await client.invalidateQueries();
    } catch (e) {
      const key = id ?? draftKey;
      setDrafts((old) => ({ ...old, [key]: old[key] || content }));
      setError(e as Error);
      await client.invalidateQueries();
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }
  function threadAction(path: string, method: string, body?: unknown) {
    action.mutate(
      { path, method, body },
      {
        onSuccess: () => {
          setMenu(false);
          setModal("");
          if (method === "DELETE") nav("/chat");
        },
      },
    );
  }
  return (
    <div className="page chat-page">
      <PageHead
        title="Study chat"
        description="Your conversations, connected across learning sessions."
        actions={
          cid && (
            <div className="menu-wrap">
              <button
                className="secondary"
                onClick={() => setMenu(!menu)}
                aria-expanded={menu}
              >
                <MoreHorizontal size={16} />
                Conversation
              </button>
              {menu && (
                <div className="menu">
                  <button
                    onClick={() => {
                      setTitle(thread.data?.title ?? "");
                      setModal("rename");
                      setMenu(false);
                    }}
                  >
                    <Pencil size={14} />
                    Rename
                  </button>
                  <button
                    onClick={() =>
                      threadAction("/conversations/" + cid, "PATCH", {
                        closed: !closed,
                      })
                    }
                  >
                    <BookOpen size={14} />
                    {closed ? "Reopen" : "Close & reflect"}
                  </button>
                  <button
                    onClick={() =>
                      threadAction(
                        "/conversations/" + cid + "/reprocess",
                        "POST",
                      )
                    }
                  >
                    <ListChecks size={14} />
                    Reprocess history
                  </button>
                  <button onClick={() => setModal("delete")}>
                    <Trash2 size={14} />
                    Delete conversation
                  </button>
                </div>
              )}
            </div>
          )
        }
      />
      <div className="chat-layout">
        <div className="chat-column">
          <ErrorBox
            error={error || action.error || thread.error || history.error}
          />
          {cid && history.isPending ? (
            <Loading />
          ) : list.length === 0 ? (
            <>
              <div className="welcome">
                <div className="welcome-text">
                  <span className="welcome-tag">
                    <CalendarDays size={14} />
                    {new Intl.DateTimeFormat("en", {
                      weekday: "long",
                      month: "long",
                      day: "numeric",
                      timeZone: zone,
                    }).format(new Date())}
                  </span>
                  <h2>
                    What are we
                    <br />
                    studying today?
                  </h2>
                  <p>
                    Pick up a thread, work through a concept, or keep track of a
                    deadline.
                  </p>
                </div>
                <MemoryArt />
              </div>
              <div className="prompt-title">
                <Sparkles size={14} />
                <h3>Start with a question</h3>
              </div>
              <div className="prompt-grid">
                {prompts.map(({ title, text, Icon }) => (
                  <button
                    key={title}
                    onClick={() => {
                      setDraft(text);
                      input.current?.focus();
                    }}
                  >
                    <Icon size={18} />
                    <span>{title}</span>
                    <ChevronRight size={13} />
                  </button>
                ))}
              </div>
            </>
          ) : (
            <section className="transcript" aria-label="Message history">
              <div className="thread-heading">
                <BookOpen size={16} />
                <h2>{thread.data?.title}</h2>
                {thread.data?.synthetic && (
                  <Pill tone="purple">Synthetic demo</Pill>
                )}
              </div>
              {list.map((m) => (
                <article
                  key={m.id}
                  id={"m-" + m.id}
                  data-source={
                    location.hash === "#m-" + m.id ? "selected" : undefined
                  }
                  className={"message " + m.role}
                >
                  <header>
                    <span className={"avatar " + m.role}>
                      {m.role === "user" ? "Y" : <Feather size={13} />}
                    </span>
                    <strong>{m.role === "user" ? "You" : "Studyfolio"}</strong>
                    <small>{displayDate(m.created_at, zone, true)}</small>
                  </header>
                  <p>{m.content}</p>
                  <div className="message-meta">
                    {m.role === "user" ? m.status : m.details.mode}
                  </div>
                  {m.details.sources?.length ? (
                    <details>
                      <summary>
                        View sources ({m.details.sources.length})
                      </summary>
                      {m.details.sources.map((h) => (
                        <div key={h.id}>
                          <small>{h.layer}</small>
                          <Sources items={h.evidence} zone={zone} />
                        </div>
                      ))}
                    </details>
                  ) : null}
                </article>
              ))}
              <div ref={bottom} />
            </section>
          )}
          <div className="composer-wrap">
            {closed ? (
              <div className="panel closed">
                <p>This conversation is closed.</p>
                <button
                  className="secondary"
                  onClick={() =>
                    threadAction("/conversations/" + cid, "PATCH", {
                      closed: false,
                    })
                  }
                >
                  Reopen conversation
                </button>
              </div>
            ) : (
              <form
                className="composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  void send();
                }}
              >
                <label htmlFor="message" className="sr-only">
                  Your message
                </label>
                <textarea
                  ref={input}
                  id="message"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !e.nativeEvent.isComposing
                    ) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  placeholder="Message your learning workspace…"
                  maxLength={16000}
                />
                <div className="composer-bar">
                  <span>
                    <CornerDownLeft size={13} /> Enter to send
                  </span>
                  <button
                    className="send"
                    aria-label="Send message"
                    disabled={busy || !draft.trim()}
                  >
                    <ArrowUp size={18} />
                    {busy ? "Saving…" : "Send"}
                  </button>
                </div>
              </form>
            )}
            <div className="privacy-line">
              <Clock3 size={12} />
              {config.data?.mode === "model"
                ? "Model enabled · Selected context is sent to your provider."
                : "Offline mode · Replies use your saved sources."}
            </div>
          </div>
        </div>
        <ContextRail cid={cid} zone={zone} />
      </div>
      {modal && (
        <Modal
          title={
            modal === "rename" ? "Rename conversation" : "Delete conversation?"
          }
          close={() => setModal("")}
        >
          {modal === "rename" ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                threadAction("/conversations/" + cid, "PATCH", { title });
              }}
            >
              <label>
                Title
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  maxLength={250}
                />
              </label>
              <button className="primary">Save title</button>
            </form>
          ) : (
            <>
              <p>
                Its messages, derived memories, and calendar records linked to
                its evidence will be removed.
              </p>
              <button
                className="danger"
                onClick={() => threadAction("/conversations/" + cid, "DELETE")}
              >
                Delete conversation
              </button>
            </>
          )}
          <ErrorBox error={action.error} />
        </Modal>
      )}
    </div>
  );
}
