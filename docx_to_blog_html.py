import argparse
import base64
import io
import html
import mimetypes
import os
import re
import zipfile
from xml.etree import ElementTree as ET


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

EMU_PER_PIXEL = 9525
MAX_IMAGE_WIDTH = 520
JPEG_QUALITY = 62
DEFAULT_PARAGRAPH_STYLE = (
    "margin: 0px 0px 11px;"
    "line-height: 107%;"
    "font-size: 15px;"
    "font-family: Calibri, sans-serif;"
)
CONTACT_URL = "https://vidyarishi.com/contact"
CONTACT_LINE_MARKERS = (
    "Website: Vidyarishi India Website",
    "Contact Number: +91 91525 35535",
)


def qname(name):
    prefix, local = name.split(":")
    return f"{{{NS[prefix]}}}{local}"


def read_relationships(docx):
    rels = {}
    try:
        rels_xml = docx.read("word/_rels/document.xml.rels")
    except KeyError:
        return rels

    root = ET.fromstring(rels_xml)
    for rel in root.findall("rel:Relationship", NS):
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        rel_type = rel.attrib.get("Type", "")
        if rel_id and target:
            rels[rel_id] = {"target": target, "type": rel_type}
    return rels


def word_path(target):
    if target.startswith("/"):
        return target.lstrip("/")
    return os.path.normpath(os.path.join("word", target)).replace("\\", "/")


def image_to_data_uri(docx, target):
    path = word_path(target)
    data = docx.read(path)
    mime_type = mimetypes.guess_type(path)[0] or "image/png"

    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "white")
                if image.mode == "RGBA":
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            else:
                image = image.convert("RGB")

            if image.width > MAX_IMAGE_WIDTH:
                ratio = MAX_IMAGE_WIDTH / image.width
                new_size = (MAX_IMAGE_WIDTH, max(1, round(image.height * ratio)))
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            data = buffer.getvalue()
            mime_type = "image/jpeg"
    except Exception as error:
        print(f"Warning: could not compress {path}: {error}")

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def attr(element, name):
    return element.attrib.get(qname(name)) if element is not None else None


def half_points_to_px(value):
    try:
        points = int(value) / 2
    except (TypeError, ValueError):
        return None
    return round(points * 96 / 72)


def run_style(run):
    props = run.find("w:rPr", NS)
    if props is None:
        return ""

    styles = []
    size = props.find("w:sz", NS)
    size_px = half_points_to_px(attr(size, "w:val"))
    if size_px:
        styles.append(f"font-size: {size_px}px")

    fonts = props.find("w:rFonts", NS)
    font_name = attr(fonts, "w:ascii") or attr(fonts, "w:hAnsi")
    if font_name:
        styles.append(f"font-family: {font_name}, sans-serif")

    color = props.find("w:color", NS)
    color_value = attr(color, "w:val")
    if color_value and color_value.lower() != "auto":
        styles.append(f"color: #{color_value}")

    return "; ".join(styles)


def wrap_run_style(run, text):
    if not text:
        return ""

    props = run.find("w:rPr", NS)
    if props is not None:
        if props.find("w:b", NS) is not None:
            text = f"<strong>{text}</strong>"
        if props.find("w:i", NS) is not None:
            text = f"<em>{text}</em>"
        if props.find("w:u", NS) is not None:
            text = f"<u>{text}</u>"

    style = run_style(run)
    if style:
        text = f'<span style="{html.escape(style, quote=True)}">{text}</span>'

    return text


def paragraph_style(paragraph, content):
    styles = [DEFAULT_PARAGRAPH_STYLE]
    props = paragraph.find("w:pPr", NS)

    if props is not None:
        justification = attr(props.find("w:jc", NS), "w:val")
        if justification in {"center", "right", "justify"}:
            styles.append(f"text-align: {justification}")

    style = paragraph.find("w:pPr/w:pStyle", NS)
    style_value = attr(style, "w:val")
    lower_style = style_value.lower() if style_value else ""

    if "heading1" in lower_style:
        styles.append("font-size: 32px")
        styles.append("font-weight: 700")
        styles.append("margin: 22px 0px 14px")
    elif "heading2" in lower_style:
        styles.append("font-size: 24px")
        styles.append("font-weight: 700")
        styles.append("margin: 18px 0px 12px")
    elif "heading3" in lower_style:
        styles.append("font-size: 19px")
        styles.append("font-weight: 700")
        styles.append("margin: 16px 0px 10px")

    if "<img " in content and "text-align:" not in "".join(styles):
        styles.append("text-align: center")
        styles.append("margin: 30px 0px")

    return "; ".join(styles)


def plain_text(html_fragment):
    without_tags = re.sub(r"<[^>]+>", "", html_fragment)
    return html.unescape(without_tags)


def contact_line_html(content):
    text = plain_text(content)
    if not any(marker in text for marker in CONTACT_LINE_MARKERS):
        return content

    normalized = re.sub(r"\s*color:\s*(?:#000000|black|windowtext)\s*;?", "", content, flags=re.I)
    normalized = re.sub(r"\s*text-decoration:\s*none\s*;?", "", normalized, flags=re.I)
    return (
        f'<a href="{CONTACT_URL}" '
        'style="color: rgb(5, 99, 193); text-decoration: underline;">'
        f"{normalized}</a>"
    )


def drawing_html(drawing, docx, rels):
    blip = drawing.find(".//a:blip", NS)
    if blip is None:
        return ""

    rel_id = blip.attrib.get(qname("r:embed")) or blip.attrib.get(qname("r:link"))
    if not rel_id or rel_id not in rels:
        return ""

    try:
        src = image_to_data_uri(docx, rels[rel_id]["target"])
    except KeyError:
        return ""

    extent = drawing.find(".//wp:extent", NS)
    width = 602
    height = None

    if extent is not None:
        cx = extent.attrib.get("cx")
        cy = extent.attrib.get("cy")
        if cx and cy:
            width = max(1, round(int(cx) / EMU_PER_PIXEL))
            height = max(1, round(int(cy) / EMU_PER_PIXEL))

    if width > MAX_IMAGE_WIDTH:
        if height:
            height = max(1, round(height * MAX_IMAGE_WIDTH / width))
        width = MAX_IMAGE_WIDTH

    height_attr = f' height="{height}"' if height else ""
    style = (
        f"width:{width}px;"
        "max-width:100%;"
        "height:auto;"
        "display:block;"
        "margin:0 auto;"
    )
    return f'<img src="{src}" width="{width}"{height_attr} style="{style}">'


def run_html(run, docx, rels):
    parts = []

    for child in run:
        if child.tag == qname("w:t"):
            parts.append(html.escape(child.text or ""))
        elif child.tag == qname("w:tab"):
            parts.append("&emsp;")
        elif child.tag == qname("w:br"):
            parts.append("<br>")
        elif child.tag == qname("w:drawing"):
            parts.append(drawing_html(child, docx, rels))

    return wrap_run_style(run, "".join(parts))


def run_field_char_type(run):
    field_char = run.find("w:fldChar", NS)
    if field_char is None:
        return None
    return field_char.attrib.get(qname("w:fldCharType"))


def run_instruction_text(run):
    instruction = run.find("w:instrText", NS)
    return instruction.text if instruction is not None else ""


def hyperlink_target_from_instruction(instruction):
    marker = "HYPERLINK"
    if marker not in instruction:
        return None

    after_marker = instruction.split(marker, 1)[1].strip()
    if after_marker.startswith('"') and '"' in after_marker[1:]:
        return after_marker.split('"', 2)[1]

    parts = after_marker.split()
    return parts[0] if parts else None


def paragraph_html(paragraph, docx, rels):
    pieces = []
    field_href = None
    field_display = []
    reading_field_instruction = False
    reading_field_display = False

    for child in paragraph:
        if child.tag == qname("w:r"):
            field_char_type = run_field_char_type(child)
            if field_char_type == "begin":
                field_href = None
                field_display = []
                reading_field_instruction = True
                reading_field_display = False
                continue

            if field_char_type == "separate":
                reading_field_instruction = False
                reading_field_display = bool(field_href)
                continue

            if field_char_type == "end":
                if field_href and field_display:
                    link_text = "".join(field_display)
                    pieces.append(
                        f'<a href="{html.escape(field_href, quote=True)}" '
                        'style="color: rgb(5, 99, 193); text-decoration: underline;">'
                        f"{link_text}</a>"
                    )
                field_href = None
                field_display = []
                reading_field_instruction = False
                reading_field_display = False
                continue

            if reading_field_instruction:
                possible_href = hyperlink_target_from_instruction(run_instruction_text(child))
                if possible_href:
                    field_href = possible_href
                continue

            if reading_field_display:
                field_display.append(run_html(child, docx, rels))
                continue

            pieces.append(run_html(child, docx, rels))
        elif child.tag == qname("w:hyperlink"):
            rel_id = child.attrib.get(qname("r:id"))
            href = rels.get(rel_id, {}).get("target", "#")
            link_text = "".join(run_html(run, docx, rels) for run in child.findall("w:r", NS))
            pieces.append(
                f'<a href="{html.escape(href, quote=True)}" '
                'style="color: rgb(5, 99, 193); text-decoration: underline;">'
                f"{link_text}</a>"
            )
        elif reading_field_display and child.tag not in {
            qname("w:proofErr"),
            qname("w:bookmarkStart"),
            qname("w:bookmarkEnd"),
        }:
            reading_field_display = False

    content = "".join(pieces)
    if not content:
        content = "&nbsp;<br>"

    content = contact_line_html(content)
    style = paragraph_style(paragraph, content)
    return f'<p class="MsoNormal" style="{style}">{content}</p>'


def table_html(table, docx, rels):
    rows = []
    for row in table.findall("w:tr", NS):
        cells = []
        for cell in row.findall("w:tc", NS):
            cell_content = "".join(
                paragraph_html(paragraph, docx, rels)
                for paragraph in cell.findall("w:p", NS)
            )
            cells.append(f"<td>{cell_content}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table>{''.join(rows)}</table>"


def convert_docx_to_html(docx_path):
    with zipfile.ZipFile(docx_path) as docx:
        rels = read_relationships(docx)
        document_xml = docx.read("word/document.xml")
        root = ET.fromstring(document_xml)
        body = root.find("w:body", NS)

        html_parts = []
        for child in body:
            if child.tag == qname("w:p"):
                html_parts.append(paragraph_html(child, docx, rels))
            elif child.tag == qname("w:tbl"):
                html_parts.append(table_html(child, docx, rels))

    return "\n\n".join(part for part in html_parts if part)


def main():
    parser = argparse.ArgumentParser(description="Convert a DOCX blog draft to HTML with embedded images.")
    parser.add_argument(
        "docx_path",
        nargs="?",
        default=os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "Blog Title.docx"),
    )
    parser.add_argument("--out", default="hello_with_images.html")
    args = parser.parse_args()

    html_content = convert_docx_to_html(args.docx_path)
    with open(args.out, "w", encoding="utf-8") as output:
        output.write(html_content)

    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
