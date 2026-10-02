export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Health = "ok" | "degraded" | "unreachable";

export async function fetchHealth(): Promise<Health> {
  try {
    const response = await fetch(`${API_URL}/health`);
    const body = await response.json();
    return body.status === "ok" ? "ok" : "degraded";
  } catch {
    return "unreachable";
  }
}
