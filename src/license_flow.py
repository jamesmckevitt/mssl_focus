import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

from .license_ui import (
    ask_license_file,
    ask_license_method,
    ask_password,
    show_license_error,
)


def _fail(message):
    show_license_error(message)
    raise SystemExit(1)


def check_license(backend):
    """Run the public licence UI using the injected private validation backend."""
    choice = ask_license_method()
    if choice is None:
        raise SystemExit(1)

    if choice == "yes":
        path_string = ask_license_file()
        if not path_string:
            raise SystemExit(1)

        license_path = Path(path_string)
        try:
            data = json.loads(license_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _fail(
                "The selected file could not be read.\n\n"
                "Please make sure you selected a valid license.dat file."
            )

        email = data.get("email", "")
        expiry = data.get("expiry", "")
        signature = data.get("signature", "")
        if not email or not expiry or not signature:
            _fail(
                "The selected license file is incomplete.\n\n"
                "Please obtain a valid license.dat from jm2@mssl.ucl.ac.uk."
            )

        expected = backend._compute_signature(email, expiry)
        if not hmac.compare_digest(signature, expected):
            _fail(
                "License signature is invalid.\n\n"
                "The license file may have been tampered with.\n"
                "Please obtain a new license from jm2@mssl.ucl.ac.uk."
            )

        try:
            expiry_date = datetime.fromisoformat(expiry)
            if expiry_date.tzinfo is None:
                expiry_date = expiry_date.replace(tzinfo=timezone.utc)
        except ValueError:
            _fail(
                "License expiry date is malformed.\n\n"
                "Please obtain a new license from jm2@mssl.ucl.ac.uk."
            )

        if expiry_date < datetime.now(timezone.utc):
            _fail(
                f"Your license expired on {expiry_date.strftime('%Y-%m-%d')}.\n\n"
                "Please contact jm2@mssl.ucl.ac.uk for a renewal."
            )
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


__all__ = ["check_license"]
