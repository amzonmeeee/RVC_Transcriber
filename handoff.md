# Codex Handoff: GitHub-Ready, Fully Removable Local Lecture Transcriber

> **Implement this as a working, reusable program.** Do not stop at a design or a list of shell commands.
>
> The user has multiple approximately 90-minute **MP4 lecture recordings**, with audio not yet extracted. Lectures are primarily **Hong Kong Cantonese with frequent English academic terms and code-switching**. The user already has Codex and ChatGPT Business and **will not pay for another API or subscription**.
>
> **The defining requirement is a disposable runtime:** clone the small source repository, run the program, download models/FFmpeg/dependencies only when needed, transcribe everything, and then remove **all program-managed downloads, caches, intermediates, logs, environments, and checkpoints**. The original MP4s must remain unchanged. The separately designated output directory must contain **only the final transcript files**. The Git repository itself must remain source-only and safe to push to GitHub.

## 1. Non-negotiable acceptance criteria (P0)

1. **Zero additional inference cost:** offline/local inference only. No OpenAI API, DashScope API, Hugging Face hosted inference endpoints, paid transcription services, or external upload of lecture content. Downloading open model weights and dependencies over HTTPS is allowed.
2. **MP4 in, transcript out:** one command consumes a directory of MP4 files, automatically extracts audio with a project-managed FFmpeg binary, and batch-transcribes each recording. Never require manual audio extraction or chunk uploads.
3. **Pushable to GitHub:** repository contains only human-authored source code, scripts, documentation, tests, dependency manifests/locks, and a small example config. It does NOT contain video, audio, transcripts, checkpoints, downloaded binaries, virtual environments, weights, secrets, or caches.
4. **On-demand bootstrap:** from a fresh clone, the launcher detects OS/architecture/hardware and installs all supported runtime tools and model assets on first use. Prefer obtaining a portable `uv` binary and a `uv`-managed Python interpreter **inside the disposable runtime**; never modify system Python, Homebrew, apt, global PATH, shell profiles, or shared model caches. If truly impossible on an OS, fail with a precise explanation; never silently install globally.
5. **One removable workspace:** all program-managed mutable artifacts, including downloader caches, local FFmpeg/ffprobe or equivalent, Python runtime, virtualenv, model weights/tokenizers, temporary audio, segment metadata, logs, tests' runtime artifacts, and checkpoints, must live under ONE project-owned `.runtime/` directory (or explicitly chosen, safely managed equivalent).
6. **Transcript-only output:** default final output is **exactly one complete UTF-8 `.txt` file per source MP4**, optionally with timestamps inside the text. No logs, JSON, SRT, WAV, FLAC, manifest, folders of chunks, or hidden files in `Transcripts/` by default. Additional formats are explicit opt-in.
7. **Automatic purge on complete success:** by default, after all requested files finish and outputs are validated, safely delete `.runtime/` (including all downloaded models and dependencies). Retain it on failure/interruption so the batch can resume; provide an explicit purge command. A `--keep-runtime` option can trade disk space for avoiding re-downloads.
8. **Safe uninstall:** removing the Git checkout and its `.runtime/` must leave no program-managed installation behind. The output directory and original MP4 files must NOT be touched by uninstall or cleanup. The outer launcher must handle cleanup only **after** the transcriber subprocess exits (important for Windows file locking).
9. **Reliable long recordings:** chunk/silence handling, sensible memory limits, overlap/de-duplication, checkpoints, retries, progress and resumability for multiple 1.5-hour recordings.
10. **Actual implementation and validation:** write the program, tests, concise documentation, and run the available tests. Do not claim Cantonese recognition quality is proven without checking representative lecture samples.

## 2. User experience / controllable program

Prioritize an easy-to-control CLI with thin one-click launchers for macOS/Linux and Windows where supported. A GUI is optional, not a replacement for the CLI.

Target interface (exact commands may differ, but implement and document equivalent functionality):

```bash
# From a new clone, no manual installation of FFmpeg or ASR model:
./run.sh doctor
./run.sh preview --input "$HOME/LecturesMP4" --output "$HOME/LectureTranscripts"
./run.sh transcribe --input "$HOME/LecturesMP4" --output "$HOME/LectureTranscripts"

# Control, inspection, and interruption handling:
./run.sh status
./run.sh transcribe --input "$HOME/LecturesMP4" --output "$HOME/LectureTranscripts" --resume
./run.sh cleanup --purge
```

For Windows, provide `run.ps1` with equivalent behavior. If truly cross-platform portability is infeasible for a backend, choose a supported fallback or give an actionable, non-destructive error; do not fake support.

Required controls and behavior:

- `doctor`: inspect OS, CPU/GPU, memory, free disk, candidate backend, and tool/model availability **without downloading model weights**.
- `preview`: transcribe a short representative sample (about 3-5 minutes, preferably including English code-switching), allowing quality inspection before committing to the full batch.
- `transcribe`: fully batch-process MP4s with clear per-lecture/per-segment progress, elapsed time, and failures. No background cloud jobs or hidden services.
- `status`: report current/previous job state, output files, selected model, total local runtime disk footprint, and whether cleanup is available. Must not download anything just to inspect status.
- `--resume`: reuse validated checkpoints after interruption; never needlessly reprocess a completed chunk.
- `cleanup --purge`: remove **only** the program's verified runtime directory, not inputs or transcripts. Operate from the small outer launcher if the runtime itself has been removed.
- `--keep-runtime`: opt out of automatic purge so model downloads can be reused next time. Document that default purging means downloads happen again on future runs.
- Support `--model auto|qwen3-asr-1.7b|qwen3-asr-0.6b|whisper-large-v3` as appropriate, `--format txt` by default, `--timestamps`, `--glossary`, `--overwrite`, `--dry-run`, and `--yes` for unattended execution. Validate flags against actual backend capabilities.
- Honor Ctrl+C/termination: checkpoint and exit gracefully where possible; do **not** purge incomplete work automatically.
- Show what will download, approximate download/disk size, and whether it requires network access before first-use downloads. Avoid unexpected changes to the machine.

## 3. Strict filesystem layout and ownership

Expected conceptual layout (inputs and final transcripts remain OUTSIDE the Git checkout):

```text
~/LecturesMP4/                      # USER DATA: read-only, never delete or modify
    HUMA1710_Lecture01.mp4
    HUMA1710_Lecture02.mp4

~/lecture-transcriber/              # SMALL, GITHUB-READY SOURCE REPOSITORY
    README.md
    handoff.md                      # This specification may be retained
    pyproject.toml / uv.lock        # or equivalent pinned dependencies
    .gitignore
    run.sh
    run.ps1
    src/...
    tests/...
    config.example.toml
    .runtime/                       # ALL MANAGED MUTABLE/THIRD-PARTY ASSETS
        .owner-marker               # unique identity + safe cleanup metadata
        tools/                      # portable uv, FFmpeg, ffprobe if needed
        python/                     # project-local managed Python
        .venv/                      # Python packages
        models/                     # downloaded model weights/tokenizers
        cache/                      # uv, pip, Hugging Face, torch etc.
        tmp/                        # extracted audio / temporary chunks
        checkpoints/                # resume state / internal JSON
        logs/                       # debug logs
        home/                       # optional scoped HOME/XDG state

~/LectureTranscripts/               # FINAL USER DATA: NEVER AUTO-DELETE
    HUMA1710_Lecture01.txt
    HUMA1710_Lecture02.txt
```

- `~/LectureTranscripts/` must contain **only final transcript files** by default, not application state.
- Use atomic writing: generate an output in `.runtime/tmp/`, validate it, then atomically move/replace it into `LectureTranscripts/`. Avoid incomplete final `.txt` files on crash.
- If filenames collide, refuse or use deterministic collision-safe naming; never silently overwrite existing transcript files.
- Preserve Unicode and spaces in input filenames. Resolve and validate all paths.
- Inputs are read-only. Do not rename, re-encode, delete, or move the user's MP4 files.
- Keep the final output path independent from the checkout and disposable runtime so the whole repository can be deleted safely.
- Reject overlap among input, final output, and runtime paths. Refuse unsafe destinations (filesystem root, home directory itself, repository root, drive root, symlink escapes, or a path inside `.runtime/`).

## 4. Bootstrap tools and dependency containment

Implement **download-on-first-use, reuse-until-purged**, without global installations.

Suggested approach:

1. The outer `run.sh` / `run.ps1` uses standard built-in OS capabilities to determine architecture and download a pinned, verified portable `uv` release **into `.runtime/tools/`**. Prefer a release artifact with published checksums/attestations; verify before execution. Do not require `curl | sh` with unverified scripts.
2. Configure `uv` to install its managed Python and virtual environment strictly inside `.runtime/`. Use locked/pinned Python package versions, respecting backend platform compatibility.
3. Make project-local `ffmpeg` available only when audio extraction is needed. A pinned, hash-verified `imageio-ffmpeg` wheel may provide an FFmpeg executable on supported platforms; use a vetted FFmpeg distribution or another defensible mechanism if a separate `ffprobe` binary is required. Do not assume `imageio-ffmpeg` supplies `ffprobe`. **Never** invoke a global package manager for FFmpeg.
4. Download the chosen ASR model weights and tokenizer to `.runtime/models/` only when a transcription actually needs them. Pin model revision/commit where feasible and validate download provenance. Do not commit or redistribute weights in Git.
5. Redirect caches, temporary paths, and build outputs of all child processes into `.runtime/`. Set relevant scoped variables as applicable: `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, `UV_PYTHON_BIN_DIR`, `UV_TOOL_DIR`, `PIP_CACHE_DIR`, `HF_HOME`, `HF_HUB_CACHE`, `HF_XET_CACHE`, `TORCH_HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `TMPDIR`/`TMP`/`TEMP`, and Python bytecode cache settings. Test the **actual** dependencies for other default cache locations and override them. Avoid setting/altering the user's global environment.
6. Do not alter shell startup files or global environment variables, and do not call `sudo`, `brew install`, `apt install`, `pip install --user`, or unscoped global `pip install`.
7. During transcription, network access should only be necessary for a clearly identified missing dependency/model download. No analytics, error-report uploads, telemetry of audio/text, or inference calls to servers.
8. If a dependency cannot be contained, disclose the exact residual path and request explicit opt-in before doing anything outside `.runtime/`; otherwise fail closed.

**Important technical boundary:** application-owned downloads/caches can be contained, but no user-space program can guarantee removal of *all OS-maintained caches* (for example, driver shader caches, security-service caches, system networking logs) or GPU drivers already installed on the host. Document this honestly; do not claim a sandbox/VM security boundary when only using scoped filesystem paths.

## 5. ASR backend selection and quality

Prefer **local Qwen3-ASR**, benchmarked on actual Cantonese-English lecture samples rather than selected purely by model size.

- Apple Silicon: evaluate `mlx-qwen3-asr` with MLX (or a better maintained, verifiable MLX Qwen3-ASR implementation).
- NVIDIA GPU / other compatible platform: evaluate the official `QwenLM/Qwen3-ASR` local implementation and its current hardware requirements.
- Lower-resource CPU-only machine: consider an appropriately sized local `faster-whisper`/Whisper fallback; never conceal that CPU-only transcription of several 90-minute videos may be slow.
- Prefer Qwen3-ASR 1.7B for quality when hardware supports it; permit 0.6B as a lower-memory option. Keep model choice configurable.
- The implementation must check the current backend API and language names. Do **not** assume that forcing a literal `yue` code is accepted by every backend; test automatic versus explicit language selection with code-switched Cantonese samples.
- Support an optional course-specific academic vocabulary/context/glossary file if the model backend exposes a context/hotword interface; do not blindly claim all backends do.
- Preserve HK Cantonese colloquialisms and particles, spoken repetitions, and English technical terms. Use Traditional Chinese (Hong Kong conventions), never rewrite speech into formal Mandarin or summarize the lecture.
- If automatic script conversion is needed, keep it separate and conservative. Simplified-to-Traditional character conversion is **not** Cantonese-language conversion.
- Handle silence/non-speech carefully. Avoid hallucinated phrases, loops/repeated outputs, silently dropped chunks, and inventing unclear speech.
- Never automatically use a paid or hosted ASR API as fallback.

Useful implementation references (evaluate current API, licenses, dependencies, and compatibility before adopting):

- Official Qwen3-ASR: https://github.com/QwenLM/Qwen3-ASR
- Apple MLX implementation: https://github.com/moona3k/mlx-qwen3-asr
- Alternative Apple MLX implementation: https://github.com/gabrimatic/qwen3-asr-mlx
- uv environment/storage documentation: https://docs.astral.sh/uv/reference/environment/

## 6. Video/audio workflow for long lectures

For every MP4:

1. Locate all supported videos in the selected input folder. Optionally support recursion with an explicit flag.
2. Inspect audio stream(s) safely; give a clear per-file error if none exist.
3. Use the project-managed FFmpeg to extract audio to a model-compatible sample rate/channel count without modifying video.
4. Work in bounded chunks for 90-minute lectures. Prefer voice activity detection or silence-aware boundaries, with controlled overlap to avoid cut-off words.
5. Keep exact original-video time offsets. If reliable alignment is not available, provide honest approximate **chunk** timestamps, not fabricated word-level timings.
6. Transcribe using a single loaded model session per batch when viable, avoiding redundant model reloads.
7. Merge chunks in sequence; conservatively de-duplicate overlap without deleting actual repeated speech.
8. Write a checkpoint **under `.runtime/checkpoints/`** after each successful segment. On resume, verify source identity (size, modification time, optionally a fast hash), model/config version, and chunk definitions before reusing cached results.
9. Validate completeness: nonempty results for audible speech, coverage of each planned segment, monotonic timestamps, and absence of missing spans. Record uncertainty; never invent missing lecture text.
10. Produce a human-readable UTF-8 transcript. Default is one `.txt` per video; format may contain `[HH:MM:SS]` headings every chunk or minute, but no verbose ASR metadata or operational logs.

A short preview test on representative 3-5 minute samples is required for model validation. Automated heuristics cannot establish true transcription accuracy; report this limitation and support manual comparison with audio. Do not silently transform a model output into a plausible but unverifiable lecture transcript.

## 7. Lifecycle and deletion semantics (critical)

### Default behavior

```text
clone source repo -> run -> bootstrap into .runtime -> transcribe MP4s
-> validate/finalize .txt transcripts into separate output directory
-> exit transcription worker -> purge entire .runtime
-> result: source-only Git checkout + untouched MP4s + final .txt transcripts
```

After the user deletes the source checkout, **only the original MP4s and final transcripts** should remain as user-owned project files. If the user later re-clones the repo, it can bootstrap afresh.

### Failure / interrupted batch

- Keep `.runtime` and checkpoints to permit `--resume`.
- Do not delete working state on partial failures, even if some individual lectures completed.
- Keep already successfully finalized transcripts safe in the output directory.
- Do not overwrite existing final transcripts without explicit `--overwrite`.
- A user may deliberately run `cleanup --purge` after abandoning the partial job; require clear confirmation if resumable work would be lost.

### Safe cleanup contract

- Creation of `.runtime/` must write a unique **ownership marker** recording repository identity and intended absolute runtime path.
- Cleanup must verify that marker, canonical path, expected parent directory, and that no currently active worker depends on the directory.
- Do not follow symlinks outside the managed tree. Defend against path traversal and symlink races.
- Cleanup must never target the input MP4 directory, output transcript directory, user home, repository root, or generic shared caches; refuse instead of guessing.
- Cleanup must remove project-managed venv/Python/uv/FFmpeg/model/tokenizer caches, extracted WAV/FLAC, logs, job checkpoint JSON, and temporary files, then remove the empty `.runtime` directory itself.
- Implement deletion in an outer launcher/supervisor **after** workers have stopped. Verify removal and report leftovers honestly.
- Provide `cleanup --dry-run` to print exactly what is owned and would be removed. Include tests that deliberately pass unsafe paths.
- Make the normal success path auto-purge, with `--keep-runtime` for opt-in reuse.
- Do not delete final transcripts even if a file is named like a cache or the output folder is adjacent to `.runtime`.

## 8. GitHub publication requirements

Deliver a GitHub-ready repository. It should be possible to create a public or private remote without disclosing user recordings or committing large assets.

Implement `.gitignore` covering at minimum:

```gitignore
.runtime/
.venv/
__pycache__/
*.pyc
.env
.env.*
!.env.example
*.mp4
*.m4a
*.mp3
*.wav
*.flac
*.srt
*.log
*.ckpt
*.safetensors
*.pt
*.pth
*.bin
*.gguf
Transcripts/
LecturesMP4/
outputs/
```

Refine patterns if the source tree genuinely needs small, intentional fixtures. Never track actual lecture recordings, transcripts, model weights, downloaded executable artifacts, or authentication tokens. Add a small pre-commit/pre-push privacy and large-file guard, and inspect staged files before any push.

Repository should include:

```text
README.md                  # install-free quick start, supported OS/hardware, cleanup
handoff.md                 # this requirement contract
LICENSE                    # appropriate project source license, if authorized
.gitignore
config.example.toml
run.sh
run.ps1
pyproject.toml
uv.lock (or equivalent)
src/lecture_transcriber/...
tests/...
.github/workflows/ci.yml  # small-source tests; do not fetch huge models by default
```

- Pin dependencies and document model/FFmpeg licensing, source URLs, and hash/revision verification; do not package third-party weights or FFmpeg binaries into the repository.
- Include no required API keys. No paid API credentials should ever be requested.
- CI must validate source code, CLI, safety checks, and mock/small fixture audio workflows without downloading multi-GB models.
- Create the repository locally with clear commit history if Git is available. **Do not create a GitHub remote or push to an account unless authenticated and authorized by the user**. If GitHub access exists and the user has authorized pushing, inspect staged content before publishing.
- Document how to clone, run one command, inspect output, and remove the entire tool afterward.

## 9. Tests Codex must actually run

Treat these as acceptance tests, not optional suggestions:

1. **Clean-start test:** on a clean working tree with no `.runtime`, launcher detects host, shows pending downloads, and bootstraps without global package-manager installs or modifying PATH/profile.
2. **MP4 smoke test:** generate/use a small synthetic or openly licensed MP4 with speech; exercise the real project-managed FFmpeg extraction and CLI output. Do not claim model accuracy without a real model sample.
3. **Batch test:** at least two MP4s, including Unicode/spaces in names, produce exactly one complete `.txt` file per MP4 by default.
4. **Interruption/resume test:** simulate failure mid-video, verify checkpoints remain under `.runtime`, and verify resume does not redo valid segments.
5. **Success-purge test:** after successful processing, `.runtime` and all its generated assets are absent, output text remains, original MP4s are unchanged, and no extra files appear in the final output directory.
6. **Failure-retention test:** partial failure preserves runtime and finalized transcripts; purge is not automatic.
7. **Cleanup safety test:** attempts to purge home, root, the input directory, the output directory, repo root, and symlink escapes are refused.
8. **Containment audit:** record known app-created paths before/after a smoke test; verify no application-managed cache/install files outside `.runtime`. Disclose any unavoidable OS-level residuals.
9. **Git staging audit:** run a check showing no media, transcripts, downloaded binaries, models, `.runtime`, or secrets would be committed.
10. **Cantonese quality preview:** if the user's real lecture MP4s are available, test a representative excerpt with Cantonese and English. Report actual problems and any manual spot-check still required; do not make up quality metrics.
11. **Portability smoke test:** validate the supported platform launchers where available; make unsupported OS paths fail explicitly and safely.
12. **Cleanup after subprocess exit:** specifically test that Windows-style locked runtime files are not removed while in use.

## 10. Documentation / handoff from Codex after implementation

Do not provide only design advice. Implement files and give a concise completion report with:

- Actual repo path and the **exact command** to process a folder of MP4 lectures.
- Detected OS, CPU/GPU, selected local ASR backend/model, and reason for selection.
- The first-use download process, expected disk footprint, and what gets removed after success.
- The exact commands for preview, full batch, resumption, status, optional cache retention, cleanup, and optional Git push.
- Tests executed, test results, remaining limitations, and any failed acceptance criteria.
- Confirmation that no paid API was used and recordings did not leave the local machine.
- Confirmation that final outputs are transcript-only, originals are untouched, and no application-managed runtime resources remain after a clean run.

## 11. Implementation priorities / decision rule

**P0:** real one-command MP4-to-Cantonese-transcript batch operation; no paid API; all runtime artifacts isolated; safe automatic purge; GitHub-safe repo; reliable resume/failure behavior.

**P1:** smart backend selection, model quality preview, timestamps, glossary/context, Windows/Linux portability, high-quality documentation.

**P2:** local graphical interface, diarization, optional `.md`/`.srt`/`.json` outputs, sophisticated forced alignment.

Do not build a heavyweight GUI or cloud service before the P0 flow passes. Make reasonable local technical decisions rather than stopping for unnecessary approval. Where access to actual MP4 recordings, platform hardware, internet, or GitHub authorization is missing, finish and test everything possible, explicitly report the precise blocker, and never fabricate successful transcription or cleanup.

**Definition of done:** With an ordinary local machine and sufficient resources, the user can clone a small GitHub repository, place multiple 1.5-hour lecture MP4s in a separate input directory, execute one command, receive one full Cantonese-English `.txt` transcript per video in a separate output directory, and finish with no project-managed models, FFmpeg, Python environment, intermediate audio, caches, or logs left installed. The original MP4s and final text remain intact; deleting the repository afterwards removes the program itself.
