#!/usr/bin/env python3
"""Compatibility entry point for config-only installation."""
import subprocess
import sys
from pathlib import Path
raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).resolve().parents[1] / 'install.py'), '--config-only', *sys.argv[1:]]))
