# Code signing policy

Official Meeting Note releases are built from the public GitHub repository by
the `Publish Windows release` GitHub Actions workflow. Release artifacts must
come from a tagged commit and pass the automated test suite before publication.
Locally built binaries are not published as official releases.

Meeting Note is applying for the SignPath Foundation open-source program.
After approval, official Windows executables and installers will use:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

Until that integration is approved and enabled, release notes explicitly state
that the binaries are unsigned.

## Signing roles

- Author, committer, and reviewer: [Ainur Nishanov](https://github.com/ainishanov)
- Signing approver: [Ainur Nishanov](https://github.com/ainishanov)

Meeting Note currently has one maintainer. Contributions from other people must
be reviewed by the maintainer before merge. A signing request must be approved
by the signing approver and must refer to the public release commit.

## Scope and verification

The policy covers `MeetingNote.exe` and `MeetingNoteSetup-vX.Y.Z.exe`. The
release workflow publishes SHA-256 checksums alongside the artifacts. The
installer, portable package, and release page must all identify the same
version and source commit.

## Privacy and network access

See the [Meeting Note privacy policy](https://ainishanov.github.io/meeting-note/privacy/).
Meeting audio, transcripts, and summaries remain local unless the user
explicitly configures and invokes an external transcription or AI provider.
Update checks contact GitHub Releases. Private feedback is sent only after the
user presses Send. Anonymous product telemetry and privacy-scrubbed crash
reports are disabled by default and require explicit consent.

## Incident response

If a signed artifact is suspected of compromise, publication and signing will
be paused, the affected release will be removed, and SignPath Foundation will
be notified so that the certificate or affected signature can be revoked when
necessary. Security reports follow [SECURITY.md](SECURITY.md).
