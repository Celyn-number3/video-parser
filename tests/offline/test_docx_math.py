"""Local export only: editable Office Math, preserved source and hostile-input fallbacks."""
import io
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from video_parser.services import docx_export, docx_math

NS={'w':docx_export.W,'m':docx_math.M}

class DocxMathTests(unittest.TestCase):
    def document(self,text):
        with ZipFile(io.BytesIO(docx_export.build(text,'合成公式验收'))) as z:
            for name in z.namelist():
                if name.endswith('.xml') or name.endswith('.rels'):ET.fromstring(z.read(name))
            xml=z.read('word/document.xml').decode()
        if '\ue000' not in text: self.assertNotIn('\ue000',xml)
        return ET.fromstring(xml)
    def text(self,root):return ''.join(root.itertext())
    def test_four_delimiters_native_math_not_images(self):
        root=self.document(r'行内 \(x_1\) 与 $y^2$。'+'\n\\[\\frac{a}{b}\\]\n$$\\sqrt{x}$$')
        self.assertEqual(len(root.findall('.//m:oMath',NS)),4)
        self.assertEqual(len(root.findall('.//m:oMathPara',NS)),2)
        for tag in ['sSub','sSup','f','rad']:self.assertIsNotNone(root.find('.//m:'+tag,NS))
        self.assertIsNone(root.find('.//w:drawing',NS))
    def test_matrices_and_sum_have_native_structure(self):
        root=self.document(r'\[\begin{bmatrix}1 & 2 \\ 3 & 4\end{bmatrix}\]'+'\n'+r'$\sum_{i=1}^{n} x_i$')
        self.assertEqual(len(root.findall('.//m:m/m:mr',NS)),2)
        self.assertEqual(len(root.findall('.//m:m/m:mr/m:e',NS)),4)
        self.assertIsNotNone(root.find('.//m:nary',NS))
    def test_titles_lists_quotes_and_table_keep_math(self):
        root=self.document('## 标题 $x_1$\n- **分数 $\\frac{a}{b}$**\n> $$\\sqrt{x}$$\n| 量 | 值 |\n| --- | --- |\n| 绝对值 | $|x|$ |')
        self.assertEqual(len(root.findall('.//m:oMath',NS)),4)
        self.assertEqual(len(root.findall('.//w:tr',NS)),2)
        self.assertEqual(len(root.findall('.//w:tr',NS)[1].findall('w:tc',NS)),2)
    def test_multiline_matrix_inside_blockquote(self):
        root=self.document('> \\[\n> \\begin{bmatrix}1&2\\\\3&4\\end{bmatrix}\n> \\]')
        self.assertIsNotNone(root.find('.//m:m',NS))
    def test_currency_code_links_and_escaped_dollar_are_literal(self):
        text='费用 $20 和 $30；`$x_1$`；[价格](https://example.com/$x$)。\\$5\n~~~tex\n\\(x_1\\)\n~~~\n```latex\n$$y$$\n```'
        root=self.document(text);self.assertEqual(len(root.findall('.//m:oMath',NS)),0)
        for value in ('$20','$30','$x_1$',r'\(x_1\)','$$y$$'):self.assertIn(value,self.text(root))
    def test_invalid_unknown_and_unsafe_keep_exact_source(self):
        for source in [r'\(x_{1\)',r'\(x_1}\)',r'\(\frac{1}\)',r'\(\unknowncommand{x}\)',r'$\href{file:///private}{x}$',r'$\def\x{\x}\x$',r'$\input{private}$']:
            with self.subTest(source=source):
                root=self.document(source);self.assertEqual(len(root.findall('.//m:oMath',NS)),0)
                self.assertIn(source,self.text(root));self.assertIn('已保留 LaTeX 原文',self.text(root))
    def test_unfinished_keeps_text_without_guessing(self):
        root=self.document(r'未完成 \(x_1 与 $y');self.assertIn(r'\(x_1',self.text(root));self.assertEqual(len(root.findall('.//m:oMath',NS)),0)
    def test_input_xml_cannot_inject_relationship_or_field(self):
        source=r'$\text{</w:t><w:fldSimple w:instr="INCLUDETEXT private"/>}$'
        root=self.document(source);self.assertIsNone(root.find('.//w:fldSimple',NS));self.assertIsNone(root.find('.//w:hyperlink',NS))
    def test_length_depth_and_count_limits_fall_back(self):
        for tex in ['x'*4097,'{'*49+'x'+'}'*49]:
            root=self.document('$'+tex+'$');self.assertEqual(len(root.findall('.//m:oMath',NS)),0);self.assertIn(tex,self.text(root))
        root=self.document('\n'.join(f'$x_{{{i}}}$' for i in range(130)))
        self.assertEqual(len(root.findall('.//m:oMath',NS)),128);self.assertIn('$x_{129}$',self.text(root))
    def test_placeholder_collision_and_plain_export(self):
        root=self.document('标记 \ue000M0\ue001 不应被当成公式。')
        self.assertIn('标记',self.text(root))
    def test_safe_formula_after_bad_formula_still_converts(self):
        root=self.document(r'$\badcommand$ 然后 $x_1$');self.assertEqual(len(root.findall('.//m:oMath',NS)),1)
        self.assertIn(r'$\badcommand$',self.text(root))

if __name__=='__main__':unittest.main()
