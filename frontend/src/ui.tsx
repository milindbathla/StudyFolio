import { useEffect, useRef, type ReactNode } from "react";
import {
  BookOpen,
  CalendarDays,
  CircleAlert,
  Database,
  ExternalLink,
  Fingerprint,
  History,
  Layers3,
  MessagesSquare,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { displayDate } from "./api";
import type { Evidence } from "./types";

export const layers = [
  {
    key: "working",
    label: "Working memory",
    Icon: MessagesSquare,
    color: "peach",
  },
  { key: "episodic", label: "Episodic memory", Icon: History, color: "blue" },
  { key: "semantic", label: "Semantic memory", Icon: Database, color: "green" },
  {
    key: "persona",
    label: "Persona assertions",
    Icon: Fingerprint,
    color: "purple",
  },
];
export function Logo() {
  return (
    <span className="logo" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );
}
export function ErrorBox({ error }: { error?: Error | null }) {
  return error ? (
    <div role="alert" className="error">
      <CircleAlert size={16} />
      {error.message}
    </div>
  ) : null;
}
export function Loading() {
  return (
    <div className="loading" role="status">
      Loading workspace…
    </div>
  );
}
export function Empty({
  title,
  children,
  icon = "book",
}: {
  title: string;
  children?: ReactNode;
  icon?: "book" | "calendar" | "layers";
}) {
  const Icon =
    icon === "book" ? BookOpen : icon === "calendar" ? CalendarDays : Layers3;
  return (
    <div className="empty">
      <Icon size={24} />
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Sources({
  items,
  zone = "Asia/Kolkata",
}: {
  items: Evidence[];
  zone?: string;
}) {
  return (
    <div className="source-list">
      {items.map((e) => (
        <Link
          className="source-link"
          key={e.message_id}
          to={
            e.document_id
              ? "/settings/sources/" + e.document_id
              : "/chat/" + e.conversation_id + "#m-" + e.message_id
          }
          title={e.span}
        >
          <ExternalLink size={12} />
          {e.document_id
            ? e.filename + " · " + e.location
            : "Source · " + displayDate(e.timestamp, zone)}
        </Link>
      ))}
    </div>
  );
}
export function Pill({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={"pill " + tone}>{children}</span>;
}
export function PageHead({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      <div className="head-actions">{actions}</div>
    </div>
  );
}
export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button
          className="icon-button"
          aria-label="Close dialog"
          onClick={close}
        >
          <X size={18} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
