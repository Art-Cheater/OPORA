"""Приведение договоров к .docx: LibreOffice или Word на Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from app.core.exceptions import ValidationError

_SOFFICE_NAMES = ("soffice", "soffice.exe", "libreoffice")
_WIN_SOFFICE = (
    Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
)
_CONVERTIBLE = frozenset({"doc", "rtf", "odt", "pdf", "ott", "dot", "dotx", "wps"})


def office_kind(path: Path) -> str:
    """docx / odt / doc / rtf / pdf — по сигнатуре, иначе по расширению."""

    header = path.read_bytes()[:8]
    suffix = path.suffix.lower().lstrip(".")
    if header.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return suffix or "unknown"
        if "word/document.xml" in names:
            return "docm" if suffix == "docm" else "docx"
        if "content.xml" in names:
            return "odt"
        return suffix or "zip"
    if header.startswith(b"%PDF"):
        return "pdf"
    if header.startswith(b"{\\rtf"):
        return "rtf"
    if header.startswith(b"\xd0\xcf\x11\xe0"):
        return "doc"
    return suffix or "unknown"


def soffice_binary() -> Path | None:
    for name in _SOFFICE_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    if os.name == "nt":
        for candidate in _WIN_SOFFICE:
            if candidate.is_file():
                return candidate
    return None


def to_docx_path(source: Path) -> Path:
    """Конвертирует файл в .docx рядом во временной папке. Возвращает путь к результату."""

    kind = office_kind(source)
    if kind in {"docx", "docm"}:
        return source
    if kind not in _CONVERTIBLE and source.suffix.lower() not in {f".{item}" for item in _CONVERTIBLE}:
        raise ValidationError(
            f"Формат «.{source.suffix.lstrip('.') or kind}» не читается. "
            "Нужен Word (.doc/.docx), OpenDocument (.odt), RTF или PDF."
        )

    converted = _convert_with_soffice(source)
    if converted is None:
        converted = _convert_with_word(source)
    if converted is None:
        raise ValidationError(
            "Этот формат сам по себе не читается (.doc, .rtf, PDF). "
            "На сервере нужен LibreOffice — или сохраните договор как .docx."
        )
    return converted


def _convert_with_soffice(source: Path) -> Path | None:
    binary = soffice_binary()
    if binary is None:
        return None
    out_dir = Path(tempfile.mkdtemp(prefix="opora-office-"))
    env = os.environ.copy()
    env.setdefault("HOME", str(out_dir))
    env.setdefault("SAL_USE_VCLPLUGIN", "svp")
    try:
        completed = subprocess.run(
            [
                str(binary),
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--convert-to",
                "docx:Office Open XML Text",
                "--outdir",
                str(out_dir),
                str(source.resolve()),
            ],
            check=False,
            capture_output=True,
            timeout=90,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        shutil.rmtree(out_dir, ignore_errors=True)
        return None
    produced = list(out_dir.glob("*.docx"))
    if completed.returncode != 0 or not produced:
        shutil.rmtree(out_dir, ignore_errors=True)
        return None
    return produced[0]


def _convert_with_word(source: Path) -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return None
    out_dir = Path(tempfile.mkdtemp(prefix="opora-word-"))
    target = out_dir / (source.stem + ".docx")
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(str(source.resolve()), ReadOnly=True)
        document.SaveAs(str(target), FileFormat=16)
        return target if target.is_file() else None
    except Exception:
        shutil.rmtree(out_dir, ignore_errors=True)
        return None
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
