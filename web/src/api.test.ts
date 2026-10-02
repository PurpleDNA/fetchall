import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { type JobEvent, subscribeToJob } from "./api";
import { FakeEventSource, installEventSource, json, media, stubFetch } from "./test/fakes";

beforeEach(() => installEventSource());
afterEach(() => vi.useRealTimers());

test("follows the live stream until the job finishes", () => {
  const events: JobEvent[] = [];
  subscribeToJob("j1", (e) => events.push(e));
  const source = FakeEventSource.latest();

  source.emit({ stage: "queued", at: 1 });
  source.emit({ stage: "extracting", at: 2 });
  source.emit({ stage: "ready", at: 3, media });

  expect(source.url).toMatch(/\/jobs\/j1\/events$/);
  expect(events.map((e) => e.stage)).toEqual(["queued", "extracting", "ready"]);
  expect(source.closed).toBe(true);
});

test("falls back to polling when the live stream drops", async () => {
  vi.useFakeTimers();
  const states = [
    { id: "j1", stage: "extracting", at: 2 },
    { id: "j1", stage: "ready", at: 3, media },
  ];
  const fetch = stubFetch({ "GET /jobs/j1": () => json(states.shift())() });
  const events: JobEvent[] = [];
  subscribeToJob("j1", (e) => events.push(e), { pollMs: 1000 });

  FakeEventSource.latest().emit({ stage: "queued", at: 1 });
  FakeEventSource.latest().fail();
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(1000);
  await vi.advanceTimersByTimeAsync(5000);

  expect(events.map((e) => e.stage)).toEqual(["queued", "extracting", "ready"]);
  expect(fetch).toHaveBeenCalledTimes(2); // stops polling once the job is finished
});

test("stops listening when unsubscribed", () => {
  const events: JobEvent[] = [];
  const stop = subscribeToJob("j1", (e) => events.push(e));

  stop();
  FakeEventSource.latest().emit({ stage: "queued", at: 1 });

  expect(events).toEqual([]);
  expect(FakeEventSource.latest().closed).toBe(true);
});
