# SPDX-License-Identifier: GPL-3.0-or-later
import sys


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    # Answer --version before importing GTK, whose import can print
    # accessibility-bus warnings in sessions without one.
    if "--version" in args or "-V" in args:
        from . import __version__
        print(f"spaced-monitor {__version__}")
        return 0
    from .app import main as app_main
    return app_main(args)


if __name__ == "__main__":
    sys.exit(main())
