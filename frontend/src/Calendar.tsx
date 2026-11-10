import { useRef, useState } from "react";
import {
  CalendarCheck2,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  FileUp,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { base, dayInZone, human, useAction, useData } from "./api";
import type { CalendarItem, Settings } from "./types";
import { Empty, ErrorBox, Loading, Modal, PageHead, Pill } from "./ui";

const categories = [
  "assignment",
  "exam",
  "quiz",
  "project",
  "meeting",
  "registration",
  "milestone",
];
function eventDay(e: CalendarItem, zone: string) {
  return e.start_utc ? dayInZone(e.start_utc, zone) : e.local_date;
}
function clock(instant: string | null, zone: string) {
  return instant
    ? new Intl.DateTimeFormat("en-GB", {
        timeZone: zone,
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(new Date(instant))
    : "";
}
function plainDate(d: Date) {
  return d.toISOString().slice(0, 10);
}
function monthText(d: Date) {
  return d.toLocaleDateString("en", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}
function Source({ item }: { item: CalendarItem }) {
  if (item.source_document_id)
    return (
      <Link
        className="source-link"
        to={"/settings/sources/" + item.source_document_id}
      >
        <ExternalLink size={12} />
        Source · {item.source_location}
      </Link>
    );
  return item.source_id && item.source_conversation_id ? (
    <Link
      className="source-link"
      to={"/chat/" + item.source_conversation_id + "#m-" + item.source_id}
    >
      <ExternalLink size={12} />
      Source conversation
    </Link>
  ) : null;
}
function Editor({
  item,
  defaultDay,
  zone,
  review = false,
  events,
  close,
}: {
  item?: CalendarItem;
  defaultDay: string;
  zone: string;
  review?: boolean;
  events: CalendarItem[];
  close: () => void;
}) {
  const tz = item?.timezone ?? zone;
  const [title, setTitle] = useState(item?.title ?? ""),
    [category, setCategory] = useState(item?.category ?? "assignment"),
    [date, setDate] = useState(item?.local_date ?? defaultDay),
    [time, setTime] = useState(clock(item?.start_utc ?? null, tz)),
    [end, setEnd] = useState(clock(item?.end_utc ?? null, tz)),
    [desc, setDesc] = useState(item?.description ?? ""),
    [target, setTarget] = useState(item?.target_id ?? "");
  const action = useAction();
  function save() {
    const body = {
      title,
      category,
      date,
      time: time || null,
      end_time: end || null,
      timezone: tz,
      description: desc,
    };
    action.mutate(
      {
        path: review
          ? "/calendar/candidates/" + item?.id + "/confirm"
          : "/calendar/events" + (item ? "/" + item.id : ""),
        method: review || !item ? "POST" : "PATCH",
        body: review ? { event: body, target_id: target || null } : body,
      },
      { onSuccess: close },
    );
  }
  return (
    <Modal
      title={
        review ? "Review suggestion" : item ? "Edit event" : "Create event"
      }
      close={close}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        {review && item?.parsed.review && (
          <p className="notice">{item.parsed.review}</p>
        )}
        <label>
          Event title
          <input
            value={title}
            required
            onChange={(e) => setTitle(e.target.value)}
            maxLength={250}
          />
        </label>
        <div className="form-pair">
          <label>
            Category
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {categories.map((x) => (
                <option key={x} value={x}>
                  {human(x)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Date
            <input
              type="date"
              value={date}
              required
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
        </div>
        <div className="form-pair">
          <label>
            Start time (optional)
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />
          </label>
          <label>
            End time (optional)
            <input
              type="time"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
        </div>
        <small>
          Times use {tz}. Leave the start time blank for an all-day event.
        </small>
        <label>
          Description
          <textarea
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            maxLength={3000}
          />
        </label>
        {item?.parsed.possible_targets?.length ? (
          <label>
            Deadline to update
            <select
              required
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">Select a deadline</option>
              {events
                .filter((e) => item.parsed.possible_targets!.includes(e.id))
                .map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.title} · {e.local_date}
                  </option>
                ))}
            </select>
          </label>
        ) : null}
        <ErrorBox error={action.error} />
        <button className="primary" disabled={action.isPending}>
          {review ? "Confirm event" : "Save event"}
        </button>
      </form>
    </Modal>
  );
}
function Agenda({
  items,
  zone,
  select,
}: {
  items: CalendarItem[];
  zone: string;
  select: (i: CalendarItem) => void;
}) {
  return items.length ? (
    <div className="agenda">
      {items.map((e) => (
        <button className="agenda-row" key={e.id} onClick={() => select(e)}>
          <span className={"category-dot " + e.category} />
          <div>
            <b>{e.title}</b>
            <small>
              {e.synthetic ? "Synthetic demo · " : ""}
              {human(e.category)} · {eventDay(e, zone)}{" "}
              {e.start_utc && clock(e.start_utc, zone)}
            </small>
          </div>
          <ChevronRight size={15} />
        </button>
      ))}
    </div>
  ) : (
    <Empty icon="calendar" title="No confirmed events">
      Add an event or confirm a suggestion from a conversation.
    </Empty>
  );
}
export function CalendarPage() {
  const cfg = useData<Settings>("/settings"),
    zone = cfg.data?.timezone ?? "Asia/Kolkata",
    today = dayInZone(new Date(), zone);
  const [month, setMonth] = useState(today.slice(0, 7)),
    [tab, setTab] = useState("Month"),
    [category, setCategory] = useState(""),
    [search, setSearch] = useState(""),
    [editor, setEditor] = useState<null | {
      day: string;
      item?: CalendarItem;
      review?: boolean;
    }>(null),
    [erase, setErase] = useState(false),
    [notice, setNotice] = useState("");
  const [params, setParams] = useSearchParams(),
    input = useRef<HTMLInputElement>(null);
  const events = useData<CalendarItem[]>("/calendar/events"),
    pending = useData<CalendarItem[]>("/calendar/candidates", true, 5000),
    late = useData<CalendarItem[]>(
      "/calendar/events?overdue=true",
      tab === "Overdue",
    ),
    upcoming = useData<CalendarItem[]>(
      "/calendar/upcoming",
      tab === "Upcoming",
    );
  const action = useAction(),
    upload = useAction<{
      accepted: string[];
      errors: { line: number; error: string }[];
    }>();
  const all = events.data ?? [],
    selected = all.find((e) => e.id === params.get("event"));
  const list =
    (tab === "Overdue"
      ? late.data
      : tab === "Upcoming"
        ? upcoming.data
        : all
    )?.filter(
      (e) =>
        (!category || e.category === category) &&
        (e.title + " " + e.description)
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) ?? [];
  const first = new Date(month + "-01T12:00:00Z"),
    offset = (first.getUTCDay() + 6) % 7;
  const length = new Date(
    Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0),
  ).getUTCDate();
  const dates = Array.from(
    { length: Math.ceil((offset + length) / 7) * 7 },
    (_, i) =>
      plainDate(
        new Date(
          Date.UTC(
            first.getUTCFullYear(),
            first.getUTCMonth(),
            1 - offset + i,
            12,
          ),
        ),
      ),
  );
  function shift(n: number) {
    setMonth(
      plainDate(
        new Date(
          Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + n, 1, 12),
        ),
      ).slice(0, 7),
    );
  }
  function review(c: CalendarItem) {
    if (c.needs_review) {
      setEditor({ day: c.local_date ?? today, item: c, review: true });
      return;
    }
    action.mutate(
      { path: "/calendar/candidates/" + c.id + "/confirm", body: {} },
      { onSuccess: () => setNotice("Event confirmed.") },
    );
  }
  async function importFile(f?: File) {
    if (!f) return;
    try {
      if (f.size > 500000) throw new Error("Choose a CSV smaller than 500 KB.");
      const content = await f.text();
      upload.mutate({ path: "/calendar/import/csv", body: { content } });
    } catch (err) {
      setNotice((err as Error).message);
    }
  }
  return (
    <div className="page">
      <PageHead
        title="Local Calendar"
        description="Academic dates and deadlines, saved on this device."
        actions={
          <button className="primary" onClick={() => setEditor({ day: today })}>
            <Plus size={16} />
            Create event
          </button>
        }
      />
      <div className="calendar-tools">
        <div className="view-switch">
          {["Month", "Agenda", "Upcoming", "Overdue"].map((t) => (
            <button
              className={t === tab ? "selected" : ""}
              key={t}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="inline">
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            aria-label="CSV file"
            onChange={(e) => {
              void importFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <button
            className="text-button"
            onClick={() => input.current?.click()}
          >
            <FileUp size={15} />
            Import CSV
          </button>
          <a
            className="text-button"
            href={base + "/calendar/export.ics"}
            download
          >
            <Download size={15} />
            Export ICS
          </a>
        </div>
      </div>
      <ErrorBox
        error={
          events.error ||
          pending.error ||
          action.error ||
          upload.error ||
          late.error ||
          upcoming.error
        }
      />
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {upload.data && (
        <div className="notice" role="status">
          {upload.data.accepted.length} valid rows processed.
          {upload.data.errors.map((e) => (
            <p key={e.line}>
              Row {e.line} · {e.error}
            </p>
          ))}
        </div>
      )}
      <div className="filter-bar">
        <label className="search-box">
          <Search size={15} />
          <input
            aria-label="Search events"
            placeholder="Search events"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <select
          aria-label="Event category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          {categories.map((k) => (
            <option key={k} value={k}>
              {human(k)}
            </option>
          ))}
        </select>
        <small>{zone}</small>
      </div>
      {events.isPending ? (
        <Loading />
      ) : tab === "Month" ? (
        <section className="month-panel">
          <div className="month-heading">
            <h2>{monthText(first)}</h2>
            <div className="inline">
              <button
                className="icon-button"
                aria-label="Previous month"
                onClick={() => shift(-1)}
              >
                <ChevronLeft size={16} />
              </button>
              <button
                className="secondary small"
                onClick={() => setMonth(today.slice(0, 7))}
              >
                Today
              </button>
              <button
                className="icon-button"
                aria-label="Next month"
                onClick={() => shift(1)}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
          <div className="month-grid">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((x) => (
              <div className="weekday" key={x}>
                {x}
              </div>
            ))}
            {dates.map((d) => (
              <div
                key={d}
                className={"day " + (d.slice(0, 7) !== month ? "outside" : "")}
              >
                <button
                  className={"day-number " + (d === today ? "today" : "")}
                  aria-label={"Add event on " + d}
                  onClick={() => setEditor({ day: d })}
                >
                  {Number(d.slice(-2))}
                </button>
                {list
                  .filter((e) => eventDay(e, zone) === d)
                  .map((e) => (
                    <button
                      key={e.id}
                      className={"day-event " + e.category}
                      title={e.title}
                      onClick={() => setParams({ event: e.id })}
                    >
                      {e.title}
                    </button>
                  ))}
              </div>
            ))}
          </div>
        </section>
      ) : (
        <Agenda
          zone={zone}
          items={list}
          select={(e) => setParams({ event: e.id })}
        />
      )}
      <section className="panel suggestions">
        <div className="rail-head">
          <CalendarCheck2 size={17} />
          <h2>Pending suggestions</h2>
          <Pill tone="peach">{pending.data?.length ?? 0}</Pill>
        </div>
        {pending.isPending ? (
          <Loading />
        ) : pending.data?.length ? (
          pending.data.map((c) => (
            <article className="suggestion" key={c.id}>
              <div>
                <b>{c.title}</b>
                <p>
                  {c.local_date ?? "Date needs clarification"} ·{" "}
                  {c.original_date_text}
                  {c.synthetic ? " · Synthetic demo" : ""}
                </p>
                <Source item={c} />
              </div>
              <div className="inline">
                <button
                  className="secondary small"
                  onClick={() => review(c)}
                  disabled={action.isPending}
                >
                  <Check size={14} />
                  {c.needs_review ? "Review" : "Confirm"}
                </button>
                <button
                  className="icon-button"
                  aria-label={"Reject " + c.title}
                  onClick={() =>
                    action.mutate({
                      path: "/calendar/candidates/" + c.id + "/reject",
                    })
                  }
                >
                  <X size={15} />
                </button>
              </div>
            </article>
          ))
        ) : (
          <p className="section-empty">
            Academic dates detected in chat appear here for review.
          </p>
        )}
      </section>
      {editor && (
        <Editor
          item={editor.item}
          defaultDay={editor.day}
          zone={zone}
          review={editor.review}
          events={all}
          close={() => setEditor(null)}
        />
      )}
      {selected && !editor && (
        <Modal
          title={selected.title}
          close={() => {
            setParams({});
            setErase(false);
          }}
        >
          <Pill tone="purple">{human(selected.category)}</Pill>
          {selected.synthetic && <Pill>Synthetic demo</Pill>}
          <div className="event-detail">
            <CalendarDays size={16} />
            {eventDay(selected, zone)} ·{" "}
            {selected.start_utc
              ? clock(selected.start_utc, zone) + " " + zone
              : "All day"}
          </div>
          {selected.description && <p>{selected.description}</p>}
          <Source item={selected} />
          <details>
            <summary>
              Revision history ({selected.history?.length ?? 0})
            </summary>
            {selected.history?.map((h) => (
              <p key={h.id}>
                {human(h.operation)} · {h.snapshot.local_date} ·{" "}
                {h.snapshot.title}
              </p>
            ))}
          </details>
          <div className="modal-actions">
            <button
              className="secondary"
              onClick={() =>
                setEditor({ day: selected.local_date ?? today, item: selected })
              }
            >
              <Pencil size={14} />
              Edit
            </button>
            <button
              className="danger"
              onClick={() => {
                if (!erase) {
                  setErase(true);
                  return;
                }
                action.mutate(
                  { path: "/calendar/events/" + selected.id, method: "DELETE" },
                  {
                    onSuccess: () => {
                      setParams({});
                      setErase(false);
                    },
                  },
                );
              }}
            >
              <Trash2 size={14} />
              {erase ? "Confirm deletion" : "Delete"}
            </button>
          </div>
          <ErrorBox error={action.error} />
        </Modal>
      )}
    </div>
  );
}
