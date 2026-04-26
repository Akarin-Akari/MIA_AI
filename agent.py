"""Root entry point — delegates to app.main.

Usage:
    python agent.py              # CLI interactive mode
    python agent.py --api        # FastAPI server mode

This file exists to satisfy the challenge requirement:
    "One command (python agent.py or equivalent) launches the agent in CLI."
"""

from app.main import main

if __name__ == "__main__":
    main()
