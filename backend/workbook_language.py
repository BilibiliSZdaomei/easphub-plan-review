"""Localise the bundled blank templates without rewriting formulas, styling or uploaded files."""
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import re
from xml.dom import minidom
from zipfile import ZipFile

COPY = json.loads((Path(__file__).parent / "templates" / "workbook-en.json").read_text("utf-8"))
HEADERS = COPY["headers"]
REASONS = {en: zh for zh, en in COPY["reasons"].items()}


def canonical_workbook_header(value):
    if not isinstance(value, str) or "\n" not in value:
        return value
    lines = value.splitlines()
    if len(lines) != 2:
        return value
    english, chinese = lines
    if (HEADERS.get(chinese) == english or (
            re.fullmatch(r"\d{4}-\d{2} 销量", chinese) and english == chinese[:7] + " sales")):
        return chinese
    return value


def elements(node, name):
    return node.getElementsByTagNameNS("*", name)


def set_text(element, value):
    if element.firstChild:
        element.firstChild.nodeValue = value
    else:
        element.appendChild(element.ownerDocument.createTextNode(value))


def edit_xml(content, action):
    with minidom.parseString(content) as document:
        action(document)
        return document.toxml(encoding="UTF-8")


def english_headers(content, months):
    # The remaining rows can be many MB of formulas. Keep their XML byte-for-byte.
    end = content.index(b"</row>") + len(b"</row>")
    closing = b"</sheetData></worksheet>"

    def change(document):
        row = elements(document, "row")[0]
        row.setAttribute("ht", "54")
        for col in elements(document, "col"):
            col.setAttribute("width", str(max(21, float(col.getAttribute("width")))))
        for cell in elements(row, "c"):
            node = elements(cell, "t")[0]
            chinese = node.firstChild.nodeValue.splitlines()[0]
            col = cell.getAttribute("r")[:-1]
            if months and col in tuple("NOPQRS"):
                month = months["NOPQRS".index(col)]
                en, chinese = month + " sales", month + " 销量"
            else:
                en = HEADERS[chinese]
            set_text(node, en + "\n" + chinese)
    header = edit_xml(content[:end] + closing, change).removesuffix(closing)
    rest = content[end:]
    if not months:
        # Keep the order and limits of the existing data-validation list.
        reasons = COPY["reasons"]
        rest = rest.replace(('"' + ','.join(reasons) + '"').encode(),
                            ('"' + ','.join(reasons.values()) + '"').encode())
    return header + rest


def english_notes(content, notes, review_logic=False):
    def change(doc):
        for comment in elements(doc, "comment"):
            ref = comment.getAttribute("ref")
            col = re.match(r"[A-Z]+", ref).group()
            index = 0
            for char in col:
                index = index * 26 + ord(char) - 64
            text = ("Used by offline Excel formulas. Reviewers and administrators manage the published rules in the system."
                    if review_logic else notes[index - 1])
            set_text(elements(comment, "t")[0], text)
    return edit_xml(content, change)


def english_guide(content, labels):
    def change(doc):
        for cell in elements(doc, "c"):
            ref = cell.getAttribute("r")
            if ref in labels:
                set_text(elements(cell, "t")[0], labels[ref])
    return edit_xml(content, change)


@lru_cache(maxsize=8)
def english_workbook(asset, revision, months=()):
    is_v3 = bool(months)
    notes = COPY["v3_notes" if is_v3 else "quantity_notes"]
    guide = COPY["v3_guide" if is_v3 else "quantity_guide"]
    output = BytesIO()
    with ZipFile(asset) as source, ZipFile(output, "w") as result:
        for entry in source.infolist():
            data = source.read(entry)
            if entry.filename == "xl/worksheets/sheet1.xml":
                data = english_headers(data, months)
            elif entry.filename == "xl/worksheets/sheet2.xml":
                data = english_guide(data, guide)
            elif entry.filename.startswith("xl/comments/comment") and entry.filename.endswith(".xml"):
                data = english_notes(data, notes, is_v3 and entry.filename.endswith("2.xml"))
            result.writestr(entry, data)
    return output.getvalue()
