"""Real production frontend, isolated static server, mocked workspace API only."""
import json,os,threading,time
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'runtimes/browsers'))
OUT=ROOT/'.local/work/artifacts/preview-download-placement';OUT.mkdir(parents=True,exist_ok=True)
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'frontend/dist')))
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
URL=f'http://127.0.0.1:{server.server_port}'
checks=[];errors=[];unexpected=[]
def check(label,condition=True):
    assert condition,label
    checks.append(label)
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  page=browser.new_page(viewport={'width':1440,'height':900})
  page.on('pageerror',lambda error:errors.append(str(error)))
  project={'id':'a'*32,'title':'Sintel（模拟进度）','platform':'youtube','part':None,'location':'mock/youtube','identity_status':'verified','archive_url':'/mock/archive','resources':[]}
  video={'id':'b'*32,'title':project['title'],'platform':'YouTube','source_url':'https://www.youtube.com/watch?v=eRsGyueVLvQ','cover_url':None,'cover_download_url':None,'warning':None,'project':project,'media':None,'qualities':[{'id':'default','label':'最高 1080p · MP4','width':None,'height':None,'media':None}],'default_quality_id':'default'}
  job={'id':'c'*32,'kind':'video','project_id':project['id'],'title':project['title'],'state':'running','phase':'downloading','message':'模拟：正在下载当前轨道','result':None,'progress':{'bytes':524288,'total_bytes':1048576,'speed_bytes_per_second':65536,'eta_seconds':8,'track':1,'tracks':2,'sampled_at':time.time()}}
  def api(route):
   path=urlsplit(route.request.url).path.split('/api/workspace',1)[-1]
   if path=='/config':route.fulfill(json={'platforms':['YouTube','哔哩哔哩','抖音'],'ai_configured':False,'media_ready':True,'subtitles_ready':True,'transcription_ready':True,'archive_root':'mock'})
   elif path=='/tasks':route.fulfill(json={'jobs':[job]})
   elif path=='/parse':route.fulfill(json=video)
   elif path.endswith('/prepare-task') or path=='/tasks/'+job['id']:route.fulfill(json=job)
   elif path.endswith('/cancel'):
    job.update(state='cancelled',phase='cancelled',message='模拟：任务已取消；归档成果保留。');route.fulfill(json=job)
   else:unexpected.append(path);route.fulfill(status=400,json={'detail':'Mock blocks processing'})
  page.route('**/api/workspace/**',api)
  page.goto(URL,wait_until='networkidle')
  page.locator('#source').fill(video['source_url']);page.locator('.parse-button').click()
  expect(page.locator('.info-title')).to_have_text(project['title'])
  page.locator('.download-button').click()
  bar=page.locator('[data-testid="page-workspace"] [role="progressbar"]')
  expect(bar).to_have_attribute('aria-valuenow','50');check('Known exact length reports current-track 50%')
  meta=page.locator('[data-testid="page-workspace"] .progress-block')
  expect(meta).to_contain_text('当前轨道 1/2');check('Track scope explicit, not whole-task percent')
  expect(meta).to_contain_text('64.0 KB/s');check('Backend measured rate shown')
  expect(meta).to_contain_text('本轨预计剩余 8 秒');check('Backend ETA shown')
  check('Progress belongs to video preview',page.locator('#video-stage [role="progressbar"]').count()==1)
  check('No duplicate progress in inspector',page.locator('.details-panel .progress-block,.details-panel .status').count()==0)
  expect(page.locator('#video-stage .download-preview-message')).to_contain_text('正在下载当前轨道');check('Status moved into preview')
  check('Old preparing placeholder replaced','正在准备视频，请稍候' not in page.locator('#video-stage').inner_text())
  for width in [1440,768,390,320,280]:
   page.set_viewport_size({'width':width,'height':900})
   check(f'Progress fits viewport {width}',page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth'))
   stage=page.locator('#video-stage').bounding_box();feedback=page.locator('.download-preview-feedback').bounding_box()
   check(f'Preview feedback centered horizontally {width}',abs((stage['x']+stage['width']/2)-(feedback['x']+feedback['width']/2))<=1)
   check(f'Preview feedback centered vertically {width}',abs((stage['y']+stage['height']/2)-(feedback['y']+feedback['height']/2))<=1)
   check(f'Feedback stays inside preview {width}',feedback['x']>=stage['x'] and feedback['y']>=stage['y'] and feedback['x']+feedback['width']<=stage['x']+stage['width'] and feedback['y']+feedback['height']<=stage['y']+stage['height'])
  page.set_viewport_size({'width':1440,'height':900})
  page.screenshot(path=str(OUT/'preview-progress-mock.png'),full_page=True)
  job['progress']['sampled_at']=time.time()-10
  expect(meta).to_contain_text('本轨剩余时间未知',timeout=6000);check('Stale sample drops rate and ETA')
  check('Stale sample does not retain measured speed','KB/s' not in meta.inner_text())
  job['progress']={'bytes':524288,'total_bytes':0,'sampled_at':time.time()}
  expect(bar).not_to_have_attribute('aria-valuenow','50',timeout=6000)
  check('Unknown total omits aria-valuenow',bar.get_attribute('aria-valuenow') is None)
  expect(meta).to_contain_text('总大小未知');check('Unknown size clearly named')
  job['progress']={'bytes':524288,'total_bytes':1048576,'estimated_total':1,'sampled_at':time.time()}
  expect(meta).to_contain_text('约 1.0 MB',timeout=6000)
  check('Estimated totals do not claim exact percentage',bar.get_attribute('aria-valuenow') is None)
  job['progress']={'bytes':524288,'total_bytes':1048576,'speed_bytes_per_second':65536,'eta_seconds':8,'track':2,'tracks':2,'sampled_at':time.time()}
  expect(meta).to_contain_text('当前轨道 2/2',timeout=6000);check('Second track clearly identified')
  page.locator('.app-sidebar nav').get_by_role('button',name='任务中心',exact=True).click()
  taskbar=page.locator('[data-testid="page-tasks"] [role="progressbar"]')
  expect(taskbar).to_have_attribute('aria-valuenow','50',timeout=6000);check('Task center uses same real metrics')
  page.screenshot(path=str(OUT/'progress-mock.png'),full_page=True)
  job.update(phase='merging',message='模拟：正在合并音视频；剩余时间未知。',progress={})
  expect(taskbar).to_have_count(0,timeout=6000);check('Merge stage has no fake percentage or transfer ETA')
  page.get_by_role('button',name='取消任务',exact=True).click()
  expect(page.locator('.task-list')).to_contain_text('已取消',timeout=6000);check('Cancellation preserves truthful terminal feedback')
  check('No browser runtime errors',not errors);check('No unmocked workspace processing',not unexpected)
  browser.close()
 # Existing integration tests reuse the new build but write separate evidence, not old reports.
 from tests.browser import browser_frontend_modern as modern
 modern.URL=URL;modern.OUT=OUT/'modern-regression';modern.main()
 from tests.browser import browser_frontend_layout as layout
 layout.URL=URL;layout.OUT=OUT/'layout-regression';layout.main()
finally:
 server.shutdown();server.server_close();thread.join(5)
 (OUT/'browser-feedback.json').write_text(json.dumps({'checks':checks,'errors':errors,'unexpected':unexpected},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'checks':len(checks),'errors':len(errors),'unexpected':len(unexpected)},ensure_ascii=False))
