import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export const base = "/api/v1";
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(base + path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((e: { msg: string }) => e.msg).join(". ")
          : "The local service could not complete this request.",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export function useData<T>(path: string, enabled = true, poll?: number) {
  return useQuery<T, Error>({
    queryKey: [path],
    queryFn: () => api<T>(path),
    enabled,
    refetchInterval: poll,
  });
}
export function useAction<T = unknown>() {
  const client = useQueryClient();
  return useMutation<
    T,
    Error,
    { path: string; method?: string; body?: unknown }
  >({
    mutationFn: ({ path, method = "POST", body }) => api<T>(path, method, body),
    onSuccess: () => client.invalidateQueries(),
  });
}
export function dayInZone(instant: Date | string, timezone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(instant));
  const field = (type: string) => parts.find((p) => p.type === type)?.value;
  return [field("year"), field("month"), field("day")].join("-");
}
export function displayDate(
  instant: Date | string,
  zone: string,
  time = false,
) {
  return new Intl.DateTimeFormat("en", {
    timeZone: zone,
    month: "short",
    day: "numeric",
    ...(time ? { hour: "numeric", minute: "2-digit" } : { year: "numeric" }),
  }).format(new Date(instant));
}
export const human = (name: string) =>
  name.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
