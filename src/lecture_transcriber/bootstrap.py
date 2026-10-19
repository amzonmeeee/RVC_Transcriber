"""Verified portable tools; all third-party state is scoped to .runtime.nosync."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile

from .safety import sha256

UV_VERSION = '0.13.1'
UV_SHA256 = 'cfe454573412ff7380d15fc7dae5997ab53ffce72fce0a78e91ddbc84001acd2'
PYTHON_VERSION = '3.12.12'
MODELS = {
    'qwen3-asr-1.7b': ('Qwen/Qwen3-ASR-1.7B', '7278e1e70fe206f11671096ffdd38061171dd6e5'),
    'qwen3-asr-0.6b': ('Qwen/Qwen3-ASR-0.6B', '5eb144179a02acc5e5ba31e748d22b0cf3e303b0'),
    'whisper-large-v3': ('Systran/faster-whisper-large-v3', 'edaa852ec7e145841d8ffdb056a99866b5f0a478'),
}


def supported():
    return platform.system() == 'Darwin' and platform.machine() == 'arm64'


def environment(runtime):
    r = runtime.path
    env = dict(os.environ)
    # Do not inherit alternate installers, caches, package indexes, or credentials.
    for key in list(env):
        if key.startswith(('UV_', 'PIP_', 'HF_', 'HUGGINGFACE_', 'PYTHON', 'CONDA_', 'VIRTUAL_ENV')):
            env.pop(key, None)
    paths = {
        'UV_CACHE_DIR': 'cache/uv', 'UV_PYTHON_INSTALL_DIR': 'python',
        'UV_PYTHON_BIN_DIR': 'tools/python-bin', 'UV_TOOL_DIR': 'tools/uv-tools',
        'UV_TOOL_BIN_DIR': 'tools/bin', 'PIP_CACHE_DIR': 'cache/pip',
        'HF_HOME': 'cache/hf', 'HF_HUB_CACHE': 'cache/hf/hub',
        'HF_XET_CACHE': 'cache/hf/xet', 'TORCH_HOME': 'cache/torch',
        'XDG_CACHE_HOME': 'cache/xdg', 'XDG_CONFIG_HOME': 'home/config',
        'XDG_DATA_HOME': 'home/data', 'XDG_STATE_HOME': 'home/state',
        'TMPDIR': 'tmp', 'TMP': 'tmp', 'TEMP': 'tmp',
        'NUMBA_CACHE_DIR': 'cache/numba', 'MPLCONFIGDIR': 'cache/matplotlib',
        'CLANG_MODULE_CACHE_PATH': 'cache/clang', 'SWIFT_MODULECACHE_PATH': 'cache/swift',
        'CUPY_CACHE_DIR': 'cache/cupy', 'CUDA_CACHE_PATH': 'cache/cuda',
        'IMAGEIO_USERDIR': 'cache/imageio',
    }
    for key, rel in paths.items():
        path = r / rel
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    # Preserve HOME; scope each dependency's actual mutable directories explicitly.
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONUNBUFFERED='1',
        PYTHONPATH=str(runtime.repo / 'src'), UV_PYTHON_PREFERENCE='only-managed',
        UV_NO_CONFIG='1', UV_NO_PROGRESS='1', UV_LINK_MODE='copy',
        UV_PYTHON_DOWNLOADS='automatic', HF_HUB_DISABLE_TELEMETRY='1',
        HF_HUB_DISABLE_IMPLICIT_TOKEN='1', HF_HUB_DISABLE_XET='1',
        DO_NOT_TRACK='1', ORT_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
    return env


def fetch(url, target, env, expected=None):
    if target.exists() and (expected is None or sha256(target) == expected):
        return
    partial = target.with_name(target.name + '.partial')
    subprocess.run(['/usr/bin/curl', '--disable', '--fail', '--location', '--show-error', '--silent',
                    '--retry', '3', '--proto', '=https', '--proto-redir', '=https',
                    '--output', str(partial), url], check=True, env=env)
    if expected and sha256(partial) != expected:
        partial.unlink()
        raise ValueError('Download checksum mismatch: ' + url)
    os.replace(partial, target)


def ensure_uv(runtime, env):
    binary = runtime.path / 'tools/uv'
    archive = runtime.path / 'tools/uv.tar.gz'
    fetch('https://github.com/astral-sh/uv/releases/download/' + UV_VERSION +
          '/uv-aarch64-apple-darwin.tar.gz', archive, env, UV_SHA256)
    # Extract just the verified regular file, never archive paths or symlinks.
    with tarfile.open(archive) as tar:
        member = tar.getmember('uv-aarch64-apple-darwin/uv')
        if not member.isfile():
            raise ValueError('Invalid uv archive')
        with tar.extractfile(member) as source, open(binary, 'wb') as dest:
            shutil.copyfileobj(source, dest)
    binary.chmod(0o700)
    return binary


def ensure_environment(runtime, env, runner):
    uv = ensure_uv(runtime, env)
    runner([str(uv), 'python', 'install', PYTHON_VERSION, '--no-bin'], env)
    venv = runtime.path / '.venv'
    python = venv / 'bin/python'
    if not python.exists():
        runner([str(uv), 'venv', '--python', PYTHON_VERSION, str(venv)], env)
    lock = runtime.repo / 'requirements.lock'
    if not lock.exists():
        raise ValueError('Missing requirements.lock; source checkout is incomplete')
    wheelhouse = runtime.path / 'tools/wheels'
    offline = ['--no-index', '--find-links', str(wheelhouse)] if wheelhouse.exists() else []
    runner([str(uv), 'pip', 'sync', '--python', str(python), '--require-hashes',
            '--only-binary', ':all:', *offline, str(lock)], env)
    return python
