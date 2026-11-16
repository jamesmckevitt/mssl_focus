"""MSSL FOCUS: the window, or the command line.

    python mssl_focus.py                        open the application
    python mssl_focus.py export SESSION.json    render a map without a window
    python mssl_focus.py COMMAND ...            work with a filter's inspection history
                                                (add, align, detect, accept, reject,
                                                unsure, sure, show, migrate, photos,
                                                replace-photos, remove, crosscheck;
                                                -h for details)
"""

from src.launch import main

if __name__ == "__main__":
    raise SystemExit(main())
