#!/usr/bin/env python3
"""Check staged files, or the complete tracked tree with --all. No media fixtures."""
import re
from pathlib import PurePosixPath
import subprocess
import sys

args = ['git', 'ls-files', '-z'] if '--all' in sys.argv else ['git','diff','--cached','--name-only','--diff-filter=ACMR','-z']
paths = subprocess.check_output(args).decode().split('\0')
bad = []
extensions = {'.mp4','.m4a','.mp3','.wav','.flac','.srt','.vtt','.log','.ckpt','.safetensors',
              '.pt','.pth','.bin','.gguf','.zip','.gz','.whl','.pyc'}
allowed_txt = {'requirements.txt', 'CMakeLists.txt'}
for name in filter(None, paths):
    p=PurePosixPath(name)
    if (p.suffix.lower() in extensions or (p.suffix=='.txt' and p.name not in allowed_txt)
        or any(x in p.parts for x in ('.runtime','.runtime.nosync','.venv','__pycache__','Transcripts','outputs'))
        or p.name.startswith('.env') and p.name!='.env.example'):
        bad.append(name+': private/generated asset')
        continue
    data=subprocess.check_output(['git','show',':'+name])
    if len(data)>1024*1024:
        bad.append(name+': exceeds 1 MiB source limit')
    if re.search(rb'(?:sk-[A-Za-z0-9_-]{32,}|hf_[A-Za-z0-9]{25,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)',data):
        bad.append(name+': potential secret')
if bad:
    print('\n'.join(bad),file=sys.stderr)
    sys.exit(1)
print('Privacy guard passed: source-only files, no detected secrets or oversized assets.')
