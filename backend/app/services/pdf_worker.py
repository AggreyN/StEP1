"""Reads the text out of a PDF, in a process of its own.

A PDF is a program for a renderer, written by a stranger. The parser is a
large C library. Two things follow: it can take forever, and it can crash in a
way Python cannot catch. Neither may happen inside the API process.

So extraction runs in a child process: this same file, run as a script. The
parent writes the PDF to its stdin and reads one line of JSON from its stdout.
If the child overruns the deadline it is killed; if it crashes, only it dies.
The API sees a result or the absence of one, and turns both into an ordinary
response.

The child is started by path, with an empty environment, in Python's isolated
mode. It imports nothing from the application, so it holds no settings, no
secrets and no database connection, and whether it can start does not depend
on how the API itself was launched.
"""

from __future__ import annotations

import json
import subprocess
import sys

# Outcomes. Anything other than OK is a sentence shown to the student.
OK = "ok"
NOT_A_PDF = "That file isn't a PDF."
ENCRYPTED = "That PDF is password-protected. Export a copy without a password."
UNREADABLE = "That PDF could not be read. Try exporting it again."
TOO_SLOW = "That PDF took too long to read. Try exporting it again as a simpler file."
_OUTCOMES = {OK, NOT_A_PDF, ENCRYPTED, UNREADABLE, TOO_SLOW}

MAGIC = b"%PDF-"


def extract(data: bytes, *, max_pages: int, max_chars: int, seconds: float) -> tuple[str, str]:
    """(outcome, text). Never raises, never runs past `seconds`, and is not
    harmed by whatever the file does to the parser."""
    if not data.startswith(MAGIC):
        return NOT_A_PDF, ""
    try:
        done = subprocess.run(
            # -I: isolated. No PYTHON* variables, no user site, no script dir
            # on the path.
            [sys.executable, "-I", __file__, str(max_pages), str(max_chars), str(seconds)],
            input=data,
            capture_output=True,
            timeout=seconds,
            env={},
            check=False,
        )
    except subprocess.TimeoutExpired:
        return TOO_SLOW, ""  # run() has already killed it
    except OSError:
        return UNREADABLE, ""  # could not start: out of processes or memory

    # A crash leaves a non-zero exit and nothing usable on stdout. What is on
    # stderr is the parser talking about the file; it is dropped, not logged.
    if done.returncode != 0:
        return UNREADABLE, ""
    try:
        reply = json.loads(done.stdout)
        outcome, text = reply["outcome"], reply["text"]
    except (ValueError, KeyError, TypeError):
        return UNREADABLE, ""
    if outcome not in _OUTCOMES or not isinstance(text, str):
        return UNREADABLE, ""
    return outcome, text[:max_chars]


# --------------------------------------------------------------------------- #
# Everything below runs in the child
# --------------------------------------------------------------------------- #


def _limit_this_process(seconds: float) -> None:
    """A second deadline, enforced by the kernel, in case the parent is not
    there to enforce the first. Best effort: not every platform honours it."""
    try:
        import resource

        cpu = int(seconds) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    except Exception:  # noqa: BLE001
        pass


def _read(data: bytes, max_pages: int, max_chars: int) -> tuple[str, str]:
    if not data.startswith(MAGIC):
        return NOT_A_PDF, ""
    import pymupdf

    # MuPDF narrates every malformed object to stderr.
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)

    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass or doc.is_encrypted:
                return ENCRYPTED, ""
            parts: list[str] = []
            taken = 0
            for number, page in enumerate(doc):
                if number >= max_pages or taken >= max_chars:
                    break
                text = page.get_text()[: max_chars - taken]
                taken += len(text)
                parts.append(text)
    except Exception:  # noqa: BLE001 — PyMuPDF raises several unrelated types
        return UNREADABLE, ""
    # Postgres TEXT cannot hold NUL, and some PDF generators emit it.
    return OK, "\n".join(parts).replace("\x00", "").strip()


def _main(argv: list[str]) -> int:
    max_pages, max_chars, seconds = int(argv[1]), int(argv[2]), float(argv[3])
    _limit_this_process(seconds)
    outcome, text = _read(sys.stdin.buffer.read(), max_pages, max_chars)
    sys.stdout.buffer.write(json.dumps({"outcome": outcome, "text": text}).encode())
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
