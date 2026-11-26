"""Entry point that starts the window or runs a command-line verb.

Starting the window imports nothing here beyond `sys`, to keep start-up light.
"""

import sys

# The command-line verbs.
COMMANDS = ("export", "add", "align", "detect", "accept", "reject", "show", "migrate", "photos",
            "replace-photos", "remove", "crosscheck", "unsure", "sure", "-h", "--help")
HELP = ("-h", "--help")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in COMMANDS:
        _attach_console()
        if not _only_help(argv):
            _require_license()
        # Imported here so the command line works where there is no display.
        from .cli import main as cli_main
        return cli_main(argv)
    from .main import run_app
    run_app()
    return 0


def _only_help(argv):
    """Whether the command line asks only for help, which needs no licence.

    That is `-h` or `--help` alone, or after a command name with nothing else. Anywhere else a
    help flag may be a file name, for example after `--`."""
    return argv[0] in HELP or (len(argv) == 2 and argv[1] in HELP)


def _require_license():
    """Check the licence for the command line without dialogs, and exit if there is none.

    At a real console it asks for the master password when no licence file is found."""
    try:
        from . import license as backend
    except ImportError:
        raise SystemExit("This copy of MSSL FOCUS is missing its licensing module and cannot run. "
                         "Please download the official release from "
                         "https://github.com/jamesmckevitt/mssl_focus/releases") from None
    from .license_flow import license_problem_quietly
    password = None
    if _interactive():
        import getpass

        def password():
            try:
                return getpass.getpass("No license file found. Master password (Enter to skip): ")
            except (EOFError, KeyboardInterrupt):
                return ""
    problem = license_problem_quietly(backend, password=password)
    if problem:
        raise SystemExit(problem)


def _interactive():
    """Whether someone can type an answer.

    On Windows `isatty` is also true of the NUL device that scripts and scheduled tasks read
    from, where a prompt would wait for ever, so the input must be a real console."""
    if sys.stdin is None:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            import msvcrt
            mode = ctypes.c_uint32()
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
        except (OSError, ValueError, AttributeError):
            return False
    try:
        return sys.stdin.isatty()
    except (OSError, ValueError):
        return False


def _attach_console():
    """Give the command line somewhere to print.

    The packaged program is a windowed one, so it starts with nowhere to print. Run from a
    terminal, it borrows that terminal's console. Otherwise its output goes to `cli.log` in the
    settings folder."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = None
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):      # the parent process's console
                stream = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        except (OSError, AttributeError):
            stream = None
    if stream is None:
        try:
            from .config import config_dir
            folder = config_dir()
            folder.mkdir(parents=True, exist_ok=True)
            stream = open(folder / "cli.log", "a", encoding="utf-8", buffering=1)
        except OSError:
            return
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
