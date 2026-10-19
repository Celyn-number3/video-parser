"""Chapter extraction + built UI. Reuses the isolated learning fixture; no real model or download."""
from pathlib import Path
import subprocess
import tempfile
from tests.browser.browser_learning_view import main as check_browser

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory(prefix='chapters-ts-') as output:
        subprocess.run(['node', str(ROOT / 'frontend/node_modules/typescript/bin/tsc'),
            'src/features/analysis/chapters.ts', '--ignoreConfig', '--target', 'es2022', '--module', 'esnext',
            '--outDir', output, '--skipLibCheck'], cwd=ROOT / 'frontend', check=True)
        script = r"""import fs from 'node:fs'; import assert from 'node:assert/strict';
const code=fs.readFileSync(process.argv[1],'utf8');
const {extractChapters,chapterTime}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const input='## [00:00] 开场\n- **[00:05]** 核心概念\n| 00:12 - 00:20 | 总结 |\n[00:05] 重复\n[99:99] 无效\n[00:21] 超出长度\n正文中的 00:02 不作为章节\n```\n[00:03] 代码示例\n```\nhttps://example.invalid/00:04';
assert.deepEqual(extractChapters(input,20),[{time:0,title:'开场'},{time:5,title:'核心概念'},{time:12,title:'总结'}]);
assert.deepEqual(extractChapters('### [1:02:03] 3D 建模',4000),[{time:3723,title:'3D 建模'}]);
assert.deepEqual(extractChapters('[00:08] 后面\n[00:02] 前面',20).map(c=>c.time),[2,8]);
assert.deepEqual(extractChapters('没有时间点的摘要。'),[]);
assert.deepEqual(extractChapters('[00:20] 视频结束',20),[]);
assert.deepEqual(extractChapters('[00:00] 开场 —— 学习目标。\n[00:05] 核心：定义和例子。',20),[
 {time:0,title:'开场',description:'学习目标。'},{time:5,title:'核心',description:'定义和例子。'}]);
assert.deepEqual(extractChapters('## [00:00] 开场\n介绍一。\n- 介绍二。\n```\n不能当介绍的代码\n```\n## [00:05] 第二章\n下一章介绍。\n## 附录\n不能串入上一章。',20),[
 {time:0,title:'开场',description:'介绍一。\n- 介绍二。'},{time:5,title:'第二章',description:'下一章介绍。'}]);
assert.deepEqual(extractChapters('| 00:00 | 标题 | 表格说明 |\n| 00:05 | 二 | 第二段 |',20),[
 {time:0,title:'标题',description:'表格说明'},{time:5,title:'二',description:'第二段'}]);
assert.deepEqual(extractChapters('[00:00] 第一章\n[99:99] 无效\n不能混入。\n[00:30] 超长\n也不能混入。',20),[{time:0,title:'第一章'}]);
assert.deepEqual(extractChapters('## [00:00]\n独立标题\n真正介绍。',20),[{time:0,title:'独立标题',description:'真正介绍。'}]);
assert.deepEqual(extractChapters('[00:00] 原文 —— 初始介绍\n[00:00] 重复 —— 不覆盖\n不合并重复介绍。',20),[{time:0,title:'原文',description:'初始介绍'}]);
assert.equal(extractChapters('[00:00] 长文 —— '+ '长'.repeat(2200),20)[0].description.length,2000);
assert.equal(extractChapters(Array.from({length:130},(_,i)=>`[${Math.floor(i/60)}:${String(i%60).padStart(2,'0')}] 第${i}段`).join('\n')).length,128);
assert.equal(chapterTime(3723),'1:02:03');assert.equal(chapterTime(5),'00:05');
assert.deepEqual(extractChapters('[00:00] 标题 —— 解释：保留 - 标点。',20),[{time:0,title:'标题',description:'解释：保留 - 标点。'}]);
console.log('PASS: chapter extraction, bounds, deduplication, code/prose rejection and time formatting');"""
        subprocess.run(['node', '--input-type=module', '-e', script, str(Path(output) / 'chapters.js')], cwd=ROOT, check=True)
    check_browser(timeline_test=True)


if __name__ == '__main__': main()
