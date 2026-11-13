"""CSV and PDF report generation."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import APP_NAME, __version__
from .db import Candidate, Job, MatchResult, SkillGapAnalysis
from .errors import StorageError

DISCLAIMER = (
    "AI-generated results are decision-support information, not a hiring decision. Scores are based on "
    "job-relevant qualifications only and may contain errors; AI cannot eliminate bias completely. "
    "A qualified person must review every result."
)
ACCENT = colors.HexColor("#2457D6")
MUTED = colors.HexColor("#5B6472")
RULE = colors.HexColor("#DDE1E8")


# --------------------------------------------------------------------------- helpers
def display_name(candidate: Candidate, blind: bool) -> str:
    return f"Candidate #{candidate.candidate_id}" if blind else (candidate.candidate_name or "Unknown")


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _fmt(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.1f}"


def _p(text: Any) -> str:
    return escape(str(text if text is not None else ""))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20,
                                textColor=colors.HexColor("#1B1F27"), alignment=TA_LEFT, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9, textColor=MUTED, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5,
                             textColor=ACCENT, spaceBefore=12, spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9.5, leading=13.5),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=8, leading=10.5, textColor=MUTED),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=8.5, leading=11),
        "cellb": ParagraphStyle("cb", parent=base["Normal"], fontSize=8.5, leading=11, fontName="Helvetica-Bold"),
    }


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, f"{APP_NAME} v{__version__} - decision support only")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _doc(path: Path, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
        bottomMargin=18 * mm, title=title, author=APP_NAME,
    )


def _table(data: list[list[Any]], widths: Sequence[float], header: bool = True) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FB")),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT)]
    t.setStyle(TableStyle(style))
    return t


def _bullets(items: Iterable[str], st: dict[str, ParagraphStyle]) -> list[Any]:
    items = [i for i in items if i]
    if not items:
        return [Paragraph("None identified.", st["small"])]
    return [Paragraph(f"&bull; {_p(i)}", st["body"]) for i in items]


def _build(path: Path, title: str, story: list[Any]) -> None:
    try:
        _doc(path, title).build(story, onFirstPage=_footer, onLaterPages=_footer)
    except OSError as exc:
        raise StorageError(f"The report could not be written to '{path}'. Check the folder permissions.") from exc


def _header(st, title: str, subtitle: str) -> list[Any]:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return [Paragraph(_p(title), st["title"]), Paragraph(f"{_p(subtitle)} &middot; Generated {stamp}", st["sub"])]


def _disclaimer(st) -> list[Any]:
    return [Spacer(1, 10), Paragraph(_p(DISCLAIMER), st["small"])]


def _match_block(match: MatchResult, st) -> list[Any]:
    d = match.details or {}
    rows = [
        ["Overall", _fmt(match.final_score) + (" (reviewer override)" if match.override_score is not None else ""),
         "Skills", _fmt(match.skill_score)],
        ["Experience", _fmt(match.experience_score), "Qualifications", _fmt(match.qualification_score)],
        ["AI semantic fit", _fmt(match.semantic_score), "Automated score", _fmt(match.overall_score)],
    ]
    cells = [[Paragraph(_p(c), st["cellb"] if i % 2 == 0 else st["cell"]) for i, c in enumerate(r)] for r in rows]
    out: list[Any] = [_table(cells, [32 * mm, 52 * mm, 32 * mm, 52 * mm], header=False)]
    out += [Paragraph("Matched skills", st["h2"]),
            Paragraph(_p(", ".join(d.get("matched_skills", [])) or "None"), st["body"])]
    out += [Paragraph("Missing skills", st["h2"]),
            Paragraph(_p(", ".join(d.get("missing_skills", [])) or "None"), st["body"])]
    out += [Paragraph("Strengths", st["h2"])] + _bullets(d.get("strengths", []), st)
    out += [Paragraph("Potential concerns", st["h2"])] + _bullets(d.get("concerns", []), st)
    out += [Paragraph("Missing or uncertain information", st["h2"])] + _bullets(d.get("uncertainties", []), st)
    out += [Paragraph("Explanation", st["h2"]), Paragraph(_p(match.analysis_explanation or "-"), st["body"])]
    if match.override_score is not None:
        note = f" Note: {match.override_note}" if match.override_note else ""
        out += [Paragraph("Reviewer decision", st["h2"]),
                Paragraph(_p(f"Score set to {match.override_score:.1f} by a reviewer.{note}"), st["body"])]
    return out


# --------------------------------------------------------------------------- CSV
def export_ranking_csv(path: Path | str, job: Job, rows: Sequence[Any], blind: bool = False) -> None:
    path = Path(path)
    header = ["Rank", "Candidate", "Final score", "Automated score", "Reviewer override", "Skills score",
              "Experience score", "Qualification score", "AI semantic score", "Experience (years)",
              "Matched skills", "Missing skills", "Reviewer note"]
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow([f"Job: {job.job_title}"])
            w.writerow([])
            w.writerow(header)
            for i, r in enumerate(rows, 1):
                m: MatchResult = r.match
                d = m.details or {}
                w.writerow([_csv_safe(v) for v in [
                    i, display_name(r.candidate, blind), round(m.final_score, 1), round(m.overall_score, 1),
                    "" if m.override_score is None else round(m.override_score, 1),
                    _opt(m.skill_score), _opt(m.experience_score), _opt(m.qualification_score),
                    _opt(m.semantic_score), r.candidate.total_experience,
                    "; ".join(d.get("matched_skills", [])), "; ".join(d.get("missing_skills", [])),
                    m.override_note or "",
                ]])
    except OSError as exc:
        raise StorageError(f"The file could not be written to '{path}'. Check the folder permissions.") from exc


def _opt(v: Optional[float]) -> Any:
    return "" if v is None else round(v, 1)


# --------------------------------------------------------------------------- PDF
def export_ranking_pdf(path: Path | str, job: Job, rows: Sequence[Any], blind: bool = False) -> None:
    st = _styles()
    story = _header(st, "Candidate ranking report", f"{job.job_title}" + (f" - {job.company_name}" if job.company_name else ""))
    data = [[Paragraph(h, st["cellb"]) for h in ("#", "Candidate", "Final", "Skills", "Exp.", "Qual.", "Missing skills")]]
    for i, r in enumerate(rows, 1):
        m = r.match
        data.append([
            Paragraph(str(i), st["cell"]),
            Paragraph(_p(display_name(r.candidate, blind)), st["cell"]),
            Paragraph(_fmt(m.final_score), st["cellb"]),
            Paragraph(_fmt(m.skill_score), st["cell"]),
            Paragraph(_fmt(m.experience_score), st["cell"]),
            Paragraph(_fmt(m.qualification_score), st["cell"]),
            Paragraph(_p(", ".join((m.details or {}).get("missing_skills", [])[:8]) or "-"), st["cell"]),
        ])
    story.append(_table(data, [8 * mm, 40 * mm, 15 * mm, 15 * mm, 15 * mm, 15 * mm, 66 * mm]))
    story.append(Paragraph("Candidate summaries", st["h2"]))
    for i, r in enumerate(rows[:25], 1):
        m = r.match
        block = [Paragraph(f"<b>{i}. {_p(display_name(r.candidate, blind))}</b> - {_fmt(m.final_score)}", st["body"]),
                 Paragraph(_p(m.analysis_explanation or ""), st["small"]), Spacer(1, 5)]
        story.append(KeepTogether(block))
    story += _disclaimer(st)
    _build(Path(path), "Candidate ranking report", story)


def export_match_pdf(path: Path | str, candidate: Candidate, job: Job, match: MatchResult, blind: bool = False) -> None:
    st = _styles()
    story = _header(st, "Job compatibility report",
                    f"{display_name(candidate, blind)} vs. {job.job_title}")
    story += _match_block(match, st)
    story += _disclaimer(st)
    _build(Path(path), "Job compatibility report", story)


def export_gap_pdf(path: Path | str, candidate: Candidate, job: Job, gap: SkillGapAnalysis, blind: bool = False) -> None:
    st = _styles()
    story = _header(st, "Skill gap report", f"{display_name(candidate, blind)} vs. {job.job_title}")
    data = [[Paragraph(h, st["cellb"]) for h in ("Required skill", "Importance", "Status")]]
    labels = {"listed": "Has skill", "mentioned": "Mentioned in experience", "equivalent": "Equivalent skill", "missing": "Missing"}
    for s in gap.skill_status or []:
        data.append([Paragraph(_p(s["name"]), st["cell"]),
                     Paragraph(_p(s["importance"].replace("_", " ")), st["cell"]),
                     Paragraph(_p(labels.get(s["status"], s["status"])), st["cell"])])
    story.append(_table(data, [80 * mm, 40 * mm, 54 * mm]))
    story.append(Paragraph("Suggested ways to close the gaps", st["h2"]))
    story.append(Paragraph("These are suggestions only; completing them does not guarantee a qualification or a job.", st["small"]))
    recs = gap.recommendations or []
    if not recs:
        story.append(Paragraph("No skill gaps were identified.", st["body"]))
    for r in recs:
        meta = []
        if r.get("difficulty"):
            meta.append(f"difficulty: {r['difficulty']}")
        if r.get("estimated_weeks"):
            meta.append(f"about {r['estimated_weeks']} weeks")
        block = [Paragraph(f"<b>{_p(r['skill'])}</b> ({_p(r['importance'].replace('_', ' '))}"
                           + (f"; {_p(', '.join(meta))}" if meta else "") + ")", st["body"])]
        if r.get("note"):
            block.append(Paragraph(_p(r["note"]), st["small"]))
        for label, key in (("Learning path", "learning_path"), ("Certifications", "certifications"), ("Practice projects", "projects")):
            if r.get(key):
                block.append(Paragraph(f"<i>{label}:</i> " + _p("; ".join(r[key])), st["body"]))
        block.append(Spacer(1, 6))
        story.append(KeepTogether(block))
    story += _disclaimer(st)
    _build(Path(path), "Skill gap report", story)


def export_candidate_pdf(
    path: Path | str, candidate: Candidate, matches: Sequence[tuple[Job, MatchResult]], blind: bool = False
) -> None:
    st = _styles()
    p = candidate.profile_json or {}
    story = _header(st, "Candidate analysis report", display_name(candidate, blind))
    if not blind:
        contact = " | ".join(x for x in (candidate.email, candidate.phone, p.get("location")) if x)
        if contact:
            story.append(Paragraph(_p(contact), st["body"]))
    story += [Paragraph("Professional summary", st["h2"]), Paragraph(_p(candidate.professional_summary or "-"), st["body"]),
              Paragraph(f"<b>Total experience:</b> {candidate.total_experience:g} years", st["body"])]
    skills = ", ".join(s["name"] for s in p.get("skills", []))
    story += [Paragraph("Skills", st["h2"]), Paragraph(_p(skills or "-"), st["body"])]
    story.append(Paragraph("Experience", st["h2"]))
    for e in p.get("experience", []):
        span = " - ".join(x for x in (e.get("start"), e.get("end")) if x)
        story.append(KeepTogether([
            Paragraph(f"<b>{_p(e.get('title'))}</b>, {_p(e.get('company'))} <font color='#5B6472'>{_p(span)}</font>", st["body"]),
            Paragraph(_p(e.get("description", "")), st["small"]), Spacer(1, 3)]))
    story.append(Paragraph("Education", st["h2"]))
    for e in p.get("education", []):
        story.append(Paragraph(_p(" ".join(x for x in (e.get("degree"), e.get("field")) if x)
                                  + (f", {e.get('institution')}" if e.get("institution") and not blind else "")), st["body"]))
    if p.get("certifications"):
        story += [Paragraph("Certifications", st["h2"])] + _bullets(p["certifications"], st)
    if p.get("projects"):
        story.append(Paragraph("Projects", st["h2"]))
        for pr in p["projects"]:
            story.append(Paragraph(f"<b>{_p(pr.get('name'))}</b> - {_p(pr.get('description'))}", st["body"]))
    if matches:
        story.append(Paragraph("Job matches", st["h2"]))
        data = [[Paragraph(h, st["cellb"]) for h in ("Job", "Final", "Skills", "Missing skills")]]
        for job, m in sorted(matches, key=lambda x: -x[1].final_score):
            data.append([Paragraph(_p(job.job_title), st["cell"]), Paragraph(_fmt(m.final_score), st["cellb"]),
                         Paragraph(_fmt(m.skill_score), st["cell"]),
                         Paragraph(_p(", ".join((m.details or {}).get("missing_skills", [])[:6]) or "-"), st["cell"])])
        story.append(_table(data, [60 * mm, 18 * mm, 18 * mm, 78 * mm]))
    story += _disclaimer(st)
    _build(Path(path), "Candidate analysis report", story)
