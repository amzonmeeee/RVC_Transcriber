# Reference

## Platform

The program supports only Apple Silicon Macs with macOS 14 or later. On other platforms, it stops with an error and installs nothing. `run.ps1` only shows this error. It is not Windows support.

The launcher uses your Python 3.9 or later only for a small standard-library supervisor. It installs no packages into that Python. Speech recognition uses a private Python 3.12.12. The program does not install Command Line Tools, Homebrew, drivers or other global software.

## Input and output

* `--input DIR`: a folder of MP4 files. You can use this option more than one time.
* `--recursive`: also find MP4 files in subfolders.
* `--output DIR`: the folder for the transcripts. The folder must contain only `.txt` files. It must be outside the checkout, and on the same disk as the checkout.

The program does not accept these output folders:

* The root folder or your home folder.
* The checkout, or a parent folder of the checkout.
* A folder that is also an input folder.
* A symbolic link.

Two recordings with the same name and the same SHA-256 make one transcript. Two different recordings with the same name cause an error. Names with Unicode characters and spaces are permitted.

## Preview

A preview transcribes 4 minutes of the first recording. By default, it starts at minute 10. To change this, use `--start 1200 --seconds 240`. The maximum is 300 seconds.

A preview file has the name `<recording>.preview.txt`. Use a different output folder for previews. Listen to the same part of the recording, and compare it with the text.

## Options

| Option | Function |
| --- | --- |
| `--model auto` | Use Qwen3-ASR 1.7B on the GPU (MLX/Metal). If Metal is not available, use Whisper large-v3 on the CPU. The CPU can take many hours. |
| `--model qwen3-asr-1.7b`, `qwen3-asr-0.6b` | Use this Qwen model on the GPU. If Metal is not available, stop with an error. The 0.6B model uses less memory and disk. |
| `--model whisper-large-v3` | Use faster-whisper on the CPU. |
| `--language Cantonese` | The default. Send `Cantonese` to Qwen or `yue` to Whisper. |
| `--language auto` | Let the model find the language. |
| `--glossary FILE` | A UTF-8 file with course terms, maximum 8000 characters. It helps the model, but it does not make the terms correct. |
| `--timestamps` | Add the approximate start time of each chunk. These times are not word times. |
| `--format txt` | The only format. |
| `--resume` | Use saved work from a stopped run. |
| `--overwrite` | Replace a transcript that exists. |
| `--dry-run` | Show the plan. Do not download or change files. |
| `--keep-runtime` | Keep the downloads after a successful run. |
| `--yes` | Do not ask for confirmation. |
| `--chunk-seconds N` | Chunk length, 10–29 seconds. The default is 28. |

When you continue with `--resume`, use the same model, language, timestamp, glossary and preview options. If a setting or a source file changes, the program does not use the saved work.

`doctor` and `status` do not download tools or models.

## Text quality

The output is speech recognition. It is not a summary. OpenCC `s2hk` changes simplified characters to Hong Kong traditional characters. It does not change Mandarin into Cantonese, and it does not correct recognition errors.

The program processes the audio in chunks of maximum 29 seconds. It cuts the chunks at quiet points if possible. If it must cut in speech, the chunks overlap by 0.6 seconds. The program removes only long, exact repeats at the overlaps. If a chunk is empty, cut short or repeats in a loop, the program tries again. Then it stops with an error. The program marks silence. It does not add text for silence.

The checks make sure that the program processed all of the audio. They do not make sure that each word is correct.

## Use as a component

Other programs can use the transcriber as a separate component. For example, HKUST Canvas Workbench uses it. These commands are for that use:

```sh
./run.sh install --model auto --json-progress --yes
./run.sh streams --streams streams.json --output DIR --keep-runtime --json-progress --yes
```

* `install` downloads the runtime and the model. It does not read audio. It keeps the runtime after it completes.
* `streams` transcribes HTTPS streams. The JSON file is a list of `{"name": ..., "stream": "https://...", "stream_id": ...}` items. `name` is the transcript file name. `stream_id` must not change between runs, so that `--resume` can find the saved work.
* `--json-progress` adds lines that start with `@@progress `, followed by one JSON object. The `event` field gives the step, for example `preparing environment`, `downloading model`, `extracting audio`, `transcribing`, `complete` or `failed`.

## Runtime and privacy

The program keeps all tools, models, caches, temporary audio, checkpoints and logs in `.runtime.nosync/`. The `.nosync` name stops iCloud from uploading this folder if the checkout is in iCloud Drive.

The first run needs HTTPS access to GitHub, PyPI and Hugging Face. It downloads approximately 4–5 GB. Keep 12 GB of free disk space. Hugging Face telemetry and ONNX Runtime telemetry are off. During recognition, the models work offline.

After a successful run, the supervisor waits for the worker to stop. Then it removes all of `.runtime.nosync/`. After a failure or Ctrl+C, it keeps the folder so that you can continue. If you delete the checkout after cleanup, the program is fully removed. Your recordings and transcripts stay.

`cleanup` removes only its own runtime folder. It does these checks first:

* The folder path is correct.
* The folder has the correct ownership record.
* No worker uses the folder.

It does not follow symbolic links.

NOTE: macOS can keep its own caches and logs, for example driver caches. The program cannot control these. The runtime folder is not a security sandbox.

## Dependencies

`requirements.lock` pins all Python wheels with SHA-256. The repository contains no binaries and no models. `bootstrap.py` contains the SHA-256 of uv 0.13.1 and the commit of each model. FFmpeg comes from the `imageio-ffmpeg` wheel. This wheel does not include ffprobe.

* [MLX Qwen3-ASR](https://github.com/moona3k/mlx-qwen3-asr) 0.4.4 and [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) models: Apache-2.0.
* [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 1.2.1, [CTranslate2](https://github.com/OpenNMT/CTranslate2) and [Whisper large-v3](https://huggingface.co/Systran/faster-whisper-large-v3): MIT.
* [uv](https://github.com/astral-sh/uv): MIT or Apache-2.0.
* [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg): BSD-2-Clause. The FFmpeg program in it has LGPL/GPL terms.
* [OpenCC](https://github.com/nk2028/opencc-python): Apache-2.0.

The source code does not have a license yet.

## Tests and Git

```sh
python3 -B -m unittest discover -s tests -v
.runtime.nosync/.venv/bin/python -B -m unittest discover -s tests -v   # also media tests
python3 -B scripts/privacy_guard.py --all
git config core.hooksPath scripts
```

The standard tests do not download models. The media tests use the project FFmpeg, test MP4 files and a mock recognizer. They do not test recognition quality. CI runs only the source and safety tests.

The privacy guard stops a commit if it has any of these items:

* Media files or model weights.
* Environments, logs or transcripts.
* Possible secrets.
* Personal home paths.
* Files larger than 1 MiB.

Before you push, examine `git diff --cached --stat`. The program never pushes to Git.
