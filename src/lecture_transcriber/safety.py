"""Ownership, locking, path validation, and atomic publication (stdlib only)."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

IDENTITY = 'rvc-local-lecture-transcriber-v1'


def nested(path, parent):
    return path == parent or parent in path.parents


def no_symlinks(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink paths are not accepted: ' + str(part))
    return path


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.partial')
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class Runtime:
    def __init__(self, repo):
        self.repo = no_symlinks(repo).resolve()
        self.path = self.repo / '.runtime.nosync'
        self.marker = self.path / '.owner-marker'

    def verify(self):
        no_symlinks(self.path)
        no_symlinks(self.marker)
        if self.path.resolve() != self.repo / '.runtime.nosync':
            raise ValueError('Unsafe runtime path')
        if self.repo in (Path('/'), Path.home()):
            raise ValueError('Unsafe repository root')
        data = json.loads(self.marker.read_text())
        if (data.get('application') != IDENTITY or data.get('repo') != str(self.repo)
                or data.get('runtime') != str(self.path) or not data.get('uuid')):
            raise ValueError('Runtime ownership mismatch; refusing to use or delete it')
        return data

    def create(self):
        no_symlinks(self.path)
        if not self.path.exists():
            self.path.mkdir(mode=0o700)
            atomic_json(self.marker, dict(application=IDENTITY, repo=str(self.repo),
                runtime=str(self.path), uuid=str(uuid.uuid4())))
        self.verify()
        for name in ('tools', 'python', 'cache', 'tmp', 'models', 'logs', 'checkpoints', 'home'):
            no_symlinks(self.path / name).mkdir(exist_ok=True)

    @contextlib.contextmanager
    def lock(self):
        self.verify()
        lock = no_symlinks(self.path / '.lock')
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another worker/supervisor owns this runtime; wait for it to exit')
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode())
            yield fd
        finally:
            os.close(fd)

    def purge_locked(self, fd):
        """Caller holds lock; child processes inherit it until they exit."""
        self.verify()
        if os.fstat(fd).st_ino != (self.path / '.lock').stat().st_ino:
            raise ValueError('Runtime lock changed')
        if not shutil.rmtree.avoids_symlink_attacks:
            raise ValueError('Safe fd-based recursive deletion is unavailable on this host')
        # fd-based rmtree never follows symlinks in the managed tree.
        shutil.rmtree(self.path)
        if self.path.exists() or self.path.is_symlink():
            raise RuntimeError('Runtime cleanup incomplete: ' + str(self.path))

    def footprint(self):
        if not self.path.exists():
            return 0
        self.verify()
        total = 0
        for base, dirs, files in os.walk(self.path, followlinks=False):
            for name in files:
                p = Path(base) / name
                if not p.is_symlink():
                    total += p.stat().st_size
        return total

    def busy(self):
        if not self.path.exists():
            return False
        self.verify()
        path = no_symlinks(self.path / '.lock')
        if not path.exists():
            return False
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True
        finally:
            os.close(fd)


def validate_paths(repo, inputs, output):
    repo = no_symlinks(repo).resolve()
    output = no_symlinks(output)
    resolved = [no_symlinks(p).resolve() for p in inputs]
    forbidden = (Path('/'), Path.home().resolve(), repo)
    for p in (*resolved, output):
        if p in forbidden or nested(p, repo) or nested(repo, p):
            raise ValueError('Input/output must be separate from the source checkout: ' + str(p))
    for source in resolved:
        if not source.is_dir():
            raise ValueError('Input is not a directory: ' + str(source))
        if nested(source, output) or nested(output, source):
            raise ValueError('Input and output overlap')
    if output.exists() and not output.is_dir():
        raise ValueError('Output must be a directory')
    # Atomic hard-link/rename publishing requires the same filesystem.
    ancestor = output
    while not ancestor.exists():
        ancestor = ancestor.parent
    if ancestor.stat().st_dev != repo.stat().st_dev:
        raise ValueError('Output must be on the same filesystem as the checkout for atomic publishing')
    if output.exists():
        for p in output.iterdir():
            if p.is_symlink() or not p.is_file() or p.suffix != '.txt':
                raise ValueError('Output must contain only final .txt files: ' + str(p))
    return resolved, output


def publish(temp, destination, overwrite=False):
    no_symlinks(destination)
    if overwrite:
        os.replace(temp, destination)
    else:
        # link() fails atomically if a concurrent writer created the destination.
        os.link(temp, destination)
        Path(temp).unlink()
    fd = os.open(Path(destination).parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
