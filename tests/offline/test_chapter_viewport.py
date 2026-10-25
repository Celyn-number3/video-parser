import json,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class ChapterViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        art=ROOT/'.local/work/artifacts/chapter-reading-layout';art.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=art);cls.addClassCleanup(cls.temp.cleanup)
        subprocess.run(['node',str(ROOT/'frontend/node_modules/typescript/bin/tsc'),'src/features/analysis/chapterViewport.ts','--ignoreConfig','--target','ES2022','--module','ESNext','--skipLibCheck','--outDir',cls.temp.name],cwd=ROOT/'frontend',check=True,capture_output=True)
        p=Path(cls.temp.name)/'chapterViewport.js';m=p.with_suffix('.mjs');m.write_bytes(p.read_bytes())
        cls.script='import {chapterWindow} from '+json.dumps(m.as_uri())+';import fs from "node:fs";console.log(JSON.stringify(chapterWindow(...JSON.parse(fs.readFileSync(0,"utf8")))));'
    def fit(self,heights,room,scroll):
        rows=[];top=0
        for height in heights:rows.append({'top':top,'height':height});top+=height+6
        p=subprocess.run(['node','--input-type=module','-e',self.script],input=json.dumps([rows,room,scroll]),capture_output=True,text=True,check=True,timeout=10)
        return json.loads(p.stdout)
    def test_equal_rows_fit_without_partial_bottom(self):self.assertEqual(self.fit([44]*20,227,0),{'top':0,'height':194})
    def test_variable_heights_and_nearest_start(self):self.assertEqual(self.fit([44,80,60,44,44,44],210,64),{'top':50,'height':196})
    def test_end_fills_preceding_whole_rows(self):self.assertEqual(self.fit([44]*8,227,349),{'top':200,'height':194})
    def test_single_and_empty(self):
        self.assertEqual(self.fit([44],500,0),{'top':0,'height':44});self.assertEqual(self.fit([],500,0),{'top':0,'height':0})
    def test_oversized_row_does_not_trap_reading(self):self.assertEqual(self.fit([800,44],200,300),{'top':300,'height':200})
if __name__=='__main__':unittest.main()
