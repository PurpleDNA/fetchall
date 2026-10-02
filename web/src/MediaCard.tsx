import { useState } from "react";
import type { Media } from "./api";
import { formatBytes, formatDuration } from "./format";

export function MediaCard({ media }: { media: Media }) {
  const [choice, setChoice] = useState(media.options[0]?.id);
  const details = [media.uploader, formatDuration(media.duration), media.site].filter(Boolean);

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
      </div>
    </article>
  );
}
