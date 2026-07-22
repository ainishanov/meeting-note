# SignPath Foundation application

This file is the source-of-truth checklist and copy deck for the Meeting Note
open-source code-signing application. Do not submit it until every preflight
item is checked against the public repository and release.

## Project details

- Project: Meeting Note
- Repository: https://github.com/ainishanov/meeting-note
- Website: https://ainishanov.github.io/meeting-note/
- Download page: https://ainishanov.github.io/meeting-note/download/
- Current public release: https://github.com/ainishanov/meeting-note/releases/latest
- Maintainer: Ainur Nishanov (`ainishanov` on GitHub)
- License: MIT
- Build system: GitHub Actions, Windows runner
- Artifacts to sign: `MeetingNote.exe` and `MeetingNoteSetup-vX.Y.Z.exe`

## Short description

Meeting Note is an open-source Windows desktop application that records call
audio, creates a transcript and summary, extracts decisions and action items,
and stores a searchable local meeting history.

## Why signing is needed

Windows currently warns users before running the unsigned installer. Signing
will give users a verifiable link from the public source repository and tagged
GitHub Actions build to the downloaded executable and installer.

## Open-source eligibility

- The application source is MIT licensed without commercial dual licensing.
- The UI uses Qt for Python under its open-source LGPLv3 option.
- Direct application dependencies use OSI-approved licenses.
- The project does not include proprietary code or SDKs.
- The project has a published Windows installer and portable executable.
- Product behavior, privacy, downloads, and limitations are documented on the
  website and in the repository.

## Build and approval flow

1. A release commit is merged into the public repository.
2. GitHub Actions installs hash-locked dependencies from
   `requirements-lock.txt`.
3. The workflow compiles the source and runs the automated test suite.
4. PyInstaller builds `MeetingNote.exe`.
5. Inno Setup builds `MeetingNoteSetup-vX.Y.Z.exe`.
6. The maintainer reviews and approves the SignPath signing request.
7. The workflow publishes the signed artifacts and SHA-256 checksums to the
   matching GitHub release.

## Public policy links

- Code signing policy: https://github.com/ainishanov/meeting-note/blob/main/CODE_SIGNING.md
- Privacy: https://ainishanov.github.io/meeting-note/privacy/
- Security: https://github.com/ainishanov/meeting-note/blob/main/SECURITY.md
- Third-party notices: https://github.com/ainishanov/meeting-note/blob/main/THIRD_PARTY_NOTICES.md

## Submission preflight

- [ ] Merge the PySide6 migration and locked release dependencies to `main`.
- [ ] Confirm the public code-signing policy link works on the website and
      download page.
- [ ] Publish one unsigned release from the new PySide6 build so SignPath can
      inspect the exact artifact form that will be signed.
- [ ] Confirm GitHub account multi-factor authentication is enabled.
- [ ] Confirm repository ownership and maintainer role from the public profile.
- [ ] Run the release workflow from a tagged public commit and record its URL.
- [ ] Verify the installer SHA-256 and a clean Windows installation.
- [ ] Submit the application only after the public release readback succeeds.

## Form-ready answers

**How is the project built?**

Official Windows artifacts are built on a GitHub-hosted Windows runner by the
public `Publish Windows release` workflow. The workflow installs hash-locked
dependencies, runs compilation and automated tests, builds a PyInstaller
executable and an Inno Setup installer, and publishes checksums with the GitHub
release.

**Who may request and approve signatures?**

The project currently has one maintainer. Ainur Nishanov is the author,
committer, reviewer, and signing approver. Contributions from other people must
be reviewed before merge, and signing requests must refer to a public release
commit.

**Does the application transfer data?**

Recordings, transcripts, summaries, and history are local by default. The user
must explicitly configure and invoke OpenAI/OpenRouter-compatible providers for
transcription and summaries. Update checks contact GitHub Releases. Feedback is
sent only when the user presses Send. Anonymous product telemetry and
privacy-scrubbed crash reporting are disabled by default and require explicit
consent. Full details are in the public privacy policy.
