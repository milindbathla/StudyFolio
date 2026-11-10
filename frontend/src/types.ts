export interface Thread {
  id: string;
  title: string;
  synthetic: boolean;
  closed: boolean;
  updated_at: string;
}
export interface Evidence {
  document_id?: string;
  filename?: string;
  location?: string;
  message_id: string;
  conversation_id: string;
  timestamp: string;
  span?: string;
}
export interface Hit {
  id: string;
  layer: string;
  content: string;
  score: number;
  reasons: string[];
  evidence: Evidence[];
  timestamp: string;
}
export interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string;
  conversation_id: string;
  status: string;
  details: {
    synthetic?: boolean;
    mode?: string;
    sources?: Hit[];
    calendar?: { id: string; title: string; date: string }[];
  };
}
export interface Memory {
  id: string;
  layer: string;
  content: string;
  category?: string;
  confidence: number;
  status: string;
  evidence: Evidence[];
  origin: string;
  basis?: string;
  synthetic: boolean;
  created_at: string;
  path?: string;
  predicate?: string;
  value?: string;
  scope?: string;
  manual: boolean;
  semantic_id?: string;
  valid_until?: string;
}
export interface Profile {
  profile: Record<string, Record<string, string | string[] | null>>;
  assertions: Memory[];
}
export interface Revision {
  id: string;
  operation: string;
  created_at: string;
  detail: { path: string; value: string; reason: string; status: string };
}
export interface CalendarItem {
  source_document_id?: string;
  source_location?: string;
  id: string;
  title: string;
  description: string;
  category: string;
  local_date: string | null;
  start_utc: string | null;
  end_utc: string | null;
  timezone: string;
  all_day: boolean;
  status: string;
  synthetic: boolean;
  source_id?: string;
  source_conversation_id?: string;
  original_date_text: string;
  needs_review?: boolean;
  target_id?: string;
  parsed: { review?: string; possible_targets?: string[] };
  history?: {
    id: string;
    operation: string;
    snapshot: { title: string; local_date: string };
  }[];
}
export interface Settings {
  timezone: string;
  mode: string;
  model: string | null;
  vector_status: string;
  max_messages: number;
  max_tokens: number;
  window_hours: number;
  reflection_threshold: number;
  require_confirmation: boolean;
  auto_explicit: boolean;
}
export interface Job {
  id: string;
  kind: string;
  status: string;
  error: string | null;
  created_at: string;
}
export interface Retrieval {
  query: string;
  selected: Hit[];
  excluded: { id: string; reason: string }[];
  budget: number;
  tokens: number;
}
