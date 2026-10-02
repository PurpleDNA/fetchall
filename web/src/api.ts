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

export type JobEvent =
  | { stage: "queued"; at: number }
  | { stage: "extracting"; at: number }
  | { stage: "ready"; at: number; media: Media }
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
