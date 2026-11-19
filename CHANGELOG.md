# Changelog

## Unreleased

### Changed

- New app icon: a speech bubble with a sound wave and a recording dot on a
  violet tile. It is drawn separately for small, taskbar and large sizes, so it
  stays sharp in the exe, installer, window, tray, desktop shortcut and site.
- Running from source now shows the Meeting Note icon on the taskbar instead
  of the Python icon, including with the Microsoft Store Python.
- `scripts/generate_app_icons.py` rebuilds `assets/app_icon.ico`, the site
  favicon and the site icons from the SVG sources.
- Lighter, more modern look. Panels are soft white cards on a pale background
  with one violet accent, rounded corners and calmer text colors. The record
  button, player, tabs, history list, summary cards, settings, onboarding,
  feedback and privacy windows and the "call detected" pop-up all share the
  same style.
- The app follows the Windows light or dark mode. Set the environment variable
  `MEETING_NOTE_THEME=light` or `dark` to choose one yourself.
- Long meeting titles in the history list now end in "…" in a narrow window
  instead of pushing the length and status off the edge.

### Fixed

- Transcription no longer fails with "Connection error" on slow uploads such
  as a VPN: audio is sent to OpenAI as compressed MP3 (64 kbps, mono, 16 kHz)
  instead of WAV, so each two-minute piece is about 0.9 MB instead of 3.8 MB.
  Speaker voice samples and short recordings are compressed too. If the MP3
  encoder is missing, the app falls back to WAV as before.

## 0.3.3 — 2026-11-19

### Fixed

- Meeting audio is no longer lost when headphones are plugged into the jack:
  the recorder captures every Windows output (speakers, headphones, USB
  headsets) by default instead of the first loopback device it finds.
- Plugging or unplugging headphones during a recording re-scans the devices
  and keeps recording; the new output joins at the right place on the timeline.
- The recording panel shows where the call sound is heard ("Meeting audio:
  Headphones") and the audio test reports which output had sound.
- A pinned output or microphone is now remembered by name, so it survives
  Windows renumbering devices; older saved microphone numbers are matched to
  the same device automatically.
- Audio capture no longer keeps the audio system open while idle, so newly
  connected devices are visible without restarting the app.
- A voice that cannot be matched to a known speaker no longer stops a long
  transcription; its speech is kept and labelled "Unidentified speaker" instead
  of borrowing another person's name, including in the summary.
- Resumed transcriptions report real progress (finished chunks are counted up
  front) and the transcript view shows the running job's progress instead of a
  Retry button.

## 0.3.2 — 2026-08-28

### Fixed

- Kept four speaker identities stable across long chunked transcriptions by
  enrolling and refreshing voice references instead of reusing request-local
  diarization labels.
- Added atomic per-chunk transcription caching so interrupted long meetings
  resume without repeating completed API work.
- Replaced ambiguous updater exceptions with explicit check, checksum, download,
  verification, save, and launch stages.
- Update dialogs now describe the actual failed stage and offer the matching
  recovery action without claiming a verified download failed.
- Added visible download progress, cancellation cleanup, and a clear
  "Close and Install" handoff after SHA-256 verification.
- Failed update checks no longer suppress automatic checks for the next 24 hours.
- Windows builds now isolate DLL discovery from developer tools, reject binaries
  outside trusted roots, require exact lock-file versions, and smoke-test the
  finished Qt executable before release.
- A damaged GUI runtime now shows a short native recovery prompt instead of a
  PyInstaller traceback, with a direct route to the official download page.

## 0.3.1 — 2026-07-22

### Changed

- Replaced PyQt6 with the LGPL-licensed Qt for Python bindings while keeping
  the application under MIT.
- Locked every release dependency and hash used by GitHub Actions.
- Added a public code-signing policy, SignPath application checklist, and
  third-party license notices to release packages.

### Fixed

- Added the previously implicit `sounddevice` dependency required by voice
  activity mode.
- Removed Qt signal disconnect warnings introduced by the binding migration.

### Verification

- 52 unit tests pass in a clean environment created from the hash-locked
  dependencies.
- A clean PyInstaller build starts successfully and initializes the
  single-instance guard on Windows.

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
