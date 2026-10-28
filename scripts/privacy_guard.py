#!/usr/bin/env python3
"""Check staged files, or the complete tracked tree with --all. No media fixtures."""
import re
from pathlib import PurePosixPath
import subprocess
import sys

args = ['git', 'ls-files', '-z'] if '--all' in sys.argv else ['git','diff','--cached','--name-only','--diff-filter=ACMR','-z']
paths = subprocess.check_output(args).decode().split('\0')
bad = []
extensions = {'.mp4','.m4v','.mov','.mkv','.avi','.webm','.m4a','.mp3','.wav','.flac',
              '.aac','.ogg','.opus','.aif','.aiff','.srt','.vtt','.log','.ckpt','.safetensors',
              '.pt','.pth','.bin','.gguf','.onnx','.npz','.npy','.h5','.hdf5','.tflite',
              '.pkl','.pickle','.msgpack','.mlmodel','.zip','.tar','.gz','.tgz','.bz2',
              '.xz','.7z','.whl','.pyc','.pyo','.dmg','.exe','.dylib','.so','.o','.a',
              '.part','.partial','.pem','.key'}
private_dirs = {'.runtime','.runtime.nosync','.venv','venv','env','__pycache__',
                'transcripts','lecturesmp4','outputs','models','weights','checkpoints',
                'cache','caches','.cache','logs','tmp','temp','.aws','.ssh','.codex','.agents'}
allowed_txt = {'requirements.txt', 'CMakeLists.txt'}
for name in filter(None, paths):
    p=PurePosixPath(name)
    if (p.suffix.lower() in extensions or (p.suffix.lower()=='.txt' and p.name not in allowed_txt)
        or any(x.lower() in private_dirs or x.lower().startswith('previewtranscripts')
               or x.lower().endswith(('.mlmodelc','.mlpackage')) for x in p.parts)
        or p.name in {'.DS_Store','id_rsa','id_ed25519','credentials.json'}
        or p.name.startswith('service-account') and p.suffix.lower()=='.json'
        or p.name.startswith('.env') and p.name!='.env.example'):
        bad.append(name+': private/generated asset')
        continue
    data=subprocess.check_output(['git','show',':'+name])
    if len(data)>1024*1024:
        bad.append(name+': exceeds 1 MiB source limit')
    if re.search(rb'(?:sk-[A-Za-z0-9_-]{32,}|hf_[A-Za-z0-9]{25,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)',data):
        bad.append(name+': potential secret')
    if re.search(rb'(?:/Users|/home)/(?!runner/|<)[A-Za-z0-9._-]+/', data):
        bad.append(name+': hard-coded personal home path')
if bad:
    print('\n'.join(bad),file=sys.stderr)
    sys.exit(1)
print('Privacy guard passed: source-only files, no detected secrets or oversized assets.')
