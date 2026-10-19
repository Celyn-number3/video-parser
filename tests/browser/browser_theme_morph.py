"""Focused Morphicons theme regression; all business APIs use existing synthetic fixtures."""
import unittest
from playwright.sync_api import expect
from tests.browser import browser_product_improvements as harness


class ThemeMorphBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.ProductImprovementsBrowserTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        harness.ProductImprovementsBrowserTests.tearDownClass()

    def setUp(self):
        self.fixture = harness.ProductImprovementsBrowserTests('test_settings_cross_tab_updates')
        self.fixture.setUp()
        self.page = self.fixture.page

    def tearDown(self):
        self.assertFalse(any(method == 'POST' for method, _, _ in self.fixture.requests))
        self.fixture.tearDown()

    def open(self, reduced='no-preference', saved=True):
        self.page.emulate_media(reduced_motion=reduced, color_scheme='dark')
        if saved:
            self.page.add_init_script("if(localStorage.getItem('vp-theme')===null)localStorage.setItem('vp-theme','dark')")
        self.page.goto(self.fixture.url, wait_until='domcontentloaded')
        self.button = self.page.locator('.theme-toggle')
        expect(self.button).to_have_attribute('aria-label', '切换到浅色主题')
        expect(self.button.locator('svg.theme-morph-icon path')).to_have_count(1)
        self.page.evaluate('window.originalThemeSvg=document.querySelector(".theme-toggle svg")')

    def sample_toggle(self, frames):
        return self.page.evaluate('''frames => new Promise(resolve => {
          const button=document.querySelector('.theme-toggle');
          const shape=()=>[...button.querySelectorAll('svg path')].map(p=>p.getAttribute('d')).join('|');
          const before=shape(), samples=[before];
          button.click();
          let count=0;
          const read=()=>{samples.push(shape());if(++count>=frames) resolve({unique:new Set(samples).size,before,last:shape(),sameSvg:button.querySelector('svg')===window.originalThemeSvg});else requestAnimationFrame(read)};
          requestAnimationFrame(read);
        })''', frames)

    def test_real_path_morph_and_saved_theme_survive_reload(self):
        self.open()
        before = self.button.bounding_box()
        values = self.sample_toggle(45)
        self.assertGreaterEqual(values['unique'], 3, 'Expected real intermediate SVG paths, not a static/CSS icon swap')
        self.assertTrue(values['sameSvg'])
        self.assertNotEqual(values['before'], values['last'])
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'light')
        self.assertEqual(self.page.evaluate("localStorage.getItem('vp-theme')"), 'light')
        after = self.button.bounding_box()
        self.assertAlmostEqual(before['width'], after['width'], delta=1)
        self.assertAlmostEqual(before['height'], after['height'], delta=1)
        self.page.reload(wait_until='domcontentloaded')
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'light')
        expect(self.page.locator('.theme-toggle')).to_have_attribute('aria-label', '切换到深色主题')
        expect(self.page.locator('.theme-toggle svg')).to_have_attribute('data-icon', 'lucide:moon')

    def test_reduced_motion_skips_intermediate_shapes(self):
        self.open(reduced='reduce')
        values = self.sample_toggle(8)
        self.assertLessEqual(values['unique'], 2, 'Reduced motion should contain only the two endpoint shapes')
        self.assertNotEqual(values['before'], values['last'])
        self.assertTrue(values['sameSvg'])
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'light')

    def test_keyboard_and_rapid_clicks_keep_one_icon(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.open()
        self.button.focus(); self.button.press('Space')
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'light')
        self.button.press('Enter')
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'dark')
        for theme in ('light', 'dark', 'light'):
            self.button.click()
            expect(self.page.locator('html')).to_have_attribute('data-theme', theme)
        expect(self.button.locator('svg')).to_have_count(1)
        self.assertTrue(self.page.evaluate('document.querySelector(".theme-toggle svg")===window.originalThemeSvg'))
        self.assertEqual(self.page.evaluate("localStorage.getItem('vp-theme')"), 'light')

    def test_system_theme_follows_until_a_manual_choice(self):
        self.open(reduced='reduce', saved=False)
        self.assertIsNone(self.page.evaluate("localStorage.getItem('vp-theme')"))
        self.page.emulate_media(color_scheme='light')
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'light')
        self.assertIsNone(self.page.evaluate("localStorage.getItem('vp-theme')"))
        self.button.click()
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'dark')
        self.page.emulate_media(color_scheme='dark')
        self.page.emulate_media(color_scheme='light')
        expect(self.page.locator('html')).to_have_attribute('data-theme', 'dark')
        self.assertEqual(self.page.evaluate("localStorage.getItem('vp-theme')"), 'dark')
