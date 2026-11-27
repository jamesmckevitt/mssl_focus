"""Preparing the private modules for a release build."""

import build_private


def test_private_modules_are_copied_and_their_imports_listed(tmp_path):
    private = tmp_path / "private" / "src"
    private.mkdir(parents=True)
    for name in build_private.MODULES:
        (private / f"{name}.py").write_text("import math\n", encoding="utf-8")
    (private / "detect.py").write_text("import numpy as np\nfrom . import geometry as geo\n"
                                       "from .camera import read_camera_info\nfrom .history import x\n",
                                       encoding="utf-8")
    (private / "license.py").write_text("def ok():\n    from cryptography.exceptions import InvalidSignature\n",
                                        encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    assert build_private.main([str(tmp_path / "private"), "--no-compile"], src=src) == 0
    assert sorted(p.stem for p in src.glob("*.py") if p.stem != "_private_deps") == sorted(build_private.MODULES)
    deps = (src / "_private_deps.py").read_text(encoding="utf-8")
    # Third-party, standard-library and public `src` imports are listed; private ones are not.
    for name in ("numpy", "math", "src.geometry", "src.camera", "cryptography.exceptions"):
        assert f"import {name}  #" in deps
    assert "src.history" not in deps
