import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import App from "./App";
import { OUTCOME_TITLES } from "./outcomes";
import { FakeEventSource, installEventSource, json, media, stubFetch } from "./test/fakes";

const healthy = { "GET /health": json({ status: "ok", redis: "ok" }) };

beforeEach(() => installEventSource());

function paste(url: string) {
  fireEvent.change(screen.getByLabelText("Video link"), { target: { value: url } });
  fireEvent.click(screen.getByRole("button", { name: "Fetch" }));
}

async function startJob() {
  stubFetch({ ...healthy, "POST /jobs": json({ id: "j1", stage: "queued", at: 1 }, 202) });
  render(<App />);
  paste("https://video.example/watch/1");
  await screen.findByText("Starting…");
  await act(async () => {}); // let the POST resolve and the stream open
  return FakeEventSource.latest();
}

test("shows each stage while the link is inspected", async () => {
  const source = await startJob();

  act(() => source.emit({ stage: "queued", at: 1 }));
  expect(screen.getByText("Waiting in line…")).toBeInTheDocument();

  act(() => source.emit({ stage: "extracting", at: 2 }));
  expect(screen.getByText("Fetching video info…")).toBeInTheDocument();
});

test("shows the video's details and quality choices with the best preselected", async () => {
  const source = await startJob();

  act(() => source.emit({ stage: "ready", at: 3, media }));

  expect(screen.getByRole("heading", { name: "A short film" })).toBeInTheDocument();
  expect(screen.getByText("Someone · 2:05 · Example")).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /1080p/ })).toBeChecked();
  expect(screen.getByRole("radio", { name: /720p/ })).not.toBeChecked();
  expect(screen.getByRole("radio", { name: /Audio only \(M4A\)/ })).toBeInTheDocument();
  expect(screen.getByText("43 MB")).toBeInTheDocument();
});

test.each(Object.entries(OUTCOME_TITLES))(
  "shows a distinct heading and the reason for a %s failure",
  async (outcome, title) => {
    const source = await startJob();

    act(() => source.emit({ stage: "failed", at: 2, outcome, message: `Because ${outcome}.` }));

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(title);
    expect(alert).toHaveTextContent(`Because ${outcome}.`);
  },
);

test("every outcome heading is different", () => {
  const titles = Object.values(OUTCOME_TITLES);
  expect(new Set(titles).size).toBe(titles.length);
});

test("explains when the link isn't a web link", async () => {
  stubFetch({ ...healthy, "POST /jobs": json({ detail: [] }, 422) });
  render(<App />);

  paste("ftp://nope");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Enter a full web link starting with http:// or https://",
  );
});

test("shows the API as unreachable when health check fails", async () => {
  stubFetch({ "GET /health": () => Promise.reject(new TypeError("Failed to fetch")) });
  render(<App />);

  expect(await screen.findByText("API unreachable")).toBeInTheDocument();
});

test("shows the API as degraded when Redis is down", async () => {
  stubFetch({ "GET /health": json({ status: "degraded", redis: "unreachable" }, 503) });
  render(<App />);

  expect(await screen.findByText("API degraded (Redis unreachable)")).toBeInTheDocument();
});

async function readyCard(plan: object, routes: Parameters<typeof stubFetch>[0] = {}) {
  const fetch = stubFetch({
    ...routes,
    ...healthy,
    "POST /jobs": json({ id: "j1", stage: "queued", at: 1 }, 202),
    "GET /jobs/j1/downloads/720p": json(plan),
    "GET /jobs/j1/downloads/thumbnail": json({ delivery: "stream", filename: "A short film.jpg", url: "/jobs/j1/files/thumbnail" }),
  });
  render(<App />);
  paste("https://video.example/watch/1");
  await screen.findByText("Starting…");
  await act(async () => {});
  act(() => FakeEventSource.latest().emit({ stage: "ready", at: 3, media }));
  return fetch;
}

test("downloads the chosen quality using the server's plan", async () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  await readyCard({ delivery: "stream", filename: "A short film (720p).mp4", url: "/jobs/j1/files/720p" });

  fireEvent.click(screen.getByRole("radio", { name: /720p/ }));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));

  await vi.waitFor(() => expect(click).toHaveBeenCalled());
  const link = click.mock.contexts[0] as HTMLAnchorElement;
  expect(link.href).toBe("http://localhost:8000/jobs/j1/files/720p");
  expect(link.download).toBe("A short film (720p).mp4");
});

test("opens direct links as they are", async () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  await readyCard({ delivery: "direct", filename: "A short film (720p).mp4", url: "https://cdn.example/v.mp4" });

  fireEvent.click(screen.getByRole("radio", { name: /720p/ }));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));

  await vi.waitFor(() => expect(click).toHaveBeenCalled());
  expect((click.mock.contexts[0] as HTMLAnchorElement).href).toBe("https://cdn.example/v.mp4");
});

test("prepares merged qualities on the server, showing progress, then saves the file", async () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  await readyCard(
    { delivery: "prepare", filename: "A short film (720p).mp4" },
    { "POST /jobs/j1/prepare/720p": json({ id: "p1", stage: "queued", at: 4 }, 202) },
  );

  fireEvent.click(screen.getByRole("radio", { name: /720p/ }));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  await vi.waitFor(() => expect(FakeEventSource.latest().url).toMatch(/\/jobs\/p1\/events$/));
  const source = FakeEventSource.latest();

  act(() => source.emit({ stage: "downloading", at: 4, progress: 0.43 }));
  expect(screen.getByText("Downloading 43%")).toBeInTheDocument();
  act(() => source.emit({ stage: "merging", at: 5 }));
  expect(screen.getByText("Merging video and audio…")).toBeInTheDocument();
  act(() =>
    source.emit({
      stage: "ready",
      at: 6,
      file: { url: "/files/p1", filename: "A short film (720p).mp4", size: 12 },
    }),
  );

  const link = click.mock.contexts[0] as HTMLAnchorElement;
  expect(link.href).toBe("http://localhost:8000/files/p1");
  expect(link.download).toBe("A short film (720p).mp4");
  expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
});

test("explains when the server is too busy to prepare", async () => {
  await readyCard(
    { delivery: "prepare", filename: "A short film (720p).mp4" },
    {
      "POST /jobs/j1/prepare/720p": json(
        { detail: "fetchall is busy preparing other downloads." },
        503,
      ),
    },
  );

  fireEvent.click(screen.getByRole("radio", { name: /720p/ }));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));

  expect(await screen.findByText("fetchall is busy preparing other downloads.")).toBeInTheDocument();
});

test("downloads the thumbnail", async () => {
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  await readyCard({ delivery: "stream", filename: "x", url: "/x" });

  fireEvent.click(screen.getByRole("button", { name: "Thumbnail" }));

  await vi.waitFor(() => expect(click).toHaveBeenCalled());
  expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe("A short film.jpg");
});
