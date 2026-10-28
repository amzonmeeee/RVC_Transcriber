# Local lecture transcriber

This program makes a text transcript of each lecture recording. It is for Hong Kong Cantonese with English terms.

The program does all speech recognition on your computer. It does not send audio or text to a server. You do not need an API key.

The program can use two types of input:

* A folder of MP4 files.
* An HKUST Canvas link. The program finds the RVC lecture recordings and reads their audio.

## Requirements

* A Mac with Apple Silicon and macOS 14 or later.
* Python 3.9 or later (`python3`).
* 12 GB of free disk space.
* For HKUST: Google Chrome. You must be signed in to HKUST Canvas.

Windows, Linux and Intel Macs are not supported.

## Install

```sh
git clone https://github.com/amzonmeeee/RVC_Transcriber.git
cd RVC_Transcriber
./run.sh doctor
```

The first transcription downloads approximately 4–5 GB of tools and models. All downloads go into `.runtime.nosync/` in the checkout.

## Transcribe HKUST Canvas recordings

1. In Chrome, select **View > Developer > Allow JavaScript from Apple Events**.
2. Show the recordings that the program finds:

   ```sh
   ./run.sh hkust "https://canvas.ust.hk/courses/<id>" --list
   ```

3. Make the transcripts:

   ```sh
   ./run.sh hkust "https://canvas.ust.hk/courses/<id>" --output "../Transcripts" --timestamps --yes
   ```

The program does not save the video. It saves only one `.txt` file for each recording. If a transcript is already in the output folder, the program does not make it again.

For more data, see [docs/HKUST.md](docs/HKUST.md).

## Transcribe MP4 files

1. Make a short preview. Compare it with the audio:

   ```sh
   ./run.sh preview --input "$HOME/LecturesMP4" --output "../PreviewTranscripts" --timestamps --keep-runtime --yes
   ```

2. Make all transcripts:

   ```sh
   ./run.sh transcribe --input "$HOME/LecturesMP4" --output "../Transcripts" --timestamps --yes
   ```

The program does not change the MP4 files.

## Stop, continue and clean up

* To stop, push Ctrl+C. The program keeps its work.
* To continue, run the same command again and add `--resume`.
* To see the status, run `./run.sh status`.
* To remove all downloads and saved work, run `./run.sh cleanup --purge`.

After a successful run, the program removes `.runtime.nosync/` automatically. To keep the downloads for the next run, add `--keep-runtime`.

## More data

* [docs/HKUST.md](docs/HKUST.md): HKUST links, Chrome setup and how the program finds recordings.
* [docs/REFERENCE.md](docs/REFERENCE.md): options, models, runtime, privacy, dependencies and tests.
