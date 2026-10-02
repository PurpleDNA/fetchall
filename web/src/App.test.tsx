import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test } from "vitest";
import App from "./App";
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

test("shows the reason when a job fails", async () => {
  const source = await startJob();

  act(() =>
    source.emit({ stage: "failed", at: 2, outcome: "login_required", message: "Needs a login." }),
  );

  expect(screen.getByRole("alert")).toHaveTextContent("Needs a login.");
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
