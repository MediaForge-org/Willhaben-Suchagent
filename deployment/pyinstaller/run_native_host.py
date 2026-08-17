"""PyInstaller entry point for the bundled native-messaging host executable."""

import sys

from agent.app.native_messaging.host import main

if __name__ == "__main__":
    sys.exit(main())
