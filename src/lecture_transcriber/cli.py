import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

from .bootstrap import MODELS, environment, ensure_environment, supported
from .safety import Runtime, atomic_json, no_symlinks, sha256, validate_paths


def parser():
    p = argparse.ArgumentParser(description='Local Cantonese/English MP4 transcription; disposable runtime.')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Inspect without downloading')
    sub.add_parser('status', help='Inspect retained job state without downloading')
    c = sub.add_parser('cleanup', help='Purge only the verified runtime')
    c.add_argument('--purge', action='store_true')
    c.add_argument('--dry-run', action='store_true')
    c.add_argument('--yes', action='store_true')
    for name in ('preview', 'transcribe'):
        s = sub.add_parser(name)
        s.add_argument('--input', action='append', required=True, help='Repeat for multiple folders')
        s.add_argument('--output', required=True)
        s.add_argument('--model', choices=['auto', *MODELS], default='auto')
        s.add_argument('--language', choices=['auto', 'Cantonese'], default='Cantonese')
        s.add_argument('--format', choices=['txt'], default='txt')
        s.add_argument('--timestamps', action='store_true', help='Approximate chunk times')
        s.add_argument('--glossary', help='UTF-8 domain context, at most 8000 characters')
        s.add_argument('--overwrite', action='store_true')
        s.add_argument('--resume', action='store_true')
        s.add_argument('--recursive', action='store_true')
        s.add_argument('--dry-run', action='store_true')
        s.add_argument('--keep-runtime', action='store_true')
        s.add_argument('--yes', action='store_true')
        s.add_argument('--chunk-seconds', type=int, default=28, choices=range(10, 30), metavar='10..29')
        if name == 'preview':
            s.add_argument('--start', type=float, default=600)
            s.add_argument('--seconds', type=float, default=240)
    return p


def discover(inputs, recursive=False):
    files = []
    seen = set()
    names = {}
    for directory in inputs:
        for source in sorted(directory.rglob('*') if recursive else directory.iterdir()):
            if source.suffix.lower() != '.mp4':
                continue
            no_symlinks(source)
            if not source.is_file():
                continue
            source = source.resolve()
            if source in seen:
                continue
            seen.add(source)
            # Case-insensitive checks avoid collisions on common macOS filesystems.
            name = source.stem + '.txt'
            key = name.casefold()
            if key in names:
                print('Checking duplicate filename: ' + source.name, flush=True)
                previous = names[key]
                if source.stat().st_size == previous.stat().st_size and sha256(source) == sha256(previous):
                    print('Identical recording: reuse one transcript for both copies.', flush=True)
                    continue
                raise ValueError('Distinct videos have colliding output names: ' + name)
            names[key] = source
            files.append(source)
    if not files:
        raise ValueError('No MP4 files found')
    return files


def ask(message, yes):
    if yes:
        return
    if not sys.stdin.isatty() or input(message + ' [y/N] ').strip().lower() != 'y':
        raise ValueError('Not confirmed. Use --yes for unattended execution.')


def supervise(argv, env, fd, log):
    """Keep the ownership lock in descendants, and wait before cleanup."""
    process = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True, pass_fds=(fd,))
    old = {}
    interrupted = []
    def stop(signum, frame):
        interrupted.append(signum)
        try:
            os.killpg(process.pid, signal.SIGINT if signum == signal.SIGINT else signal.SIGTERM)
        except ProcessLookupError:
            pass
    for signum in (signal.SIGINT, signal.SIGTERM):
        old[signum] = signal.signal(signum, stop)
    try:
        with open(log, 'a', encoding='utf-8') as stream:
            for line in process.stdout:
                print(line, end='', flush=True)
                stream.write(line)
                stream.flush()
        code = process.wait()
    finally:
        if process.poll() is None:
            stop(signal.SIGTERM, None)
            process.wait()
        process.stdout.close()
        for signum, handler in old.items():
            signal.signal(signum, handler)
    if code or interrupted:
        raise RuntimeError('Child exited with code %s. Runtime retained; rerun with --resume.' % code)


def main(argv=None):
    args = parser().parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    runtime = Runtime(repo)
    try:
        if args.command == 'doctor':
            print('Host:', platform.system(), platform.release(), platform.machine())
            print('Backend:', 'MLX Qwen3-ASR (Metal GPU), Whisper CPU fallback' if supported() else 'unsupported; requires Apple Silicon macOS')
            print('Free disk: %.1f GiB' % (shutil.disk_usage(repo).free / 2**30))
            try:
                memory = subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.memsize'], stderr=subprocess.DEVNULL, text=True)
                print('Memory: %.1f GiB' % (int(memory) / 2**30))
            except (OSError, subprocess.CalledProcessError):
                print('Memory: unavailable in this execution environment')
            print('Runtime:', runtime.path, 'present' if runtime.path.exists() else 'absent')
            print('Managed Python:', (runtime.path / '.venv/bin/python').exists())
            if (runtime.path / '.venv/bin/python').exists():
                probe = subprocess.run([str(runtime.path / '.venv/bin/python'), '-B', '-c',
                    'import mlx.core as mx; print("Metal available:", mx.metal.is_available())'],
                    env=environment(runtime), capture_output=True, text=True)
                print(probe.stdout.strip() if probe.returncode == 0 else 'Metal probe: ' + probe.stderr.strip().splitlines()[-1])
            print('Model snapshots:', [p.name for p in (runtime.path / 'models').glob('*')] if runtime.path.exists() else [])
            print('First use: HTTPS downloads ~4-5 GB; allow 12 GB disk, 8+ GB RAM. No model downloaded by doctor.')
            return 0
        if args.command == 'status':
            print('Runtime: %.2f GiB' % (runtime.footprint() / 2**30))
            status = runtime.path / 'checkpoints/status.json'
            if status.exists():
                print(status.read_text())
            else:
                print('No retained job state. Successful default runs purge their state.')
            print('Worker active:', runtime.busy())
            print('Cleanup available:', runtime.path.exists() and not runtime.busy())
            return 0
        if args.command == 'cleanup':
            if not runtime.path.exists() and not runtime.path.is_symlink():
                print('Runtime already absent.')
                return 0
            runtime.verify()
            with runtime.lock() as fd:
                print('Owned runtime only:', runtime.path, '(%.2f GiB)' % (runtime.footprint() / 2**30))
                if args.dry_run:
                    for p in sorted(runtime.path.iterdir()):
                        print('Would remove:', p)
                    return 0
                if not args.purge:
                    raise ValueError('Use cleanup --purge (or --dry-run)')
                ask('Delete all models, dependencies and resumable checkpoints?', args.yes)
                runtime.purge_locked(fd)
            print('Runtime removed. Inputs and final transcripts preserved.')
            return 0
        if not supported():
            raise ValueError('This release requires Apple Silicon macOS. It does not install anything on other platforms.')
        inputs, output = validate_paths(repo, args.input, args.output)
        files = discover(inputs, args.recursive)
        if args.command == 'preview':
            if args.start < 0 or not 0 < args.seconds <= 300:
                raise ValueError('Preview start must be >= 0 and duration must be 1..300 seconds')
            files = files[:1]
        model = 'qwen3-asr-1.7b' if args.model == 'auto' else args.model
        glossary = ''
        if args.glossary:
            glossary = no_symlinks(args.glossary).read_text(encoding='utf-8')
            if len(glossary) > 8000:
                raise ValueError('Glossary exceeds 8000 characters')
        items = []
        for file in files:
            dest = output / (file.stem + ('.preview' if args.command == 'preview' else '') + '.txt')
            no_symlinks(dest)
            if dest.exists() and not (args.overwrite or args.resume):
                raise ValueError('Transcript exists; use --resume with retained state or --overwrite: ' + str(dest))
            items.append(dict(source=str(file), output=str(dest)))
        print('%d recording(s); model=%s; language=%s; output=%s' % (len(items), model, args.language, output), flush=True)
        print('First use downloads portable uv, managed Python, hash-locked packages/FFmpeg and pinned ASR weights over HTTPS.', flush=True)
        print('Budget: ~4-5 GB downloads / up to 12 GB runtime disk. Audio/text never uploaded. Success purges runtime unless --keep-runtime.', flush=True)
        if args.dry_run:
            for item in items:
                print(item['source'], '->', item['output'])
            return 0
        ask('Proceed with local processing and missing downloads?', args.yes)
        if shutil.disk_usage(repo).free < 6 * 2**30:
            raise ValueError('At least 6 GiB free disk required; 12 GiB recommended')
        runtime.create()
        with runtime.lock() as fd:
            env = environment(runtime)
            log = runtime.path / 'logs/run.log'
            runner = lambda cmd, e: supervise(cmd, e, fd, log)
            python = ensure_environment(runtime, env, runner)
            if args.model == 'auto':
                probe = subprocess.run([str(python), '-B', '-c',
                    'import mlx.core as mx; raise SystemExit(0 if mx.metal.is_available() else 1)'],
                    env=env, capture_output=True, text=True)
                if probe.returncode:
                    model = 'whisper-large-v3'
                    print('Metal unavailable in this process: auto selected local Whisper large-v3 CPU int8. This may take hours.', flush=True)
            job = dict(items=items, model=model, model_id=MODELS[model][0], revision=MODELS[model][1],
                language=args.language, glossary=glossary, timestamps=args.timestamps,
                chunk_seconds=args.chunk_seconds, resume=args.resume, overwrite=args.overwrite,
                preview=args.command == 'preview', start=getattr(args, 'start', 0),
                seconds=getattr(args, 'seconds', None), runtime=str(runtime.path))
            job_path = runtime.path / 'job.json'
            atomic_json(job_path, job)
            runner([str(python), '-B', '-m', 'lecture_transcriber.worker', str(job_path)], env)
            # At this point every worker has exited and no runtime executable is in use.
            pending = [p for p in (runtime.path / 'checkpoints').glob('*.json')
                       if p.name != 'status.json' and not json.loads(p.read_text()).get('complete')]
            if pending:
                print('Current batch complete. Retaining runtime because other unfinished checkpoints exist; use cleanup --purge to discard them.', flush=True)
            elif not args.keep_runtime:
                runtime.purge_locked(fd)
                print('Success: all final transcripts validated; runtime removed.', flush=True)
            else:
                print('Success: runtime retained by --keep-runtime.', flush=True)
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print('ERROR:', error, file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('Interrupted; runtime/checkpoints retained.', file=sys.stderr)
        return 130
