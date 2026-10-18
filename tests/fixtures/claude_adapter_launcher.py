"""Synthetic Claude tool process: exits after its adapter announces ready."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lienzo"))

from claude_pipe_adapter import launch_adapter

launch_adapter({"session_id": sys.argv[1]})
