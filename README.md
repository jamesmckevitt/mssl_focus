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

Press **F1** in the application for a step-by-step guide.

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
