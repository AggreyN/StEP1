// Hand-written types for the StEP1 API contract (FRONTEND_BRIEF.md "Shared
// response shapes" + the agreed endpoint list). Field names here must match
// the backend exactly — do not add fields the contract doesn't carry.

export type RoleKey =
  | "software"
  | "ai_ml_data"
  | "data_analytics"
  | "hardware"
  | "quant"
  | "product_management"
  | "program_management"
  | "solutions_architecture"
  | "security"
  | "infra_devops"
  | "design_ux"
  | "it_support"
  | "tech_consulting"
  | "research";

export interface User {
  id: number | string;
  email: string;
  display_name: string | null;
}

export interface Me extends User {
  onboarded: boolean;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

export interface Reason {
  code: string;
  label: string;
  detail: string | null;
}

export interface Salary {
  min: number | null;
  max: number | null;
  unit: string | null;
}

export interface PostingApplicationRef {
  id: number;
  status: string;
}

export interface Posting {
  id: string;
  title: string;
  company: { name: string; url: string | null };
  roles: string[];
  role_labels: string[];
  locations: string[];
  is_remote: boolean;
  terms: string[];
  degrees: string[];
  url: string;
  /** null when the source list did not give a date */
  date_posted: string | null;
  salary: Salary | null;
  source: string;
  /** null when the posting has not been scored for this user */
  score: number | null;
  reasons: Reason[];
  saved: boolean;
  application: PostingApplicationRef | null;
}

export interface Page<T> {
  items: T[];
  page: number;
  total: number;
  has_more: boolean;
}

export interface FeedStatus {
  state: "building" | "ready";
  pct: number;
  step: string;
}

export interface Interest {
  role: string;
  label?: string;
  rank: number;
}

export interface Resume {
  filename: string;
  uploaded_at: string;
  skills: string[];
  needs_ocr?: boolean;
}

export interface Profile {
  school: string | null;
  major: string | null;
  minor: string | null;
  degree_level: string | null;
  grad_year: number | null;
  gpa: number | null;
  target_terms: string[];
  preferred_locations: string[];
  remote_ok: boolean;
  interests: Interest[];
  resume: Resume | null;
  profile_version: number;
}

export interface ProfileInput {
  school: string;
  major: string;
  minor?: string | null;
  degree_level: string;
  grad_year: number;
  gpa?: number | null;
  target_terms: string[];
  preferred_locations: string[];
  remote_ok: boolean;
  interests: { role: string; rank: number }[];
  skills?: string[];
}

export interface ProfileAccepted {
  profile_version: number;
  state: "building" | "ready";
}

export interface Presign {
  upload_url: string;
  key: string;
  method: "PUT";
  headers: Record<string, string>;
}

export interface ApplicationEvent {
  id: number;
  kind: string;
  occurred_at: string;
  note: string | null;
  source: string;
}

export interface ApplicationSummary {
  id: number;
  posting: Posting;
  status: string;
  applied_at: string | null;
  last_event_at: string | null;
}

export interface ApplicationDetail {
  id: number;
  posting: Posting;
  status: string;
  applied_at: string | null;
  events: ApplicationEvent[];
  next_transitions: string[];
}

/** One upstream list in GET /ingest/status. */
export interface IngestSource {
  source: string;
  last_success_at: string | null;
  last_attempt_at: string | null;
  fetched: number;
  upserted: number;
  deactivated: number;
  error: string | null;
}

/** GET /ingest/status — how fresh the listings are. */
export interface IngestStatus {
  last_success_at: string | null;
  next_due_at: string | null;
  interval_hours: number;
  auto: boolean;
  running: boolean;
  active_postings: number;
  sources: IngestSource[];
}

/** GET /feed `sort`. `recent` is the default: newest first, then score. */
export type FeedSort = "recent" | "score";

/** Dashboard filters — mirrors the GET /feed query params. */
export interface FeedFilters {
  roles: string[];
  location: string;
  term: string;
  min_score: number | null;
  remote: boolean;
}
