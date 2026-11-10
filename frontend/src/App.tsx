import { useState } from "react";
import {
  BookMarked,
  CalendarDays,
  ChevronRight,
  CircleUserRound,
  Layers3,
  Menu,
  MessageSquare,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useAction, useData } from "./api";
import { ErrorBox, Logo } from "./ui";
import { ChatPage } from "./Chat";
import { DataSources } from "./DataSources";
import { MemoryPage, PersonaPage } from "./Memory";
import { CalendarPage } from "./Calendar";
import { SettingsPage } from "./Settings";
import type { Thread, Settings } from "./types";

const pages = [
  { url: "/chat", name: "Study chat", Icon: MessageSquare },
  { url: "/memory", name: "Memory Explorer", Icon: Layers3 },
  { url: "/persona", name: "Learner Persona", Icon: CircleUserRound },
  { url: "/calendar", name: "Local Calendar", Icon: CalendarDays },
];
export function App() {
  const [search, setSearch] = useState(""),
    [mobile, setMobile] = useState(false);
  const nav = useNavigate(),
    loc = useLocation(),
    create = useAction<Thread>();
  const threads = useData<Thread[]>(
      "/conversations" + (search ? "?q=" + encodeURIComponent(search) : ""),
    ),
    cfg = useData<Settings>("/settings");
  const page =
    pages.find((p) => loc.pathname.startsWith(p.url))?.name ?? "Settings";
  function newThread() {
    create.mutate(
      { path: "/conversations", body: {} },
      {
        onSuccess: (t) => {
          nav("/chat/" + t.id);
          setMobile(false);
        },
      },
    );
  }
  return (
    <div className="app-shell">
      <a className="skip" href="#main">
        Skip to content
      </a>
      {mobile && (
        <button
          className="scrim"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <Link className="brand" to="/chat" onClick={() => setMobile(false)}>
          <Logo />
          <span>Studyfolio</span>
        </Link>
        <button
          className="new-thread"
          onClick={newThread}
          disabled={create.isPending}
        >
          <Plus size={16} />
          New conversation
        </button>
        <ErrorBox error={create.error} />
        <div className="nav-label">Workspace</div>
        <nav aria-label="Workspace">
          {pages.map(({ url, name, Icon }) => (
            <NavLink key={url} to={url} onClick={() => setMobile(false)}>
              <Icon size={18} />
              {name}
            </NavLink>
          ))}
        </nav>
        <div className="side-divider" />
        <div className="nav-label">Conversations</div>
        <label className="side-search">
          <Search size={14} />
          <input
            aria-label="Search conversation history"
            placeholder="Search history"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button aria-label="Clear search" onClick={() => setSearch("")}>
              <X size={12} />
            </button>
          )}
        </label>
        <div className="thread-list">
          {threads.isPending ? (
            <p>Loading history…</p>
          ) : threads.isError ? (
            <ErrorBox error={threads.error} />
          ) : threads.data?.length ? (
            threads.data.map((t) => (
              <NavLink
                key={t.id}
                to={"/chat/" + t.id}
                onClick={() => setMobile(false)}
                title={t.title}
              >
                <MessageSquare size={13} />
                <span>
                  {t.synthetic ? "Demo · " : ""}
                  {t.title}
                </span>
              </NavLink>
            ))
          ) : (
            <p>
              {search
                ? "No matching conversations."
                : "Your conversations will appear here."}
            </p>
          )}
        </div>
        <div className="side-footer">
          <NavLink
            className="settings-link"
            to="/settings"
            onClick={() => setMobile(false)}
          >
            <Settings2 size={17} />
            Settings
          </NavLink>
          <div className="device">
            <span className="device-icon">
              <BookMarked size={18} />
            </span>
            <div>
              <strong>Local workspace</strong>
              <small>
                <i className="status-dot" />
                On this device
              </small>
            </div>
          </div>
        </div>
      </aside>
      <div className="content-shell">
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            aria-label="Open navigation"
            onClick={() => setMobile(true)}
          >
            <Menu size={19} />
          </button>
          <span className="crumb">Workspace</span>
          <ChevronRight size={13} />
          <b>{page}</b>
          <Link className="mode" to="/settings">
            <ShieldCheck size={14} />
            {cfg.isError
              ? "Service unavailable"
              : cfg.data?.mode === "model"
                ? "Model configured"
                : cfg.data
                  ? "Offline mode"
                  : "Connecting"}
          </Link>
        </header>
        <main id="main">
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat/:cid?" element={<ChatPage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/persona" element={<PersonaPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/settings/sources/:id?" element={<DataSources />} />
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
