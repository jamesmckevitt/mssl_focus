#!/usr/bin/env python3
"""Copy the private modules into `src` and compile them with Cython for a release build.

    python build_private.py PRIVATE_CHECKOUT [--no-compile]

Also writes `src/_private_deps.py`, which imports everything the compiled modules import, so
PyInstaller bundles those libraries; it cannot see imports inside a compiled module.
"""

import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODULES = ["license", "detect", "autoalign", "history", "photos"]
SRC = Path(__file__).resolve().parent / "src"


def imports_of(path):
    """Modules a file imports, absolute names, with relative imports given under `src`."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = "src" + (f".{node.module}" if node.module else "")
                found.update(f"{base}.{alias.name}" if not node.module else base for alias in node.names)
            else:
                found.add(node.module)
    return found


def main(argv=None, src=SRC):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 1
    private = Path(argv[0]) / "src"
    names = []
    for module in MODULES:
        source = private / f"{module}.py"
        if not source.is_file():
            raise SystemExit(f"missing private module {source}")
        shutil.copy2(source, src / f"{module}.py")
        names.append(src / f"{module}.py")

    deps = set()
    for path in names:
        deps |= imports_of(path)
    deps -= {f"src.{m}" for m in MODULES}
    lines = ['"""Imports of the compiled private modules, so PyInstaller bundles them."""', ""]
    lines += [f"import {name}  # noqa: F401" for name in sorted(deps)]
    (src / "_private_deps.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"copied {len(names)} private modules; {len(deps)} imports listed in src/_private_deps.py")

    if "--no-compile" in argv:
        return 0
    subprocess.run([sys.executable, "-m", "cython", "--version"], check=True)
    # Cython builds from the folder above the package, so the modules are compiled in a copy of
    # `src` in a folder of their own. Otherwise the build reads pyproject.toml, whose version is a
    # branch name in a build started by hand.
    with tempfile.TemporaryDirectory() as work:
        package = Path(work) / "src"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        copies = [shutil.copy2(path, package / path.name) for path in names]
        subprocess.run([sys.executable, "-m", "Cython.Build.Cythonize", "-3", "-i", *map(str, copies)],
                       check=True, cwd=work)
        for path in names:
            compiled = list(package.glob(f"{path.stem}.*.pyd")) + list(package.glob(f"{path.stem}.*.so"))
            if not compiled:
                raise SystemExit(f"no compiled module for {path.name}")
            shutil.copy2(compiled[0], src / compiled[0].name)
            path.unlink()
            print(f"compiled {compiled[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
