"""Small stdlib supervisor; remains outside the disposable interpreter."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from lecture_transcriber.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
