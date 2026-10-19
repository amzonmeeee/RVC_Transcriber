import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from lecture_transcriber.safety import Runtime, atomic_json, publish, sha256, validate_paths
from lecture_transcriber.cli import discover, supervise, main
from lecture_transcriber.bootstrap import environment, supported
from lecture_transcriber.worker import checkpoint_key, deduplicate, process_file, run, validate_plan


class Fixture(unittest.TestCase):
    def setUp(self):
        Runtime(REPO).create()
        parent = REPO / '.runtime.nosync' / 'test-artifacts'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.runtime = Runtime(self.repo)
        self.runtime.create()
        self.inputs, self.output = self.base / 'inputs', self.base / 'output'
        self.inputs.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def job(self, files):
        return dict(items=[dict(source=str(p), output=str(self.output/(p.stem+'.txt'))) for p in files],
            model='qwen3-asr-1.7b', model_id='Qwen/Qwen3-ASR-1.7B', revision='test',
            runtime=str(self.runtime.path), glossary='', language='Cantonese', timestamps=True,
            chunk_seconds=10, preview=False, start=0, seconds=None, resume=False, overwrite=False)


class SafetyTests(Fixture):
    def test_unsafe_input_output_paths(self):
        for p in (Path('/'), Path.home(), self.repo, self.repo/'.runtime.nosync', self.inputs):
            with self.subTest(path=p), self.assertRaises(ValueError):
                validate_paths(self.repo, [self.inputs], p)
        self.assertEqual(validate_paths(self.repo, [self.inputs], self.output)[1], self.output)

    def test_output_symlink_escape(self):
        link = self.base/'link'
        link.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises(ValueError):
            validate_paths(self.repo, [self.inputs], link/'nested')

    def test_runtime_and_marker_symlinks_refused(self):
        with self.runtime.lock() as fd:
            self.runtime.purge_locked(fd)
        self.runtime.path.symlink_to(self.inputs, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.runtime.create()
        self.runtime.path.unlink()
        self.runtime.create()
        self.runtime.marker.unlink()
        target = self.base/'marker'
        target.write_text('{}')
        self.runtime.marker.symlink_to(target)
        with self.assertRaises(ValueError):
            self.runtime.verify()

    def test_owner_mismatch_refused(self):
        data = json.loads(self.runtime.marker.read_text())
        data['runtime'] = str(self.inputs)
        atomic_json(self.runtime.marker, data)
        with self.assertRaises(ValueError):
            self.runtime.verify()

    def test_purge_cannot_be_retargeted(self):
        for target in (Path('/'), Path.home(), self.inputs, self.output, self.repo):
            hostile = Runtime(self.repo)
            hostile.path = target
            with self.subTest(target=target), self.assertRaises(ValueError):
                hostile.verify()

    def test_nested_symlink_cleanup_preserves_target(self):
        original = self.inputs/'keep.mp4'
        original.write_bytes(b'original')
        (self.runtime.path/'tmp'/'external').symlink_to(self.inputs, target_is_directory=True)
        with self.runtime.lock() as fd:
            self.runtime.purge_locked(fd)
        self.assertEqual(original.read_bytes(), b'original')
        self.assertFalse(self.runtime.path.exists())

    def test_active_lock_and_exit_before_cleanup(self):
        self.assertFalse(self.runtime.busy())
        with self.runtime.lock() as fd:
            self.assertTrue(self.runtime.busy())
            with self.assertRaises(ValueError):
                with self.runtime.lock():
                    pass
            done = self.runtime.path/'tmp'/'closed'
            cmd = [sys.executable, '-B', '-c',
                'import time,pathlib; time.sleep(.1); pathlib.Path('+repr(str(done))+').write_text("exited")']
            supervise(cmd, environment(self.runtime), fd, self.runtime.path/'logs/test.log')
            self.assertEqual(done.read_text(), 'exited')
            self.runtime.purge_locked(fd)
        self.assertFalse(self.runtime.path.exists())

    def test_child_failure_retains_runtime(self):
        with self.runtime.lock() as fd, self.assertRaises(RuntimeError):
            supervise([sys.executable, '-B', '-c', 'raise SystemExit(3)'], environment(self.runtime),
                      fd, self.runtime.path/'logs/test.log')
        self.assertTrue(self.runtime.marker.exists())

    def test_atomic_publication_does_not_clobber(self):
        self.output.mkdir()
        destination = self.output/'text.txt'
        destination.write_text('original')
        temporary = self.runtime.path/'tmp/new.txt'
        temporary.write_text('new')
        with self.assertRaises(FileExistsError):
            publish(temporary, destination)
        self.assertEqual(destination.read_text(), 'original')
        publish(temporary, destination, True)
        self.assertEqual(destination.read_text(), 'new')
        self.assertEqual(list(self.output.iterdir()), [destination])

    def test_collision_and_identical_duplicate(self):
        a = self.inputs/'廣東話 lecture.mp4'
        a.write_bytes(b'video')
        second = self.base/'second'
        second.mkdir()
        b = second/a.name
        b.write_bytes(b'video')
        self.assertEqual(len(discover([self.inputs, second])), 1)
        b.write_bytes(b'other')
        with self.assertRaises(ValueError):
            discover([self.inputs, second])

    def test_containment_environment(self):
        before = dict(os.environ)
        env = environment(self.runtime)
        self.assertEqual(dict(os.environ), before)
        for key in ('TMPDIR', 'UV_CACHE_DIR', 'UV_PYTHON_INSTALL_DIR', 'UV_PYTHON_BIN_DIR',
                    'HF_HOME', 'HF_HUB_CACHE', 'HF_XET_CACHE', 'TORCH_HOME', 'XDG_CACHE_HOME',
                    'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'PIP_CACHE_DIR', 'IMAGEIO_USERDIR'):
            self.assertTrue(Path(env[key]).is_relative_to(self.runtime.path), key)
        self.assertEqual(env['HF_HUB_DISABLE_TELEMETRY'], '1')
        self.assertEqual(env['ORT_DISABLE_TELEMETRY'], '1')
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')

    def test_chunk_coverage_and_conservative_deduplication(self):
        validate_plan([dict(start=0,end=10,overlap_next=1),dict(start=9,end=20,overlap_next=0)],20)
        with self.assertRaises(ValueError):
            validate_plan([dict(start=0,end=10,overlap_next=0),dict(start=11,end=20,overlap_next=0)],20)
        self.assertEqual(deduplicate('yes yes', 'yes again', True), 'yes again')
        self.assertEqual(deduplicate('some phraseABCDEF', 'ABCDEF next', True), 'next')
        self.assertEqual(deduplicate('some ABCDEF', 'ABCDEF next', False), 'ABCDEF next')

    def test_cli_inspection_no_bootstrap(self):
        with mock.patch('lecture_transcriber.cli.ensure_environment', side_effect=AssertionError('download')):
            self.assertEqual(main(['doctor']), 0)
            self.assertEqual(main(['status']), 0)
        with mock.patch('lecture_transcriber.cli.supported', return_value=False):
            self.assertEqual(main(['transcribe','--input',str(self.inputs),'--output',str(self.output),'--yes']), 1)


try:
    import numpy
    import imageio_ffmpeg
    HAVE_MEDIA = True
except ImportError:
    HAVE_MEDIA = False


@unittest.skipUnless(HAVE_MEDIA, 'Integration tests require the contained runtime dependencies')
class MediaTests(Fixture):
    def setUp(self):
        super().setUp()
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self.files = [self.inputs/'粵語 lecture 1.mp4', self.inputs/'English lecture 2.mp4']
        # Test tones exercise media/coverage, not speech-recognition quality.
        for f in self.files:
            subprocess.run([self.ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-f','lavfi',
                '-i','sine=frequency=440:duration=23','-c:a','aac',str(f)], check=True)

    class Backend:
        def __init__(self):
            self.calls = 0
        def transcribe(self, audio, limit):
            self.calls += 1
            return '測試粵語 academic term %d。' % self.calls

    def test_cli_auto_purge_only_after_worker_returns(self):
        finished = []
        def worker(argv, env, fd, log):
            job=json.loads(Path(argv[-1]).read_text())
            code=run(job,self.Backend,self.ffmpeg,lambda s:s)
            self.assertEqual(code,0)
            self.assertTrue(self.runtime.path.exists())
            finished.append(True)
        with mock.patch('lecture_transcriber.cli.Runtime',return_value=self.runtime), \
             mock.patch('lecture_transcriber.cli.validate_paths',return_value=([self.inputs],self.output)), \
             mock.patch('lecture_transcriber.cli.ensure_environment',return_value=Path(sys.executable)), \
             mock.patch('lecture_transcriber.cli.supervise',side_effect=worker), \
             mock.patch('lecture_transcriber.cli.supported',return_value=True):
            result=main(['transcribe','--input',str(self.inputs),'--output',str(self.output),
                         '--model','whisper-large-v3','--yes'])
        self.assertEqual(result,0)
        self.assertEqual(finished,[True])
        self.assertFalse(self.runtime.path.exists())
        self.assertEqual(len(list(self.output.iterdir())),2)

    def test_two_mp4s_success_purge_preserves_inputs_outputs(self):
        before = [sha256(p) for p in self.files]
        job = self.job(self.files)
        backend = self.Backend()
        self.assertEqual(run(job, lambda:backend, self.ffmpeg, lambda s:s), 0)
        self.assertEqual(len(list(self.output.iterdir())), 2)
        self.assertTrue(all(p.suffix=='.txt' and p.read_text().strip() for p in self.output.iterdir()))
        with self.runtime.lock() as fd:
            self.runtime.purge_locked(fd)
        self.assertEqual(before, [sha256(p) for p in self.files])
        self.assertEqual(len(list(self.output.iterdir())), 2)

    def test_interruption_resume_skips_valid_segments_and_final_files(self):
        job = self.job(self.files[:1])
        backend = self.Backend()
        def interrupt(audio, limit):
            if backend.calls >= 1:
                raise KeyboardInterrupt
            return self.Backend.transcribe(backend, audio, limit)
        backend.transcribe = interrupt
        with self.assertRaises(KeyboardInterrupt):
            run(job, lambda:backend, self.ffmpeg, lambda s:s)
        key,_ = checkpoint_key(job['items'][0],job)
        state=json.loads((self.runtime.path/'checkpoints'/(key+'.json')).read_text())
        self.assertEqual(len(state['segments']),1)
        self.assertFalse(self.output.exists())
        job['resume']=True
        resumed=self.Backend()
        self.assertEqual(run(job,lambda:resumed,self.ffmpeg,lambda s:s),0)
        self.assertEqual(resumed.calls,len(state['plan'])-1)
        calls=resumed.calls
        self.assertEqual(run(job,lambda:resumed,self.ffmpeg,lambda s:s),0)
        self.assertEqual(resumed.calls,calls)

    def test_failure_retains_already_published_transcript(self):
        job=self.job(self.files)
        self.files[1].write_bytes(b'bad mp4')
        self.assertEqual(run(job,self.Backend,self.ffmpeg,lambda s:s),1)
        self.assertTrue(Path(job['items'][0]['output']).exists())
        self.assertFalse(Path(job['items'][1]['output']).exists())
        self.assertTrue(self.runtime.marker.exists())

    def test_modified_source_and_corrupt_output_not_skipped(self):
        job=self.job(self.files[:1])
        self.assertEqual(run(job,self.Backend,self.ffmpeg,lambda s:s),0)
        job['resume']=True
        Path(job['items'][0]['output']).write_text('tampered')
        self.assertEqual(run(job,self.Backend,self.ffmpeg,lambda s:s),1)
        self.files[0].write_bytes(b'changed input')
        self.assertEqual(run(job,self.Backend,self.ffmpeg,lambda s:s),1)


if __name__ == '__main__':
    unittest.main()
