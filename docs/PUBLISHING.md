# Publishing Checklist

Use this before the first public push and before each release.

## Before Making The Repository Public

- Confirm `.env`, `data/`, audio files, logs, local databases, and local agent
  folders are ignored.
- Scan the current tree for API keys and private paths.
- Scan git history for secrets and local-only files.
- If private files are present in history, publish from a sanitized branch or
  rewrite history before pushing publicly.
- Confirm README, license, contributing guide, security policy, issue templates,
  and CI are present.

## Before A Release

- Run `python -m compileall src`.
- Run `python -m unittest discover -s tests`.
- Build the Windows package.
- Build and install `installer/MeetingNote.iss` with Inno Setup.
- Smoke-test start, stop, close, transcription retry, summary retry, export, and
  settings.
- Confirm the in-app update check can parse the release and verify the published
  `SHA256SUMS.txt` entry.
- If code-signing secrets are configured, verify Authenticode on both the EXE
  and installer. If they are not configured, keep the SmartScreen warning in
  the release notes.
- Create release notes with known limitations.
- Attach the installer, portable archive, standalone EXE, and checksums.

## Release Secrets

- `WINDOWS_SIGNING_CERTIFICATE_BASE64`: base64-encoded PFX code-signing
  certificate.
- `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`: password for that PFX.
- `MEETING_NOTE_SENTRY_DSN`: optional Sentry-compatible DSN for scrubbed crash
  stack traces. Anonymous milestone and basic crash signals work through the
  private Google Forms sink without this secret.

Never commit a PFX, certificate password, provider token, or API key.

## Repository Settings

After creating the GitHub repository:

- Add topics such as `meeting-notes`, `meeting-transcription`,
  `speech-to-text`, `windows`, `pyqt6`, `openai`, `local-first`, and
  `productivity`.
- Enable Issues.
- Enable Discussions if you want product questions and ideas outside issue
  tracking.
- Add a social preview image.
- Pin a roadmap issue and a help-wanted issue.
