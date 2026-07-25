# PDF Pair Merger

A desktop application that combines any number of PDF files into a single,
print-ready PDF by placing **two source pages side by side on every output
sheet**.

Instead of stacking PDFs one after another, PDF Pair Merger processes your
files **in pairs**:

```
PDF A: A1 A2 A3
PDF B: B1 B2 B3

Output:
  Sheet 1:  [A1] [B1]
  Sheet 2:  [A2] [B2]
  Sheet 3:  [A3] [B3]
```

With more than two files, the files are grouped two at a time, in the
order you arrange them:

```
Files:  A  B  C  D  E  F

Sheet 1: A1 | B1        Sheet 4: C2 | D2
Sheet 2: A2 | B2        Sheet 5: E1 | F1
Sheet 3: C1 | D1        Sheet 6: E2 | F2
```

If you select an odd number of PDFs, the last one is paired with a blank
half-page. If one PDF in a pair is longer than the other, the shorter
one's missing pages simply leave that half of the sheet blank.

All page content is copied as **vector data** (via PyMuPDF's
`show_pdf_page`) — nothing is rasterized, so text stays sharp, selectable
and searchable, and images keep their original resolution.

---

## Features

- Add any number of PDFs, in any order, via a file dialog or drag & drop.
- Reorder files (Move Up / Move Down) and remove files from the queue.
- Choose paper size (A4, A3, Letter, Legal) and orientation
  (Landscape / Portrait).
- Configure the gap between the two halves and the page margins, in
  millimeters.
- Three scaling modes: **Fit** (scale up or down to fill the half-page),
  **Fit (shrink only)** (never enlarges small pages), and **Actual Size**
  (100% scale, center-cropped if the source page is larger than its half).
- Pages are always centered within their half and never stretched —
  aspect ratio is preserved.
- Background processing with a live progress bar and status messages, so
  the window never freezes on large jobs.
- Remembers your last output folder, paper size, orientation, margins,
  gap, scale mode, and window size between runs (`config.json`).
- Modern dark-themed interface built with CustomTkinter.

---

## Requirements

- Python 3.12+ (the code is compatible with Python 3.9+, but 3.12+ is the
  targeted/tested version).
- A desktop environment with Tk available (on most Linux distributions
  this means the `python3-tk` system package must be installed — see
  Troubleshooting below).

---

## Installation

1. **Clone or download** the project files into a folder, e.g. `pdf-pair-merger/`:
   ```
   pdf-pair-merger/
   ├── main.py
   ├── gui.py
   ├── pdf_engine.py
   ├── requirements.txt
   └── README.md
   ```

2. **(Recommended) Create a virtual environment:**
   ```bash
   python3 -m venv venv

   # Windows
   venv\Scripts\activate

   # macOS / Linux
   source venv/bin/activate
   ```

3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application:**
   ```bash
   python main.py
   ```

The app window should open immediately — no further setup is required.

---

## Dependencies

| Package        | Purpose                                                              |
|----------------|-----------------------------------------------------------------------|
| `PyMuPDF`      | Reads source PDFs and writes the merged output as vector content.    |
| `customtkinter`| Provides the modern, dark-themed widgets used throughout the GUI.    |
| `tkinterdnd2`  | *(Optional)* Enables dragging PDF files onto the window to add them. |

If `tkinterdnd2` cannot be installed on your platform, simply remove it
from `requirements.txt`/skip it — the application detects its absence at
startup and disables drag & drop only, everything else (including
"+ Add PDFs") continues to work normally.

---

## Usage

1. Click **"+ Add PDFs"** (or drag PDF files onto the left panel) to add
   your source files. Each entry shows its filename and page count.
2. Select a file in the list and use **↑ Move Up** / **↓ Move Down** to
   reorder, or **✖ Remove** to delete it from the queue. Files are always
   paired in the order shown: 1st+2nd, 3rd+4th, 5th+6th, and so on.
3. In **Layout Settings**, choose:
   - **Paper Size** — A4, A3, Letter, or Legal.
   - **Orientation** — Landscape (default, recommended for side-by-side
     pages) or Portrait.
   - **Gap (mm)** — spacing between the two halves of each sheet.
   - **Margins (mm)** — spacing around the outer edge of each sheet.
   - **Scale** — how source pages are fitted into their half
     (Fit / Fit (shrink only) / Actual Size).
4. Under **Output File**, type a path or click **Browse** to choose where
   the merged PDF should be saved.
5. Click **Generate PDF**. Progress is shown in the progress bar and
   status line; a confirmation dialog appears when the file has been
   created (or an error dialog explains what went wrong).

### Example

Merging `Invoice.pdf` (3 pages) and `Terms.pdf` (3 pages) with default
settings (A4, Landscape, 10 mm gap and margins, Fit) produces a 3-page
`merged_output.pdf`, where every sheet shows one invoice page on the left
and the matching terms page on the right — ready to print.

---

## Configuration file

PDF Pair Merger stores your preferences in:

- **Windows:** `C:\Users\<you>\.pdf_pair_merger\config.json`
- **macOS / Linux:** `~/.pdf_pair_merger/config.json`

It remembers: last output directory, paper size, orientation, gap,
margins, scale mode, and window size. Delete this file (or its parent
folder) at any time to reset the app to its defaults; it will be
recreated automatically the next time you save settings.

---

## Building an executable with PyInstaller

You can package PDF Pair Merger as a standalone executable so it can run
on a machine without Python installed.

1. Install PyInstaller into the same environment:
   ```bash
   pip install pyinstaller
   ```

2. From the project folder, build a one-folder application:
   ```bash
   pyinstaller --noconfirm --windowed --name PDFPairMerger main.py
   ```
   - `--windowed` prevents a console window from appearing alongside the
     GUI (Windows/macOS).
   - The result is created in `dist/PDFPairMerger/`. Distribute the whole
     folder — it contains the executable plus all required libraries and
     assets (including CustomTkinter's theme/asset files and, if
     installed, tkinterdnd2's native drag-and-drop library).

3. **Optional: single-file executable.** If you prefer one `.exe` /
   binary file instead of a folder, use `--onefile` instead of the
   default one-folder mode:
   ```bash
   pyinstaller --noconfirm --windowed --onefile --name PDFPairMerger main.py
   ```
   One-file builds take a bit longer to start (they unpack to a temp
   folder on every launch), but are easier to distribute as a single file.

4. **If PyInstaller does not automatically find CustomTkinter's assets or
   tkinterdnd2's native library** (this can happen with older
   `pyinstaller-hooks-contrib` versions), add explicit collection flags:
   ```bash
   pyinstaller --noconfirm --windowed --name PDFPairMerger ^
       --collect-data customtkinter ^
       --collect-all tkinterdnd2 ^
       main.py
   ```
   (Use `\` instead of `^` for line continuation on macOS/Linux.)

5. Run the generated executable from `dist/PDFPairMerger/` (or the single
   file produced by `--onefile`) to verify it launches correctly before
   distributing it.

The `config.json` preferences file is written to the user's home
directory regardless of whether the app is run from source or as a
frozen executable, so settings persist across both.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'tkinter'` (Linux)**
Tk is a system-level package on Linux and is not installed by `pip`.
Install it with your package manager, e.g.:
```bash
sudo apt-get install python3-tk      # Debian/Ubuntu
sudo dnf install python3-tkinter     # Fedora
sudo pacman -S tk                    # Arch
```

**Drag & drop does not work / app starts without it**
This is expected if `tkinterdnd2` is not installed, or if its native
`tkdnd` library isn't available for your OS/architecture (this can happen
on some ARM-based Linux systems). The application detects this
automatically at startup and simply disables drag & drop — use the
**"+ Add PDFs"** button instead, which always works.

**"The chosen margins and gap are too large for the selected paper size"**
Your margins + gap leave no usable space on the page. Reduce the gap
and/or margin values, or switch to a larger paper size.

**A password-protected PDF fails to open**
PDF Pair Merger can open PDFs with an *empty* owner/user password
automatically, but cannot merge files protected with an actual password.
Remove the password from the source file first (e.g. with your PDF
reader's "Save a copy without security" feature) and try again.

**One half of a sheet is blank**
This is expected when: (a) you selected an odd number of PDFs, so the
last file is paired with a blank page, or (b) the two PDFs in a pair have
different page counts, so the shorter document has no more pages to place
on that sheet.

**The generated PDF looks blurry when zoomed in**
It shouldn't — pages are embedded as vector content (`show_pdf_page`),
never rasterized. If a *source* PDF itself contains a scanned/rasterized
image, that page will look exactly as sharp (or blurry) as it did in the
original file.

**The app window doesn't remember my last settings**
Preferences are saved when you close the app window or after a
successful merge. Make sure the app has permission to write to your home
directory (`~/.pdf_pair_merger/config.json`), and that you're closing the
app via the window's close button rather than force-killing the process.

---

## Project structure

```
pdf-pair-merger/
├── main.py          # Application entry point
├── gui.py            # CustomTkinter GUI (presentation & interaction only)
├── pdf_engine.py      # PDF merge logic (PyMuPDF), no GUI dependencies
├── requirements.txt   # Runtime dependencies
└── README.md          # This file
```

`pdf_engine.py` has no dependency on `gui.py` or Tkinter, so it can also
be imported and used directly from your own scripts, e.g.:

```python
from pdf_engine import MergeSettings, PDFPairMerger, PaperSize, Orientation, ScaleMode

settings = MergeSettings(
    paper_size=PaperSize.A4,
    orientation=Orientation.LANDSCAPE,
    gap_mm=10,
    margin_mm=10,
    scale_mode=ScaleMode.FIT,
    output_path="merged.pdf",
)
PDFPairMerger(settings).merge(["A.pdf", "B.pdf", "C.pdf"])
```

---

## License

This project is provided as-is. Add your preferred license (e.g. MIT)
before distributing it.
