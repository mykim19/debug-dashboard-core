"""Knowledge Hub — Debug Dashboard (thin launcher)"""

import sys
from pathlib import Path

# Add debugger_agent root so debug_dashboard_core is importable
# examples/project0914/app.py → parent.parent.parent = debugger_agent/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from debug_dashboard_core.app import create_app

app = create_app(config_path=str(Path(__file__).resolve().parent / "config.yaml"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=False, threaded=True)
