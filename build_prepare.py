#!/usr/bin/env python3
"""Write the files the GitHub Actions build needs for a release tag.

Usage: python build_prepare.py <git-tag>, for example python build_prepare.py v1.2.3

Writes:
  _version.txt           - version string, the tag without its leading `v`
  app.ico                - application icon, multi-size ICO made with Pillow
  app.png                - application icon as PNG, for Linux and the running app
  file_version_info.txt  - PyInstaller Windows VERSIONINFO resource

Updates:
  pyproject.toml         - sets project.version to the version string
"""

import pathlib
import re
import sys


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "dev"
    ver_str = tag.lstrip("v") or "dev"

    # ------------------------------------------------------------------ #
    # _version.txt
    # ------------------------------------------------------------------ #
    with open("_version.txt", "w") as fh:
        fh.write(ver_str)
    print(f"Wrote _version.txt: {ver_str}")

    # ------------------------------------------------------------------ #
    # app.ico and app.png, made with Pillow (installed by the workflow)
    # ------------------------------------------------------------------ #
    from PIL import Image, ImageDraw

    # Simple 3x3 black grid on a white square
    sz = 256
    m = 18
    img = Image.new("RGBA", (sz, sz), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    x0, y0 = m, m
    x1, y1 = sz - m - 1, sz - m - 1
    d.rectangle([x0, y0, x1, y1], fill="white", outline="black", width=8)
    line_w = 10
    for frac in (1 / 3, 2 / 3):
      x = round(x0 + frac * (x1 - x0))
      y = round(y0 + frac * (y1 - y0))
      d.line([(x, y0), (x, y1)], fill="black", width=line_w)
      d.line([(x0, y), (x1, y)], fill="black", width=line_w)

    img.save(
        "app.ico",
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    img.save("app.png", format="PNG")
    print("Generated app.ico and app.png")

    # ------------------------------------------------------------------ #
    # file_version_info.txt, the Windows VERSIONINFO resource for PyInstaller
    # ------------------------------------------------------------------ #
    parts = re.findall(r"\d+", ver_str) + ["0", "0", "0", "0"]
    a, b, c, dv = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])

    vinfo = f"""\
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {dv}),
    prodvers=({a}, {b}, {c}, {dv}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'UCL MSSL'),
        StringStruct(u'FileDescription', u'MSSL FOCUS - Filter Optical Characterisation Utility Software'),
        StringStruct(u'FileVersion', u'{ver_str}'),
        StringStruct(u'InternalName', u'mssl_focus'),
        StringStruct(u'LegalCopyright', u'\\xa9 James McKevitt, UCL MSSL'),
        StringStruct(u'OriginalFilename', u'mssl_focus.exe'),
        StringStruct(u'ProductName', u'MSSL FOCUS'),
        StringStruct(u'ProductVersion', u'{ver_str}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [0x0409, 1200])])
  ])
"""
    with open("file_version_info.txt", "w", encoding="utf-8") as fh:
        fh.write(vinfo)
    print("Generated file_version_info.txt")

    # ------------------------------------------------------------------ #
    # pyproject.toml, with project.version set to the version string
    # ------------------------------------------------------------------ #
    toml_path = pathlib.Path("pyproject.toml")
    if toml_path.exists():
        content = toml_path.read_text(encoding="utf-8")
        content, count = re.subn(
            r'^version\s*=\s*"[^"]*"',
            f'version = "{ver_str}"',
            content,
            flags=re.MULTILINE,
        )
        if count:
            toml_path.write_text(content, encoding="utf-8")
            print(f"Stamped pyproject.toml with version: {ver_str}")
        else:
            print("WARNING: could not find version string in pyproject.toml")


if __name__ == "__main__":
    main()
