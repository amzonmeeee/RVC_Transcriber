"""HKUST Canvas/RVC integration (no network or Chrome). All course data below is fictional."""
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.parse

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from lecture_transcriber import hkust, worker

MODULE_PAGE = '''<p>RVC Recordings:</p>
<a title="COMP1000-L1-2026-09-01-09-00" href="https://canvas.ust.hk/courses/12345/pages/comp1000-l1-2026-09-01-09-00"
 data-api-endpoint="https://canvas.ust.hk/api/v1/courses/12345/pages/comp1000-l1-2026-09-01-09-00">Lecture 1</a>
<a href="https://canvas.ust.hk/courses/12345/pages/lecture-notes-week-1">Notes</a>
<a href="https://canvas.ust.hk/courses/99999/pages/comp1000-l1-2026-09-03-09-00">other course</a>'''
RVC_PAGE = '<iframe src="https://rvcmedia.ust.hk/media/?path=26FA_COMP1000-L1_260901_AbCdEf1234" width="1280"></iframe>'
PLAYER = """function JwplayerSetup() {
            var streamingServer = 'stream01.ust.hk';
            var streamingUrl = 'rvcsecured/mp4:26FA_COMP1000-L1_260901_AbCdEf1234.mp4/playlist.m3u8?rvctokenendtime=1&rvctokenhash=Zz=';"""


class ParsingTests(unittest.TestCase):
    def test_link_kinds(self):
        cases = {
            'https://canvas.ust.hk/courses/12345': ('course', '12345', None),
            'canvas.ust.hk/courses/12345/modules': ('course', '12345', None),
            'https://canvas.ust.hk/courses/12345/modules#module_5': ('module', '12345', '5'),
            'https://canvas.ust.hk/courses/12345/modules/123': ('module', '12345', '123'),
            'https://canvas.ust.hk/courses/12345/modules/items/456': ('module_item', '12345', '456'),
            'https://canvas.ust.hk/courses/12345/pages/comp1000-l1-2026-09-01-09-00?module_item_id=9':
                ('page', '12345', 'comp1000-l1-2026-09-01-09-00'),
            'https://rvcmedia.ust.hk/media/?path=26FA_A-L1_260901_x': ('media', None, '26FA_A-L1_260901_x'),
            'https://rvcmedia.ust.hk/Media/Play?path=26FA_A-L1_260901_x': ('media', None, '26FA_A-L1_260901_x'),
        }
        for link, expected in cases.items():
            with self.subTest(link=link):
                self.assertEqual(hkust.parse_link(link), expected)
        for bad in ('https://example.com/courses/1', 'https://canvas.ust.hk/profile'):
            with self.subTest(link=bad), self.assertRaises(ValueError):
                hkust.parse_link(bad)

    def test_page_patterns(self):
        self.assertEqual(hkust.media_paths(RVC_PAGE + RVC_PAGE), ['26FA_COMP1000-L1_260901_AbCdEf1234'])
        self.assertEqual(hkust.rvc_page_slugs(MODULE_PAGE, 12345), ['comp1000-l1-2026-09-01-09-00'])
        for title in ('COMP1000-L1-2026-09-01-09-00', 'MATH2000-L1-L3-2026-02-03-09-00',
                      'LANG1000-T02-2026-01-01-10-30'):
            self.assertTrue(hkust.RVC_TITLE.match(title), title)
        self.assertFalse(hkust.RVC_TITLE.match('lecture-notes-week-1'))

    def test_player_parsing_and_host_check(self):
        self.assertEqual(hkust.parse_player(PLAYER), 'https://stream01.ust.hk/rvcsecured/mp4:'
                         '26FA_COMP1000-L1_260901_AbCdEf1234.mp4/playlist.m3u8?rvctokenendtime=1&rvctokenhash=Zz=')
        self.assertIsNone(hkust.parse_player('<button>Sign in is required to view this video</button>'))
        with self.assertRaises(ValueError):
            hkust.parse_player(PLAYER.replace('stream01.ust.hk', 'evil.example.com'))

    def test_names_selection_and_order(self):
        a = hkust.Recording('COMP1000-L1-2026-09-01-09-00', '26FA_COMP1000-L1_260901_aaa')
        b = hkust.Recording('Lecture: 1/9', '26FA_COMP1000-L1_260901_bbb')
        c = hkust.Recording('', '26FA_COMP1000-L1_260901_ccc')
        hkust.unique_names([a, b, c])
        self.assertEqual(a.filename, 'COMP1000-L1-2026-09-01-09-00')
        self.assertEqual(b.filename, '26FA_COMP1000-L1_260901')
        self.assertEqual(c.filename, '26FA_COMP1000-L1_260901_ccc')
        self.assertEqual(hkust.select([a, b, c], ['aaa|ccc']), [a, c])
        self.assertEqual(hkust.select([a, b, c], latest=1), [c])
        self.assertEqual(hkust.safe_name('a/b:c?'), 'a-b-c')

    def test_find_recordings_follows_module_page_links(self):
        pages = {
            'lecture-notes-week-1': dict(title='Notes', url='lecture-notes-week-1', body=MODULE_PAGE),
            'comp1000-l1-2026-09-01-09-00': dict(title='COMP1000-L1-2026-09-01-09-00',
                                                 url='comp1000-l1-2026-09-01-09-00', body=RVC_PAGE),
        }

        class FakeCanvas:
            def get(self, path, missing_ok=False):
                if path == '/api/v1/courses/12345':
                    return dict(course_code='COMP1000 (L1)')
                return pages.get(urllib.parse.unquote(path.rsplit('/', 1)[-1]))
        info, found = hkust.find_recordings(FakeCanvas(), 'https://canvas.ust.hk/courses/12345/pages/lecture-notes-week-1')
        self.assertEqual(info['course_code'], 'COMP1000 (L1)')
        self.assertEqual([(r.title, r.media_path) for r in found],
                         [('COMP1000-L1-2026-09-01-09-00', '26FA_COMP1000-L1_260901_AbCdEf1234')])


class StreamExtractionTests(unittest.TestCase):
    def run_extract(self, preview):
        job = dict(preview=preview, start=600, seconds=30)
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            raise RuntimeError('stop after building the command')
        with mock.patch.object(worker.subprocess, 'run', fake_run), self.assertRaises(RuntimeError):
            worker.extract('ffmpeg', Path('rvc:x'), Path('/nonexistent/a.wav'), job, 'https://h.ust.hk/p.m3u8')
        return calls[0]

    def test_stream_input_and_preview_seek(self):
        full = self.run_extract(False)
        self.assertEqual(full[full.index('-i') + 1], 'https://h.ust.hk/p.m3u8')
        self.assertNotIn('-ss', full)
        self.assertIn('-vn', full)  # audio only; the video track is discarded
        preview = self.run_extract(True)
        # Seek before -i, so a preview fetches only the requested part of the stream.
        self.assertLess(preview.index('-ss'), preview.index('-i'))
        self.assertGreater(preview.index('-t'), preview.index('-i'))

    def test_stream_identity_ignores_token(self):
        self.assertEqual(worker.fingerprint(Path('rvc:x'), 'MEDIA_ID'), dict(stream='MEDIA_ID'))
        job = dict(model='m', revision='r', language='Cantonese', glossary='', timestamps=True, chunk_seconds=28,
                   preview=False, start=0, seconds=None)
        one = dict(source='rvc:MEDIA_ID', output='/o/a.txt', stream='https://h/p.m3u8?token=1', stream_id='MEDIA_ID')
        two = dict(one, stream='https://h/p.m3u8?token=2')
        self.assertEqual(worker.checkpoint_key(one, job)[0], worker.checkpoint_key(two, job)[0])


if __name__ == '__main__':
    unittest.main()
