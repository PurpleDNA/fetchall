import { Link } from "../router";
import { useAbout } from "../useAbout";

export function Terms() {
  const { about } = useAbout();
  return (
    <article className="page-text">
      <h2>Terms of use</h2>
      <p>
        fetchall downloads videos from public web pages. It's a personal portfolio project, offered
        as-is with no guarantees.
      </p>
      <h3>What you may use it for</h3>
      <ul>
        <li>Public content that you have the right to download, such as your own uploads, openly licensed videos, or copies the law allows you to keep.</li>
        <li>Not content behind a login, paywall or DRM. fetchall refuses these.</li>
        <li>Not content shared without consent, or anything illegal where you or the source are.</li>
      </ul>
      <h3>What fetchall keeps</h3>
      <p>
        Videos are processed temporarily and deleted after you download them, or after{" "}
        {about.temp_file_minutes} minutes. Nothing is cached or re-shared. See the{" "}
        <Link to="/privacy">privacy note</Link>.
      </p>
      <h3>Adult content</h3>
      <p>Videos marked 18+ are only shown after you confirm you're an adult.</p>
      <h3>Takedowns</h3>
      <p>
        If something you own, or something showing you, is fetchable here, <Link to="/report">report it</Link>{" "}
        and it will be blocked.
      </p>
    </article>
  );
}
