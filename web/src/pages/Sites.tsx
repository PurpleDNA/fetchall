import { useEffect, useMemo, useState } from "react";
import { fetchSites } from "../api";

export function Sites() {
  const [sites, setSites] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetchSites()
      .then(setSites)
      .catch((e: Error) => setError(e.message));
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (sites ?? []).filter((site) => site.toLowerCase().includes(q));
  }, [sites, query]);

  return (
    <article className="page-text">
      <h2>Supported sites</h2>
      <p>
        fetchall uses <a href="https://github.com/yt-dlp/yt-dlp">yt-dlp</a>, so it works with these
        sites, and often with other pages that simply contain a video.
      </p>
      <label htmlFor="site-search" className="visually-hidden">
        Search sites
      </label>
      <input
        id="site-search"
        className="search"
        type="search"
        placeholder="Search sites…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {error && <p role="alert">{error}</p>}
      {!sites && !error && <p role="status">Loading…</p>}
      {sites && (
        <>
          <p className="details" role="status">
            {shown.length} of {sites.length} sites
          </p>
          <ul className="sites">
            {shown.map((site) => (
              <li key={site}>{site}</li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}
