// Thin client for the FastAPI backend. The login token lives in localStorage and goes in the Authorization header.
const TOKEN_KEY = "career-scout-token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string | null) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY));

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // Only log out if the rejected token is still the current one (a stale request from before a new login,
    // or another tab, must not wipe a fresh token).
    if (res.status === 401 && token && getToken() === token) {
      setToken(null);
      window.dispatchEvent(new Event("logged-out"));
    }
    const detail = typeof data.detail === "string" ? data.detail : "Something went wrong. Please try again.";
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export type Me = {
  email: string;
  email_verified: boolean;
  search_id: number; // the open saved search
  country: string | null;
  city: string | null;
  steps: string[];
  steps_done: number[]; // 1-based step numbers completed
  next_step: number | null; // first step not done yet
};
// Buttons the boss attaches under a reply.
export type ChatAction =
  | { type: "open_tab"; tab: "employers" | "tracker"; label: string }
  | { type: "track"; companies: string[]; label: string }
  | { type: "say"; text: string; label: string };
export type ChatMsg = { role: "user" | "assistant"; text: string; actions?: ChatAction[] };
export type Search = { id: number; label: string; country: string | null; city: string | null; tracked: number; steps_done: number; active: boolean };
export type Job = { title: string; location: string; level: string; url: string; first_seen: string; location_flexible: number };
export type TrackerDetail = {
  company: string;
  status: Status;
  careers_url: string;
  notes: string;
  updated: string;
  research: {
    salary_low: number | null; salary_high: number | null; currency: string | null; salary_note: string | null;
    visa: "yes" | "no" | "unsure"; roles: string[]; locations: string[]; recruiting: string | null;
  } | null;
  jobs: Job[];
  jobs_checked: string | null;
  jobs_note: string | null;
};
export type TrackerRow = { company: string; status: Status; careers_url: string; notes: string; updated: string };
export type Posting = { company: string; title: string; location: string; level: string; url: string; first_seen: string; location_flexible: number };
export type SchoolTag = { school: string; hired: boolean }; // hired = report says it hired grads (else: recruiting only)
export type EmployerRow = { company: string; industry: string; function: string; schools: SchoolTag[]; hired: boolean; top_pick: boolean };
export type EmployerView = { location: string; overview: string | null; files: string[]; rows: EmployerRow[]; created_at: string };
export const STATUSES = ["interested", "applied", "interviewing", "offer", "rejected"] as const;
export type Status = (typeof STATUSES)[number];

export const api = {
  signup: (email: string, password: string) => request<{ token: string }>("POST", "/signup", { email, password }),
  login: (email: string, password: string) => request<{ token: string }>("POST", "/login", { email, password }),
  logout: () => request("POST", "/logout"),
  forgot: (email: string) => request("POST", "/password/forgot", { email }),
  reset: (token: string, password: string) => request("POST", "/password/reset", { token, password }),
  verify: (token: string) => request("POST", "/verify-email", { token }),
  resendVerify: () => request("POST", "/verify-email/resend"),
  me: () => request<Me>("GET", "/me"),
  history: () => request<ChatMsg[]>("GET", "/chat/history"),
  newChat: (opts: { new_search: boolean }) => request("POST", "/chat/new", opts),
  chat: (message: string) => request<{ answer: string; actions: ChatAction[] }>("POST", "/chat", { message }),
  searches: () => request<Search[]>("GET", "/searches"),
  newSearch: () => request("POST", "/searches"),
  switchSearch: (id: number) => request("POST", `/searches/${id}/activate`),
  deleteSearch: (id: number) => request("DELETE", `/searches/${id}`),
  trackerDetails: () => request<{ location: string | null; rows: TrackerDetail[] }>("GET", "/tracker/details"),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ saved: string }>("POST", "/upload", fd);
  },
  tracker: () => request<TrackerRow[]>("GET", "/tracker"),
  addTracker: (companies: string[]) =>
    request<{ added: string[]; full: string[]; count: number; max: number }>("POST", "/tracker", { companies }),
  employers: () => request<EmployerView | null>("GET", "/employers"),
  updateTracker: (company: string, status: Status) => request("PATCH", "/tracker", { company, status }),
  removeTracker: (company: string) => request("DELETE", `/tracker/${encodeURIComponent(company)}`),
  postings: () => request<Posting[]>("GET", "/postings"),
};
