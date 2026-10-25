"""Actual TypeScript extraction, including pre-existing chapter regressions."""
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from tests.browser import browser_chapter_timeline as original

ROOT=Path(__file__).resolve().parents[2]

class ChapterMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        art=ROOT/'.local/work/artifacts/math-surface-repair';art.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(prefix='chapter-tests-',dir=art);cls.addClassCleanup(cls.temp.cleanup)
        subprocess.run(['node',str(ROOT/'frontend/node_modules/typescript/bin/tsc'),'src/features/analysis/chapters.ts','--ignoreConfig','--target','es2022','--module','esnext','--outDir',cls.temp.name,'--skipLibCheck'],cwd=ROOT/'frontend',check=True,capture_output=True)
        root=Path(cls.temp.name);math=(root/'components/markdownMath.js').read_bytes()
        import base64
        code=(root/'features/analysis/chapters.js').read_text(encoding='utf-8').replace("'../../components/markdownMath'",json.dumps('data:text/javascript;base64,'+base64.b64encode(math).decode()))
        cls.script='import {extractChapters} from '+json.dumps('data:text/javascript;base64,'+base64.b64encode(code.encode()).decode())+";import fs from 'node:fs';console.log(JSON.stringify(extractChapters(JSON.parse(fs.readFileSync(0,'utf8')),3000)));"
    def extract(self,text):
        r=subprocess.run(['node','--input-type=module','-e',self.script],input=json.dumps(text),capture_output=True,text=True,encoding='utf-8',check=True,timeout=15)
        return json.loads(r.stdout)
    def test_existing_chapter_regressions(self):original.main(extract_only=True)
    def test_subscripts_bars_colons_and_emphasis_preserved(self):
        for formula in [r'\(x_1\)',r'\(|x|\)',r'\(f:A\to B\)',r'$a*b$',r'$$x_{ij}$$']:
            row=self.extract('## [00:02] **标题 '+formula+'** — 介绍 '+formula)[0]
            self.assertEqual(row['title'],'标题 '+formula);self.assertEqual(row['description'],'介绍 '+formula)
    def test_multiline_matrix_and_formula_timestamp_are_atomic(self):
        formula='\\[\n\\begin{bmatrix}1&2\\\\3&4\\end{bmatrix}\n\\]'
        row=self.extract('[00:02] 矩阵 '+formula+'\n介绍 \\(12:34\\)。')[0]
        self.assertIn(formula,row['title']);self.assertIn(r'\(12:34\)',row['description'])
        self.assertEqual(self.extract(r'## \(12:34\) 不是章节'),[])
    def test_fenced_and_inline_code_stay_literal(self):
        self.assertEqual(self.extract('```\n[00:01] \\(x_1\\)\n```'),[])
        self.assertEqual(self.extract('````\n```\n[00:01] $x$\n~~~\n[00:02] $y$\n````'),[])
        row=self.extract(r'[00:02] 示例 `\(x_1\)`')[0]
        self.assertEqual(row['title'],r'示例 `\(x_1\)`')
    def test_soft_limits_do_not_cut_math_or_leak_tokens(self):
        formula=r'\(x_{12345678901234567890}\)'
        row=self.extract('[00:02] '+'长'*155+formula+'尾巴 — '+'长'*1995+formula+'尾巴')[0]
        self.assertTrue(row['title'].endswith(formula));self.assertTrue(row['description'].endswith(formula))
        self.assertNotIn('\ue000',json.dumps(row,ensure_ascii=False))
    def test_incomplete_subscript_and_currency_not_rewritten(self):
        self.assertEqual(self.extract(r'[00:02] 公式 \(x_1')[0]['title'],r'公式 \(x_1')
        self.assertEqual(self.extract('[00:02] 费用 $20 和 $30')[0]['title'],'费用 $20 和 $30')

if __name__=='__main__':unittest.main()
