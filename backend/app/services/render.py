import re
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


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


def _append_field(run, instruction):
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    run._r.append(begin)

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    run._r.append(instr)

    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    run._r.append(separate)

    placeholder = OxmlElement("w:t")
    placeholder.text = "1"
    run._r.append(placeholder)

    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(end)


def _add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _append_field(paragraph.add_run(), "PAGE")



def _is_markdown_table_row(line):
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _markdown_cells(line):
    return [_clean_inline(cell) for cell in line.strip().strip("|").split("|")]


def _add_markdown_table(document, rows):
    if not rows:
        return
    headers = _markdown_cells(rows[0])
    data_rows = [
        _markdown_cells(row) for row in rows[1:]
        if not re.match(r"^\\s*\\|?\\s*:?-{3,}", row)
    ]
    column_count = max(1, len(headers))
    table = document.add_table(rows=1, cols=column_count)
    table.style = "Light Shading Accent 1"
    table.autofit = True
    for index in range(column_count):
        cell = table.rows[0].cells[index]
        cell.text = headers[index] if index < len(headers) else ""
        for run in cell.paragraphs[0].runs:
            run.bold = True
            run.font.size = Pt(8.5)
    for row_data in data_rows:
        cells = table.add_row().cells
        for index in range(column_count):
            cells[index].text = row_data[index] if index < len(row_data) else ""
            for paragraph in cells[index].paragraphs:
                paragraph.paragraph_format.space_after = Pt(2)
                for run in paragraph.runs:
                    run.font.size = Pt(8)
    document.add_paragraph()


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
    # Build a populated, reliable contents list from the same headings used below.
    # Unlike a field-only TOC, these entries are visible immediately in Word previews.
    for raw in markdown.splitlines():
        heading = re.match(r"^(#{1,3})\\s+(.+?)\\s*$", raw)
        if not heading:
            continue
        level = len(heading.group(1))
        title = _clean_inline(heading.group(2))
        if title.lower() in {"technical design document"}:
            continue
        entry = document.add_paragraph()
        entry.paragraph_format.left_indent = Inches(0.22 * (level - 1))
        entry.paragraph_format.space_after = Pt(3)
        run = entry.add_run(title)
        run.font.size = Pt(10 if level == 1 else 9)
        run.bold = level == 1

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
    markdown_lines = markdown.splitlines()
    index = 0
    while index < len(markdown_lines):
        line = markdown_lines[index].rstrip()
        if line.startswith(fence):
            if in_code:
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.left_indent = Inches(0.18)
                paragraph.paragraph_format.right_indent = Inches(0.18)
                run = paragraph.add_run("\\n".join(code_lines))
                run.font.name = "Consolas"
                run.font.size = Pt(8)
                run.font.color.rgb = RGBColor(55, 65, 81)
                code_lines, in_code = [], False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not line.strip():
            index += 1
            continue
        if _is_markdown_table_row(line):
            table_rows = []
            while index < len(markdown_lines) and _is_markdown_table_row(markdown_lines[index]):
                table_rows.append(markdown_lines[index].rstrip())
                index += 1
            _add_markdown_table(document, table_rows)
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
        elif re.match(r"^\\d+[.)]\\s+", line):
            document.add_paragraph(_clean_inline(re.sub(r"^\\d+[.)]\\s+", "", line)), style="List Number")
        else:
            document.add_paragraph(_clean_inline(line))
        index += 1

    if in_code and code_lines:
        paragraph = document.add_paragraph()
        run = paragraph.add_run("\n".join(code_lines))
        run.font.name = "Consolas"
        run.font.size = Pt(8)

    settings = document.settings.element
    update_fields = OxmlElement("w:updateFields")
    update_fields.set(qn("w:val"), "true")
    settings.append(update_fields)

    document.core_properties.title = f"{repository} - Software Architecture and Technical Design"
    document.core_properties.subject = "Evidence-led repository architecture analysis"
    document.core_properties.author = "RepoLens"
    document.save(str(output))
