#!/usr/bin/env python3
"""
Quick launcher for Debug Dashboard Core.

Usage:
    python run_dashboard.py run <workspace_path> [--port PORT] [--add-workspace PATH ...]
    python run_dashboard.py init <workspace_path> [--name NAME] [--port PORT]

Examples:
    python run_dashboard.py run /Volumes/01_Kioxia/project0914
    python run_dashboard.py run /Volumes/01_Kioxia/project0914 --port 5010
    python run_dashboard.py run /Volumes/01_Kioxia/project0914 --add-workspace /path/to/other

This is equivalent to:
    python -m debug_dashboard_core run <workspace_path>
"""

import sys
import os

# Ensure the package is importable (works from any directory)
_this_dir = os.path.dirname(os.path.abspath(__file__))
# If this script is in debug_dashboard_core/, go one level up
if os.path.basename(_this_dir) == "debug_dashboard_core":
    _parent = os.path.dirname(_this_dir)
else:
    _parent = _this_dir

if _parent not in sys.path:
    sys.path.insert(0, _parent)

from debug_dashboard_core.cli import main

sys.exit(main())
