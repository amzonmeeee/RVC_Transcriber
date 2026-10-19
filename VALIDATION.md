# Local validation

Validated on 2026-10-20 on Apple M4, 24 GB RAM, macOS 27.0.1 (native arm64). This records observed results, not a claim of perfect recognition.

## Passed

* Portable uv 0.13.1 verified against the published SHA-256; managed Python 3.12.12 installed inside the owned runtime. All 27 runtime packages were resolved, hash-verified, installed offline from local wheels, and checked for compatibility. No global Python/package-manager installation was performed.
* 18 unittest checks passed, covering dangerous path/ownership rejection, symlinks, active-worker locks, subprocess-exit ordering, overwrite protection, shared-cache environment containment, Unicode/spaced filenames, duplicate/collision handling, chunk coverage, conservative overlap removal, failure retention, checkpoint integrity, interrupted-segment resumption, completed-output verification, two-file MP4 publication, and automatic success purge at the supervisor layer.
* The media integration checks used the actual bundled arm64 FFmpeg 7.1, generated MP4 tones and a mocked recognizer. The distributed FFmpeg build enables GPL components. No ffprobe or global FFmpeg was used.
* A real 240-second Cantonese lecture excerpt (original-video minutes 10–14) was transcribed with faster-whisper large-v3, CPU int8, explicit Cantonese (`yue`). Ten planned chunks covered all 240 seconds. Processing took approximately 248 seconds and produced a validated UTF-8 preview with ten timestamped paragraphs. The original source hash was checked before and after processing.
* Preview text includes colloquial Cantonese and English tokens. This is a qualitative text inspection only: no word-error rate, semantic accuracy, or complete word-level coverage has been established without listening and a reference transcript. No lecture text or audio is included in this repository.
* The live preview's runtime lock rejected a concurrent cleanup attempt. Preview intentionally used `--keep-runtime`, allowing reuse for the full batch.
* Before/after observations found no changes in four monitored shared Hugging Face/uv/ONNX cache paths during the preview. An initial synthetic VAD diagnostic exposed an ONNX Runtime telemetry-ID attempt, which was blocked by the execution sandbox. `ORT_DISABLE_TELEMETRY=1` was then added before initialization; retesting was clean. This audit does not assert control over all OS-maintained caches or logs.
* Source parsing, whitespace checks and staged/tracked privacy/large-file guards passed. A source-only local Git repository was initialized; no remote or upload was created.

## Environment limitations and remaining validation

* MLX 0.32.4 imports fail in the current tool execution environment with `No Metal device available`. The hardware is an M4, but this process cannot access its GPU. This differs from a missing `metal` compiler. GPU/Qwen runtime inference and Qwen auto-versus-explicit Cantonese comparison are not yet validated here. The model's pinned config explicitly lists `Cantonese`, and the installed API's Session/context signatures were inspected.
* General installer networking is restricted by this environment, and the requested sandbox escalation was rejected by its permission policy. Authorized HTTPS downloads were made through the allowed download tool, then packages were installed offline in the same contained runtime. Thus a completely unattended online fresh-clone bootstrap has **not** been demonstrated inside this restricted environment.
* Windows/Linux/Intel inference is not implemented. Windows launcher execution was not tested on Windows. A real Windows file-locking test is not claimed; POSIX tests verified ordering and rejection of cleanup while a worker lock is held.
* Automatic-vs-forced language quality comparison, manual audio spot-checking and a quantified Cantonese accuracy evaluation remain outstanding.
* The full batch comprises 11 input files / 10 distinct recordings, approximately 12.5 hours of audio. It was started with the CPU backend after the preview. At this report's creation it is **in progress**, so completion of all final transcripts and removal of the real production runtime are **not yet claimed**. Use `./run.sh status` for live state; a successful default batch purges that state and its runtime after final output validation.

The runtime is deliberately retained while the batch is active or incomplete. Its `.nosync` suffix prevents iCloud synchronization of working audio and checkpoints; final text follows the separately selected output directory's own sync settings.
