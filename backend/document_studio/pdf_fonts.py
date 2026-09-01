"""Cross-platform PDF font bootstrap for Document Studio exports."""
from __future__ import annotations
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
PDF_FONT_NAME = "LuminaUnicode"
PDF_FONT_BOLD_NAME = "LuminaUnicodeBold"
REGULAR_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\segoeui.ttf"), Path(r"C:\Windows\Fonts\calibri.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"), Path("/Library/Fonts/Arial.ttf"), Path.home()/"Library/Fonts/Arial.ttf",
)
BOLD_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\arialbd.ttf"), Path(r"C:\Windows\Fonts\segoeuib.ttf"), Path(r"C:\Windows\Fonts\calibrib.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    Path("/Library/Fonts/Arial Bold.ttf"), Path.home()/"Library/Fonts/Arial Bold.ttf",
)
def _first_existing(candidates):
    return next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)
def _register_builtin_alias(name: str, face_name: str) -> None:
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(pdfmetrics.Font(name, face_name, "WinAnsiEncoding"))
def ensure_pdf_font_aliases() -> dict[str, str | bool | None]:
    regular_path = _first_existing(REGULAR_FONT_CANDIDATES)
    bold_path = _first_existing(BOLD_FONT_CANDIDATES)
    if PDF_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(regular_path))) if regular_path else _register_builtin_alias(PDF_FONT_NAME, "Helvetica")
    if PDF_FONT_BOLD_NAME not in pdfmetrics.getRegisteredFontNames():
        if bold_path:
            pdfmetrics.registerFont(TTFont(PDF_FONT_BOLD_NAME, str(bold_path)))
        elif regular_path:
            pdfmetrics.registerFont(TTFont(PDF_FONT_BOLD_NAME, str(regular_path)))
        else:
            _register_builtin_alias(PDF_FONT_BOLD_NAME, "Helvetica-Bold")
    return {"regular_registered": PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames(), "bold_registered": PDF_FONT_BOLD_NAME in pdfmetrics.getRegisteredFontNames(), "regular_path": str(regular_path) if regular_path else None, "bold_path": str(bold_path) if bold_path else None, "unicode_font_available": regular_path is not None}
