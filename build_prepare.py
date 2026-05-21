#!/usr/bin/env python3
"""
Pre-build helper called by the GitHub Actions workflow.

Usage: python build_prepare.py <git-tag>   e.g.  python build_prepare.py v1.2.3

Writes:
  _version.txt           -- plain version string (tag with leading 'v' stripped)
  app.ico                -- application icon (multi-size ICO via Pillow)
  file_version_info.txt  -- PyInstaller Windows VERSIONINFO resource
"""

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
    # app.ico  (requires Pillow, already installed by the workflow)
    # ------------------------------------------------------------------ #
    from PIL import Image, ImageDraw

    sz = 256
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 10
    # Outer ring — filter housing
    d.ellipse([m, m, sz - m - 1, sz - m - 1],
              fill="#1a3a5c", outline="#4a8ab5", width=14)
    # Mid ring — thin-film coating layers
    q = sz // 4
    d.ellipse([q, q, sz - q, sz - q],
              fill="#0d2540", outline="#6ab0dc", width=8)
    # Inner ring
    e = sz * 3 // 8
    d.ellipse([e, e, sz - e, sz - e],
              fill="#162e48", outline="#90c8e8", width=5)
    # Centre spot
    c0, c1 = sz * 7 // 16, sz * 9 // 16
    d.ellipse([c0, c0, c1, c1], fill="#b0deff")

    img.save(
        "app.ico",
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print("Generated app.ico")

    # ------------------------------------------------------------------ #
    # file_version_info.txt  (Windows VERSIONINFO for PyInstaller)
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
        StringStruct(u'FileDescription', u'MSSL Filter Inspector'),
        StringStruct(u'FileVersion', u'{ver_str}'),
        StringStruct(u'InternalName', u'mssl_filter_inspector'),
        StringStruct(u'LegalCopyright', u'\\xa9 James McKevitt, UCL MSSL'),
        StringStruct(u'OriginalFilename', u'mssl_filter_inspector.exe'),
        StringStruct(u'ProductName', u'MSSL Filter Inspector'),
        StringStruct(u'ProductVersion', u'{ver_str}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [0x0409, 1200])])
  ])
"""
    with open("file_version_info.txt", "w", encoding="utf-8") as fh:
        fh.write(vinfo)
    print("Generated file_version_info.txt")


if __name__ == "__main__":
    main()
