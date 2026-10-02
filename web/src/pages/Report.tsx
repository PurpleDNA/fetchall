import { type FormEvent, useState } from "react";
import { useAbout } from "../useAbout";

const REASONS = [
  "I own the copyright",
  "It shows me without my consent",
  "It's illegal or abusive",
  "Something else",
];

export function reportMailto(email: string, link: string, reason: string, details: string) {
  const subject = `fetchall report: ${reason}`;
  const body = `Link: ${link}\nReason: ${reason}\n\n${details}`.trim();
  return `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

export function Report() {
  const { about, loaded } = useAbout();
  const [link, setLink] = useState("");
  const [reason, setReason] = useState(REASONS[0]);
  const [details, setDetails] = useState("");

  function send(event: FormEvent) {
    event.preventDefault();
    if (about.report_email) window.location.href = reportMailto(about.report_email, link, reason, details);
  }

  return (
    <article className="page-text">
      <h2>Report content</h2>
      <p>
        Tell us about a link that shouldn't be downloadable here. Reported links are checked and
        blocked; blocked links stop working straight away.
      </p>
      {loaded && !about.report_email && (
        <p role="alert">Reporting isn't set up on this instance yet.</p>
      )}
      {about.report_email && (
        <form className="report" onSubmit={send}>
          <label>
            Link
            <input type="url" required value={link} onChange={(e) => setLink(e.target.value)} />
          </label>
          <label>
            Reason
            <select value={reason} onChange={(e) => setReason(e.target.value)}>
              {REASONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </label>
          <label>
            Details
            <textarea rows={4} value={details} onChange={(e) => setDetails(e.target.value)} />
          </label>
          <button type="submit">Write the email</button>
          <p className="details">
            This opens your email app with the report filled in, addressed to {about.report_email}.
          </p>
        </form>
      )}
    </article>
  );
}
