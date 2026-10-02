import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "./api";

const LABELS: Record<Health | "checking", string> = {
  checking: "Checking API…",
  ok: "API healthy",
  degraded: "API degraded (Redis unreachable)",
  unreachable: "API unreachable",
};

export default function App() {
  const [health, setHealth] = useState<Health | "checking">("checking");

  useEffect(() => {
    fetchHealth().then(setHealth);
  }, []);

  return (
    <main>
      <h1>fetchall</h1>
      <p role="status">{LABELS[health]}</p>
    </main>
  );
}
