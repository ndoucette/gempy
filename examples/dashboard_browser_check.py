import copy
from datetime import date, timedelta
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright
from web_app import create_app, save_password

class Service:
    def sessions(self):
        return [dict(id='42:100',pid=42,character='Hero',realm='prime',running=True,attachment='Headless'),
                dict(id='43:200',pid=43,character='Hero',realm='test',running=True,attachment='Attached'),
                dict(id='44:300',pid=44,character='Quiet',realm='prime',running=True,attachment='Unknown')]
    def attach(self, identity, client='vellum_despana'):
        return {'connection': {'note':'Test connection', 'host':'127.0.0.1','port':8000,
                'desktop_command':'vellum test','terminal_command':'vellum test','ssh_command':'ssh test'}}

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    save_password('browser test password',root)
    config={'paths':{'lich_bin':str(root/'lich.rbw')},'accounts':{'Main':['Hero','Quiet']}}
    import yaml
    config_path=root/'config.yaml';config_path.write_text(yaml.safe_dump(config))
    history=root/'data/GSIV/Offline/exp_sagapanel_history.yaml';history.parent.mkdir(parents=True)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    history.write_text(f'daily:\n  "{yesterday}": {{exp: 12345, asc: 50000}}\nmonthly:\n  "{today[:7]}": {{exp: 12345, asc: 50000}}\n')
    app=create_app(config,Service(),root,config_path=config_path)
    store=app.state.telemetry
    data=dict(schema_version=1,pid=42,realm='prime',reporter_id='browser',sequence=1,
        character={'name':'Hero','level':80},location={'room_id':123,'room_title':'Town Square'},
        vitals={k:{'current':50,'max':100,'percent':50} for k in ('health','mana','stamina','spirit')},
        status={'mindstate':{'text':'Clear','value':0},'stance':{'text':'Defensive'},'encumbrance':{'text':'None'}},
        experience={'lifetime_exp':1000000,'ascension_exp':50000,'hourly_rate':1234,'best_pulse':100},
        injuries={'wounds':{'head':2,'nsys':1},'scars':{'leftArm':1}},effects={'spells':[{'name':'Stone Skin','end_time':int(time.time())+60}], 'buffs':[],'debuffs':[],'cooldowns':[]},
        bonuses={'lumnis_stage':2,'lumnis_reset_at':int(time.time())+3600},resources={'weekly':2000,'total':5000},daily_tracking={})
    store.ingest(data,Service().sessions())
    data['sequence']=2;data['experience']['lifetime_exp']+=125
    store.ingest(data,Service().sessions())
    test=copy.deepcopy(data);test.update(pid=43,realm='test',sequence=1,reporter_id='test')
    store.ingest(test,Service().sessions());store.live['43:200']['monotonic']-=30
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    deadline=time.monotonic()+10
    while not server.started:
        if time.monotonic()>deadline:raise RuntimeError('Temporary browser test server failed to start')
        time.sleep(.02)
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{port}')
        page.locator('#login input[name=password]').fill('browser test password')
        page.locator('#loginButton').click()
        page.wait_for_selector('.live-card')
        assert page.locator('.live-card').count()==3
        assert page.locator('#characters').is_hidden()
        page.locator('#liveRealm').select_option('prime');assert page.locator('.live-card').count()==2
        page.locator('#liveRealm').select_option('')
        page.screenshot(path='/tmp/gempy-live-desktop.png',full_page=True)
        page.locator('.character-link').first.click()
        page.screenshot(path='/tmp/gempy-inspector-desktop.png',full_page=True)
        page.locator('[data-detail=experience]').click()
        page.locator('.pin-options input').first.check()
        page.locator('[data-detail=bonuses]').click()
        page.locator('[data-detail=history]').click()
        page.wait_for_function("() => !document.querySelector('#detailContent').textContent.includes('Loading history')")
        page.locator('#detailClose').click()
        page.locator('#settingsTab').click()
        page.locator('#importHistory').click()
        page.wait_for_function("() => document.querySelector('#importOutput').textContent.includes('Imported')")
        page.locator('#settingsForm [name=density]').select_option('compact')
        page.locator('#settingsForm button[type=submit]').click()
        page.wait_for_function("() => document.querySelector('#message').textContent.includes('Settings saved')")
        page.locator('#reporterToken').click()
        page.wait_for_function("() => document.querySelector('#tokenOutput').textContent.includes('Reporter token')")
        with page.expect_download() as download:
          page.locator('a[href="/api/history/backup"]').click()
        assert download.value.suggested_filename=='gempy-history.sqlite3'
        page.locator('#progressTab').click()
        page.locator('#progressPeriod').select_option('month')
        page.wait_for_selector('.progress-table')
        assert 'Offline' in page.locator('#progressContent').inner_text()
        page.locator('#progressPeriod').select_option('custom')
        page.locator('#progressStart').fill(yesterday);page.locator('#progressEnd').fill(today)
        page.wait_for_function("date => document.querySelector('#progressContent').textContent.includes(date)", arg=yesterday)
        page.screenshot(path='/tmp/gempy-progress-desktop.png',full_page=True)
        page.locator('#charactersTab').click()
        page.locator('.roster-edit').filter(has_text='Edit').first.click()
        page.locator('#rosterEditDialog input').nth(1).fill('Moved')
        page.locator('#rosterEditDialog button[type=submit]').click()
        page.wait_for_function("() => document.querySelector('#accounts').textContent.includes('Moved')")
        page.locator('#sessionsTab').click()
        page.locator('#layoutToggle').click()
        page.locator('#layoutToggle').click()
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path='/tmp/gempy-live-mobile.png',full_page=True)
        assert page.evaluate('() => document.documentElement.scrollWidth<=window.innerWidth'), 'Mobile overflow'
        for width in (320, 768, 1024, 1920):
          page.set_viewport_size({'width':width,'height':900})
          assert page.evaluate('() => document.documentElement.scrollWidth<=window.innerWidth'), f'Overflow at {width}'
        page.set_viewport_size({'width':390,'height':844})
        page.locator('.character-link').first.click()
        page.screenshot(path='/tmp/gempy-inspector-mobile.png',full_page=True)
        assert page.locator('#characterDetails').bounding_box()['width']<=390
        page.locator('#detailClose').click()
        page.locator('#settingsTab').click()
        assert page.locator('#tokenOutput').inner_text()==''
        page.locator('#logout').click()
        page.wait_for_selector('#loginLayout',state='visible')
        assert not errors,errors
        browser.close()
        print('Browser dashboard checks passed: navigation, live/details, pins, imports, settings, backup, custom progress, roster editing, mobile, logout')
    finally:
      server.should_exit=True;thread.join(timeout=5)
