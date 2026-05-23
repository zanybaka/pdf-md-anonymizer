"""Post-install smoke test for the pdf-to-markdown backend."""

from __future__ import annotations

from pathlib import Path


def _minimal_pdf() -> bytes:
    """Build a tiny well-formed single-page PDF in pure bytes.

    Used only for the post-install smoke test, so generating it deterministically
    in code keeps the repo free of binary fixtures and the byte offsets honest
    no matter what Python writes the bytes.
    """
    body_objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length 44>>\nstream\nBT /F1 12 Tf 100 700 Td (Hello World) Tj ET\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(body_objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    n = len(body_objects) + 1
    out += b"xref\n" + f"0 {n}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n" + f"<</Size {n}/Root 1 0 R>>\n".encode()
    out += b"startxref\n" + f"{xref_offset}\n".encode() + b"%%EOF\n"
    return out


def _smoke_test(prefix: Path) -> tuple[bool, str]:
    """Run ``pdf2md`` on a tiny embedded PDF; return ``(ok, reason)``.

    A 120-second timeout is generous enough for model load on first use yet
    short enough that a hung subprocess does not freeze the Update flow.
    The reason string is included in the result for surfacing to the user
    (e.g. ``"MPS float64"`` vs ``"timeout"`` vs ``"exit 1"``).
    """
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    script = prefix / "bin" / "pdf2md"
    if not script.is_file():
        return False, "pdf2md script missing"
    pdf_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
    try:
        pdf_path.write_bytes(_minimal_pdf())
        try:
            proc = subprocess.run(
                [str(script), str(pdf_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except OSError as exc:
            return False, f"spawn failed: {exc}"
        if proc.returncode == 0:
            return True, "ok"
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        reason = (
            "MPS float64"
            if "float64" in tail[0] and "MPS" in tail[0]
            else f"exit {proc.returncode}"
        )
        return False, reason
    finally:
        pdf_path.unlink(missing_ok=True)
