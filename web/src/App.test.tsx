import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";

function stubFetch(impl: () => Promise<unknown>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

const respond = (status: number, body: unknown) => () =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

test("shows the API as healthy", async () => {
  stubFetch(respond(200, { status: "ok", redis: "ok" }));
  render(<App />);
  expect(await screen.findByText("API healthy")).toBeInTheDocument();
});

test("shows the API as degraded when Redis is down", async () => {
  stubFetch(respond(503, { status: "degraded", redis: "unreachable" }));
  render(<App />);
  expect(await screen.findByText("API degraded (Redis unreachable)")).toBeInTheDocument();
});

test("shows the API as unreachable when the request fails", async () => {
  stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
  render(<App />);
  expect(await screen.findByText("API unreachable")).toBeInTheDocument();
});
