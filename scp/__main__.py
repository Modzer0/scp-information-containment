from __future__ import annotations

import sys


USAGE = "usage: python -m scp {daemon|tui}"


def main() -> None:
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(2)

    sub = sys.argv[1]
    if sub == "daemon":
        from .daemon.main import main as daemon_main

        daemon_main()
    elif sub == "tui":
        from .tui.main import main as tui_main

        tui_main()
    else:
        print(f"unknown subcommand: {sub}")
        print(USAGE)
        sys.exit(2)


if __name__ == "__main__":
    main()
