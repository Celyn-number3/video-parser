"""Bounded, pure local TeX -> MathML -> editable Office Math. Never execute TeX/macros."""
from dataclasses import dataclass
import re
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from latex2mathml.converter import convert as to_mathml
from mathml2omml import convert as to_omml

M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
UNSAFE = re.compile(r'\\(?:[egx]?def|let|futurelet|(?:re)?newcommand|(?:re)?newenvironment|csname|input|include\w*|write\d*|openout|read|special|href|url|html\w*|require)\b')
MAX_TEX = 4096
MAX_FORMULAS = 128

@dataclass(frozen=True)
class Formula:
    source: str
    tex: str
    display: bool


def escaped(text, at):
    count = 0
    while at > 0 and text[at - 1] == '\\':
        at -= 1; count += 1
    return count % 2 == 1


def protect_math(text):
    """Match the UI's four delimiters, excluding code, URLs, currency and incomplete input."""
    prefix = '\ue000M'
    while prefix in text: prefix += 'M'
    expressions, chunks, missing = {}, [], set()
    at = copied = 0
    while at < len(text):
        if at == 0 or text[at - 1] == '\n':
            fence = re.match(r'[ \t]*(`{3,}|~{3,})[^\n]*(?:\n|$)', text[at:])
            if fence:
                start = at + fence.end()
                end = re.search(r'^[ \t]*' + re.escape(fence[1][0]) + '{' + str(len(fence[1])) + r',}[ \t]*(?:\n|$)', text[start:], re.M)
                at = start + end.end() if end else len(text)
                continue
        if text[at] == '`' and not escaped(text, at):
            ticks = re.match(r'`+', text[at:])[0]; end = text.find(ticks, at + len(ticks))
            at = end + len(ticks) if end >= 0 else at + len(ticks)
            continue
        if text[at] == '[':
            link = re.match(r'\[[^\]\n]+\]\(https?://[^)\s]+\)', text[at:])
            if link: at += link.end(); continue
        opening = next((v for v in ('\\[', '\\(', '$$', '$') if text.startswith(v, at)), '')
        if not opening or escaped(text, at): at += 1; continue
        closing = {'\\[': '\\]', '\\(': '\\)'}.get(opening, opening)
        if closing in missing: at += len(opening); continue
        start = at + len(opening); end = text.find(closing, start)
        while end >= 0 and escaped(text, end): end = text.find(closing, end + len(closing))
        if end < 0: missing.add(closing)
        invalid_dollar = opening == '$' and (start >= len(text) or text[start].isspace() or text[start] == '$' or end < 0
            or text[end - 1].isspace() or (end + 1 < len(text) and (text[end + 1].isdigit() or text[end + 1] == '$')) or re.search(r'[\n`]|https?://', text[start:end], re.I))
        if end < 0 or invalid_dollar: at += len(opening); continue
        stop = end + len(closing); token = f'{prefix}{len(expressions)}\ue001'; tex = text[start:end]
        quote = re.match(r'[ \t]*(?:>[ \t]*)+', text[text.rfind('\n', 0, at) + 1:at])
        if quote: tex = re.sub(r'\n[ \t]*(?:>[ \t]*){' + str(quote[0].count('>')) + '}', '\n', tex)
        expressions[token] = Formula(text[at:stop], tex, opening in ('\\[', '$$'))
        chunks.extend((text[copied:at], token)); copied = stop; at = stop
    chunks.append(text[copied:])
    return ''.join(chunks), expressions, prefix


def office_math(tex):
    if not tex.strip() or len(tex) > MAX_TEX or UNSAFE.search(tex): return None
    depth = 0
    for at, char in enumerate(tex):
        if escaped(tex, at): continue
        if char == '{':
            depth += 1
            if depth > 48: return None
        elif char == '}':
            depth -= 1
            if depth < 0: return None
    if depth: return None
    try:
        mathml = to_mathml(tex)
        if len(mathml) > 200000 or '<!' in mathml: return None
        tree = ET.fromstring(mathml)
        if sum(1 for _ in tree.iter()) > 4096: return None
        # Unknown commands must remain visible source, not silently become an incorrect equation.
        if any(re.search(r'\\[A-Za-z]+', value) for value in tree.itertext()): return None
        if any(key.rsplit('}', 1)[-1] in ('href', 'src') for node in tree.iter() for key in node.attrib): return None
        omml = to_omml(mathml)
        if len(omml) > 500000: return None
        checked = ET.fromstring(f'<root xmlns:m="{M}">{omml}</root>')
        if len(checked) != 1 or checked[0].tag != '{' + M + '}oMath': return None
        return omml
    except Exception:
        # A failed expression must not prevent exporting the rest of the document.
        return None


class MathContext:
    def __init__(self, text):
        self.text, self.expressions, prefix = protect_math(text)
        self.pattern = re.compile('(' + re.escape(prefix) + r'\d+\ue001)')
        self.failed = set(); self.cache = {}; self.attempts = 0

    def render(self, token, display=False):
        expression = self.expressions[token]
        if expression.tex not in self.cache:
            self.attempts += 1
            self.cache[expression.tex] = office_math(expression.tex) if self.attempts <= MAX_FORMULAS else None
        xml = self.cache[expression.tex]
        if xml is None:
            self.failed.add(token)
            # Exact source, no second pass through Markdown emphasis parsing.
            return '<w:r><w:rPr><w:shd w:val="clear" w:fill="F2F2F2"/></w:rPr><w:t xml:space="preserve">' + escape(expression.source) + '</w:t></w:r>'
        return '<m:oMathPara>' + xml + '</m:oMathPara>' if display and expression.display else xml
