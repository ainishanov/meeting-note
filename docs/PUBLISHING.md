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
- Smoke-test start, stop, close, transcription retry, summary retry, export, and
  settings.
- Create release notes with known limitations.
- Attach the release archive and checksums.

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
