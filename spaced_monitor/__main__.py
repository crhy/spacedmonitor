# SPDX-License-Identifier: GPL-3.0-or-later
import sys


def main(argv=None):
    from .app import main as app_main
    return app_main(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
