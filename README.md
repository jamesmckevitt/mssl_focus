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

- Side-by-side and blended overlay view modes
- Pan, zoom, and per-image/global rotation
- Point-based image alignment with guided circle indicator
- Annotation circles with optional floating labels
- Brightness / contrast / blacks / whites adjustment per image
- Crop export - select a canvas region to export a high-resolution side-by-side PNG
- Session save/load - persist all settings, alignment, and annotations to a `.json` file

## Access and Licensing

This software is copyright (c) 2026 James McKevitt, UCL Mullard Space Science Laboratory. All rights reserved.

MSSL FOCUS requires a valid license file (`license.dat`) to run. On startup you will be asked to locate your license file, or enter a master password.

To request a license, contact [jm2@mssl.ucl.ac.uk](mailto:jm2@mssl.ucl.ac.uk).

### Running from source (local development)

The software can be run directly from source, when `src/license.py` is present, using:
```bash
python -m src
```