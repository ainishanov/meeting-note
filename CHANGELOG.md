# Changelog

## 0.3.0 — 2026-07-22

### Added

- Opt-in anonymous milestones for app start, recording, transcription, summary,
  feedback, updates, and privacy-safe crash signals.
- A one-time privacy choice plus persistent controls for analytics, crash
  reports, and update checks.
- Direct in-app feedback backed by a private Google Form, with no GitHub or
  Google account required for respondents.
- Daily GitHub Releases checks and SHA-256-verified installer downloads.
- An Inno Setup Windows installer and optional Authenticode signing in CI.
- A new outcome-led social preview and 30-second product demo.

### Changed

- The website now leads with the outcome—clear decisions and next steps—rather
  than price.
- Feedback has its own public website section and remains available through
  public GitHub channels for technical discussions.

### Privacy

- Analytics and crash sharing are off by default.
- No recordings, transcripts, summaries, meeting titles, API keys, or logs are
  included in anonymous events.
- Full crash stack traces are sent only when a Sentry-compatible DSN is present;
  PII, local variables, source context, host identity, paths, and breadcrumbs
  are scrubbed first.

## 0.2.0 — 2026-07-22

### Added

- Four-step first-run setup for language, API keys, and audio checks.
- A compact call-detected state with a direct recording action.
- Semantic meeting titles generated from the conversation.
- Feedback routes for improvements, bug reports, and discussions.

### Changed

- Completed meetings now open on the Summary tab.
- Decisions and action items appear before the long-form summary.
- The recording bar and history list use a more compact layout.
- Existing date-only meetings are upgraded from stored summaries when possible.

### Fixed

- Meeting selection no longer initializes Qt Multimedia or renders long transcripts synchronously.
- Audio files and transcripts are loaded only when the user opens them.

### Verification

- 38 unit tests pass on Windows.
- The PyInstaller EXE was tested in first-run and returning-user flows.
- The installed desktop-shortcut target was verified after replacement.
