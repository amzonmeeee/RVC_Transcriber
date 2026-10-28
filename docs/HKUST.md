# HKUST Canvas and RVC recordings

The `hkust` command finds the RVC (Remote Video Capture) recordings of a course. It reads only the audio of each recording and makes a transcript.

## Setup

1. Sign in to HKUST Canvas in Google Chrome.
2. In Chrome, select **View > Developer > Allow JavaScript from Apple Events**.
3. Run the command one time. macOS asks if Terminal can control Chrome. Select **Allow**.

The program opens its own Chrome tabs. It uses your Chrome sign-in to read Canvas and rvcmedia. Then it closes these tabs. The program does not keep a password, a cookie or a token.

## Commands

```sh
./run.sh hkust "<link>" --list
./run.sh hkust "<link>" --output "../Transcripts" --timestamps --yes
./run.sh hkust "<link>" --select 2026-09 --latest 2 --output "../Transcripts"
./run.sh hkust "<link>" --preview --output "../PreviewTranscripts" --keep-runtime --yes
```

| Option | Function |
| --- | --- |
| `--list` | Show the recordings. Do not transcribe. |
| `--output DIR` | The folder for the transcripts. |
| `--select REGEX` | Use only recordings with a title or media ID that matches. You can use this option more than one time. |
| `--latest N` | Use only the newest N recordings. |
| `--preview` | Transcribe a short part of the first recording. Use `--start` and `--seconds` to change the part. |

All options of `transcribe` are also available, for example `--model`, `--glossary`, `--resume`, `--overwrite`, `--keep-runtime` and `--dry-run`. See [REFERENCE.md](REFERENCE.md).

## Links that you can use

* A course home page: `https://canvas.ust.hk/courses/<id>`
* The modules page, or one module
* A module item
* A page that has links to recordings
* One recording page
* An `rvcmedia.ust.hk` player link

## How the program finds recordings

HKUST published RVC recordings in this pattern in 2026. The example names are not real.

1. Each lecture has a Canvas page. The title has the course, section, date and time, for example `COMP1000-L1-2026-09-01-09-00`. Module pages usually have links to these pages.
2. The lecture page has a player from `https://rvcmedia.ust.hk/media/?path=<media id>`.
3. After you sign in, the page `https://rvcmedia.ust.hk/Media/Play?path=<media id>` gives an HLS playlist (`.m3u8`). The playlist link has a token that expires after some hours.
4. FFmpeg reads the playlist directly. It keeps only the audio as 16 kHz mono WAV in `.runtime.nosync/`.

The program gets a new playlist link each time that it runs. Thus `--resume` works after a token expires.

## Limits

* The program cannot read Zoom cloud recordings. Some courses use Zoom recordings and not RVC.
* If HKUST changes the page pattern, the program cannot find the recordings.
* Unpublished recording pages are not available to students. The program shows them as skipped.

CAUTION: The recordings are subject to the HKUST copyright policy. Use the transcripts only for your own study.
