import { useAbout } from "../useAbout";

export function Privacy() {
  const { about } = useAbout();
  return (
    <article className="page-text">
      <h2>Privacy</h2>
      <p>fetchall has no accounts, no ads and no tracking.</p>
      <h3>What's logged</h3>
      <p>
        For each job: the link you pasted, the site, whether it worked, its size, and a salted hash
        of your IP address. Your IP itself is never stored. The log is deleted after{" "}
        {about.log_retention_days} days. It's used only to stop abuse and answer takedown requests.
      </p>
      <h3>Rate limits</h3>
      <p>The same IP hash is used briefly to enforce fair-use limits, then expires.</p>
      <h3>In your browser</h3>
      <p>
        If you confirm you're 18+, that choice is kept in this tab's session storage until you close
        it. No cookies are set.
      </p>
      <h3>Downloaded files</h3>
      <p>
        Files prepared on the server are deleted as soon as you've downloaded them, or after{" "}
        {about.temp_file_minutes} minutes.
      </p>
    </article>
  );
}
