import { useEffect, useState } from "react";
import { type About, fetchAbout } from "./api";

const DEFAULTS: About = { report_email: null, log_retention_days: 7, temp_file_minutes: 15 };

export function useAbout(): { about: About; loaded: boolean } {
  const [state, setState] = useState({ about: DEFAULTS, loaded: false });
  useEffect(() => {
    fetchAbout()
      .then((about) => setState({ about, loaded: true }))
      .catch(() => setState({ about: DEFAULTS, loaded: true }));
  }, []);
  return state;
}
