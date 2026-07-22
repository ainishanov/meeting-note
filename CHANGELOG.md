# Changelog

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
