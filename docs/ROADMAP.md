# Roadmap

This roadmap is intentionally practical. Meeting Note should stay local-first,
fast, and useful for people who need searchable meeting notes without a heavy
cloud workflow.

## Near Term

- Publish a signed or checksummed Windows release package.
- Add a first-run setup checklist for API keys, audio device selection, and test
  recording.
- Improve audio-device diagnostics when WASAPI loopback is unavailable.
- Add screenshots and a short demo GIF to the README.
- Add more focused tests around processing queue recovery and UI state changes.

## Product Improvements

- Better meeting detection rules and per-app settings.
- Per-recording language override.
- Editable summaries and action items.
- Export templates for Markdown, DOCX, and plain text.
- Global search filters by date, status, and speaker.
- Safer transcript redaction tools before sharing logs or bug reports.

## Contributor-Friendly Work

Good first issues should be small, testable, and not require API keys or live
audio hardware. Good candidates:

- Improve copy in settings and error messages.
- Add unit tests for existing pure-Python helpers.
- Improve troubleshooting docs with confirmed fixes.
- Add export formatting options.
- Add small UI polish that does not change recording behavior.

## Out Of Scope For Now

- Cloud storage as a default behavior.
- Recording meetings without appropriate consent.
- Server-side collaboration features.
- Mobile apps.
