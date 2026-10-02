import { vi } from "vitest";

export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((message: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  static latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1);
    if (!source) throw new Error("No EventSource was opened");
    return source;
  }

  emit(event: object) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }

  fail() {
    this.onerror?.();
  }

  close() {
    this.closed = true;
  }
}

export function installEventSource() {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
}

type Route = (init?: RequestInit) => Response | Promise<Response>;

export function stubFetch(routes: Record<string, Route>) {
  const fetch = vi.fn(async (input: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${new URL(input).pathname}`;
    const route = routes[key];
    if (!route) throw new TypeError(`Unexpected request: ${key}`);
    return route(init);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

export const json = (body: unknown, status = 200) => () =>
  new Response(JSON.stringify(body), { status });

export const media = {
  title: "A short film",
  url: "https://video.example/watch/1",
  site: "Example",
  uploader: "Someone",
  duration: 125,
  thumbnail: "https://video.example/thumb.jpg",
  age_limit: 0,
  age_restricted: false,
  options: [
    { id: "1080p", label: "1080p", height: 1080, size: 43_000_000, needs_merge: true, audio_only: false },
    { id: "720p", label: "720p", height: 720, size: 25_000_000, needs_merge: false, audio_only: false },
    { id: "audio", label: "Audio only (M4A)", height: null, size: 3_000_000, needs_merge: false, audio_only: true },
  ],
};
