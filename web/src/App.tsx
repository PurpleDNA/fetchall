import { type FormEvent, type JSX, useEffect, useRef, useState } from "react";
import {
  createInspectJob,
  fetchHealth,
  type Health,
  InvalidLink,
  Refused,
  type Media,
  subscribeToJob,
} from "./api";
import { MediaCard } from "./MediaCard";
import { outcomeTitle } from "./outcomes";
import { Privacy } from "./pages/Privacy";
import { Report } from "./pages/Report";
import { Sites } from "./pages/Sites";
import { Terms } from "./pages/Terms";
import { Link, usePath } from "./router";

type View =
  | { kind: "idle" }
  | { kind: "working"; stage: "starting" | "queued" | "extracting"; position?: number | null }
  | { kind: "ready"; jobId: string; media: Media }
  | { kind: "failed"; outcome?: string; message: string };

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

const PAGES: Record<string, () => JSX.Element> = {
  "/": Home,
  "/terms": Terms,
  "/privacy": Privacy,
  "/sites": Sites,
  "/report": Report,
};

export default function App() {
  const path = usePath();
  const [health, setHealth] = useState<Health | "checking">("checking");
  const Page = PAGES[path] ?? NotFound;

  useEffect(() => {
    fetchHealth().then(setHealth);
  }, []);

  return (
    <div className="page">
      <header>
        <h1>
          <Link to="/">fetchall</Link>
        </h1>
        <p className="tagline">Paste a link, get the video.</p>
      </header>

      <Page />

      <footer>
        <nav aria-label="About fetchall">
          <Link to="/terms">Terms</Link>
          <Link to="/privacy">Privacy</Link>
          <Link to="/sites">Supported sites</Link>
          <Link to="/report">Report content</Link>
        </nav>
        <p>
          <span className={`dot ${health}`} /> {HEALTH_LABELS[health]}
        </p>
      </footer>
    </div>
  );
}

function NotFound() {
  return (
    <article className="page-text">
      <h2>Page not found</h2>
      <p>
        <Link to="/">Go back to fetchall</Link>
      </p>
    </article>
  );
}

function Home() {
  const [url, setUrl] = useState("");
  const [view, setView] = useState<View>({ kind: "idle" });
  const unsubscribe = useRef<(() => void) | null>(null);

  useEffect(() => () => unsubscribe.current?.(), []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    unsubscribe.current?.();
    setView({ kind: "working", stage: "starting" });
    try {
      const id = await createInspectJob(url.trim());
      unsubscribe.current = subscribeToJob(id, (e) => {
        if (e.stage === "ready" && e.media) setView({ kind: "ready", jobId: id, media: e.media });
        else if (e.stage === "failed")
          setView({ kind: "failed", outcome: e.outcome, message: e.message });
        else if (e.stage === "queued")
          setView({ kind: "working", stage: "queued", position: e.position });
        else if (e.stage === "extracting") setView({ kind: "working", stage: "extracting" });
      });
    } catch (error) {
      if (error instanceof Refused) {
        setView({ kind: "failed", outcome: "busy", message: error.message });
        return;
      }
      const message =
        error instanceof InvalidLink ? error.message : "Couldn't reach fetchall. Try again.";
      setView({ kind: "failed", outcome: "unsupported", message });
    }
  }

  return (
    <>
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
            <span>
              {STAGE_LABELS[view.stage]}
              {view.stage === "queued" && view.position ? ` You're number ${view.position}.` : ""}
            </span>
          </div>
        )}
        {view.kind === "failed" && (
          <div className="error" role="alert">
            <strong>{outcomeTitle(view.outcome)}</strong>
            <p>{view.message}</p>
          </div>
        )}
        {view.kind === "ready" && <MediaCard jobId={view.jobId} media={view.media} />}
      </section>
    </>
  );
}
