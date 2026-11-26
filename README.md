# MSSL FOCUS

Filter Optical Characterisation Utility Software, developed at UCL Mullard Space Science Laboratory (MSSL).

MSSL FOCUS maps pinholes in thin-film optical filters from a backlit and a frontlit photograph of each filter. It shows the two images side by side or blended, finds pinholes automatically and exports annotated maps. A history file for each filter keeps every inspection and every pinhole found, so a filter can be followed through its tests.

## Download

The executables need no Python installation.

| Platform | Download |
|----------|----------|
| Windows  | [![Download for Windows](https://img.shields.io/github/v/release/jamesmckevitt/mssl_focus?label=Download%20%28Windows%29&color=0078D4&logoColor=white)](https://github.com/jamesmckevitt/mssl_focus/releases/latest/download/mssl_focus.exe) |
| Linux    | [![Download for Linux](https://img.shields.io/github/v/release/jamesmckevitt/mssl_focus?label=Download%20%28Linux%29&color=FCC624&logoColor=black)](https://github.com/jamesmckevitt/mssl_focus/releases/latest/download/mssl_focus) |

The software is developed on Linux, and the Windows executable is tested.

## Features

- Side-by-side and blended views of the backlit and frontlit images, with linked pan and zoom
- A reference row showing an earlier inspection of the same filter, aligned to the current one
- Tools to level the filter, align the images by matching points (with a residual estimate), annotate, move markers and export a region
- Camera RAW files (ARW, NEF, CR2, DNG and others) read directly, with dark-field development and noise reduction for backlit frames
- Automatic pinhole search with a review step, showing spots that are new since the reference inspection first
- Markers numbered per colour, a legend with counts, and undo and redo
- Brightness, contrast, black and white levels for each image
- Export of a region or the whole view at full resolution, with markers, legend and date
- Sessions saved as `.json` files that still open after their folder is moved or renamed
- A history file for each filter that keeps all its inspections (see below)

Press F1 in the application for a step-by-step guide.

## Filter histories and the command line

A history file, for example `em2.json`, holds every inspection of one filter in date order. It also holds every pinhole found in the filter, with a permanent ID such as `I3` or `S1`, the inspection where it was first seen, and whether it was accepted or rejected. Pinholes are stored in filter coordinates, so they carry across inspections. A spot rejected once is skipped when it is found again. The application opens a history like a session, after you pick an inspection, and saves changes back into it.

The command line works without a window. A history is named by its file, or by the filter name for `<name>.json` in the current folder.

```bash
python mssl_focus.py migrate incoming.json shock.json -o em2.json   # build a history from sessions, oldest first
python mssl_focus.py photos 5_thermal_test/em2                      # list the RAW photographs and the ones chosen
python mssl_focus.py add em2 thermal 5_thermal_test/em2              # add an inspection and align it
python mssl_focus.py replace-photos em2 thermal 5_thermal_test/em2   # use other photographs for an inspection
python mssl_focus.py remove em2 thermal                              # remove an inspection and the pinholes first seen in it
python mssl_focus.py detect em2 thermal                              # search an inspection for new pinholes
python mssl_focus.py crosscheck em2                                  # find faint pinholes seen in two or more inspections
python mssl_focus.py reject em2 T4 T7                                # or accept em2 T7
python mssl_focus.py unsure em2 T2 T3                                # labelled T2?, undone with sure em2 T2
python mssl_focus.py show em2 --pinholes
python mssl_focus.py export em2 --inspection thermal -o map.png      # map of every pinhole known up to thermal
python mssl_focus.py export SESSION.json -o map.png                  # map of a single session
```

Run any command with `-h` for its options.

The packaged program takes the same commands, for example `mssl_focus.exe show em2`. The commands need a license, as the window does. The program uses the license file chosen in the window, a `license*.dat` beside the program, or the file named by the `MSSL_FOCUS_LICENSE` environment variable. On Windows the program is a windowed one, so a terminal does not wait for it to finish. Use `start /wait /b mssl_focus.exe ...` in Command Prompt, or `Start-Process -Wait -NoNewWindow mssl_focus.exe ...` in PowerShell.

### Choosing the photographs

Given a folder, the program chooses from its RAW files and ignores TIFF and JPEG copies. The backlit photograph is the one with the longest exposure, or the latest if several share it. The frontlit photograph is the one with the exposure nearest 0.25 s, leaving out dimmer lightings, and the nearest in sequence to the backlit one. A RAW file that cannot be read is listed and left out. If the standard development turns the noise of a dark backlit frame into thousands of spots, the frame is developed a stop or more darker, and the setting is kept with the inspection.

### Alignment and detection

Adding an inspection aligns the frontlit photograph on the backlit one, turns the filter upright using its frame, and takes the outline of the membrane from the opening in the frame. The inspection is then placed on the filter using the pinholes already known.

A pinhole is a point of light. Detection takes clear spots, and fainter spots when they are sharp, bright points on dark membrane. Sensor noise in a dark, strongly stretched photograph and the texture of stray-light glow make soft smudges, which are left out. With `--sensitivity 75` detection takes every fainter spot instead, and the window offers them all for review.

A pinhole too faint to tell from noise in one photograph still shows at the same place on the filter in the other inspections. Noise and hot pixels do not, so `crosscheck` adds such points.

Repairs show in the frontlit photograph as round white patches and are recorded as repairs. A backlit spot on a patch is that repair letting light through, not a new pinhole.

### Maps

A map shows every pinhole known up to its inspection. The legend lists every stage checked so far, with `n=0` where nothing new was found. Where pinholes are close together their circles shrink, and break where they would cross a neighbour, so every pinhole stays visible.

## Access and licensing

Copyright (c) 2026 James McKevitt, UCL Mullard Space Science Laboratory. All rights reserved.

MSSL FOCUS needs a valid license file (`license.dat`) to run. The first time it starts, it asks for the license file or a master password. The file is remembered and checked again on later starts. A `license*.dat` beside the program is found automatically.

To request a license, contact [jm2@mssl.ucl.ac.uk](mailto:jm2@mssl.ucl.ac.uk).

### Running from source

With `src/license.py` present, run the software from source with

```bash
python -m src
```

The tests need a display but not the license module.

```bash
pip install -e .[test]
python -m pytest tests
```
