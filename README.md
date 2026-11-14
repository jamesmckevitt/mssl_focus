# MSSL FOCUS

**Filter Optical Characterisation Utility Software**

Developed at UCL Mullard Space Science Laboratory (MSSL).

A desktop tool for comparing and annotating pairs of thin-film optical filter images side-by-side or as a blended overlay. Tools for alignment, annotation, crop export, and session save/load.

## Download

No Python required, the executables are fully self-contained.

| Platform | Download |
|----------|----------|
| Windows  | [![Download for Windows](https://img.shields.io/github/v/release/jamesmckevitt/mssl_focus?label=Download%20%28Windows%29&color=0078D4&logoColor=white)](https://github.com/jamesmckevitt/mssl_focus/releases/latest/download/mssl_focus.exe) |
| Linux    | [![Download for Linux](https://img.shields.io/github/v/release/jamesmckevitt/mssl_focus?label=Download%20%28Linux%29&color=FCC624&logoColor=black)](https://github.com/jamesmckevitt/mssl_focus/releases/latest/download/mssl_focus) |

> **Note:** This software is developed in Linux and the executable for Windows is tested.

## Features

- Side-by-side and blended overlay views of a backlit / frontlit image pair, with linked pan and zoom
- A reference row showing an earlier inspection of the same filter, aligned to the current one, for before / after comparison
- Guided tools: level (make the filter upright), align by matching points (with a residual estimate), annotate, move, crop export
- Camera RAW files (ARW, NEF, CR2, DNG, ...) developed directly, with dark-field treatment and noise reduction for backlit frames
- Automatic pinhole search, with a review step; spots that are new since the reference inspection are shown first
- Annotation markers with automatic numbering per colour, a legend with counts, undo / redo
- Brightness / contrast / blacks / whites adjustment per image
- Export of a region or the whole view at full resolution, with markers, legend and date stamp
- Sessions saved to a `.json` file that still opens after its folder is moved or renamed
- A history file per filter that stacks its inspections (see below)

Press **F1** in the application for a step-by-step guide.

## Filter histories and the command line

A filter's history (for example `em2.json`) holds every inspection of that filter in order, and every pinhole ever found in it with a permanent ID (`I3`, `S1`, ...), the inspection it first appeared in, and whether it was accepted or rejected. Pinholes are kept in filter coordinates, so they carry across inspections, and a spot rejected once is skipped when it is found again. The application opens a history like a session (pick the inspection) and saves changes back into it.

Everything else runs headless; a history is named by its file or, for `<name>.json` in the current folder, by the filter's name:

```bash
python mssl_focus.py migrate incoming.json shock.json -o em2.json   # sessions, oldest first
python mssl_focus.py photos 5_thermal_test/em2                      # which RAW photos would be used
python mssl_focus.py add em2 thermal 5_thermal_test/em2              # chooses them, aligns automatically
python mssl_focus.py replace-photos em2 thermal 5_thermal_test/em2   # other photos of an inspection
python mssl_focus.py remove em2 thermal                              # with the pinholes first seen there
python mssl_focus.py detect em2 thermal                              # sharp points; --sensitivity for every spot
python mssl_focus.py crosscheck em2                                  # faint ones, seen in two inspections or more
python mssl_focus.py reject em2 T4 T7                                # or: accept em2 T7
python mssl_focus.py show em2 --pinholes
python mssl_focus.py export em2 --inspection thermal -o map.png      # everything known up to it
python mssl_focus.py export SESSION.json -o map.png                  # a single session, as before
```

Given a folder, the photographs are chosen from its RAW files (TIFF and JPEG copies are ignored): the backlit one with the longest exposure, the latest if several share it, and the frontlit one with the exposure nearest 0.25 s, leaving out dimmer lightings, nearest in sequence to the backlit one. If the standard development turns a dark backlit frame's noise into thousands of spots, it is developed a stop or two darker, and the setting is kept with the inspection.

Adding an inspection lines the frontlit photograph up on the backlit one, turns the filter upright by its frame, finds the outline of the membrane from the frame's opening, and places the inspection on the filter using the pinholes already known. Run any command with `-h` for its options.

Detection takes clear spots, and fainter "likely" ones when they are sharp, bright points on dark membrane: a pinhole is a point of light, while sensor noise in a dark, strongly stretched photograph and the texture of stray-light glow make soft smudges. `--sensitivity 75` takes every likely spot instead, and the window still offers them all for review. A pinhole too faint to tell from noise in one photograph shows as a sharp point at the same place on the filter in its other inspections, which noise and hot pixels do not; `crosscheck` finds those. Repairs are found in the frontlit photograph, where each patch shows as a round white spot, and recorded as repairs; a backlit spot on a patch is that repair letting light through, not a new pinhole.

A map's legend lists every stage checked up to its inspection, with `n=0` where nothing new was found. Where pinholes crowd together their circles shrink, and break where they would cross a neighbour, so every pinhole stays visible.

## Access and Licensing

This software is copyright (c) 2026 James McKevitt, UCL Mullard Space Science Laboratory. All rights reserved.

MSSL FOCUS requires a valid license file (`license.dat`) to run. The first time it starts you will be asked to locate your license file, or enter a master password. The file is remembered and re-checked on later starts; a `license*.dat` placed beside the program is picked up automatically.

To request a license, contact [jm2@mssl.ucl.ac.uk](mailto:jm2@mssl.ucl.ac.uk).

### Running from source (local development)

The software can be run directly from source, when `src/license.py` is present, using:
```bash
python -m src
```

The automated tests need a display but not the license module:
```bash
pip install -e .[test]
python -m pytest tests
```
