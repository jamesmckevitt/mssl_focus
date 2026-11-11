"""MSSL FOCUS: the window, or a command-line export.

    python mssl_focus.py                      open the application
    python mssl_focus.py export SESSION.json  render a map without a window
"""

import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "export":
        # Imported here so the command line works where there is no display.
        from src.cli import main as export_main
        return export_main(argv[1:])
    from src.main import run_app
    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
