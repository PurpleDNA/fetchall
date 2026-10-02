import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  createInspectJob,
  fetchHealth,
  type Health,
  InvalidLink,
  type Media,
  subscribeToJob,
} from "./api";
import { MediaCard } from "./MediaCard";

type View =
  | { kind: "idle" }
  | { kind: "working"; stage: "starting" | "queued" | "extracting" }
  | { kind: "ready"; jobId: string; media: Media }
  | { kind: "failed"; message: string };

const STAGE_LABELS = {
  starting: "Starting…",
  queued: "Waiting in line…",
  extracting: "Fetching video info…",
};

const HEALTH_LABELS: Record<Health | "checking", string> = {
  checking: "Checking API…",
  ok: "API healthy",
  degraded: "API degraded (Redis unreachable)",
  unreachable: "API unreachable",
};

export default function App() {
  const [url, setUrl] = useState("");
  const [view, setView] = useState<View>({ kind: "idle" });
  const [health, setHealth] = useState<Health | "checking">("checking");
  const unsubscribe = useRef<(() => void) | null>(null);

  useEffect(() => {
    fetchHealth().then(setHealth);
    return () => unsubscribe.current?.();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    unsubscribe.current?.();
    setView({ kind: "working", stage: "starting" });
    try {
      const id = await createInspectJob(url.trim());
      unsubscribe.current = subscribeToJob(id, (e) => {
        if (e.stage === "ready") setView({ kind: "ready", jobId: id, media: e.media });
        else if (e.stage === "failed") setView({ kind: "failed", message: e.message });
        else setView({ kind: "working", stage: e.stage });
      });
    } catch (error) {
      const message =
        error instanceof InvalidLink ? error.message : "Couldn't reach fetchall. Try again.";
      setView({ kind: "failed", message });
    }
  }

  return (
    <div className="page">
      <header>
        <h1>fetchall</h1>
        <p className="tagline">Paste a link, get the video.</p>
      </header>

      <form className="paste" onSubmit={submit}>
        <label htmlFor="url" className="visually-hidden">
          Video link
        </label>
        <input
          id="url"
          type="text"
          inputMode="url"
          placeholder="https://…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
        />
        <button type="submit" disabled={view.kind === "working"}>
          Fetch
        </button>
      </form>

      <section aria-live="polite">
        {view.kind === "working" && (
          <div className="progress" role="status">
            <div className="bar" />
            <span>{STAGE_LABELS[view.stage]}</span>
          </div>
        )}
        {view.kind === "failed" && (
          <p className="error" role="alert">
            {view.message}
          </p>
        )}
        {view.kind === "ready" && <MediaCard jobId={view.jobId} media={view.media} />}
      </section>

      <footer>
        <span className={`dot ${health}`} /> {HEALTH_LABELS[health]}
      </footer>
    </div>
  );
}
