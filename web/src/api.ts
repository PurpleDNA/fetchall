export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Health = "ok" | "degraded" | "unreachable";

export type QualityOption = {
  id: string;
  label: string;
  height: number | null;
  size: number | null;
  needs_merge: boolean;
  audio_only: boolean;
};

export type Media = {
  title: string;
  url: string;
  site: string;
  uploader: string | null;
  duration: number | null;
  thumbnail: string | null;
  age_limit: number;
  options: QualityOption[];
};

export type PreparedFile = { url: string; filename: string; size: number };

export type JobEvent =
  | { stage: "queued"; at: number }
  | { stage: "extracting"; at: number }
  | { stage: "downloading"; at: number; progress: number }
  | { stage: "merging"; at: number }
  | { stage: "ready"; at: number; media?: Media; file?: PreparedFile }
  | { stage: "failed"; at: number; outcome: string; message: string };

const TERMINAL = new Set(["ready", "failed"]);

export async function fetchHealth(): Promise<Health> {
  try {
    const response = await fetch(`${API_URL}/health`);
    const body = await response.json();
    return body.status === "ok" ? "ok" : "degraded";
  } catch {
    return "unreachable";
  }
}

export type DownloadPlan = {
  delivery: "direct" | "stream" | "prepare";
  filename: string;
  url?: string;
};

export class InvalidLink extends Error {}

export async function createInspectJob(url: string): Promise<string> {
  const response = await fetch(`${API_URL}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (response.status === 422) {
    throw new InvalidLink("Enter a full web link starting with http:// or https://");
  }
  if (!response.ok) throw new Error(`Couldn't start the job (HTTP ${response.status}).`);
  return (await response.json()).id;
}

export async function planDownload(jobId: string, optionId: string): Promise<DownloadPlan> {
  const response = await fetch(`${API_URL}/jobs/${jobId}/downloads/${optionId}`);
  if (!response.ok) throw new Error("That download isn't available any more. Fetch the link again.");
  return response.json();
}

export async function startPrepare(jobId: string, optionId: string): Promise<string> {
  const response = await fetch(`${API_URL}/jobs/${jobId}/prepare/${optionId}`, { method: "POST" });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? "Couldn't start preparing that download.");
  }
  return (await response.json()).id;
}

export function saveFile(plan: { url?: string; filename: string }) {
  if (!plan.url) return;
  const link = document.createElement("a");
  link.href = plan.url.startsWith("/") ? `${API_URL}${plan.url}` : plan.url;
  link.download = plan.filename;
  link.target = "_blank";
  link.rel = "noopener";
  link.click();
}

export function subscribeToJob(
  id: string,
  onEvent: (event: JobEvent) => void,
  { pollMs = 1500 }: { pollMs?: number } = {},
): () => void {
  let stopped = false;
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const stop = () => {
    stopped = true;
    source?.close();
    clearTimeout(timer);
  };

  const deliver = (event: JobEvent) => {
    if (stopped) return;
    onEvent(event);
    if (TERMINAL.has(event.stage)) stop();
  };

  const poll = async () => {
    if (stopped) return;
    try {
      const response = await fetch(`${API_URL}/jobs/${id}`);
      if (response.ok) deliver(await response.json());
    } catch {}
    if (!stopped) timer = setTimeout(poll, pollMs);
  };

  if (typeof EventSource === "undefined") {
    poll();
  } else {
    source = new EventSource(`${API_URL}/jobs/${id}/events`);
    source.onmessage = (message) => deliver(JSON.parse(message.data));
    source.onerror = () => {
      source?.close();
      source = null;
      poll();
    };
  }
  return stop;
}
