# Local lecture transcriber

Turn MP4 lectures into one UTF-8 text file per recording, locally. Designed for Hong Kong Cantonese with English academic terms. Audio and text are never sent to an inference service. No API key or subscription is required.

## Quick start

Supported release: **Apple Silicon macOS 14+**, an existing Python 3.9+ for the small standard-library supervisor, and built-in `curl`. The supervisor installs no packages into that Python. Inference uses a private Python 3.12.12. This checkout does not install Command Line Tools, Homebrew, drivers, or anything globally. Windows, Linux and Intel Macs currently fail with an explicit unsupported-platform error; `run.ps1` is an explanatory stub, not Windows support.

```sh
git clone https://github.com/amzonmeeee/RVC_Transcriber.git
cd RVC_Transcriber
```

```sh
./run.sh doctor
./run.sh preview --input "$HOME/LecturesMP4" --output "../PreviewTranscripts" --timestamps --keep-runtime --yes
./run.sh transcribe --input "$HOME/LecturesMP4" --output "../Transcripts" --timestamps --yes
```

Use a separate preview destination so preview files cannot be confused with complete lectures. Preview defaults to minutes 10–14 of the first recording. Adjust with `--start 1200 --seconds 240`. Listen to that original-video interval while reading the preview before relying on recognition accuracy. A preview has `.preview.txt` in its filename. It also purges its runtime by default: pass `--keep-runtime` when continuing to a full batch.

Multiple input folders are accepted in one invocation:

```sh
./run.sh transcribe --input "$HOME/LecturesMP4/Week 1" --input "$HOME/LecturesMP4/Week 2" --output "../Transcripts" --timestamps --yes
```

Same-named recordings are compared by complete SHA-256. Identical copies share one transcript; distinct same-named recordings are refused. Unicode and spaces are supported. Recursive discovery is opt-in with `--recursive`.


## Controls

```sh
./run.sh status
./run.sh transcribe --input "$HOME/LecturesMP4" --output "../Transcripts" --resume --yes
./run.sh cleanup --dry-run
./run.sh cleanup --purge                  # interactive confirmation
./run.sh cleanup --purge --yes            # deliberately discard resumable work
```

Repeat the original model, language, timestamp, glossary and preview options when resuming. Checkpoints bind the full source hash, size, modification time, output path, model revision, settings and sample-accurate chunk plan. Completed text is skipped only if it matches a retained checkpoint and output hash. After a success purge, retained checkpoints no longer exist: choose a fresh destination or explicitly use `--overwrite` to regenerate.

`--dry-run` inspects paths and lists planned outputs without downloading or changing files. `doctor` and `status` do not download tools or weights. `--overwrite` explicitly allows replacement; otherwise publication is an atomic no-clobber operation. `--format txt` is the only supported format. Output directories must contain only `.txt` files and must be outside the checkout, separate from inputs, on the same filesystem as the checkout. Root, home, checkout ancestors, overlaps and symlink paths are rejected.

## Models and text

* `--model auto`: try Qwen3-ASR 1.7B using MLX/Metal. If the installed runtime cannot access Metal, announce a switch to local Whisper large-v3 on CPU, int8. CPU processing may take many hours.
* `--model qwen3-asr-1.7b` or `qwen3-asr-0.6b`: explicit MLX model; failure to access Metal is an error, not a silent model switch. The smaller model reduces memory/download size.
* `--model whisper-large-v3`: local faster-whisper/CTranslate2 CPU backend; useful in GPU-restricted processes.
* `--language Cantonese` (default) passes the backend's supported name: `Cantonese` to Qwen, `yue` to Whisper. `--language auto` permits automatic detection. Comparing them on an actual mixed-language excerpt is recommended.
* `--glossary course-vocabulary.txt`: UTF-8 domain context, up to 8000 characters; Qwen context or Whisper initial prompt. This biases recognition and does not guarantee correct terms.

Output is speech recognition, not a summary. OpenCC `s2hk` separately converts simplified characters to Hong Kong traditional forms; it cannot convert Mandarin paraphrases into spoken Cantonese or correct recognition errors. Repetitions and English terms are retained as recognized.

FFmpeg extracts only the first audio track as mono 16 kHz PCM, without changing the MP4. Audio extraction is on disk; inference reads at most 29 seconds at once. Default 28-second chunks prefer quiet boundaries, with 0.6-second overlap only where a speech cut is unavoidable. Only substantial exact boundary repetitions are removed. Each completed chunk is checkpointed atomically. Truncated, empty audible, or looping output is retried and then fails visibly if unresolved. Silence is marked, not filled with invented text. Coverage checks prove each planned audio interval was processed, **not that every spoken word was recognized correctly**.

`--timestamps` inserts approximate chunk-start times from the original video. These are not word-level alignment. No diarization, subtitle formats or forced aligner is included.

## Disposable runtime and privacy

This release keeps all managed state in **`.runtime.nosync/`**. The `.nosync` suffix avoids iCloud uploading the working audio/model tree when the source checkout is in iCloud Drive ([Apple documentation](https://developer.apple.com/library/archive/documentation/General/Conceptual/iCloudDesignGuide/Chapters/iCloudFundametals.html)). Final outputs follow the user's chosen directory and its own sync settings.

Everything program-managed lives under that one directory: portable uv, managed Python, venv, FFmpeg, weights/tokenizers, dependency/model caches, temporary WAVs, checkpoints, logs, status, and test artifacts. The output directory contains final text files only. First use needs HTTPS access to GitHub/Astral, PyPI and Hugging Face/CDN; allow approximately 4–5 GB downloads and 12 GB free disk for one backend, more if retaining multiple models. Downloads can be reused until cleanup. Hugging Face telemetry and implicit authentication are disabled; model loading uses local paths and inference sets offline mode. ONNX Runtime telemetry is disabled before initialization with `ORT_DISABLE_TELEMETRY=1` ([upstream privacy documentation](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md)).

On complete success, the outer supervisor waits for its worker to exit, validates the runtime ownership marker and lock, and removes the entire runtime. On failure/Ctrl+C it retains state. `--keep-runtime` retains downloads after success. Default cleanup means a future run downloads again. Deleting the checkout after cleanup removes the program; original videos and the independent output directory remain.

Cleanup accepts no arbitrary directory argument. It verifies the canonical checkout/runtime path, a UUID ownership record and an exclusive process lock. It uses Python's fd-based symlink-resistant `rmtree`, refusing hosts without that implementation. Symlinks inside the tree are unlinked without deleting their targets. The runtime lock is inherited by the worker; cleanup cannot run concurrently with an active worker. OS/driver/security-service caches, crash reports and networking logs are outside application control: this is contained application state, not a VM or security sandbox.

## Dependencies and provenance

`requirements.lock` pins all transitive wheels with SHA-256 for CPython 3.12 on Apple Silicon. No third-party binaries or models are committed. uv 0.13.1 has its release SHA-256 embedded in `bootstrap.py`; its managed Python download is checked by uv's bundled release manifest. FFmpeg comes only from the hash-locked `imageio-ffmpeg` wheel; this distribution does **not** provide ffprobe. Stream selection and decoded WAV frame counts use FFmpeg and the standard WAV reader.

* [MLX Qwen3-ASR](https://github.com/moona3k/mlx-qwen3-asr), pinned package 0.4.4: Apache-2.0; [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) model snapshots are pinned to immutable Hugging Face commits in `bootstrap.py` (Apache-2.0).
* [faster-whisper](https://github.com/SYSTRAN/faster-whisper), pinned 1.2.1, and [CTranslate2](https://github.com/OpenNMT/CTranslate2): MIT; [converted Whisper large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) uses a pinned revision and verified model hash (MIT).
* [uv](https://github.com/astral-sh/uv): MIT/Apache-2.0. [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) wrapper: BSD-2-Clause; its bundled FFmpeg executable has separate LGPL/GPL build terms (inspect `-version`/`-L` before redistribution). [OpenCC](https://github.com/nk2028/opencc-python): Apache-2.0.

No source license has been chosen yet. Model licenses and upstream compatibility are separate from source licensing.

## Tests and Git hygiene

```sh
python3 -B -m unittest discover -s tests -v
# When dependencies are present, run all media integration tests as well:
.runtime.nosync/.venv/bin/python -B -m unittest discover -s tests -v
python3 -B scripts/privacy_guard.py --all
git config core.hooksPath scripts
```

Stdlib tests run without downloading weights. Media tests use actual project-managed FFmpeg and generated MP4 test tones with an explicitly mocked recognizer: they test media, resumability, atomic text publication and deletion, not ASR accuracy. All temporary test fixtures stay in the disposable runtime. CI runs source/safety checks, not multi-GB model inference.

The privacy guard rejects staged/tracked media, model weights, environments, logs, transcripts, likely secrets and files above 1 MiB. `.gitignore` additionally excludes generated text, model/cache folders, binary downloads and local credentials. Review `git diff --cached --stat` before publishing. Transcription commands never create a remote or push automatically; publication is an explicit Git operation.
