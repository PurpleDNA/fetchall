import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test } from "vitest";
import App from "./App";
import { reportMailto } from "./pages/Report";
import { installEventSource, json, stubFetch } from "./test/fakes";

const about = { report_email: "takedown@fetchall.example", log_retention_days: 7, temp_file_minutes: 15 };

function routes(overrides = {}) {
  return {
    "GET /health": json({ status: "ok", redis: "ok" }),
    "GET /about": json(about),
    "GET /sites": json({ sites: ["Reddit", "TikTok", "Twitter", "Vimeo", "YouTube"] }),
    ...overrides,
  };
}

beforeEach(() => installEventSource());

test.each([
  ["Terms", "Terms of use"],
  ["Privacy", "Privacy"],
  ["Supported sites", "Supported sites"],
  ["Report content", "Report content"],
])("the footer link %s opens its page", async (link, heading) => {
  stubFetch(routes());
  render(<App />);

  fireEvent.click(screen.getByRole("link", { name: link }));

  expect(await screen.findByRole("heading", { name: heading, level: 2 })).toBeInTheDocument();
  expect(window.location.pathname).not.toBe("/");
});

test("the logo goes back home", async () => {
  stubFetch(routes());
  window.history.replaceState(null, "", "/terms");
  render(<App />);

  fireEvent.click(screen.getByRole("link", { name: "fetchall" }));

  expect(screen.getByLabelText("Video link")).toBeInTheDocument();
});

test("the supported sites list comes from the API and can be searched", async () => {
  stubFetch(routes());
  window.history.replaceState(null, "", "/sites");
  render(<App />);

  expect(await screen.findByText("5 of 5 sites")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Search sites"), { target: { value: "tu" } });

  expect(screen.getByText("1 of 5 sites")).toBeInTheDocument();
  expect(screen.getByText("YouTube")).toBeInTheDocument();
  expect(screen.queryByText("Reddit")).not.toBeInTheDocument();
});

test("the privacy note states the configured retention", async () => {
  stubFetch(routes({ "GET /about": json({ ...about, log_retention_days: 3 }) }));
  window.history.replaceState(null, "", "/privacy");
  render(<App />);

  expect(await screen.findByText(/deleted after 3 days/)).toBeInTheDocument();
});

test("reports are addressed to the configured operator", async () => {
  stubFetch(routes());
  window.history.replaceState(null, "", "/report");
  render(<App />);

  expect(await screen.findByText(/addressed to takedown@fetchall\.example/)).toBeInTheDocument();
  expect(reportMailto("takedown@fetchall.example", "https://x.example/v", "I own the copyright", "Mine.")).toBe(
    "mailto:takedown@fetchall.example?subject=fetchall%20report%3A%20I%20own%20the%20copyright" +
      "&body=Link%3A%20https%3A%2F%2Fx.example%2Fv%0AReason%3A%20I%20own%20the%20copyright%0A%0AMine.",
  );
});

test("the report page says so when no contact is configured", async () => {
  stubFetch(routes({ "GET /about": json({ ...about, report_email: null }) }));
  window.history.replaceState(null, "", "/report");
  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Reporting isn't set up");
});

test("unknown pages offer a way home", () => {
  stubFetch(routes());
  window.history.replaceState(null, "", "/nope");
  render(<App />);

  expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
});
