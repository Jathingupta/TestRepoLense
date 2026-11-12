import shutil,subprocess
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Preformatted
def render_pdf(markdown,output):
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name="H1x",parent=styles["Heading1"],spaceBefore=12,spaceAfter=7))
    story=[]; code=[]; in_code=False
    for line in markdown.splitlines():
        if line.startswith("```"):
            if in_code: story.append(Preformatted("\n".join(code),styles["Code"])); code=[]; in_code=False
            else: in_code=True
            continue
        if in_code: code.append(line); continue
        if not line.strip(): story.append(Spacer(1,3))
        elif line.startswith("# "): story.append(Paragraph(escape(line[2:]),styles["Title"]))
        elif line.startswith("## "): story.append(Paragraph(escape(line[3:]),styles["H1x"]))
        elif line.startswith("- "): story.append(Paragraph("• "+escape(line[2:]),styles["BodyText"]))
        else: story.append(Paragraph(escape(line),styles["BodyText"]))
    if in_code: story.append(Preformatted("\n".join(code),styles["Code"]))
    SimpleDocTemplate(str(output),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=18*mm,bottomMargin=18*mm).build(story)
def render_svg(mermaid,output):
    exe=shutil.which("mmdc")
    if not exe: return False
    src=output.with_suffix(".mmd"); src.write_text(mermaid,encoding="utf-8")
    try: subprocess.run([exe,"-i",str(src),"-o",str(output),"-b","transparent"],capture_output=True,timeout=45,check=True); return True
    except Exception: return False
