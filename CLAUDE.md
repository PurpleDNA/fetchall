# fetchall

## Agent skills

### Issue tracker

Issues live in GitHub Issues for PurpleDNA/fetchall, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five default triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Coding standards

- Keep code comments to a minimum. Prefer clear names; comment only a non-obvious *why* (a security, protocol or platform constraint). No docstrings that restate the name.
- Behaviour is tested through the public seams described in the spec (#1): the HTTP API with a fake Extractor, and the egress proxy with a fake resolver/connector.
