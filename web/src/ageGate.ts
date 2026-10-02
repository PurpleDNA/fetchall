const KEY = "fetchall:age-confirmed";

export function ageConfirmed(): boolean {
  try {
    return sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function confirmAge() {
  try {
    sessionStorage.setItem(KEY, "1");
  } catch {}
}
