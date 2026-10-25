"""Markdown → minimal Word (.docx) with bounded native Office Math.

Covers what analysis reports use: headings, paragraphs, bullet/numbered lists, tables,
block quotes, rules, **bold**, *italic*, `code` and bounded native Office Math.
"""
from .docx_math import MathContext, M
from io import BytesIO
import re
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
FONT = '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei" w:cs="Calibri"/>'

CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                 '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                 '</Types>')
ROOT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
             '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
             '</Relationships>')
DOCUMENT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                 '</Relationships>')


def _style(style_id, name, size, bold=False, before=0, after=120, extra=''):
    return (f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
            f'<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="{before}" w:after="{after}"/>{extra}</w:pPr>'
            f'<w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr></w:style>')


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>{FONT}<w:sz w:val="21"/><w:szCs w:val="21"/>'
          '<w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/>'
          '</w:pPr></w:pPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
          + _style('Title', 'Title', 36, True, 0, 240)
          + _style('Heading1', 'heading 1', 30, True, 360, 160, '<w:outlineLvl w:val="0"/>')
          + _style('Heading2', 'heading 2', 26, True, 300, 120, '<w:outlineLvl w:val="1"/>')
          + _style('Heading3', 'heading 3', 23, True, 240, 100, '<w:outlineLvl w:val="2"/>')
          + '<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/>'
            '<w:pPr><w:ind w:left="360"/><w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="999999"/></w:pBdr></w:pPr>'
            '<w:rPr><w:color w:val="555555"/></w:rPr></w:style>'
          + '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>'
          + ''.join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>' for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
          + '</w:tblBorders><w:tblCellMar><w:left w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
          '</w:styles>')

INLINE = re.compile(r'(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*)')


def _clean(text):
    # Drop characters XML 1.0 forbids so a stray control code cannot corrupt the file.
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)


def runs(text, bold=False, math=None, display=False):
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'\1（\2）', _clean(text))
    result = []
    for part in INLINE.split(text):
        if not part:
            continue
        props, body = [], part
        if (part.startswith('**') and part.endswith('**')) or (part.startswith('__') and part.endswith('__')):
            props.append('<w:b/>'); body = part[2:-2]
        elif part.startswith('`') and part.endswith('`'):
            props.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>'); body = part[1:-1]
        elif part.startswith('*') and part.endswith('*') and len(part) > 2:
            props.append('<w:i/>'); body = part[1:-1]
        if bold and '<w:b/>' not in props:
            props.insert(0, '<w:b/>')
        for segment in math.pattern.split(body) if math else [body]:
            if math and segment in math.expressions:
                result.append(math.render(segment, display=display))
            elif segment:
                result.append(f'<w:r>{"<w:rPr>" + "".join(props) + "</w:rPr>" if props else ""}<w:t xml:space="preserve">{escape(segment)}</w:t></w:r>')
    return ''.join(result)


def paragraph(text, style=None, indent=0, bold=False, math=None):
    props = (f'<w:pStyle w:val="{style}"/>' if style else '') + (f'<w:ind w:left="{indent}" w:hanging="280"/>' if indent else '')
    return f'<w:p>{"<w:pPr>" + props + "</w:pPr>" if props else ""}{runs(text, bold, math, display=bool(math and text.strip() in math.expressions))}</w:p>'


def table(rows, math=None):
    cells = [[cell.strip() for cell in row.strip().strip('|').split('|')] for row in rows]
    cells = [row for row in cells if not all(re.fullmatch(r':?-{2,}:?', cell or '-') for cell in row)]
    width = max(len(row) for row in cells)
    body = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/></w:tblPr><w:tblGrid>'
            + '<w:gridCol/>' * width + '</w:tblGrid>']
    shade = '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>'
    for index, row in enumerate(cells):
        body.append('<w:tr>' + ''.join(
            f'<w:tc><w:tcPr>{shade if index == 0 else ""}</w:tcPr>'
            f'{paragraph(row[column] if column < len(row) else "", bold=index == 0, math=math)}</w:tc>' for column in range(width)) + '</w:tr>')
    body.append('</w:tbl><w:p/>')
    return ''.join(body)


def body_xml(markdown):
    math = MathContext(_clean(markdown.replace('\r\n', '\n')))
    parts, lines, index = [], math.text.split('\n'), 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if re.match(r'^(`{3,}|~{3,})', stripped):
            fence = re.match(r'^(`{3,}|~{3,})', stripped)[0]
            index += 1
            while index < len(lines) and not re.fullmatch(re.escape(fence[0]) + '{' + str(len(fence)) + ',}', lines[index].strip()):
                parts.append(f'<w:p><w:pPr><w:spacing w:after="0"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/></w:rPr>'
                             f'<w:t xml:space="preserve">{escape(_clean(lines[index]))}</w:t></w:r></w:p>')
                index += 1
            index += 1
            continue
        if stripped.startswith('|') and stripped.count('|') >= 2:
            rows = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                rows.append(lines[index]); index += 1
            parts.append(table(rows, math))
            continue
        heading = re.match(r'^(#{1,6})\s+(.*)$', stripped)
        bullet = re.match(r'^(\s*)[-*+]\s+(.*)$', line)
        number = re.match(r'^(\s*)(\d+)[.)]\s+(.*)$', line)
        if not stripped:
            pass
        elif heading:
            parts.append(paragraph(heading[2], {1: 'Heading1', 2: 'Heading2'}.get(len(heading[1]), 'Heading3'), math=math))
        elif re.fullmatch(r'(-{3,}|\*{3,}|_{3,})', stripped):
            parts.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="BFBFBF"/></w:pBdr></w:pPr></w:p>')
        elif stripped.startswith('>'):
            parts.append(paragraph(stripped.lstrip('>').strip(), 'Quote', math=math))
        elif bullet:
            parts.append(paragraph('• ' + bullet[2], indent=360 + 360 * (len(bullet[1].expandtabs(4)) // 2), math=math))
        elif number:
            parts.append(paragraph(f'{number[2]}. {number[3]}', indent=360 + 360 * (len(number[1].expandtabs(4)) // 2), math=math))
        else:
            parts.append(paragraph(stripped, math=math))
        index += 1
    if math.failed:
        parts.append(paragraph(f'有 {len(math.failed)} 个公式无法转换为 Word 公式，已保留 LaTeX 原文。'))
    return ''.join(parts)


def build(markdown, title=''):
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}" xmlns:m="{M}"><w:body>{body_xml(markdown)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1300" w:bottom="1440" w:left="1300" '
                'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:title>{escape(_clean(title))}</dc:title><dc:creator>video-parser</dc:creator></cp:coreProperties>')
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as package:
        package.writestr('[Content_Types].xml', CONTENT_TYPES)
        package.writestr('_rels/.rels', ROOT_RELS)
        package.writestr('word/_rels/document.xml.rels', DOCUMENT_RELS)
        package.writestr('word/document.xml', document)
        package.writestr('word/styles.xml', STYLES)
        package.writestr('docProps/core.xml', core)
    return output.getvalue()
