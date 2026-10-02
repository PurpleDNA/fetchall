export const OUTCOME_TITLES: Record<string, string> = {
  blocked: "Temporarily blocked",
  login_required: "Needs a login",
  not_found: "Video not found",
  no_media: "No video here",
  drm: "DRM-protected",
  too_large: "Too large",
  unsupported: "Can't download this link",
  internal: "Something went wrong",
  busy: "Please wait",
};

export function outcomeTitle(outcome: string | undefined): string {
  return (outcome && OUTCOME_TITLES[outcome]) || OUTCOME_TITLES.internal;
}
