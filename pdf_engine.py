"""
pdf_engine.py

Core PDF processing engine for PDF Pair Merger.

This module contains every piece of PDF manipulation logic used by the
application. It is completely decoupled from the GUI layer (``gui.py``) so
it can be tested, reused, or scripted independently.

The central idea implemented here is "pair merging": given an ordered list
of input PDF files, the files are grouped two-by-two (A+B, C+D, E+F, ...).
For every pair, a new output sheet is created for every page index that
exists in either of the two source documents. The left half of the sheet
receives the corresponding page from the first document of the pair, the
right half receives the corresponding page from the second document. If a
pair has an odd number of PDFs left over (or the user supplies a single
PDF), the last document is paired with an empty "virtual" document, so its
right half is simply left blank. If one document in a pair has fewer pages
than the other, the missing half is left blank for the extra pages.

All page content is copied as vector data via ``fitz.Page.show_pdf_page``,
never rasterized, which keeps text selectable/searchable and images at
full resolution in the output file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Tuple

import fitz  # PyMuPDF


# --------------------------------------------------------------------------
# Constants & unit helpers
# --------------------------------------------------------------------------

#: Conversion factor from millimeters to PDF points (1 inch = 25.4 mm = 72 pt).
MM_TO_POINTS: float = 72.0 / 25.4


def mm_to_pt(value_mm: float) -> float:
    """Convert a length expressed in millimeters to PDF points.

    Args:
        value_mm: A length in millimeters.

    Returns:
        The equivalent length in PDF points (1/72 inch).
    """
    return value_mm * MM_TO_POINTS


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class PaperSize(str, Enum):
    """Supported output paper sizes.

    Values are the human-readable labels shown in the GUI and are also
    used as the on-disk / config representation, so they must stay stable.
    """

    A4 = "A4"
    A3 = "A3"
    LETTER = "Letter"
    LEGAL = "Legal"

    @property
    def portrait_dimensions_mm(self) -> Tuple[float, float]:
        """Return the (width_mm, height_mm) of this paper size in PORTRAIT orientation."""
        sizes_mm = {
            PaperSize.A4: (210.0, 297.0),
            PaperSize.A3: (297.0, 420.0),
            PaperSize.LETTER: (215.9, 279.4),
            PaperSize.LEGAL: (215.9, 355.6),
        }
        return sizes_mm[self]

    @property
    def portrait_dimensions_pt(self) -> Tuple[float, float]:
        """Return the (width_pt, height_pt) of this paper size in PORTRAIT orientation."""
        width_mm, height_mm = self.portrait_dimensions_mm
        return mm_to_pt(width_mm), mm_to_pt(height_mm)


class Orientation(str, Enum):
    """Output page orientation."""

    LANDSCAPE = "Landscape"
    PORTRAIT = "Portrait"


class ScaleMode(str, Enum):
    """How a source page is fitted into its half of the output sheet."""

    FIT = "Fit"
    FIT_SHRINK_ONLY = "Fit (shrink only)"
    ACTUAL_SIZE = "Actual Size"


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class MergeError(Exception):
    """Raised for any recoverable, user-facing error during the merge process."""


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

@dataclass
class MergeSettings:
    """All user-configurable settings that control how the output PDF is built."""

    paper_size: PaperSize = PaperSize.A4
    orientation: Orientation = Orientation.LANDSCAPE
    gap_mm: float = 10.0
    margin_mm: float = 10.0
    scale_mode: ScaleMode = ScaleMode.FIT
    output_path: str = ""

    def page_dimensions_pt(self) -> Tuple[float, float]:
        """Compute the final (width_pt, height_pt) of an output page.

        The paper size is always defined in portrait terms; this method
        swaps width/height when landscape orientation is requested.
        """
        width_pt, height_pt = self.paper_size.portrait_dimensions_pt
        if self.orientation == Orientation.LANDSCAPE:
            return max(width_pt, height_pt), min(width_pt, height_pt)
        return min(width_pt, height_pt), max(width_pt, height_pt)

    def validate(self) -> None:
        """Validate numeric settings, raising :class:`MergeError` on problems."""
        if self.gap_mm < 0:
            raise MergeError("Gap must be zero or a positive number.")
        if self.margin_mm < 0:
            raise MergeError("Margins must be zero or a positive number.")
        if not self.output_path:
            raise MergeError("Please choose an output file name.")


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def _compute_fit_rect(cell: fitz.Rect, src_width: float, src_height: float, shrink_only: bool) -> fitz.Rect:
    """Compute the destination rectangle for a source page scaled to fit inside ``cell``.

    The aspect ratio of the source page is always preserved; the resulting
    rectangle is centered horizontally and vertically within ``cell``.

    Args:
        cell: The target half-page rectangle (in destination page coordinates).
        src_width: Width of the source page, in points.
        src_height: Height of the source page, in points.
        shrink_only: If True, the source page is never scaled up beyond 100%
            (small pages keep their real size instead of being stretched to
            fill the cell). If False, the page is always scaled to fully
            fit the cell (up or down) while preserving its aspect ratio.

    Returns:
        A :class:`fitz.Rect` describing where and at what size the source
        page should be drawn.
    """
    if src_width <= 0 or src_height <= 0 or cell.width <= 0 or cell.height <= 0:
        return cell

    scale = min(cell.width / src_width, cell.height / src_height)
    if shrink_only:
        scale = min(scale, 1.0)

    draw_width = src_width * scale
    draw_height = src_height * scale

    dest_x0 = cell.x0 + (cell.width - draw_width) / 2.0
    dest_y0 = cell.y0 + (cell.height - draw_height) / 2.0
    return fitz.Rect(dest_x0, dest_y0, dest_x0 + draw_width, dest_y0 + draw_height)


def _compute_actual_size_layout(
    cell: fitz.Rect, src_rect: fitz.Rect
) -> Tuple[fitz.Rect, Optional[fitz.Rect]]:
    """Compute placement for drawing a source page at true 100% scale, centered in ``cell``.

    If the source page is larger than ``cell`` in either dimension, it is
    center-cropped (never scaled) so the visible portion fits exactly
    within the cell.

    Args:
        cell: The target half-page rectangle (in destination page coordinates).
        src_rect: The source page's own rectangle (``page.rect``).

    Returns:
        A tuple ``(dest_rect, clip_rect)`` where ``dest_rect`` is where the
        content is drawn on the destination page and ``clip_rect`` is the
        (possibly ``None``) sub-rectangle of the source page to display, in
        the source page's own coordinate space.
    """
    src_width, src_height = src_rect.width, src_rect.height
    draw_width = min(src_width, cell.width)
    draw_height = min(src_height, cell.height)

    dest_x0 = cell.x0 + (cell.width - draw_width) / 2.0
    dest_y0 = cell.y0 + (cell.height - draw_height) / 2.0
    dest_rect = fitz.Rect(dest_x0, dest_y0, dest_x0 + draw_width, dest_y0 + draw_height)

    if draw_width < src_width or draw_height < src_height:
        clip_x0 = src_rect.x0 + (src_width - draw_width) / 2.0
        clip_y0 = src_rect.y0 + (src_height - draw_height) / 2.0
        clip_rect: Optional[fitz.Rect] = fitz.Rect(
            clip_x0, clip_y0, clip_x0 + draw_width, clip_y0 + draw_height
        )
    else:
        clip_rect = None

    return dest_rect, clip_rect


# --------------------------------------------------------------------------
# Progress reporting
# --------------------------------------------------------------------------

#: Signature: (sheets_done, sheets_total, status_message) -> None
ProgressCallback = Callable[[int, int, str], None]


# --------------------------------------------------------------------------
# Main engine
# --------------------------------------------------------------------------

class PDFPairMerger:
    """Builds a single output PDF from a list of input PDFs, placing pairs of pages side by side."""

    def __init__(self, settings: MergeSettings) -> None:
        """Create a merger bound to a specific set of :class:`MergeSettings`.

        Args:
            settings: The output configuration (paper size, orientation,
                margins, gap, scale mode, output path).
        """
        self.settings = settings

    # -- public API --------------------------------------------------------

    def merge(self, input_paths: List[str], progress_cb: Optional[ProgressCallback] = None) -> str:
        """Merge the given PDF files in pairs and write the result to disk.

        Args:
            input_paths: Ordered list of paths to source PDF files. Files
                are paired sequentially: (0, 1), (2, 3), (4, 5), ... If the
                list has an odd length, the last file is paired with a
                blank half-page.
            progress_cb: Optional callback invoked after every output sheet
                is generated, as ``progress_cb(done, total, message)``.

        Returns:
            The absolute path to the generated PDF file.

        Raises:
            MergeError: For any recoverable, user-facing problem (missing
                files, corrupt/encrypted PDFs, invalid settings, no pages
                to merge, etc).
        """
        self.settings.validate()

        if not input_paths:
            raise MergeError("Please add at least one PDF file to merge.")

        for path in input_paths:
            if not os.path.isfile(path):
                raise MergeError(f"File not found: {path}")

        opened_docs: List[fitz.Document] = []
        out_doc: Optional[fitz.Document] = None
        try:
            for path in input_paths:
                opened_docs.append(self._open_document(path))

            pairs = self._build_pairs(opened_docs)
            total_sheets = sum(self._sheet_count_for_pair(left, right) for left, right in pairs)

            if total_sheets == 0:
                raise MergeError("The selected PDF files do not contain any pages.")

            page_width, page_height = self.settings.page_dimensions_pt()
            left_cell, right_cell = self._compute_cells(page_width, page_height)

            out_doc = fitz.open()
            sheets_done = 0

            for left_doc, right_doc in pairs:
                sheet_count = self._sheet_count_for_pair(left_doc, right_doc)
                for page_index in range(sheet_count):
                    out_page = out_doc.new_page(width=page_width, height=page_height)
                    self._place_page(out_page, left_doc, page_index, left_cell)
                    if right_doc is not None:
                        self._place_page(out_page, right_doc, page_index, right_cell)

                    sheets_done += 1
                    if progress_cb is not None:
                        progress_cb(
                            sheets_done,
                            total_sheets,
                            f"Building sheet {sheets_done} of {total_sheets}...",
                        )

            self._save_output(out_doc)
            return os.path.abspath(self.settings.output_path)

        finally:
            if out_doc is not None:
                out_doc.close()
            for doc in opened_docs:
                try:
                    doc.close()
                except Exception:
                    pass

    # -- internal helpers ----------------------------------------------------

    @staticmethod
    def _open_document(path: str) -> fitz.Document:
        """Open a single PDF file, raising :class:`MergeError` on any failure."""
        filename = os.path.basename(path)
        try:
            doc = fitz.open(path)
        except Exception as exc:
            raise MergeError(f"Failed to open '{filename}': {exc}") from exc

        if doc.is_encrypted:
            if not doc.authenticate(""):
                doc.close()
                raise MergeError(
                    f"'{filename}' is password-protected. Please remove the "
                    f"password before merging."
                )

        if doc.page_count == 0:
            doc.close()
            raise MergeError(f"'{filename}' contains no pages.")

        return doc

    @staticmethod
    def _build_pairs(
        docs: List[fitz.Document],
    ) -> List[Tuple[fitz.Document, Optional[fitz.Document]]]:
        """Group an ordered list of open documents into consecutive pairs.

        If the list has an odd number of documents, the final pair's second
        element is ``None``, meaning that half of the sheet stays blank.
        """
        pairs: List[Tuple[fitz.Document, Optional[fitz.Document]]] = []
        index = 0
        while index < len(docs):
            left = docs[index]
            right = docs[index + 1] if index + 1 < len(docs) else None
            pairs.append((left, right))
            index += 2
        return pairs

    @staticmethod
    def _sheet_count_for_pair(left: fitz.Document, right: Optional[fitz.Document]) -> int:
        """Number of output sheets required for one pair (max of the two page counts)."""
        right_count = right.page_count if right is not None else 0
        return max(left.page_count, right_count)

    def _compute_cells(self, page_width: float, page_height: float) -> Tuple[fitz.Rect, fitz.Rect]:
        """Compute the left/right half-page destination rectangles for the current settings.

        Raises:
            MergeError: If the requested margins and gap leave no usable
                space on the page.
        """
        margin = mm_to_pt(self.settings.margin_mm)
        gap = mm_to_pt(self.settings.gap_mm)

        usable_width = page_width - (2 * margin) - gap
        usable_height = page_height - (2 * margin)

        if usable_width <= 0 or usable_height <= 0:
            raise MergeError(
                "The chosen margins and gap are too large for the selected "
                "paper size and orientation. Please reduce them."
            )

        half_width = usable_width / 2.0

        left_cell = fitz.Rect(margin, margin, margin + half_width, margin + usable_height)
        right_cell = fitz.Rect(
            margin + half_width + gap,
            margin,
            margin + half_width + gap + half_width,
            margin + usable_height,
        )
        return left_cell, right_cell

    def _place_page(
        self, out_page: fitz.Page, src_doc: fitz.Document, page_index: int, cell: fitz.Rect
    ) -> None:
        """Draw a single source page (if it exists) into a destination cell.

        If ``page_index`` is beyond the end of ``src_doc``, the cell is left
        blank, satisfying the "leave that half blank" requirement.
        """
        if page_index >= src_doc.page_count:
            return

        src_page = src_doc[page_index]
        src_rect = src_page.rect
        if src_rect.width <= 0 or src_rect.height <= 0:
            return

        if self.settings.scale_mode == ScaleMode.ACTUAL_SIZE:
            dest_rect, clip_rect = _compute_actual_size_layout(cell, src_rect)
            out_page.show_pdf_page(
                dest_rect,
                src_doc,
                page_index,
                clip=clip_rect,
                keep_proportion=True,
            )
        else:
            shrink_only = self.settings.scale_mode == ScaleMode.FIT_SHRINK_ONLY
            dest_rect = _compute_fit_rect(cell, src_rect.width, src_rect.height, shrink_only)
            out_page.show_pdf_page(dest_rect, src_doc, page_index, keep_proportion=True)

    def _save_output(self, out_doc: fitz.Document) -> None:
        """Persist the generated document to :attr:`MergeSettings.output_path`."""
        output_path = self.settings.output_path
        output_dir = os.path.dirname(os.path.abspath(output_path))
        try:
            if output_dir and not os.path.isdir(output_dir):
                os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            raise MergeError(f"Could not create output folder: {exc}") from exc

        try:
            out_doc.save(output_path, garbage=4, deflate=True)
        except Exception as exc:
            raise MergeError(f"Failed to save output PDF: {exc}") from exc
