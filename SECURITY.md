# Security

Meeting Note records local system audio and microphone input. Treat recordings,
transcripts, summaries, logs, and the SQLite database as sensitive user data.

## Secrets

API keys should be stored through the app settings, which use Windows Credential
Manager, or in an untracked local `.env` file. Do not commit real API keys.

## Reporting issues

If you find a security issue, do not include private recordings, transcripts,
API keys, or personal meeting details in a public issue. Share a minimal
reproduction and redact sensitive data.

