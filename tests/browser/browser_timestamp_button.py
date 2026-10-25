"""Fixture-only timestamp appearance and keyboard/mouse seek regression."""
import json,re,unittest
from playwright.sync_api import expect
from tests.browser import browser_markdown_math as harness

def contrast(a,b):
    def luminance(c):
        values=[int(v)/255 for v in re.findall(r'\d+',c)[:3]]
        values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(v*w for v,w in zip(values,(.2126,.7152,.0722)))
    x,y=sorted((luminance(a),luminance(b)));return (y+.05)/(x+.05)

class TimestampButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):harness.MarkdownMathBrowserTests.setUpClass()
    @classmethod
    def tearDownClass(cls):harness.MarkdownMathBrowserTests.tearDownClass()
    def setUp(self):
        self.h=harness.MarkdownMathBrowserTests('test_all_four_delimiters_and_multiline_matrix');self.h.setUp();self.page=self.h.page
    def tearDown(self):self.h.tearDown()
    def test_themes_states_borders_no_tooltip_and_keyboard_seek(self):
        self.h.open('[00:05] 课程介绍与学习资源。\n\n[00:12] 矩阵 $Ax=b$。',learning=True)
        material=self.page.locator('.learning-materials');button=material.locator('.md-time').first
        measurements=[]
        for theme in ('dark','light'):
            self.page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
            for width in (1440,390):
                self.page.set_viewport_size({'width':width,'height':1000})
                for state in ('normal','hover','focus'):
                    self.page.mouse.move(0,0);button.evaluate('(e)=>e.blur()')
                    if state=='hover':button.hover()
                    elif state=='focus':
                        button.focus();self.page.keyboard.press('Tab');self.page.keyboard.press('Shift+Tab')
                    self.page.wait_for_function("([s,t])=>{const c=getComputedStyle(document.querySelector('.learning-materials .md-time'));return c.color===(t==='dark'?'rgb(250, 250, 250)':'rgb(10, 10, 10)') && c.backgroundColor===(t==='dark'?'rgb(38, 38, 38)':'rgb(244, 244, 244)')}",arg=[state,theme])
                    data=button.evaluate('(e)=>{const c=getComputedStyle(e);return {color:c.color,bg:c.backgroundColor,border:c.borderTopColor,borderWidth:c.borderTopWidth,borderStyle:c.borderTopStyle,outline:c.outlineStyle,title:e.hasAttribute("title"),width:e.getBoundingClientRect().width}}')
                    self.assertFalse(data['title']);self.assertEqual(data['borderWidth'],'1px');self.assertEqual(data['borderStyle'],'solid')
                    self.assertGreaterEqual(contrast(data['color'],data['bg']),4.5)
                    self.assertGreaterEqual(contrast(data['border'],data['bg']),3)
                    if state=='focus':self.assertEqual(data['outline'],'solid')
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    material.screenshot(path=str(self.h.f.output/f'timestamp-{theme}-{width}-{state}.png'),animations='disabled')
                    measurements.append(dict(theme=theme,viewport=width,state=state,**data))
        (self.h.f.output/'timestamp-styles.json').write_text(json.dumps(measurements,indent=2),encoding='utf-8')
        button.focus();self.page.keyboard.press('Enter')
        self.page.wait_for_function('document.querySelector("video").currentTime>=5.1');self.page.locator('video').evaluate('(v)=>v.pause()')
        self.assertLess(self.page.locator('video').evaluate('(v)=>v.currentTime'),6)
        expect(material.locator('.katex')).to_have_count(1)

if __name__=='__main__':unittest.main()
