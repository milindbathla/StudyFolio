import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import type { CalendarItem, Profile, Settings } from "./types";

const settings: Settings = {
  timezone: "Asia/Kolkata",
  mode: "offline",
  model: null,
  vector_status: "disabled",
  max_messages: 30,
  max_tokens: 4000,
  window_hours: 24,
  reflection_threshold: 8,
  require_confirmation: true,
  auto_explicit: true,
};
const profile: Profile = {
  profile: {
    identity: { name: null },
    academic_profile: { completed_courses: [] },
    learning_preferences: { explanation_depth: null },
    goals: { short_term: [] },
    behavioral_patterns: { study_routines: [] },
    interests: { academic: [] },
    constraints: { time_constraints: [] },
  },
  assertions: [],
};
const event = {
  id: "quiz",
  title: "Physics quiz",
  category: "quiz",
  description: "",
  local_date: "2026-11-19",
  timezone: "Asia/Kolkata",
  start_utc: null,
  end_utc: null,
  all_day: true,
  status: "proposed",
  synthetic: false,
  original_date_text: "November 19",
  parsed: {},
} satisfies CalendarItem;
type Handler = (
  path: string,
  method: string,
  body: Record<string, unknown>,
) => unknown;
function setup(path: string, handler?: Handler) {
  const calls = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = String(input).replace("/api/v1", ""),
      method = init?.method ?? "GET",
      body = init?.body ? JSON.parse(String(init.body)) : {};
    const override = handler?.(key, method, body);
    if (override instanceof Error)
      return new Response(JSON.stringify({ detail: override.message }), {
        status: 503,
      });
    const result =
      override !== undefined
        ? override
        : key === "/settings"
          ? settings
          : key === "/persona"
            ? profile
            : [];
    return new Response(JSON.stringify(result), { status: 200 });
  });
  vi.stubGlobal("fetch", calls);
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { calls, user: userEvent.setup() };
}

describe("Local workspace", () => {
  it("keeps synthetic survey answers unselected until explicit confirmation", async () => {
    const doc = {
      id: "s",
      filename: "sample.json",
      kind: "survey_json",
      status: "ready",
      version: 1,
      warnings: [],
      conflicts: [],
      pages: [],
      schema_fields: [],
      report: { review: 1 },
      items: [
        {
          id: "one",
          field: "skill_ml_level",
          locator: "/skill_ml_level",
          relation: "HAS_REPORTED_SKILL_LEVEL",
          value: { raw: "Beginner" },
          provenance: "synthetic",
          status: "review",
          version: 1,
          excerpt: "Beginner",
        },
      ],
    };
    const { user, calls } = setup("/settings/sources/s", (p) =>
      p === "/sources/s"
        ? doc
        : p === "/sources"
          ? [doc]
          : p === "/graph/status"
            ? { state: "SQLite graph", pending: 0 }
            : undefined,
    );
    const button = await screen.findByRole("button", {
      name: "Confirm selected fields",
    });
    expect(button).toBeDisabled();
    await user.click(
      screen.getByRole("checkbox", { name: "Select skill_ml_level" }),
    );
    await user.click(button);
    expect(
      calls.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith("/sources/s/confirm") &&
          String(init?.body).includes("Beginner"),
      ),
    ).toBe(true);
  });
  it("shows a failed source and exposes its reprocessing control", async () => {
    const doc = {
      id: "s",
      filename: "broken.pdf",
      kind: "academic_transcript",
      status: "failed",
      version: 0,
      warnings: ["Parsing failed."],
      conflicts: [],
      pages: [],
      items: [],
      schema_fields: [],
      report: {},
    };
    setup("/settings/sources/s", (p) =>
      p === "/sources/s" ? doc : p === "/sources" ? [doc] : undefined,
    );
    expect(await screen.findByText("Parsing failed.")).toBeVisible();
    expect(screen.getByRole("button", { name: /Reprocess as/ })).toBeEnabled();
  });
  it("opens the chat empty state and fills an example without storing a turn", async () => {
    const { user, calls } = setup("/chat");
    expect(
      await screen.findByRole("heading", {
        name: /What are we studying today/i,
      }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Check my deadlines" }),
    );
    expect(screen.getByLabelText("Your message")).toHaveValue(
      "Which assignments do I have this week?",
    );
    expect(
      calls.mock.calls.some(([path]) => String(path) === "/api/v1/chat"),
    ).toBe(false);
  });
  it("creates a thread and loads its stored conversation", async () => {
    let created = false;
    const t = {
      id: "test-cid",
      title: "Particle mechanics",
      closed: false,
      synthetic: false,
      updated_at: "2026-11-10T10:00:00Z",
    };
    const { user } = setup("/chat", (path, method) => {
      if (path === "/conversations" && method === "POST") {
        created = true;
        return t;
      }
      if (path === "/conversations") return created ? [t] : [];
      if (path === "/conversations/test-cid") return t;
      if (path.endsWith("/messages"))
        return [
          {
            id: "m1",
            role: "user",
            created_at: t.updated_at,
            content: "Review angular momentum",
            details: {},
            status: "processed",
          },
        ];
    });
    await user.click(screen.getByRole("button", { name: "New conversation" }));
    expect(await screen.findByText("Review angular momentum")).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Particle mechanics" }),
    ).toBeVisible();
  });
  it("shows grounded persona values with their provenance", async () => {
    setup("/persona", (path) =>
      path === "/persona"
        ? {
            ...profile,
            assertions: [
              {
                id: "a1",
                layer: "persona",
                content: "Prefers derivations",
                path: "learning_preferences.explanation_depth",
                value: "Detailed derivations",
                origin: "explicit",
                confidence: 0.93,
                status: "active",
                evidence: [
                  {
                    message_id: "m1",
                    conversation_id: "c1",
                    timestamp: "2026-11-10T10:00:00Z",
                  },
                ],
                created_at: "2026-11-10T10:00:00Z",
              },
            ],
          }
        : undefined,
    );
    expect(await screen.findByText("Detailed derivations")).toBeVisible();
    expect(screen.getByRole("link", { name: /Source ·/ })).toHaveAttribute(
      "href",
      "/chat/c1#m-m1",
    );
    expect(screen.getByText("Explicit")).toBeVisible();
  });
  it("renders the month, confirms a suggestion and lists the event", async () => {
    let confirmed = false;
    const { user } = setup("/calendar", (path, method) => {
      if (path === "/calendar/candidates") return confirmed ? [] : [event];
      if (path === "/calendar/candidates/quiz/confirm" && method === "POST") {
        confirmed = true;
        return { ...event, status: "confirmed" };
      }
      if (path === "/calendar/events")
        return confirmed ? [{ ...event, status: "confirmed" }] : [];
    });
    expect(await screen.findByText("Mon")).toBeVisible();
    await user.click(await screen.findByRole("button", { name: "Confirm" }));
    await user.click(screen.getByRole("button", { name: "Agenda" }));
    expect(
      await screen.findByRole("button", { name: /Physics quiz/ }),
    ).toBeVisible();
    expect(confirmed).toBe(true);
  });
  it("presents API errors in chat", async () => {
    setup("/chat/missing", (path) =>
      path === "/conversations/missing"
        ? new Error("Record not found")
        : undefined,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Record not found",
    );
  });
  it("shows empty memory layers and evaluates a retrieval query", async () => {
    const { user } = setup("/memory?layer=semantic", (path) =>
      path === "/memory/search"
        ? {
            query: "physics",
            selected: [],
            excluded: [],
            budget: 4000,
            tokens: 0,
          }
        : undefined,
    );
    expect(
      await screen.findByText("No matching semantic memory"),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Inspect retrieval" }));
    await user.type(screen.getByLabelText("Query"), "physics");
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    expect(
      await screen.findByText("No relevant memories in this context."),
    ).toBeVisible();
  });
  it("saves settings and requires typed confirmation before erasing data", async () => {
    let changed = false;
    const { user } = setup("/settings", (path, method, body) => {
      if (path === "/settings" && method === "PATCH") {
        changed = body.max_messages === 19;
        return settings;
      }
    });
    const limit = await screen.findByLabelText("Recent message limit");
    await user.clear(limit);
    await user.type(limit, "19");
    await user.click(screen.getByRole("button", { name: "Save preferences" }));
    expect(await screen.findByText("Preferences saved.")).toBeVisible();
    expect(changed).toBe(true);
    await user.click(screen.getByRole("button", { name: "Erase local data" }));
    expect(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Erase data",
      }),
    ).toBeDisabled();
  });
});
