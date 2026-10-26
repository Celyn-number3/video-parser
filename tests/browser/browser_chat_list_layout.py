"""Chat Markdown must keep inline flow inside lists; isolated fixture sessions only."""
import copy,unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as math

QUESTION=r'''- **问题**：请解释 \(Ax=b\)。
  - **补充**：说明列向量。
'''
ANSWER=r'''这节课是**线性代数入门**，理解 \(Ax=b\)。

- **行图像**：二维里，两条直线的交点是方程组的解。
- **列图像**：把 \(Ax=b\) 看成矩阵各列向量的线性组合。
  - **分量**：系数 \(x_1\) 与向量 $b$。

1. **第一步**：观察系数。
2. **第二步**：回看 [00:02] 的说明。

显示公式仍单独排版：
\[
\begin{bmatrix}1&2\\3&4\end{bmatrix}x=b
\]
'''
class ChatListLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):math.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):math.MarkdownMathBrowserTests.tearDownClass()
    def setUp(self):
        self.h=math.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');self.h.setUp();self.addCleanup(self.h.tearDown);self.page=self.h.page
        self.h.f.sessions=[{'id':'f'*32,'title':'列表排版测试','title_generated':True,'video_resource':self.h.f.resource,'origin_record':None,'agent':{'engine':'api','model':'','effort':''},'messages':[{'id':'one','question':QUESTION,'answer':ANSWER,'position':0,'created_at':''}],'created_at':'','updated_at':''}]
        self.original=copy.deepcopy(self.h.f.sessions);self.h.open(learning=True);self.page.get_by_role('tab',name='AI 对话',exact=True).click()
        self.log=self.page.locator('.ai-chat-log');self.answer=self.log.locator('.ai-chat-answer');expect(self.answer).to_contain_text('行图像')
    def geometry(self):
        data=self.log.evaluate('''e=>({outer:[...e.children].map(x=>({display:getComputedStyle(x).display,direction:getComputedStyle(x).flexDirection})),items:[...e.querySelectorAll('.markdown li')].map(li=>{const h=li.querySelector('strong'),n=[...li.childNodes].find(n=>n.nodeType===3&&n.textContent.startsWith('：'));let offset=null;if(h&&n){const r=document.createRange();r.setStart(n,0);r.setEnd(n,1);offset=r.getBoundingClientRect().top-h.getBoundingClientRect().top}return {display:getComputedStyle(li).display,marker:getComputedStyle(li).listStyleType,offset}}),overflow:document.documentElement.scrollWidth>innerWidth})''')
        self.assertEqual(len(data['items']),7,data)
        for item in data['items']:
            self.assertEqual(item['display'],'list-item',data);self.assertNotEqual(item['marker'],'none',data);self.assertIsNotNone(item['offset'],data);self.assertLess(abs(item['offset']),2,data)
        self.assertEqual(data['outer'],[{'display':'flex','direction':'column'}]);self.assertFalse(data['overflow'])
    def test_question_answer_bold_inline_math_and_nested_lists_keep_flow(self):
        for theme in ('dark','light'):
            self.page.evaluate('(x)=>document.documentElement.dataset.theme=x',theme)
            for width in (1440,768,390,280):
                self.page.set_viewport_size({'width':width,'height':1000});self.geometry()
        self.assertEqual(self.h.f.sessions,self.original)
    def test_display_math_and_timestamp_seek_are_preserved(self):
        self.geometry();expect(self.answer.locator('.katex-display')).to_have_count(1)
        expect(self.answer.locator('li .md-math')).to_have_count(3);expect(self.answer.locator('li .md-math-display')).to_have_count(0)
        expect(self.answer.locator('.md-math-fallback')).to_have_count(0)
        self.answer.get_by_role('button',name='00:02',exact=True).click()
        self.page.wait_for_function('()=>document.querySelector("video").currentTime>=1.9');self.page.locator('video').evaluate('(v)=>v.pause()')
        self.assertEqual(self.h.f.sessions,self.original)
    def test_reload_preserves_original_markdown_and_message_layout(self):
        self.page.reload();self.page.get_by_role('button',name='学习视图',exact=True).click();self.page.get_by_role('tab',name='AI 对话',exact=True).click()
        expect(self.answer).to_contain_text('行图像');self.geometry();self.assertEqual(self.h.f.sessions,self.original)
        self.assertEqual(self.h.f.sessions[0]['messages'][0]['answer'],ANSWER)
