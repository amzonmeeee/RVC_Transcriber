"""`run.sh hkust <canvas link>`: find RVC recordings, stream their audio and transcribe.

No video file is saved: the worker's FFmpeg reads each HLS stream and keeps 16 kHz mono audio inside the
disposable runtime, exactly like audio extracted from a local MP4.
"""
from pathlib import Path

from . import hkust
from .bootstrap import supported
from .safety import validate_paths


def run_hkust(args, repo, runtime):
    from .cli import run_batch
    if not supported():
        raise ValueError('HKUST integration needs Apple Silicon macOS with Google Chrome.')
    if not args.list and not args.output:
        raise ValueError('--output is required (or use --list)')
    if args.preview and (args.start < 0 or not 0 < args.seconds <= 300):
        raise ValueError('Preview start must be >= 0 and duration must be 1..300 seconds')

    tabs = []
    try:
        canvas_tab = hkust.ChromeTab(hkust.CANVAS, hkust.CANVAS + '/')
        tabs.append(canvas_tab)
        print('Scanning Canvas for RVC recordings...', flush=True)
        info, recordings = hkust.find_recordings(hkust.Canvas(canvas_tab), args.link)
        recordings = hkust.unique_names(hkust.select(recordings, args.select, args.latest))
        if not recordings:
            raise ValueError('No RVC recordings found for this link (or none match --select). Try the course '
                             'home link, or the module page that lists the RVC recordings.')
        course = (info or {}).get('course_code') or 'RVC'
        print('%s: %d recording(s)' % (course, len(recordings)), flush=True)
        for r in recordings:
            print('  %s  [%s]' % (r.filename, r.media_path), flush=True)
        if args.list:
            return 0

        _, output = validate_paths(repo, [], Path(args.output).expanduser())  # same rules as transcribe
        if args.preview:
            recordings = recordings[:1]
        todo = []
        for r in recordings:
            name = r.filename + ('.preview' if args.preview else '') + '.txt'
            if (output / name).exists() and not (args.overwrite or args.resume):
                print('Transcript exists, skipping:', name, flush=True)
            else:
                todo.append(r)
        if not todo:
            print('Nothing to do: every selected recording is already transcribed.')
            return 0
        if args.dry_run:
            sources = [dict(name=r.filename, source='rvc:' + r.media_path, stream_id=r.media_path) for r in todo]
            return run_batch(args, repo, runtime, sources, output, preview=args.preview)

        # Stream tokens last a few hours; fetch them right before transcription starts.
        rvc_tab = hkust.ChromeTab(hkust.RVCMEDIA, hkust.RVCMEDIA + '/Media/Play?path=' + todo[0].media_path)
        tabs.append(rvc_tab)
        sources = []
        for r in todo:
            sources.append(dict(name=r.filename, source='rvc:' + r.media_path, stream_id=r.media_path,
                                stream=hkust.resolve_stream(rvc_tab, r)))
        print('Resolved %d stream(s); audio is streamed directly, no video is saved.' % len(sources), flush=True)
    finally:
        for tab in tabs:
            tab.close()
    return run_batch(args, repo, runtime, sources, output, preview=args.preview)
