"""Starting the program, where the command line checks the licence without dialogs."""

import hashlib
import json

from src import launch
from src.license_flow import LICENSE_ENV, license_problem_quietly


class FakeBackend:
    _MASTER_HASH = hashlib.sha256(b"open sesame").hexdigest()

    @staticmethod
    def _compute_signature(email, expiry):
        return hashlib.sha256(f"{email}|{expiry}".encode()).hexdigest()


class FakeConfig:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def _licence(path, expiry="2099-01-01"):
    email = "someone@example.org"
    path.write_text(json.dumps({"email": email, "expiry": expiry,
                                "signature": FakeBackend._compute_signature(email, expiry)}))
    return path


def test_a_licence_file_is_found_and_remembered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = FakeConfig()
    good = _licence(tmp_path / "elsewhere.dat")
    assert license_problem_quietly(FakeBackend, config, environ={LICENSE_ENV: str(good)}) is None
    assert config.values["license_path"] == str(good.resolve())
    # Next time it is remembered.
    assert license_problem_quietly(FakeBackend, config, environ={}) is None
    # One beside the program (here, the current folder) is taken too.
    fresh = FakeConfig()
    _licence(tmp_path / "license_2099.dat")
    assert license_problem_quietly(FakeBackend, fresh, environ={}) is None


def test_without_a_licence_the_command_line_says_how_to_get_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    expired = _licence(tmp_path / "old.dat", expiry="2001-01-01")
    problem = license_problem_quietly(FakeBackend, FakeConfig(), environ={LICENSE_ENV: str(expired)})
    assert "expired" in problem and LICENSE_ENV in problem
    assert "Incorrect master password" in license_problem_quietly(
        FakeBackend, FakeConfig(), environ={}, password=lambda: "wrong")
    assert license_problem_quietly(FakeBackend, FakeConfig(), environ={}, password=lambda: "open sesame") is None


def test_commands_check_the_licence_but_help_does_not(monkeypatch):
    calls = []
    monkeypatch.setattr(launch, "_require_license", lambda: calls.append("licence"))
    monkeypatch.setattr("src.cli.main", lambda argv: calls.append(argv[0]) or 0)
    assert launch.main(["show", "em9"]) == 0
    assert launch.main(["--help"]) == 0
    assert launch.main(["export", "-h"]) == 0
    assert calls == ["licence", "show", "--help", "export"]
