"""HKUST Canvas -> RVC recording stream (stdlib only, macOS + Google Chrome).

How HKUST RVC recordings are published on canvas.ust.hk (examples are fictional):

1. One Canvas page per lecture, titled and slugged like ``COMP1000-L1-2026-09-01-09-00``
   (course-section-date-time). Module pages usually link to these pages.
2. That page embeds ``https://rvcmedia.ust.hk/media/?path=26FA_COMP1000-L1_260901_<token>``.
3. After HKUST sign-in, ``https://rvcmedia.ust.hk/Media/Play?path=<path>`` configures JW Player with
   ``streamingServer`` + ``streamingUrl``: an HLS playlist (.m3u8) carrying a time-limited token.
4. The playlist itself needs no cookies, so the project FFmpeg reads it directly and keeps audio only.

Canvas and rvcmedia are read through the user's signed-in Google Chrome via AppleScript
("View > Developer > Allow JavaScript from Apple Events" must be on). No password or token is stored.
"""
import json
import re
import subprocess
import time
import urllib.parse

CANVAS = 'https://canvas.ust.hk'
RVCMEDIA = 'https://rvcmedia.ust.hk'
# COMP1000-L1-2026-09-01-09-00 (section may be L1, T02, LA1 ...; some courses use L1-L3).
RVC_TITLE = re.compile(r'^[A-Za-z]{4}\d{4}[A-Za-z]?(?:-[A-Za-z0-9]+)+-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}$')
MEDIA_PATH = re.compile(r'rvcmedia\.ust\.hk/(?:media/?|Media/Play)\?(?:[^"\'<>\s]*&(?:amp;)?)?path=([A-Za-z0-9_\-]+)',
                        re.IGNORECASE)
PAGE_LINK = re.compile(r'/courses/(\d+)/pages/([A-Za-z0-9_\-%.]+)')


class Recording:
    def __init__(self, title, media_path, page=None):
        self.title, self.media_path, self.page = title, media_path, page

    @property
    def date(self):
        # Media path: <term>_<COURSE-SECTION>_<YYMMDD>_<token>
        parts = self.media_path.split('_')
        return parts[-2] if len(parts) >= 4 and parts[-2].isdigit() else ''

    @property
    def name(self):
        if RVC_TITLE.match(self.title or ''):
            return safe_name(self.title)
        # Untitled embeds: drop the random token, keep term/course/date.
        parts = self.media_path.split('_')
        return safe_name('_'.join(parts[:-1]) if len(parts) >= 4 else self.media_path)

    def __repr__(self):
        return 'Recording(%r, %r)' % (self.title, self.media_path)


def safe_name(text):
    text = re.sub(r'[\x00-\x1f/\\:*?"<>|]+', '-', text).strip(' .-')
    return text[:120] or 'recording'


# ---------------------------------------------------------------- link parsing / HTML patterns

def parse_link(link):
    """Return (kind, course_id, value) for a Canvas or rvcmedia link."""
    link = link.strip()
    if '://' not in link:
        link = 'https://' + link
    url = urllib.parse.urlsplit(link)
    host = (url.hostname or '').lower()
    query = urllib.parse.parse_qs(url.query)
    if host == 'rvcmedia.ust.hk' and query.get('path'):
        return 'media', None, query['path'][0]
    if host != 'canvas.ust.hk':
        raise ValueError('Expected a canvas.ust.hk or rvcmedia.ust.hk link: ' + link)
    m = re.match(r'^/courses/(\d+)(/.*)?$', url.path)
    if not m:
        raise ValueError('Link is not inside a Canvas course: ' + link)
    course, rest = m.group(1), (m.group(2) or '').rstrip('/')
    patterns = (
        ('page', r'^/pages/([^/]+)$'),
        ('module_item', r'^/modules/items/(\d+)$'),
        ('module', r'^/modules/(\d+)$'),
    )
    for kind, pattern in patterns:
        hit = re.match(pattern, rest)
        if hit:
            return kind, course, urllib.parse.unquote(hit.group(1))
    hit = re.match(r'^module_(\d+)$', url.fragment)
    if rest == '/modules' and hit:
        return 'module', course, hit.group(1)
    return 'course', course, None


def media_paths(html):
    seen, out = set(), []
    for path in MEDIA_PATH.findall(html or ''):
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def rvc_page_slugs(html, course):
    """Linked pages in this course that look like RVC lecture pages."""
    out = []
    for c, slug in PAGE_LINK.findall(html or ''):
        slug = urllib.parse.unquote(slug)
        if c == str(course) and RVC_TITLE.match(slug) and slug not in out:
            out.append(slug)
    return out


def parse_player(html):
    """Extract the HLS URL from a /Media/Play page."""
    server = re.search(r"streamingServer\s*=\s*'([^']+)'", html or '')
    path = re.search(r"streamingUrl\s*=\s*'([^']+)'", html or '')
    if not (server and path):
        return None
    host = server.group(1).strip().lower()
    if not re.fullmatch(r'[a-z0-9.-]+\.ust\.hk', host):
        raise ValueError('Unexpected RVC streaming host: ' + host)
    return 'https://%s/%s' % (host, path.group(1).lstrip('/'))


# ---------------------------------------------------------------- Chrome bridge (osascript)

# Always a fresh tab: Chrome freezes idle background tabs, and a frozen tab never answers AppleScript.
OPEN_TAB = r'''
on run argv
  tell application "Google Chrome"
    if (count of windows) is 0 then make new window
    set w to front window
    set t to make new tab at end of tabs of w with properties {URL:(item 1 of argv)}
    return (id of w as text) & " " & (id of t as text)
  end tell
end run
'''

TAB_JS = r'''
on run argv
  set wid to (item 1 of argv) as integer
  set tid to (item 2 of argv) as integer
  tell application "Google Chrome"
    set t to (first tab of (first window whose id is wid) whose id is tid)
    if (item 3 of argv) is "url" then return URL of t
    if (item 3 of argv) is "load" then
      set URL of t to (item 4 of argv)
      return ""
    end if
    if (item 3 of argv) is "close" then
      close t
      return ""
    end if
    if loading of t then return "__LOADING__"
    return execute t javascript (item 4 of argv)
  end tell
end run
'''


def osascript(script, *args, timeout=90):
    try:
        result = subprocess.run(['/usr/bin/osascript', '-', *args], input=script, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('AppleScript call timed out (Chrome tab frozen or a Chrome dialog is open). '
                           'Close any dialog and rerun.')
    if result.returncode:
        message = result.stderr.strip()
        if 'JavaScript' in message and ('Apple' in message or 'turned off' in message):
            raise RuntimeError('Chrome blocks AppleScript JavaScript. In Chrome enable '
                               'View > Developer > Allow JavaScript from Apple Events, then rerun.')
        if '-1743' in message or 'Not authorized' in message:
            raise RuntimeError('macOS denied automation of Google Chrome. Allow it in System Settings > '
                               'Privacy & Security > Automation, then rerun.')
        raise RuntimeError('osascript failed: ' + message[-500:])
    return result.stdout.rstrip('\n')


class ChromeTab:
    """A tab we open on an HKUST origin, run same-origin requests in, and close afterwards."""

    def __init__(self, origin, start_url, wait=120):
        self.window, self.tab = osascript(OPEN_TAB, start_url).split()
        self.origin = origin
        self.wait_ready(start_url, wait)

    def _call(self, action, value=''):
        return osascript(TAB_JS, self.window, self.tab, action, value)

    def wait_ready(self, start_url, wait):
        deadline, told = time.time() + wait, False
        while True:
            url = self._call('url')
            if url.startswith(self.origin) and self._call('js', 'document.readyState') == 'complete':
                return
            if time.time() > deadline:
                raise RuntimeError('Chrome tab did not reach %s. Sign in to HKUST in that Chrome tab, then rerun.'
                                   % self.origin)
            if not told and not url.startswith(self.origin):
                print('Waiting for HKUST sign-in in Chrome (%s)...' % start_url, flush=True)
                told = True
            time.sleep(2)

    def js(self, code):
        for _ in range(60):
            out = self._call('js', code)
            if out != '__LOADING__':
                return out
            time.sleep(1)
        raise RuntimeError('Chrome tab kept loading')

    def close(self):
        try:
            self._call('close')
        except (RuntimeError, subprocess.SubprocessError):
            pass


CANVAS_GET = r'''(function(u){var out=[];var n=0;while(u&&n++<50){var x=new XMLHttpRequest();
x.open('GET',u,false);x.setRequestHeader('Accept','application/json');x.send();
if(x.status>=400||x.status==0)return JSON.stringify({status:x.status,error:x.responseText.slice(0,300)});
var d=JSON.parse(x.responseText.replace(/^while\(1\);/,''));
if(!Array.isArray(d))return JSON.stringify({status:x.status,data:d});
out=out.concat(d);var l=x.getResponseHeader('Link')||'';var m=l.match(/<([^>]+)>;\s*rel="next"/);
u=m?m[1]:null;}return JSON.stringify({status:200,data:out});})(%s)'''

PLAY_GET = r'''(function(p){var x=new XMLHttpRequest();x.open('GET','/Media/Play?path='+encodeURIComponent(p),false);
try{x.send();}catch(e){return JSON.stringify({status:0,url:'',html:''});}
return JSON.stringify({status:x.status,url:x.responseURL,html:x.responseText});})(%s)'''


class Canvas:
    def __init__(self, tab):
        self.tab = tab

    def get(self, path, missing_ok=False):
        data = json.loads(self.tab.js(CANVAS_GET % json.dumps(path)))
        if data['status'] != 200:
            if missing_ok:
                return None
            if data['status'] in (0, 401):
                raise RuntimeError('Canvas refused %s (status %s). Sign in at canvas.ust.hk in Chrome.'
                                   % (path, data['status']))
            raise RuntimeError('Canvas API %s failed: %s %s' % (path, data['status'], data.get('error', '')))
        return data['data']


# ---------------------------------------------------------------- discovery

def find_recordings(canvas, link):
    kind, course, value = parse_link(link)
    if kind == 'media':
        return None, [Recording('', value)]
    info = canvas.get('/api/v1/courses/%s' % course)
    found, seen_pages = {}, set()

    def add(title, path, page):
        if path not in found:
            found[path] = Recording(title, path, page)
        elif RVC_TITLE.match(title or '') and not RVC_TITLE.match(found[path].title or ''):
            found[path].title = title

    def scan_page(slug, follow=True):
        if slug in seen_pages:
            return
        seen_pages.add(slug)
        page = canvas.get('/api/v1/courses/%s/pages/%s' % (course, urllib.parse.quote(slug)), missing_ok=True)
        if not page:
            if RVC_TITLE.match(slug):
                print('  skipped %s: not available to you (unpublished or locked)' % slug, flush=True)
            return
        body = page.get('body') or ''
        for path in media_paths(body):
            add(page.get('title') or slug, path, page.get('url'))
        if follow:
            for linked in rvc_page_slugs(body, course):
                scan_page(linked, follow=False)

    def scan_item(item):
        if item.get('type') == 'Page' and item.get('page_url'):
            scan_page(item['page_url'])
        for path in media_paths(item.get('external_url') or ''):
            add(item.get('title') or '', path, None)

    if kind == 'page':
        scan_page(value)
    elif kind == 'module_item':
        seq = canvas.get('/api/v1/courses/%s/module_item_sequence?asset_type=ModuleItem&asset_id=%s'
                         % (course, value))
        for entry in seq.get('items', []):
            if entry.get('current'):
                scan_item(entry['current'])
    elif kind == 'module':
        for item in canvas.get('/api/v1/courses/%s/modules/%s/items?per_page=100' % (course, value)):
            scan_item(item)
    else:
        for module in canvas.get('/api/v1/courses/%s/modules?include[]=items&per_page=100' % course,
                                 missing_ok=True) or []:
            for item in module.get('items') or []:
                scan_item(item)
        # The Pages index is hidden in many courses; use it only when visible.
        for page in canvas.get('/api/v1/courses/%s/pages?per_page=100&sort=title' % course, missing_ok=True) or []:
            if RVC_TITLE.match(page.get('title') or '') or RVC_TITLE.match(page.get('url') or ''):
                scan_page(page['url'], follow=False)
        front = canvas.get('/api/v1/courses/%s/front_page' % course, missing_ok=True)
        if front and front.get('url'):
            scan_page(front['url'])
    recordings = sorted(found.values(), key=lambda r: (r.date, r.title, r.media_path))
    return info, recordings


def select(recordings, patterns=None, latest=None):
    if patterns:
        regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
        recordings = [r for r in recordings if any(x.search(r.title) or x.search(r.media_path) for x in regexes)]
    if latest:
        recordings = recordings[-latest:]
    return recordings


def unique_names(recordings):
    names = {}
    for r in recordings:
        name = r.name
        if name.casefold() in names:
            name = safe_name(name + '_' + r.media_path.split('_')[-1])
        names[name.casefold()] = r
        r.filename = name
    return recordings


def resolve_stream(tab, recording):
    data = json.loads(tab.js(PLAY_GET % json.dumps(recording.media_path)))
    stream = parse_player(data.get('html', '')) if data.get('status') == 200 else None
    if not stream:
        if 'Sign in' in data.get('html', '') or data.get('status') in (0, 401, 403):
            raise RuntimeError('rvcmedia.ust.hk sign-in expired. Open %s/Media/Play?path=%s in Chrome, sign in, '
                               'then rerun.' % (RVCMEDIA, recording.media_path))
        raise RuntimeError('No stream found for %s (status %s)' % (recording.media_path, data.get('status')))
    return stream
