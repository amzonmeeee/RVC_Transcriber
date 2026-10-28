"""Contained worker. Model downloads finish before local-only inference starts."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import wave

# Set before any third-party import, even when invoking the worker directly.
os.environ['ORT_DISABLE_TELEMETRY'] = '1'

from .safety import atomic_json, no_symlinks, publish, sha256

SCHEMA = 1
SAMPLE_RATE = 16000


def inference_offline():
    import huggingface_hub.constants as constants
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    constants.HF_HUB_OFFLINE = True


def fingerprint(path, stream_id=None):
    if stream_id:
        # Streams are identified by their stable RVC media path; the URL token changes per run.
        return dict(stream=stream_id)
    s = path.stat()
    # Full hash is deliberate: same-name/copy recordings and changed inputs are verified.
    return dict(size=s.st_size, mtime_ns=s.st_mtime_ns, sha256=sha256(path))


def checkpoint_key(item, job):
    cfg = {k: job[k] for k in ('model', 'revision', 'language', 'glossary', 'timestamps',
            'chunk_seconds', 'preview', 'start', 'seconds')}
    cfg.update(schema=SCHEMA, source=item['source'], output=item['output'])
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(), cfg


# Network options for HLS streams (HKUST RVC); local files never touch the network.
STREAM_OPTIONS = ['-reconnect', '1', '-reconnect_on_network_error', '1', '-reconnect_delay_max', '30',
                  '-rw_timeout', '60000000']


def extract(ffmpeg, source, audio, job, stream=None):
    args = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
    if stream:
        # Input seeking: a preview fetches only the requested part of the stream.
        if job['preview']:
            args += ['-ss', str(job['start'])]
        args += [*STREAM_OPTIONS, '-i', stream]
        if job['preview']:
            args += ['-t', str(job['seconds'])]
    else:
        args += ['-i', str(source)]
        if job['preview']:
            args += ['-ss', str(job['start']), '-t', str(job['seconds'])]
    args += ['-map', '0:a:0', '-vn', '-ac', '1', '-ar', str(SAMPLE_RATE), '-c:a', 'pcm_s16le', str(audio)]
    partial = audio.with_suffix('.partial.wav')
    args[-1] = str(partial)
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Audio extraction failed (missing audio stream, corrupt MP4, or expired/unreachable '
                           'stream; rerun to fetch a fresh stream link): ' + result.stderr[-3000:])
    with wave.open(str(partial), 'rb') as wav:
        if wav.getnframes() == 0:
            raise ValueError('No audio in selected interval')
        if wav.getnchannels() != 1 or wav.getframerate() != SAMPLE_RATE or wav.getsampwidth() != 2:
            raise ValueError('FFmpeg produced unexpected audio format')
    os.replace(partial, audio)


def plan_chunks(audio, seconds):
    """Bounded reads, low-energy cuts, zero gaps; overlap only on hard speech cuts."""
    import numpy as np
    with wave.open(str(audio), 'rb') as wav:
        total = wav.getnframes()
        plan, start = [], 0
        nominal = seconds * SAMPLE_RATE
        while start < total:
            end = min(total, start + nominal)
            overlap = 0
            if end < total:
                search = max(start + 8 * SAMPLE_RATE, end - 4 * SAMPLE_RATE)
                wav.setpos(search)
                data = np.frombuffer(wav.readframes(end - search), dtype='<i2').astype(np.float32) / 32768
                frame = 320  # 20 ms
                n = len(data) // frame
                energy = np.sqrt(np.mean(data[:n * frame].reshape(n, frame) ** 2, axis=1))
                # Choose a quiet 100 ms region to avoid cutting a consonant.
                smooth = np.convolve(energy, np.ones(5) / 5, mode='valid')
                index = int(np.argmin(smooth))
                if smooth[index] < 0.012:
                    end = search + (index + 2) * frame
                else:
                    overlap = int(0.6 * SAMPLE_RATE)
            plan.append(dict(start=start, end=end, overlap_next=overlap))
            start = end - overlap
    validate_plan(plan, total)
    return plan, total


def validate_plan(plan, total):
    if not plan or plan[0]['start'] != 0 or plan[-1]['end'] != total:
        raise ValueError('Incomplete audio coverage')
    previous = None
    for part in plan:
        if not (0 <= part['start'] < part['end'] <= total):
            raise ValueError('Invalid chunk boundaries')
        if previous and (part['start'] != previous['end'] - previous['overlap_next'] or part['end'] <= previous['end']):
            raise ValueError('Gap or non-monotonic chunk coverage')
        previous = part


def read_chunk(wav, part):
    import numpy as np
    wav.setpos(part['start'])
    data = np.frombuffer(wav.readframes(part['end'] - part['start']), dtype='<i2').astype(np.float32) / 32768
    if len(data) != part['end'] - part['start']:
        raise ValueError('Short audio read')
    return data


def repetition(text):
    stripped = re.sub(r'\s+', '', text)
    return bool(re.search(r'(.{4,40})\1{5,}', stripped))


def deduplicate(previous, current, overlap):
    if not overlap:
        return current
    # Only exact, substantial suffix/prefix matches within the 0.6 second overlap.
    # Ambiguous short repeats remain, preserving deliberate spoken repetition.
    for n in range(min(16, len(previous), len(current)), 5, -1):
        if previous[-n:] == current[:n]:
            return current[n:].lstrip()
    return current


def timestamp(seconds):
    seconds = int(seconds)
    return '%02d:%02d:%02d' % (seconds // 3600, seconds % 3600 // 60, seconds % 60)


class QwenBackend:
    def __init__(self, job):
        from huggingface_hub import snapshot_download
        import mlx.core as mx
        if not mx.metal.is_available():
            raise RuntimeError('Metal GPU is unavailable in this process; use a local macOS Terminal with GPU access.')
        # Pin immutable revision and download only runtime model/tokenizer assets.
        path = snapshot_download(repo_id=job['model_id'], revision=job['revision'],
            local_dir=str(Path(job['runtime']) / 'models' / job['model']),
            allow_patterns=['*.json', '*.safetensors', 'merges.txt', 'vocab.json'], token=False)
        inference_offline()
        from mlx_qwen3_asr import Session
        self.session = Session(model=path)
        self.language = None if job['language'] == 'auto' else 'Cantonese'
        self.context = job['glossary']
        self.mx = mx
        if hasattr(mx, 'set_cache_limit'):
            mx.set_cache_limit(512 * 1024 * 1024)

    def transcribe(self, audio, limit=768):
        result = self.session.transcribe(audio, language=self.language, context=self.context,
                                         max_new_tokens=limit, return_chunks=True)
        if getattr(result, 'truncated', False) or any(c.get('truncated') for c in (result.chunks or [])):
            raise ValueError('Decoder reached token limit; refusing a truncated transcript')
        if repetition(result.text):
            raise ValueError('Suspected decoder repetition loop')
        return result.text.strip()


class WhisperBackend:
    def __init__(self, job):
        from huggingface_hub import snapshot_download
        from faster_whisper import WhisperModel
        path = Path(job['runtime']) / 'models' / job['model']
        ready = path / '.verified-model.json'
        valid = False
        if ready.exists():
            manifest = json.loads(ready.read_text())
            valid = manifest.get('revision') == job['revision'] and all(
                (path / name).is_file() and sha256(path / name) == digest
                for name, digest in manifest.get('files', {}).items()) and len(manifest.get('files', {})) == 5
        if not valid:
            snapshot_download(repo_id=job['model_id'], revision=job['revision'],
                local_dir=str(path), allow_patterns=['*.json', 'model.bin'], token=False)
        if sha256(path / 'model.bin') != '69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1':
            raise ValueError('Whisper model checksum mismatch')
        inference_offline()
        self.session = WhisperModel(str(path), device='cpu', compute_type='int8',
                                    cpu_threads=8, local_files_only=True)
        self.language = None if job['language'] == 'auto' else 'yue'
        self.context = job['glossary'] or None
        if self.context and len(self.session.hf_tokenizer.encode(self.context).ids) > 200:
            raise ValueError('Whisper glossary exceeds 200 tokens; shorten the vocabulary list or use Qwen context.')

    def transcribe(self, audio, limit=768):
        # The Whisper decoder has a fixed 448-token context, including prompt tokens.
        segments, info = self.session.transcribe(audio, language=self.language, task='transcribe',
            beam_size=3, temperature=0.0, condition_on_previous_text=False,
            initial_prompt=self.context, vad_filter=False, word_timestamps=False,
            no_speech_threshold=0.6, compression_ratio_threshold=2.4)
        parts = list(segments)
        if any(len(s.tokens) >= 440 for s in parts):
            raise ValueError('Whisper decoder output approached token limit')
        text = ''.join(s.text for s in parts).strip()
        if repetition(text):
            raise ValueError('Suspected Whisper repetition loop')
        return text

    def has_speech(self, audio):
        from faster_whisper.vad import get_speech_timestamps, VadOptions
        # Low threshold errs toward retaining quiet speech. Non-speech is marked explicitly.
        return bool(get_speech_timestamps(audio, VadOptions(threshold=0.25, min_speech_duration_ms=100)))


def recognize(backend, audio):
    """Retry an uncertain chunk as smaller pieces; never silently discard it."""
    import numpy as np
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if peak < 0.001 and rms < 0.0001:
        return '[靜音]', 'silence'
    if hasattr(backend, 'has_speech') and not backend.has_speech(audio):
        return '[未偵測到語音]', 'non-speech'
    errors = []
    for attempt in range(2):
        try:
            text = backend.transcribe(audio, 768 if attempt == 0 else 1024)
            if not text:
                raise ValueError('Empty recognition for non-silent audio')
            return text, 'recognized'
        except (ValueError, RuntimeError) as exc:
            errors.append(str(exc))
    # A long loop/empty result is retried on half-length subchunks with no missing samples.
    if len(audio) > 8 * SAMPLE_RATE:
        mid = len(audio) // 2
        left, right = backend.transcribe(audio[:mid], 768), backend.transcribe(audio[mid:], 768)
        if left and right and not repetition(left + right):
            return left + ' ' + right, 'split-retry'
    raise RuntimeError('Unresolved audible segment; checkpoint retained: ' + '; '.join(errors))


def render(state, job, converter):
    parts, previous = [], ''
    for i, entry in enumerate(state['segments']):
        part = state['plan'][i]
        text = converter(entry['text'])
        text = deduplicate(previous, text, i > 0 and state['plan'][i - 1]['overlap_next'])
        previous = converter(entry['text'])
        if job['timestamps']:
            text = '[' + timestamp(job['start'] + part['start'] / SAMPLE_RATE) + '] ' + text
        parts.append(text)
    return '\n\n'.join(parts).strip() + '\n'


def validate_segments(state):
    validate_plan(state['plan'], state['frames'])
    for i, segment in enumerate(state['segments']):
        if i >= len(state['plan']) or segment['index'] != i or not segment['text'].strip():
            raise ValueError('Invalid checkpoint segment')
        if segment['text_sha256'] != hashlib.sha256(segment['text'].encode()).hexdigest():
            raise ValueError('Corrupt checkpoint text')


def process_file(item, job, ffmpeg, backend_factory, converter, progress):
    root = Path(job['runtime'])
    source, output = Path(item['source']), Path(item['output'])
    key, cfg = checkpoint_key(item, job)
    checkpoint = root / 'checkpoints' / (key + '.json')
    stream, stream_id = item.get('stream'), item.get('stream_id')
    identity = fingerprint(source, stream_id)
    state = None
    if checkpoint.exists() and job['resume']:
        state = json.loads(checkpoint.read_text())
        if state['config'] != cfg or state['source'] != identity:
            raise ValueError('Source/config changed; refusing stale checkpoint for ' + source.name)
        validate_segments(state)
    if output.exists() and not job['overwrite']:
        # Resume only skips a previously finalized output with its saved hash.
        if state and len(state['segments']) == len(state['plan']):
            digest = state.get('output_sha256')
            if not digest:  # recover a crash immediately after atomic publication
                digest = hashlib.sha256(render(state, job, converter).encode()).hexdigest()
            if sha256(output) == digest:
                state['output_sha256'] = digest
                state['complete'] = True
                atomic_json(checkpoint, state)
                progress('already complete', output=str(output))
                return
        raise ValueError('Existing output has no matching complete checkpoint: ' + str(output))
    audio = root / 'tmp' / (key + '.wav')
    # Extraction is deterministic and cheap; regenerate unless hash was validated.
    if not (state and audio.exists() and state.get('audio_sha256') == sha256(audio)):
        progress('extracting audio')
        extract(ffmpeg, source, audio, job, stream)
    plan, frames = plan_chunks(audio, job['chunk_seconds'])
    if state:
        if plan != state['plan'] or frames != state['frames']:
            raise ValueError('Audio/chunk plan changed; refusing stale checkpoint')
    else:
        state = dict(config=cfg, source=identity, plan=plan, frames=frames,
                     audio_sha256=sha256(audio), segments=[], complete=False)
        atomic_json(checkpoint, state)
    backend = None
    with wave.open(str(audio), 'rb') as wav:
        for i in range(len(state['segments']), len(plan)):
            if backend is None:
                backend = backend_factory()
            progress('transcribing', segment=i + 1, segments=len(plan),
                     audio_time=timestamp(job['start'] + plan[i]['start'] / SAMPLE_RATE))
            text, kind = recognize(backend, read_chunk(wav, plan[i]))
            state['segments'].append(dict(index=i, text=text, kind=kind,
                text_sha256=hashlib.sha256(text.encode()).hexdigest()))
            atomic_json(checkpoint, state)
    validate_segments(state)
    if len(state['segments']) != len(plan):
        raise ValueError('Incomplete segment coverage')
    if all(s['kind'] in ('silence', 'non-speech') for s in state['segments']):
        raise ValueError('No speech recognized in recording; review audio before finalizing')
    if fingerprint(source, stream_id) != identity:
        raise ValueError('Input changed during transcription; output was not published')
    text = render(state, job, converter)
    if not text.strip() or '\x00' in text:
        raise ValueError('Invalid final transcript')
    no_symlinks(output.parent).mkdir(parents=True, exist_ok=True)
    temp = root / 'tmp' / (key + '.txt')
    with open(temp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    state['output_sha256'] = sha256(temp)
    # Save expected output hash before publish for crash recovery.
    atomic_json(checkpoint, state)
    publish(temp, output, job['overwrite'])
    state['complete'] = True
    atomic_json(checkpoint, state)
    audio.unlink(missing_ok=True)
    progress('complete', output=str(output), characters=len(text))


def run(job, backend_factory=None, ffmpeg=None, converter=None):
    if ffmpeg is None:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if converter is None:
        from opencc import OpenCC
        converter = OpenCC('s2hk').convert
    session = []
    def factory():
        if not session:
            constructor = WhisperBackend if job['model'] == 'whisper-large-v3' else QwenBackend
            session.append(constructor(job) if backend_factory is None else backend_factory())
        return session[0]
    started = time.monotonic()
    failures, outputs = [], []
    status = Path(job['runtime']) / 'checkpoints/status.json'
    for number, item in enumerate(job['items'], 1):
        def progress(event, **details):
            data = dict(event=event, file=number, files=len(job['items']), source=item['source'],
                        model=job['model'], elapsed_seconds=round(time.monotonic() - started, 1),
                        outputs=outputs.copy(), failures=failures.copy(), **details)
            atomic_json(status, data)
            detail = ' %s/%s @ %s' % (details['segment'], details['segments'], details['audio_time']) if 'segment' in details else ''
            print('[%d/%d] %s%s (%.0fs)' % (number, len(job['items']), event, detail, data['elapsed_seconds']), flush=True)
        progress('starting')
        try:
            process_file(item, job, ffmpeg, factory, converter, progress)
            outputs.append(item['output'])
        except (KeyboardInterrupt, SystemExit):
            progress('interrupted')
            raise
        except Exception as exc:
            failures.append(dict(source=item['source'], error=str(exc)))
            progress('failed')
            print('ERROR: ' + str(exc), file=sys.stderr, flush=True)
            # GPU initialization errors will affect every file; stop promptly.
            if not session:
                break
    atomic_json(status, dict(event='failed' if failures else 'complete', outputs=outputs,
        failures=failures, model=job['model'], elapsed_seconds=round(time.monotonic() - started, 1)))
    return 1 if failures else 0


def main():
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    job = json.loads(Path(sys.argv[1]).read_text())
    try:
        return run(job)
    except KeyboardInterrupt:
        print('Interrupted. Finished segments are checkpointed.', flush=True)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
