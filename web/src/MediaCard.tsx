import { useState } from "react";
import { type Media, planDownload, saveFile } from "./api";
import { formatBytes, formatDuration } from "./format";

const PREPARE_NOTE = "This quality needs processing on the server, which isn't available yet.";

export function MediaCard({ jobId, media }: { jobId: string; media: Media }) {
  const [choice, setChoice] = useState(media.options[0]?.id);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const details = [media.uploader, formatDuration(media.duration), media.site].filter(Boolean);

  async function download(optionId: string | undefined) {
    if (!optionId) return;
    setBusy(true);
    setNote(null);
    try {
      const plan = await planDownload(jobId, optionId);
      if (plan.delivery === "prepare") setNote(PREPARE_NOTE);
      else saveFile(plan);
    } catch (error) {
      setNote((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="media">
      {media.thumbnail && (
        <img className="thumb" src={media.thumbnail} alt="" referrerPolicy="no-referrer" />
      )}
      <div className="media-body">
        <h2>{media.title}</h2>
        <p className="details">{details.join(" · ")}</p>
        <fieldset className="options">
          <legend>Choose a quality</legend>
          {media.options.map((option) => (
            <label key={option.id} className="option">
              <input
                type="radio"
                name="quality"
                value={option.id}
                checked={choice === option.id}
                onChange={() => setChoice(option.id)}
              />
              <span>{option.label}</span>
              {option.size != null && <span className="size">{formatBytes(option.size)}</span>}
            </label>
          ))}
        </fieldset>
        <div className="actions">
          <button type="button" className="primary" disabled={busy} onClick={() => download(choice)}>
            Download
          </button>
          {media.thumbnail && (
            <button type="button" disabled={busy} onClick={() => download("thumbnail")}>
              Thumbnail
            </button>
          )}
        </div>
        {note && (
          <p className="note" role="status">
            {note}
          </p>
        )}
      </div>
    </article>
  );
}
