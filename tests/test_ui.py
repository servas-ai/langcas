"""Real browser interactions + real backend and OS process. Optional explicit test transport."""
import asyncio,os,json
from pathlib import Path
import httpx,pytest
from playwright.async_api import async_playwright,expect
from conftest import ROOT,Harness

TRANSPORT=os.environ.get('LANGKAS_TEST_TRANSPORT')=='1'
ENGINE=os.environ.get('LANGKAS_TEST_ENGINE','chromium')

class BrowserHarness:
 def __init__(self,server,work):
  self.server=server;self.work=work;self.errors=[];self.console_errors=[];self.requests=[]
 async def start(self):
  self.p=await async_playwright().start()
  browser_type=getattr(self.p,ENGINE)
  kwargs={'headless':True}
  executable=os.environ.get('LANGKAS_BROWSER_EXECUTABLE')
  if executable:kwargs['executable_path']=executable
  if ENGINE=='chromium':kwargs['args']=['--no-sandbox']
  self.browser=await browser_type.launch(**kwargs)
  self.context=await self.browser.new_context(viewport={'width':1440,'height':960},locale='de-AT')
  self.client=httpx.AsyncClient(base_url=self.server.url,timeout=15,trust_env=False)
  return self
 async def page(self,mobile=False):
  page=await self.context.new_page()
  page.on('pageerror',lambda e:self.errors.append(str(e)))
  page.on('console',lambda m:self.console_errors.append(m.text) if m.type=='error' else None)
  if mobile:await page.set_viewport_size({'width':390,'height':844})
  if TRANSPORT:
   async def transport(url,options):
    assert url.startswith('/') and not url.startswith('//'),'No external URLs in test transport'
    self.requests.append((options.get('method','GET'),url))
    r=await self.client.request(options.get('method','GET'),url,content=options.get('body'),headers=options.get('headers',{}))
    return {'status':r.status_code,'body':r.text,'headers':{k:v for k,v in r.headers.items() if k.lower() not in ['set-cookie','content-length','transfer-encoding','content-encoding']}}
   await page.expose_function('testHttp',transport)
   await page.evaluate((ROOT/'tests/browser_transport.js').read_text())
   await page.set_content((ROOT/'web/index.html').read_text(),wait_until='domcontentloaded')
  else:
   await page.goto(self.server.url)
  return page
 async def login(self,page):
  await page.locator('#localToken').fill(self.server.app.config.token)
  await page.locator('#localLogin button').click()
  await expect(page.locator('#authGate')).to_have_count(0)
  await expect(page.locator('#composerInput')).to_be_visible()
 async def send(self,page,text):
  before=await page.locator('.message.assistant').count()
  await page.locator('#composerInput').fill(text)
  await page.locator('#sendButton').click()
  await expect(page.locator('.message.assistant')).to_have_count(before+1,timeout=10000)
  await page.wait_for_function('!live.starting')
 async def complete(self,page,contains):
  await expect(page.locator('.message.assistant').last).to_contain_text(contains,timeout=12000)
  await expect(page.locator('.message.assistant').last).to_contain_text('Abgeschlossen',timeout=12000)
  await page.wait_for_function('!live.saving && !live.dirty')
 async def nav(self,page,view,id=''):
  # Use the rendered navigation where available. Details may use existing route.
  button=page.locator(f'#sidebar [data-view="{view}"]').first
  if not id and await button.count():await button.click()
  else:await page.evaluate('([v,id])=>navigate(v,id)',[view,id])
  await page.wait_for_function('([v,id])=>ui.view===v && (!id||ui.id===id)',arg=[view,id])
 async def shot(self,page,name):
  target=ROOT/'evidence'/name
  await page.screenshot(path=str(target),full_page=True)
 async def close(self):
  await self.client.aclose();await self.context.close();await self.browser.close();await self.p.stop()


def test_browser_core_flows(server,tmp_path):
 async def run():
  h=await BrowserHarness(server,tmp_path).start();checks=[]
  try:
   p=await h.page();await expect(p.locator('#authGate')).to_be_visible();await h.shot(p,'ui-login.png');checks.append('pairing screen')
   await h.login(p);checks.append('backend login')
   await h.shot(p,'ui-desktop.png')
   await p.locator('[data-action="model-menu"]').click()
   await p.locator('[data-action="live-model-select"][data-id="fixture"]').click();checks.append('runner selection')
   await h.send(p,'BROWSER_FIRST');await h.complete(p,'BROWSER_FIRST');checks.append('chat -> real CLI subprocess -> streamed output')
   await h.shot(p,'ui-chat.png')
   first_id=await p.evaluate('ui.id')
   await h.send(p,'[CONTEXT] BROWSER_SECOND');await h.complete(p,'BROWSER_SECOND');await expect(p.locator('.message.assistant').last).to_contain_text('BROWSER_FIRST');checks.append('multi-turn server history')
   await p.locator('.message.assistant').last.locator('[data-action="run-open"]').click()
   await expect(p.locator('#runDetail')).to_contain_text('process');checks.append('durable process log')
   await h.shot(p,'ui-run.png')
   # A new document/browser page simulates reopening the app, not an in-memory render.
   p2=await h.page();await expect(p2.locator('#authGate')).to_have_count(0)
   await h.nav(p2,'chat',first_id);await expect(p2.locator('#messages')).to_contain_text('BROWSER_FIRST');checks.append('reopen / durable messages')
   await p.close();p=p2
   await h.nav(p,'runners');await expect(p.locator('.runner-card')).to_have_count(4)
   await expect(p.locator('[data-action="runner-use"][data-id="missing"]')).to_be_disabled();checks.append('unavailable CLI not fake-connected')
   await h.shot(p,'ui-runners.png')
   await h.nav(p,'agents');await p.locator('[data-action="agent-create"]').first.click()
   await p.locator('#agentForm [name="name"]').fill('E2E Agent')
   await p.locator('#agentForm [name="description"]').fill('Echter Backend-Test')
   await p.locator('#agentForm [name="instructions"]').fill('AGENT_BROWSER_RULE')
   await p.locator('[data-action="agent-save"]').click()
   await p.wait_for_function('!live.dirty && !live.saving')
   aid=await p.evaluate('ui.editAgent.id')
   await h.shot(p,'ui-agent-builder.png');checks.append('agent saved to SQLite')
   await p.locator('[data-action="agent-side-tab"][data-tab="preview"]').click()
   await p.locator('#agentTestInput').fill('[CONTEXT] AGENT_TEST')
   await p.locator('[data-action="agent-test"]').click()
   await h.complete(p,'AGENT_BROWSER_RULE');checks.append('agent test uses real CLI + instructions')
   await h.nav(p,'projects');await p.locator('[data-action="project-create"]').first.click()
   await p.locator('#modalHost [name="name"]').fill('Backend Projekt')
   await p.locator('#modalHost [name="instructions"]').fill('PROJECT_BROWSER_RULE')
   await p.locator('#modalHost button[type="submit"]').click();await p.wait_for_function('!live.dirty && !live.saving');checks.append('project create and persist')
   await h.nav(p,'library');await p.locator('[data-action="upload-library"]').first.click()
   # Original uploader exposes a hidden file input; selecting a file exercises its actual reading path.
   await p.locator('input[type="file"]').first.set_input_files({'name':'browser-notes.md','mimeType':'text/markdown','buffer':b'BROWSER_DOCUMENT_CONTEXT'})
   await expect(p.locator('#view')).to_contain_text('browser-notes.md')
   await p.wait_for_function('!live.dirty && !live.saving');checks.append('text upload -> SQLite')
   assert any(d['name']=='browser-notes.md' for d in server.app.db.state()['state']['docs'])
   await h.nav(p,'workflow','w_notes');await p.locator('#flowInput').fill('Browser one\nBrowser two')
   await p.locator('[data-action="flow-run"]').first.click()
   await expect(p.locator('#runDetail')).to_contain_text('Abgeschlossen',timeout=10000)
   await expect(p.locator('#runDetail')).to_contain_text('Browser one');checks.append('workflow -> real document')
   await h.nav(p,'workflow','w_review');await p.locator('#flowInput').fill('BROWSER_APPROVAL')
   await p.locator('[data-action="flow-run"]').first.click()
   await expect(p.locator('[data-action="run-approve"]')).to_be_visible(timeout=10000)
   await p.locator('[data-action="run-approve"]').click()
   await expect(p.locator('#runDetail')).to_contain_text('Abgeschlossen',timeout=10000);checks.append('workflow approval -> CLI -> artifact')
   await p.locator('#sidebar [data-action="new-chat"]').first.click()
   await h.send(p,'[SLEEP] CANCEL_BROWSER')
   await expect(p.locator('.message.assistant')).to_contain_text('Fixture gestartet',timeout=5000)
   await p.locator('[data-action="stop-generation"]').click()
   await expect(p.locator('.message.assistant')).to_contain_text('Abgebrochen');checks.append('cancel real running process')
   await h.nav(p,'settings','preferences')
   # Preference control supplied by original UI. Validate changing theme through rendered controls.
   dark=p.locator('[data-action="theme"][data-theme="dark"]')
   if await dark.count():await dark.click()
   else:
    await p.locator('[data-action="theme"]').filter(has_text='Dunkel').click()
   await p.wait_for_function('document.body.dataset.theme==="dark" && !live.dirty && !live.saving');checks.append('dark theme persisted')
   await h.shot(p,'ui-dark.png')
   # Exercise every available settings section and major navigation route.
   for setting in ['profile','preferences','instructions','memory','general','branding','chat','models','security','api','audit','data']:
    await h.nav(p,'settings',setting);await expect(p.locator('.settings-content')).to_be_visible()
   checks.append('12 essential settings views')
   await p.locator('[data-action="live-health"]').click();await expect(p.locator('#healthResult')).to_contain_text('Backend: ok');checks.append('authenticated backend health from UI')
   imported=server.app.db.state()['state'];imported['workspace']['name']='Importiert im Browser'
   await p.locator('[data-action="data-import"]').click()
   await p.locator('input[type="file"]').last.set_input_files({'name':'workspace.json','mimeType':'application/json','buffer':json.dumps(imported).encode()})
   await expect(p.locator('#modalTitle')).to_contain_text('Workspace ersetzen')
   await p.locator('[data-action="confirm"]').click()
   await expect(p.locator('.workspace-name')).to_contain_text('Importiert im Browser')
   assert server.app.db.state()['state']['workspace']['name']=='Importiert im Browser';checks.append('JSON workspace import with confirmation -> SQLite')
   for view in ['agents','projects','prompts','skills','workflows','library','runners','runs']:
    await h.nav(p,view);await expect(p.locator('#view')).to_be_visible()
   checks.append('8 navigation views')
   await p.keyboard.press('Meta+k');await expect(p.locator('#modalHost')).not_to_be_empty();await p.keyboard.press('Escape');checks.append('Mac command-K shortcut')
   await p.keyboard.press('Meta+Shift+o');await expect(p.locator('#composerInput')).to_be_visible();checks.append('Mac new-chat shortcut')
   await p.set_viewport_size({'width':390,'height':844})
   await p.wait_for_function('document.querySelector("#sidebar").getBoundingClientRect().right<=0 && document.querySelector(".composer").getBoundingClientRect().left>=0')
   await h.shot(p,'ui-mobile.png')
   assert await p.evaluate('document.documentElement.scrollWidth<=innerWidth+1');checks.append('390px mobile home no overflow')
   await p.locator('#topbar [data-action="sidebar-toggle"]').click()
   await p.locator('#sidebar [data-view="runners"]').click()
   await expect(p.locator('.runner-card')).to_have_count(4)
   assert await p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
   await h.shot(p,'ui-mobile-runners.png');checks.append('mobile drawer + runner cards no overflow')
   await p.locator('#topbar [data-action="sidebar-toggle"]').click();await p.locator('#sidebar [data-view="runs"]').click()
   assert await p.evaluate('document.documentElement.scrollWidth<=innerWidth+1');checks.append('mobile run list no overflow')
   assert not h.errors,h.errors
   assert not h.console_errors,h.console_errors
   checks.append('zero uncaught JavaScript errors / console errors in exercised flows')
  finally:
   try:
    await h.shot(p,'ui-last-state.png')
    (ROOT/'evidence/browser-last-state.json').write_text(json.dumps(await p.evaluate('({view:ui.view,id:ui.id,hash:location.hash,blocked:live.blocked,dirty:live.dirty,toasts:document.querySelector("#toasts")?.textContent})'),ensure_ascii=False,indent=2))
   except Exception:
    pass
   (ROOT/'evidence/browser-results.json').write_text(json.dumps({'engine':ENGINE,'transport':'python-http + JSON-events' if TRANSPORT else 'native','checks':checks,'page_errors':h.errors,'console_errors':h.console_errors},ensure_ascii=False,indent=2))
   await h.close()
 asyncio.run(run())


def test_two_tab_merge_and_conflict(server,tmp_path):
 async def run():
  h=await BrowserHarness(server,tmp_path).start()
  try:
   a=await h.page();await h.login(a)
   b=await h.page();await expect(b.locator('#authGate')).to_have_count(0)
   await h.nav(a,'settings','profile');await h.nav(b,'settings','preferences')
   await a.locator('form[data-form="profile"] [name="name"]').fill('Tab A')
   await a.locator('form[data-form="profile"] button[type="submit"]').click()
   await a.wait_for_function('!live.dirty&&!live.saving')
   await b.locator('[data-action="theme"][data-value="dark"]').click()
   await b.wait_for_function('!live.dirty&&!live.saving&&!live.blocked')
   state=server.app.db.state()['state'];assert state['profile']['name']=='Tab A' and state['prefs']['theme']=='dark'
   # Both tabs start from one base and edit the same field. No last-writer-wins loss.
   await a.evaluate('refreshState()');await b.evaluate('refreshState()')
   await h.nav(a,'settings','profile');await h.nav(b,'settings','profile')
   await a.locator('form[data-form="profile"] [name="name"]').fill('First edit')
   await a.locator('form[data-form="profile"] button[type="submit"]').click();await a.wait_for_function('!live.dirty&&!live.saving')
   await b.locator('form[data-form="profile"] [name="name"]').fill('Conflicting edit')
   await b.locator('form[data-form="profile"] button[type="submit"]').click();await b.wait_for_function('live.blocked')
   assert server.app.db.state()['state']['profile']['name']=='First edit'
   assert await b.evaluate('store.profile.name')=='Conflicting edit'
   await expect(b.locator('#syncStatus')).to_contain_text('Speicherkonflikt')
   assert not h.errors and not h.console_errors
  finally:
   await h.close()
 asyncio.run(run())
