import re
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor


def render_pdf(markdown, output):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1x", parent=styles["Heading1"], spaceBefore=12, spaceAfter=7))
    story, code, in_code = [], [], False
    fence = chr(96) * 3
    for line in markdown.splitlines():
        if line.startswith(fence):
            if in_code:
                story.append(Preformatted("\n".join(code), styles["Code"]))
                code, in_code = [], False
            else:
                in_code = True
            continue
        if in_code:
            code.append(line)
        elif not line.strip():
            story.append(Spacer(1, 3))
        elif line.startswith("# "):
            story.append(Paragraph(escape(line[2:]), styles["Title"]))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), styles["H1x"]))
        elif line.startswith("- "):
            story.append(Paragraph("• " + escape(line[2:]), styles["BodyText"]))
        else:
            story.append(Paragraph(escape(line), styles["BodyText"]))
    if in_code:
        story.append(Preformatted("\n".join(code), styles["Code"]))
    SimpleDocTemplate(
        str(output), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm
    ).build(story)


def render_svg(mermaid, output):
    exe = shutil.which("mmdc")
    if not exe:
        return False
    source = output.with_suffix(".mmd")
    source.write_text(mermaid, encoding="utf-8")
    try:
        subprocess.run([exe, "-i", str(source), "-o", str(output), "-b", "white"],
                       capture_output=True, timeout=45, check=True)
        return True
    except Exception:
        return False


def render_png(mermaid, output):
    exe = shutil.which("mmdc")
    if not exe:
        return False
    source = output.with_suffix(".mmd")
    source.write_text(mermaid, encoding="utf-8")
    try:
        subprocess.run([exe, "-i", str(source), "-o", str(output), "-b", "white", "-w", "1800"],
                       capture_output=True, timeout=60, check=True)
        return output.is_file() and output.stat().st_size > 0
    except Exception:
        return False


def _clean_inline(text):
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace(chr(96), "")
    return text.replace("*", "").strip()


def _add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    begin = run._r.add_fldChar()
    begin.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType", "begin")
    instruction = run._r.add_instrText()
    instruction.text = " PAGE "
    end = run._r.add_fldChar()
    end.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType", "end")


def render_docx(markdown, output, repository="Repository", diagram_png=None):
    """Create an editable, styled Word report from the generated technical design."""
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.72)
    section.bottom_margin = Inches(0.72)
    section.left_margin = Inches(0.82)
    section.right_margin = Inches(0.82)

    styles = document.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(9.5)
    styles["Normal"].font.color.rgb = RGBColor(40, 48, 58)
    for name, size, color in [
        ("Title", 30, RGBColor(24, 54, 92)),
        ("Heading 1", 18, RGBColor(24, 72, 120)),
        ("Heading 2", 13, RGBColor(36, 93, 145)),
        ("Heading 3", 11, RGBColor(65, 83, 105)),
    ]:
        styles[name].font.name = "Aptos Display"
        styles[name].font.size = Pt(size)
        styles[name].font.bold = True
        styles[name].font.color.rgb = color

    header = section.header.paragraphs[0]
    header.text = f"REPOLENS  |  SOFTWARE ARCHITECTURE REPORT  |  {repository}"
    header.style = styles["Caption"]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _add_page_number(section.footer.paragraphs[0])

    cover = document.add_paragraph()
    cover.paragraph_format.space_before = Pt(90)
    cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = cover.add_run("RepoLens")
    run.bold = True
    run.font.size = Pt(34)
    run.font.color.rgb = RGBColor(24, 54, 92)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subrun = subtitle.add_run("SOFTWARE ARCHITECTURE & TECHNICAL DESIGN")
    subrun.bold = True
    subrun.font.size = Pt(13)
    subrun.font.color.rgb = RGBColor(55, 105, 155)

    repo_line = document.add_paragraph()
    repo_line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    repo_line.paragraph_format.space_before = Pt(22)
    repo_line.add_run(repository).font.size = Pt(16)

    generated = document.add_paragraph()
    generated.alignment = WD_ALIGN_PARAGRAPH.CENTER
    generated.paragraph_format.space_before = Pt(8)
    generated.add_run("Generated from static repository analysis").italic = True

    document.add_page_break()
    document.add_heading("Contents", level=1)
    p = document.add_paragraph()
    r = p.add_run()
    fld = r._r
    begin = fld.add_fldChar()
    begin.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType", "begin")
    instr = fld.add_instrText()
    instr.text = ' TOC \\\\o "1-3" \\\\h \\\\z '
    separate = fld.add_fldChar()
    separate.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType", "separate")
    placeholder = p.add_run("Open in Word and update the table of contents if it is not populated.")
    placeholder.italic = True
    end_run = p.add_run()
    end = end_run._r.add_fldChar()
    end.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType", "end")

    document.add_page_break()
    if diagram_png and Path(diagram_png).is_file():
        document.add_heading("Architecture diagram", level=1)
        document.add_picture(str(diagram_png), width=Inches(6.4))
        document.add_paragraph(
            "Relationships shown are limited to repository-local imports resolved by static analysis.",
            style="Caption",
        )
        document.add_page_break()

    in_code, code_lines = False, []
    fence = chr(96) * 3
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith(fence):
            if in_code:
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.left_indent = Inches(0.18)
                paragraph.paragraph_format.right_indent = Inches(0.18)
                run = paragraph.add_run("\n".join(code_lines))
                run.font.name = "Consolas"
                run.font.size = Pt(8)
                run.font.color.rgb = RGBColor(55, 65, 81)
                code_lines, in_code = [], False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            continue
        if line.startswith("# "):
            document.add_heading(_clean_inline(line[2:]), level=1)
        elif line.startswith("## "):
            document.add_heading(_clean_inline(line[3:]), level=1)
        elif line.startswith("### "):
            document.add_heading(_clean_inline(line[4:]), level=2)
        elif line.startswith("#### "):
            document.add_heading(_clean_inline(line[5:]), level=3)
        elif line.startswith(("- ", "* ")):
            document.add_paragraph(_clean_inline(line[2:]), style="List Bullet")
        elif re.match(r"^\d+[.)]\s+", line):
            document.add_paragraph(_clean_inline(re.sub(r"^\d+[.)]\s+", "", line)), style="List Number")
        else:
            document.add_paragraph(_clean_inline(line))

    if in_code and code_lines:
        paragraph = document.add_paragraph()
        run = paragraph.add_run("\n".join(code_lines))
        run.font.name = "Consolas"
        run.font.size = Pt(8)

    document.core_properties.title = f"{repository} - Software Architecture and Technical Design"
    document.core_properties.subject = "Evidence-led repository architecture analysis"
    document.core_properties.author = "RepoLens"
    document.save(str(output))
