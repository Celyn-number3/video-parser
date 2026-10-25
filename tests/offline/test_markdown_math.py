"""Exercise the actual TypeScript math lexer with Node; no model or network calls."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MarkdownMathLexerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        compiler = ROOT / 'frontend/node_modules/typescript/bin/tsc'
        if not cls.node or not compiler.is_file():
            raise unittest.SkipTest('Frontend Node/TypeScript dependencies are required')
        artifacts = ROOT / '.local/work/artifacts/latex-rendering'
        artifacts.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='lexer-', dir=artifacts)
        cls.addClassCleanup(cls.temp.cleanup)
        result = subprocess.run([cls.node, str(compiler), '--ignoreConfig', '--target', 'ES2022', '--module', 'ESNext',
            '--skipLibCheck', '--outDir', cls.temp.name, 'src/components/markdownMath.ts'],
            cwd=ROOT / 'frontend', capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        module = Path(cls.temp.name) / 'markdownMath.mjs'
        module.write_bytes((module.with_suffix('.js')).read_bytes())
        cls.script = f"import {{protectMath}} from {json.dumps(module.as_uri())};" + '''
import fs from 'node:fs';
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = protectMath(source);
let restored = result.text;
for (const [token, expression] of result.expressions) restored = restored.replace(token, () => expression.source);
console.log(JSON.stringify({text:result.text, restored, expressions:[...result.expressions.values()]}));
'''

    def check(self, source, expected):
        result = subprocess.run([self.node, '--input-type=module', '-e', self.script], input=json.dumps(source),
            capture_output=True, text=True, encoding='utf-8', check=True, timeout=10)
        data = json.loads(result.stdout)
        self.assertEqual(data['restored'], source, 'Protection must round-trip source exactly')
        self.assertEqual([(item['tex'], item['display']) for item in data['expressions']], expected)
        return data

    def test_plain_markdown(self):
        self.check('## 标题\n1. **要点** [00:12]\n普通文本。', [])

    def test_four_delimiters(self):
        self.check(r'\(x_1\) $y^2$ \[A\] $$\frac{a}{b}$$',
                   [('x_1', False), ('y^2', False), ('A', True), (r'\frac{a}{b}', True)])

    def test_multiline_matrix_keeps_row_separators(self):
        tex = '\n' + r'\begin{bmatrix}1 & 2 \\ 3 & 4\end{bmatrix}' + '\n'
        self.check('\\[' + tex + '\\]', [(tex, True)])

    def test_fenced_code_and_unclosed_fence(self):
        self.check('```latex\n\\(x\\)\n$$y$$\n```\n$z$', [('z', False)])
        self.check('```latex\n$z$', [])

    def test_longer_and_tilde_fences(self):
        self.check('````latex\n```\n$x$\n````\n$z$', [('z', False)])
        self.check('~~~latex\n$x$\n~~~\n$z$', [('z', False)])

    def test_inline_code(self):
        self.check(r'`$x$` 与 ``\(y\)`` 和 $z$', [('z', False)])

    def test_currency_and_escape(self):
        self.check(r'$20 和 $30；费用 \$5；公式 $x$。', [('x', False)])
        self.check(r'\\(x\\) 与 \(y\)；\$x\$。', [('y', False)])
        self.check(r'$\text{\$5}$', [(r'\text{\$5}', False)])

    def test_currency_cannot_capture_dollars_inside_code_or_links(self):
        self.check(r'费用 $20 和 $30；`$x_1$`；[价格](https://example.com/$x$)。', [])

    def test_dollar_whitespace_and_newline(self):
        self.check('$ x$ 与 $y $。\n$a\nb$', [])

    def test_unfinished_expressions(self):
        for value in (r'\(x', r'\[x', '$$x', '$x'):
            with self.subTest(value=value):
                self.check(value, [])

    def test_markdown_characters_inside_tex_are_protected(self):
        data = self.check('**\\(x*y\\)**\n| $|x|$ | 值 |', [('x*y', False), ('|x|', False)])
        self.assertNotIn('x*y', data['text'])
        self.assertEqual(data['text'].count('|'), 3)

    def test_existing_placeholder_like_input_does_not_collide(self):
        source = '\uE000M0\uE001 \uE000MM1\uE001 $x$'
        self.check(source, [('x', False)])

    def test_links_keep_dollars_in_url(self):
        self.check('[费用](https://example.invalid/$x$) 和 $y$', [('y', False)])

    def test_indented_multiline_list_math(self):
        tex = '\n  x+y\n  '
        self.check('1. 公式：\\[' + tex + '\\]\n2. 后续', [(tex, True)])

    def test_blockquote_markers_are_not_part_of_tex(self):
        self.check('> \\[\n> x+y\n> \\]', [('\nx+y\n', True)])
