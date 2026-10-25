"""Generate sample resume fixtures (DOCX; PDF via pypdf if available) to test parsing."""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).parent / "fixtures"

RESUME_TEXT = """Senior Backend Engineer
Bangalore, India | jane.doe@example.com | +91 98765 43210

SUMMARY
Backend engineer with 6 years of experience building Python microservices on AWS.

SKILLS
Python, FastAPI, PostgreSQL, Redis, AWS, Docker, Kubernetes, REST API, Kafka

EXPERIENCE
Senior Backend Engineer, Acme Corp (2022 - Present)
- Designed Python FastAPI services handling 20k requests per second with Redis caching.
- Migrated monolith to Kubernetes microservices on AWS, cutting cost 30 percent.
- Built REST API integrations with PostgreSQL and Kafka event streaming.

Backend Developer, Beta Systems (2020 - 2022)
- Developed Django services and PostgreSQL data models.
- Implemented CI/CD with Jenkins and Docker.

EDUCATION
B.Tech Computer Science, IIT Delhi, 2020, 8.5 CGPA
"""


def make_docx() -> Path:
    import docx
    OUT.mkdir(parents=True, exist_ok=True)
    doc = docx.Document()
    for line in RESUME_TEXT.splitlines():
        doc.add_paragraph(line)
    path = OUT / "sample_resume.docx"
    doc.save(str(path))
    return path


def make_pdf_text_attempt() -> Path | None:
    """Create a simple PDF with reportlab if present; else skip."""
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        return None
    path = OUT / "sample_resume.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 750
    for line in RESUME_TEXT.splitlines():
        c.drawString(50, y, line[:110])
        y -= 16
        if y < 50:
            c.showPage()
            y = 750
    c.save()
    return path


if __name__ == "__main__":
    print(make_docx())
    print(make_pdf_text_attempt())