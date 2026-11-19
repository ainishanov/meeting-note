# Troubleshooting

Updated: 2026-11-19

This guide focuses on safe checks that do not require sharing private meeting
content.

## Recording Does Not Start

1. Open `File -> Settings -> Audio`.
2. Click `Refresh List`.
3. Keep `Automatic — all outputs (speakers, headphones)` selected.
4. Click `Test Audio (3 sec)` while some sound is playing. The result names the
   output where the sound was heard.
5. Confirm that Windows lists the output under Sound settings.

If no output appears, update the audio driver or try another output device.

## Call Is Not Recorded With Headphones

By default the app records every output at once, so it does not matter whether
the call plays through speakers or headphones. During a recording the panel
shows `Meeting audio: <output>` once it hears the call.

1. If the panel says `Listening: …` but never names an output, check that the
   call app is not muted and plays through a Windows output (not Bluetooth
   hands-free mode, which some headsets switch to during calls).
2. If an output is pinned in `File -> Settings -> Audio`, switch back to
   `Automatic — all outputs`.
3. Plugging or unplugging headphones mid-meeting is handled automatically.
   Changing the default microphone in Windows without plugging anything is not
   detected until the next recording.

## Microphone Is Missing

1. Open `File -> Settings -> Audio`.
2. Enable `Record microphone`.
3. Leave `Automatic (same as Windows)` or select the microphone manually.
4. Check Windows microphone privacy settings.
5. Run `Test Audio (3 sec)`.

## Transcription Fails

1. Check that `OPENAI_API_KEY` is configured or set it in
   `File -> Settings -> API`.
2. Check account balance and model access. "You have no credits remaining"
   or `credit_balance_exhausted` means the OpenAI balance is empty: add
   credits at platform.openai.com, then retry.
3. "The connection to OpenAI was interrupted" usually means a slow upload,
   for example through a VPN. The app sends audio as compressed MP3 pieces of
   about 0.9 MB; `data/meeting_note.log` shows the size of each upload
   ("Chunk 1 upload: ... KB"). If uploads still drop, try another VPN server
   or a connection with faster upload.
4. Try a shorter recording.
5. Retry transcription from the recording view. The recording is kept, and
   finished pieces are not sent again.

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
