# Troubleshooting

This guide focuses on safe checks that do not require sharing private meeting
content.

## Recording Does Not Start

1. Open `File -> Settings -> Audio`.
2. Click `Refresh List`.
3. Select a system audio device with loopback support.
4. Click `Test Audio (3 sec)`.
5. Confirm that Windows is playing audio through the selected output device.

If no loopback device appears, update the audio driver or try another output
device.

## Microphone Is Missing

1. Open `File -> Settings -> Audio`.
2. Enable `Record microphone`.
3. Select the microphone manually instead of `Default`.
4. Check Windows microphone privacy settings.
5. Run `Test Audio (3 sec)`.

## Transcription Fails

1. Check that `OPENAI_API_KEY` is configured or set it in
   `File -> Settings -> API`.
2. Check account balance and model access.
3. Try a shorter recording.
4. Retry transcription from the recording view.

## Summary Fails

1. Check that `OPENROUTER_API_KEY` is configured or set it in
   `File -> Settings -> API`.
2. Check OpenRouter account balance and model access.
3. Try `Refresh Summary` from the summary tab.
4. Try a smaller transcript if the meeting is very long.

## App Feels Slow Or Freezes

1. Make sure you are running the latest release or latest `main` branch.
2. Check whether antivirus is scanning the `data/recordings` directory.
3. Keep recordings on a local drive when possible.
4. Include `data/meeting_note.log` in bug reports only after removing private
   paths, meeting content, and API keys.

## Safe Bug Reports

Do not paste private meeting transcripts or audio. For logs, redact:

- API keys and tokens.
- Personal names and email addresses.
- Local paths that reveal usernames.
- Meeting content.
