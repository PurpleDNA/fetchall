import { useEffect, useRef, useState } from "react";
import { type Media, planDownload, saveFile, startPrepare, subscribeToJob } from "./api";
import { ageConfirmed, confirmAge } from "./ageGate";
import { formatBytes, formatDuration } from "./format";

type Preparing = { stage: "queued" | "downloading" | "merging"; progress: number };

export function MediaCard({ jobId, media }: { jobId: string; media: Media }) {
  const [choice, setChoice] = useState(media.options[0]?.id);
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState<Preparing | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(() => !media.age_restricted || ageConfirmed());
  const unsubscribe = useRef<(() => void) | null>(null);
  const details = [media.uploader, formatDuration(media.duration), media.site].filter(Boolean);

  useEffect(() => () => unsubscribe.current?.(), []);

  function prepare(optionId: string) {
    return startPrepare(jobId, optionId, media.age_restricted).then((prepareId) => {
      setPreparing({ stage: "queued", progress: 0 });
      unsubscribe.current = subscribeToJob(prepareId, (e) => {
        if (e.stage === "downloading") setPreparing({ stage: "downloading", progress: e.progress });
        else if (e.stage === "merging") setPreparing({ stage: "merging", progress: 1 });
        else if (e.stage === "ready" && e.file) {
          setPreparing(null);
          setBusy(false);
          saveFile(e.file);
        } else if (e.stage === "failed") {
          setPreparing(null);
          setBusy(false);
          setNote(e.message);
        }
      });
    });
  }

  async function download(optionId: string | undefined) {
    if (!optionId) return;
    setBusy(true);
    setNote(null);
    try {
      const plan = await planDownload(jobId, optionId, media.age_restricted);
      if (plan.delivery === "prepare") {
        await prepare(optionId);
        return;
      }
      saveFile(plan);
    } catch (error) {
      setNote((error as Error).message);
    }
    setBusy(false);
  }

  return (
    <article className="media">
      {media.thumbnail && (
        <img
          className={confirmed ? "thumb" : "thumb blurred"}
          src={media.thumbnail}
          alt=""
          referrerPolicy="no-referrer"
        />
      )}
      <div className="media-body">
        <h2>{media.title}</h2>
        <p className="details">{details.join(" · ")}</p>
        {!confirmed && (
          <div className="age-gate" role="group" aria-label="Age confirmation">
            <p>This video is marked 18+. Confirm you're 18 or older to see the download options.</p>
            <button
              type="button"
              className="primary"
              onClick={() => {
                confirmAge();
                setConfirmed(true);
              }}
            >
              I'm 18 or older
            </button>
          </div>
        )}
        {confirmed && (
          <>
            <fieldset className="options" disabled={busy}>
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
            {preparing && <PrepareProgress {...preparing} />}
          </>
        )}
        {note && (
          <p className="note" role="status">
            {note}
          </p>
        )}
      </div>
    </article>
  );
}

function PrepareProgress({ stage, progress }: Preparing) {
  const label =
    stage === "queued"
      ? "Waiting in line…"
      : stage === "merging"
        ? "Merging video and audio…"
        : `Downloading ${Math.round(progress * 100)}%`;
  return (
    <div className="prepare" role="status">
      <progress max={1} value={stage === "queued" ? undefined : progress} />
      <span>{label}</span>
    </div>
  );
}
