# PDF Workbench

[日本語](README.md) | **English**

For an illustrated walkthrough and a two-page sample PDF, see the [Japanese quick start](docs/QUICK_START_JA.md).

A desktop GUI for preparing PDF pages for external OCR, then restoring a searchable OCR-result PDF to the source page layout. PDF Workbench handles the **split / restore** steps, not OCR itself.

## What the current GUI does

- Open a PDF, browse page thumbnails, and configure each page independently.
- Start new pages with **Custom split / one region**. Split a selected region horizontally or vertically, drag a red divider, delete a divider or merge eligible rectangular selections, and adjust the OCR output order.
- Use **頁全体を4分割** and **分割なし（1領域）** as quick presets; continue editing the resulting Custom layout. The old standalone `No split`, `Horizontal 2 split`, and `4 split` editor modes are no longer shown.
- Manually apply the current layout to specified pages, selected thumbnails, or all pages. A page lock excludes other pages from bulk replacement without preventing direct edits on the currently displayed page.
- Select multiple thumbnails with ⌘-click / Shift-click. After a manual edit is completed in the central preview, its resulting layout is copied to the selected, unlocked pages **when the displayed page is also selected**. Merely selecting thumbnails or navigating does not change layouts. A grouped manual change can be undone/redone together.
- Use the separate **自動分割** tab to look for whitespace divisions in the selected region, current page, specified page range, or selected pages. Automatic batch processing analyzes each target page separately rather than copying the preview layout. Sensitivity, maximum regions, and optional balancing are adjustable; manual inspection and correction remain important.
- Export an OCR Bundle, resume editing from an existing Bundle, or update that Bundle after further adjustments. Restore an externally OCRed, searchable PDF to the original page dimensions and region positions.

The original PDF is not modified by opening, editing, or exporting it.

## Requirements and setup (macOS-focused)

- Python 3.10 or later
- PyMuPDF, Pillow, PySide6

For the first run, open Terminal and clone the repository. Create a virtual environment, install the package and dependencies, then launch the GUI:

```bash
git clone https://github.com/brontelandscape54-ops/pdf-workbench-public.git
cd pdf-workbench-public
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m pdf_workbench
```

The final `python3 -m pdf_workbench` command **opens the GUI**. The application is currently distributed as Python source, not as a double-clickable macOS `.app` bundle.

### Launching the GUI on subsequent occasions

Open Terminal, return to the same `pdf-workbench-public` directory, then run:

```bash
source .venv/bin/activate
python3 -m pdf_workbench
```

You do not need to reinstall the package on every launch. Alternatively, run `./.venv/bin/python -m pdf_workbench` from the repository directory without activating the environment. Installing `requirements.txt` alone only installs listed dependencies (including pytest); installing the application itself requires `python3 -m pip install -e .`.

## Running the tests

After the editable installation, install the test dependency with `python3 -m pip install 'pytest>=8,<9'`, then run `python3 -m pytest`. GUI verification requires a graphical desktop environment.

On September 22, 2026, the release candidate was installed in a fresh virtual environment on macOS (Apple Silicon) with Python 3.10.4, PyMuPDF 1.28.2, PySide6 6.11.2, Pillow 12.3.0, and pytest 8.4.2. **All 94 automated tests passed (five deprecation warnings)**, and the GUI launched on the test machine. An end-to-end run with an external OCR application was **not** part of this verification; results on other platforms have not been confirmed.

## Working with pages

1. Choose **Open PDF…** and select the page to edit in the left thumbnail list. The manual controls are on the **手動・出力** tab.
2. Select a region in the central preview and use **上下に分割（横線）** or **左右に分割（縦線）**. Drag the red dividers to adjust their positions. The 4-region and 1-region presets provide convenient starting points.
3. Check the numbered OCR reading order. Select a contiguous sequence of numbered regions and use **選択領域の順番を振り直す** to click them in the desired order. Undo/Redo are available in the Edit menu and via ⌘Z / the platform redo shortcut.
4. For page-specific exceptions, adjust the individual page. To copy the same manually edited layout across pages, select their thumbnails and edit the displayed, selected page; alternatively use the explicit page-range/selection/all-page copy buttons. Fixed target pages are omitted from bulk application.
5. Optionally use the **自動分割** tab for content-based division, then inspect and correct page layouts in the manual tab.
6. Choose the overlap, export DPI, JPEG quality, color/grayscale, and whether to include the source PDF in the Bundle. New sessions default to **color**.
7. Choose **Export for OCR…**. The current GUI is OCR-Bundle-oriented: the older standalone **Export PDF…** button is hidden, although its implementation remains in the code.

The page-range field accepts individual pages and ranges, including periodic ranges such as `4,11-60/7`. A lock protects a page from bulk changes; it does not prohibit directly editing that page.

For exact multi-selection semantics, see [docs/multi-page-edit.md](docs/multi-page-edit.md).

## OCR Bundle and round trip

```text
source PDF
  ↓ PDF Workbench: Export for OCR…
<source>_ocr_bundle/
├── manifest.json
├── workspace.json
├── <source>_split_for_ocr.pdf
└── README.txt
  ↓ external OCR application (preserve page count and order)
searchable OCR-result PDF
  ↓ PDF Workbench: Restore OCR Results…
original-layout searchable PDF
```

The Bundle contains the split PDF for external OCR and the geometry/ordering metadata needed for reconstruction. `workspace.json` stores editing-session information, including a source-PDF path, current page, locked pages, and export/automatic-split settings. If requested, `source/original.pdf` is also included.

**To resume editing:** choose **Open OCR Bundle…** and select the Bundle directory. The application uses the original PDF (or its optional embedded copy) to display the pages and checks candidate source files against the recorded SHA-256. If the source was moved, it prompts for a file. A Bundle made before `workspace.json` was introduced can still supply layouts through its manifest, but does not restore the missing session details.

**To update a Bundle:** after editing, choose **Export for OCR…** and select the same parent folder. If the named Bundle already exists, confirm the update. Workbench-generated files are replaced with the current split PDF and metadata; additional files, such as independently saved OCR results or notes, are carried forward. **An OCR result produced from an earlier split PDF may no longer match the updated manifest.** If the split layout or output page ordering changed, run OCR again on the newly exported split PDF before restoring.

**To restore:** run any external OCR tool on the Bundle's `*_split_for_ocr.pdf`, save its result as a searchable PDF without inserting, deleting, or reordering pages, then select **Restore OCR Results…** and provide the Bundle and OCR-result PDF. The original source PDF is not required for this restoration step. PDF Workbench imports the OCR-result PDF page content without intentionally rasterizing it again; searchable text is retained where the external OCR output and clipped regions permit.

### v1 compatibility and limits

Whole-page uniform scaling, DPI changes, recompression, and grayscale conversion can work if each split page's normalized geometry is preserved. Restoration **does not support** OCR tools that crop page boundaries, add unequal margins, rotate pages, apply arbitrary deskew/affine transformations, or change page count or order.

Overlap can reduce clipped characters during OCR, but restoration keeps only the non-overlapping ownership area of each region. OCR text spanning a boundary may therefore be cut; position split lines in whitespace where practical.

The `manifest.json` and `workspace.json` are **independently versioned**, and both currently use version 1. Historic fixed-mode layouts remain readable and are converted to editable Custom layouts in memory; simply opening an older Bundle does not rewrite its manifest. See [docs/bundle-schema-migrations.md](docs/bundle-schema-migrations.md).

**Before sharing a Bundle**, review its contents: `workspace.json` contains an absolute local path to the original PDF, and an optional embedded `source/original.pdf` contains the source document itself. The manifest is designed not to record the original absolute path.

## Background

PDF Workbench was developed from the concept of [ocr-pdf-cut-to-four](https://github.com/brontelandscape54-ops/ocr-pdf-cut-to-four), a separate command-line tool for splitting two-column PDFs into four OCR-friendly pages. PDF Workbench adds visual, per-page Custom splitting and reversible placement of the externally OCRed PDF. It is a separate project, not a Git-history continuation of the earlier CLI. No particular OCR engine is required.

## Project structure

- `src/pdf_workbench/core/`: split tree, geometry, page-range parsing, auto-split analysis, Bundle/manifest/workspace handling, and OCR-result restoration. The Core is independent of the GUI.
- `src/pdf_workbench/gui/`: page preview, thumbnail navigation, manual and automatic editing controls, Bundle update/resume, locking, multi-page editing, and contextual help.
- `tests/`: automated tests for Core behavior and selected GUI workflows.

This is still a development workbench, not a general-purpose PDF editor. Features such as PDF page deletion, rotation, arbitrary document merging, and embedded OCR execution are not part of the current workflow.

## License

The project's original code is intended to be distributed under **AGPL-3.0-or-later**; see `LICENSE` in the public distribution for the full license text. PyMuPDF, PySide6 and Pillow are third-party dependencies under their respective licenses. If redistributing or incorporating those libraries, review the applicable notice and distribution requirements for your chosen packaging method.
