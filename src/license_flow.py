import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import Config

# The licence file the command line uses when none was accepted before.
LICENSE_ENV = "MSSL_FOCUS_LICENSE"


def _fail(message):
    from .license_ui import show_license_error
    show_license_error(message)
    raise SystemExit(1)


def _license_problem(backend, license_path):
    """Return ``None`` if the licence file is valid, else a message saying why not."""
    try:
        data = json.loads(Path(license_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return ("The selected file could not be read.\n\n"
                "Please make sure you selected a valid license.dat file.")
    if not isinstance(data, dict):
        data = {}

    email = data.get("email", "")
    expiry = data.get("expiry", "")
    signature = data.get("signature", "")
    if not email or not expiry or not signature:
        return ("The selected license file is incomplete.\n\n"
                "Please obtain a valid license.dat from jm2@mssl.ucl.ac.uk.")

    expected = backend._compute_signature(email, expiry)
    if not hmac.compare_digest(str(signature), expected):
        return ("License signature is invalid.\n\n"
                "The license file may have been tampered with.\n"
                "Please obtain a new license from jm2@mssl.ucl.ac.uk.")

    try:
        expiry_date = datetime.fromisoformat(expiry)
        if expiry_date.tzinfo is None:
            expiry_date = expiry_date.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ("License expiry date is malformed.\n\n"
                "Please obtain a new license from jm2@mssl.ucl.ac.uk.")

    if expiry_date < datetime.now(timezone.utc):
        return (f"Your license expired on {expiry_date.strftime('%Y-%m-%d')}.\n\n"
                "Please contact jm2@mssl.ucl.ac.uk for a renewal.")
    return None


def _known_license_files(config):
    """Licence files to try before asking: the last one used, then any beside the program."""
    candidates = []
    remembered = config.get("license_path")
    if remembered:
        candidates.append(Path(remembered))
    program_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    try:
        candidates.extend(sorted(program_dir.glob("license*.dat"), reverse=True))
    except OSError:
        pass
    return candidates


def check_license(backend, config=None):
    """Run the public licence UI using the injected private validation backend.

    A licence file that was accepted before (or one sitting beside the program)
    is re-validated silently, so a licensed user is not asked on every start.
    """
    from .license_ui import ask_license_file, ask_license_method, ask_password
    config = config if config is not None else Config()
    for candidate in _known_license_files(config):
        if candidate.is_file() and _license_problem(backend, candidate) is None:
            config.set("license_path", str(candidate))
            return

    choice = ask_license_method()
    if choice is None:
        raise SystemExit(1)

    if choice == "yes":
        path_string = ask_license_file()
        if not path_string:
            raise SystemExit(1)
        problem = _license_problem(backend, path_string)
        if problem is not None:
            _fail(problem)
        config.set("license_path", str(Path(path_string).resolve()))
        return

    master_input = ask_password("Enter master password:")
    if master_input is None:
        raise SystemExit(1)

    master_hash = hashlib.sha256(master_input.encode("utf-8")).hexdigest()
    if hmac.compare_digest(master_hash, backend._MASTER_HASH):
        return

    _fail(
        "Incorrect master password.\n\n"
        "Please contact jm2@mssl.ucl.ac.uk for a license file."
    )


def license_problem_quietly(backend, config=None, environ=None, password=None):
    """The licence check for the command line, which has no dialogs: ``None`` if
    licensed, else a message saying how to become so.

    A licence file accepted before (in the window), one beside the program, or
    one named by the ``MSSL_FOCUS_LICENSE`` environment variable is accepted;
    failing those, ``password`` (a callable, used at an interactive terminal)
    is asked for the master password.
    """
    config = config if config is not None else Config()
    environ = os.environ if environ is None else environ
    named = environ.get(LICENSE_ENV)
    problems = []
    if named:
        problem = _license_problem(backend, named)
        if problem is None:
            config.set("license_path", str(Path(named).resolve()))
            return None
        problems.append(f"{named}: {problem}")
    for candidate in _known_license_files(config):
        if candidate.is_file() and _license_problem(backend, candidate) is None:
            config.set("license_path", str(candidate))
            return None
    if password is not None:
        entered = password()
        if entered:
            digest = hashlib.sha256(entered.encode("utf-8")).hexdigest()
            if hmac.compare_digest(digest, backend._MASTER_HASH):
                return None
            problems.append("Incorrect master password.")
    return "\n".join(problems + [
        "MSSL FOCUS needs a valid license file. Open the application once and choose your "
        f"license.dat (it is remembered), put it beside the program, or set {LICENSE_ENV} to its path. "
        "To request a license, contact jm2@mssl.ucl.ac.uk."])


__all__ = ["check_license", "license_problem_quietly", "LICENSE_ENV"]
