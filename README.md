# Meeting Note

Records and summarizes calls.

Meeting Note is a Windows desktop app that captures meeting audio, transcribes it,
generates a summary, and keeps a searchable local history.

Website: https://ainishanov.github.io/meeting-note/

Download for Windows:
https://github.com/ainishanov/meeting-note/releases/download/v0.1.2/MeetingNote-v0.1.2-windows-x64.zip

## Project Status

Meeting Note is early public software. The core recording, transcription,
summary, search, and export workflows are in place, but packaging and hardware
compatibility still need broader testing.

## What It Does

- Records system audio through WASAPI loopback.
- Optionally records and mixes microphone audio.
- Detects meeting apps and can show a recording prompt.
- Transcribes audio through OpenAI speech-to-text models.
- Generates meeting summaries through OpenRouter-compatible chat models.
- Keeps a durable processing queue, so transcription and summary jobs can resume after restart.
- Exports notes to TXT, Markdown, and DOCX.
- Searches across meeting titles and transcript text.

## Privacy

Meeting Note stores recordings, transcripts, summaries, logs, and the SQLite
database locally under `data/` by default. These files can contain sensitive
meeting content and are ignored by git.

Only record meetings when you have the right consent for your jurisdiction and
organization.

## Requirements

- Windows 10/11
- Python 3.11+
- Audio output device with WASAPI loopback support
- OpenAI API key for transcription
- OpenRouter API key for summaries

Optional:
- Visual C++ Build Tools if you install `webrtcvad` for voice activity detection.

## Quick Start

```powershell
git clone <repo-url>
cd meeting_note

python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
python run.py
```

API keys can also be entered in `File -> Settings -> API`. The app stores keys
in Windows Credential Manager when configured through the UI.

The public interface defaults to English. Change the UI language in
`File -> Settings -> General -> Language`; restart the app after saving.

## Configuration

Create `.env` from `.env.example` and fill in local values:

```env
OPENAI_API_KEY=
OPENROUTER_API_KEY=
SUMMARY_MODEL=google/gemini-2.5-flash-lite
TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
TRANSCRIPTION_LANGUAGE=
APP_LANGUAGE=en
```

Leave `TRANSCRIPTION_LANGUAGE` empty to auto-detect the meeting language.
Set `APP_LANGUAGE` to `en` or `ru`.

Do not commit `.env`.

## Recording Modes

| Mode | Behavior |
| --- | --- |
| Manual | Start and stop with the UI or `Ctrl+Shift+R`. |
| Notification | Show a prompt when a meeting app is detected. |
| Process | Start automatically when a meeting app is detected. |
| Voice activity | Start after sustained speech is detected. |
| Combined | Require a meeting app plus voice activity. |

The default mode is notification mode.

## Supported Meeting Apps

- Zoom
- Microsoft Teams
- Google Meet in a browser
- Discord
- Slack
- Yandex Telemost

Detection is based on Windows processes and window titles.

## Transcription Models

The transcription model is configured in settings or with `TRANSCRIPTION_MODEL`.

| Model | Use case |
| --- | --- |
| `gpt-4o-mini-transcribe` | Default balance of speed and cost. |
| `gpt-4o-transcribe` | Higher accuracy. |
| `gpt-4o-transcribe-diarize` | Speaker labels / diarization. |
| `whisper-1` | Legacy compatibility. |

## Local Data

Default local data layout:

```text
data/
  database.db
  recordings/
  meeting_note.log
  processing/
```

These paths are ignored by git because they may contain private meeting content.

## Desktop Shortcut

After installing dependencies, create a Windows desktop shortcut:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_shortcut.ps1
```

## Development

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests
python -m compileall src
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development notes.

## Community

- Read the [roadmap](docs/ROADMAP.md).
- Check [troubleshooting](docs/TROUBLESHOOTING.md) before opening a bug.
- Use GitHub Issues for reproducible bugs and scoped feature requests.
- Use GitHub Discussions for workflow ideas, questions, and product feedback.
- Review the [security policy](SECURITY.md) before reporting vulnerabilities.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for audio, transcription,
summary, and privacy-safe bug report guidance.

## License

MIT. See [LICENSE](LICENSE).
