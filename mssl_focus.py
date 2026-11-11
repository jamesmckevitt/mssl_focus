"""MSSL FOCUS: the window, or the command line.

    python mssl_focus.py                        open the application
    python mssl_focus.py export SESSION.json    render a map without a window
    python mssl_focus.py COMMAND ...            work with a filter's inspection history
                                                (add, align, detect, accept, reject,
                                                show, migrate, photos, replace-photos,
                                                remove; -h for details)
"""

import sys

# The command-line verbs; kept here so starting the window imports nothing extra.
COMMANDS = ("export", "add", "align", "detect", "accept", "reject", "show", "migrate", "photos",
            "replace-photos", "remove", "-h", "--help")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        # Imported here so the command line works where there is no display.
        from src.cli import main as cli_main
        return cli_main(argv)
    from src.main import run_app
    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
