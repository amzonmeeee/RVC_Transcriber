"""Interface used by programs that embed the transcriber (install, streams, JSON progress)."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from lecture_transcriber import cli, worker


class StreamsFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name).resolve() / 'streams.json'

    def tearDown(self):
        self.temp.cleanup()

    def load(self, data):
        self.path.write_text(json.dumps(data), encoding='utf-8')
        return cli.load_streams(self.path)

    def test_valid_streams(self):
        result = self.load([dict(name='COMP1000-L1-2026-09-01-09-00', stream='https://h.ust.hk/p.m3u8?t=1',
                                 stream_id='26FA_COMP1000-L1_260901_x')])
        self.assertEqual(result, [dict(name='COMP1000-L1-2026-09-01-09-00', source='stream:26FA_COMP1000-L1_260901_x',
                                       stream='https://h.ust.hk/p.m3u8?t=1', stream_id='26FA_COMP1000-L1_260901_x')])

    def test_rejected_streams(self):
        good = dict(name='a', stream='https://h/p.m3u8', stream_id='x')
        bad = [[], {}, [dict(good, name='../a')], [dict(good, name='.hidden')], [dict(good, name='a/b')],
               [dict(good, stream='http://h/p.m3u8')], [dict(good, stream='file:///etc/passwd')],
               [dict(good, stream_id='')], [good, dict(good, name='A')]]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.load(data)


class ProgressTests(unittest.TestCase):
    def test_emit_only_when_enabled(self):
        out = io.StringIO()
        with redirect_stdout(out):
            worker.emit(dict(json_progress=False), 'x')
            worker.emit(dict(json_progress=True), 'transcribing', segment=2, segments=9)
        line = out.getvalue().strip()
        self.assertTrue(line.startswith('@@progress '))
        self.assertEqual(json.loads(line.split(' ', 1)[1]), dict(event='transcribing', segment=2, segments=9))

    def test_prefetch_downloads_model_only(self):
        job = dict(prefetch=True, json_progress=True, model='qwen3-asr-0.6b', model_id='Q', revision='r', runtime='/r')
        with mock.patch.object(worker, 'fetch_qwen') as qwen, mock.patch.object(worker, 'fetch_whisper') as whisper, \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(worker.prefetch(job), 0)
        qwen.assert_called_once_with(job)
        whisper.assert_not_called()
        self.assertIn('"installed"', out.getvalue())

    def test_new_commands_parse(self):
        p = cli.parser()
        self.assertTrue(p.parse_args(['install', '--model', 'qwen3-asr-0.6b', '--yes', '--json-progress']).json_progress)
        args = p.parse_args(['streams', '--streams', 's.json', '--output', 'o', '--json-progress', '--keep-runtime'])
        self.assertEqual((args.command, args.keep_runtime, args.json_progress), ('streams', True, True))


if __name__ == '__main__':
    unittest.main()
