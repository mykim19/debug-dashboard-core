"""Entry point for: python -m debug_dashboard_core <subcommand>"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
