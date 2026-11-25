from pathlib import Path
from functools import lru_cache
from io import BytesIO
from xml.dom import minidom
from zipfile import ZipFile

from .periods import previous_sales_months


_DIRECTORY = Path(__file__).parent / "templates"
WORKBOOK_TEMPLATES = {
    "v3": (_DIRECTORY / "plan-review-v3.xlsx", "计划审核V3模板.xlsx"),
    "plan": (_DIRECTORY / "replenishment-plan.xlsx", "补货计划模板.xlsx"),
    "v2": (_DIRECTORY / "plan-review-v2.xlsx", "计划审核V2模板.xlsx"),
}


def dated_v3_template(period):
    asset,_=WORKBOOK_TEMPLATES["v3"]
    return _month_headers(asset,asset.stat().st_mtime_ns,previous_sales_months(period))


@lru_cache(maxsize=8)
def _month_headers(asset, asset_revision, months):
    # Patch just the six header cells. A workbook save would drop formula caches
    # and could rewrite Excel note drawings and other independent workbook parts.
    worksheet="xl/worksheets/sheet1.xml"  # 审核表 in the bundled V3 asset.
    output=BytesIO()
    with ZipFile(asset) as source, ZipFile(output,"w") as result:
        for entry in source.infolist():
            content=source.read(entry)
            if entry.filename==worksheet:
                # The asset contains thousands of styled rows. Parse only the
                # header, retaining the worksheet's namespace declarations.
                end_of_header=content.index(b"</row>")+len(b"</row>")
                closing_tags=b"</sheetData></worksheet>"
                with minidom.parseString(content[:end_of_header]+closing_tags) as document:
                    ns=document.documentElement.namespaceURI
                    header=document.getElementsByTagNameNS(ns,"row")[0]
                    cells={c.getAttribute("r"):c for c in header.getElementsByTagNameNS(ns,"c")}
                    for column,month in zip("NOPQRS",months):
                        cell=cells[column+"1"]
                        cell.setAttribute("t","inlineStr")
                        for child in list(cell.childNodes):
                            cell.removeChild(child).unlink()
                        inline=document.createElementNS(ns,"is")
                        value=document.createElementNS(ns,"t")
                        value.appendChild(document.createTextNode(month+" 销量"))
                        inline.appendChild(value)
                        cell.appendChild(inline)
                    prefix=document.toxml(encoding="UTF-8").removesuffix(closing_tags)
                    content=prefix+content[end_of_header:]
            result.writestr(entry,content)
    return output.getvalue()
