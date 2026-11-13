"""Application entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import APP_ID, APP_NAME, __version__
from .logging_setup import setup_logging

log = logging.getLogger(__name__)


def resource_path(*parts: str) -> Path:
    """Locate bundled data files both from source and from a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def selftest() -> int:
    """Headless start-up check used by CI on the *built* artifacts (exe / installed .deb).

    Builds the real main window with a throw-away data folder, visits every screen and
    exits 0 on success. No network access and no API key are needed.
    """
    import os
    import shutil
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    home = Path(tempfile.mkdtemp(prefix="rm_selftest_"))
    os.environ["RESUME_MATCHER_HOME"] = str(home)
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication([])
        from .ui.fonts import load_fonts

        if not load_fonts(resource_path("assets", "fonts")):
            raise RuntimeError("bundled fonts could not be loaded")
        from .services import Core
        from .ui.main_window import NAV, MainWindow

        core = Core(home=home)
        window = MainWindow(core)
        window.show()
        for i in range(len(NAV)):
            window.nav.setCurrentRow(i)
            app.processEvents()
        # The document stack must really work inside the bundle, not just import.
        import docx
        import pymupdf
        from google import genai  # noqa: F401

        from . import reports
        from .parsing import extract_text

        sample = "Jane Doe - Software Engineer with strong Python and SQL experience."
        pdf = pymupdf.open()
        pdf.new_page().insert_text((72, 100), sample)
        pdf.save(home / "t.pdf")
        pdf.close()
        d = docx.Document()
        d.add_paragraph(sample)
        d.save(home / "t.docx")
        for name in ("t.pdf", "t.docx"):
            if "Software Engineer" not in extract_text(home / name):
                raise RuntimeError(f"text extraction failed for {name}")
        from .db import Job

        with core.db.session() as s:
            job = Job(job_title="Test Role", job_description=sample)
            s.add(job)
            s.flush()
        reports.export_ranking_csv(home / "r.csv", job, [])
        reports.export_ranking_pdf(home / "r.pdf", job, [])
        if not (home / "r.pdf").read_bytes().startswith(b"%PDF"):
            raise RuntimeError("PDF report generation failed")

        # job-search stack: HTTP client, provider parsing and the local analyser must work in the bundle
        import httpx

        from .jobsearch import HttpClient, SearchQuery, SkillExtractor, all_providers, analyse_posting

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jobs": [{
                "id": 1, "url": "https://example.test/j/1", "title": "Python Developer", "company_name": "Acme",
                "candidate_required_location": "Worldwide", "publication_date": "2026-01-01T00:00:00",
                "description": "<p>Required: Python, SQL. 3+ years experience.</p>"}]})

        http = HttpClient(transport=httpx.MockTransport(handler))
        remotive = next(p for p in all_providers() if p.id == "remotive")
        posts = remotive.fetch(http, SearchQuery(keywords=["python"]), {})
        http.close()
        if not posts or "python" not in [x["name"].lower() for x in analyse_posting(posts[0], SkillExtractor())["skills"]]:
            raise RuntimeError("job search stack failed")

        window.close()
        print(f"selftest ok: {APP_NAME} {__version__}")
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print(f"selftest FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    if "--selftest" in (sys.argv if argv is None else argv):
        return selftest()
    if "--version" in (sys.argv if argv is None else argv):
        print(f"{APP_NAME} {__version__}")
        return 0
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .config import data_dir
    from .errors import AppError

    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_ID)
    from .ui.fonts import load_fonts

    load_fonts(resource_path("assets", "fonts"))
    icon_file = resource_path("assets", "icon.png")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    try:
        home = data_dir()
        setup_logging(home / "logs")
        log.info("%s %s starting", APP_NAME, __version__)
        from .services import Core
        from .ui.main_window import MainWindow

        core = Core(home=home)
        window = MainWindow(core)
    except AppError as exc:
        QMessageBox.critical(None, APP_NAME, exc.user_message)
        return 1
    except Exception:  # noqa: BLE001
        log.exception("fatal start-up error")
        QMessageBox.critical(None, APP_NAME, "The application could not start. See the log file in the data folder.")
        return 1

    def excepthook(exc_type, exc, tb):  # never let an unhandled error kill the UI silently
        log.error("unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = excepthook
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
