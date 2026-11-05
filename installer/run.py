#!/usr/bin/python -I
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v8_installer.__main__ import main
main()
