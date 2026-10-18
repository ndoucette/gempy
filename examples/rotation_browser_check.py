"""Exercise weekly rotation with real API-derived fixture profiles."""
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright
from web_app import create_app,save_password

WIZARDS=[('Eggable','WRAITH84'),('Saxx','DRAKON6'),('Renwaldo','DRAKON6'),('Celdiseth','DRAKON6'),
         ('Nikorasu','DRAKON6'),('Bubbage','DRAKON6'),('Tumerok','TOHRMENT1'),('Liviloo','VLAT')]
MAINS=[('Dartwen','WRAITH84'),('Voxy','TOHRMENT1'),('Cragstone','VLAT')]
accounts={account:[name for name,a in WIZARDS+MAINS if a==account and name!='Voxy'] for account in ['WRAITH84','TOHRMENT1','VLAT','DRAKON6']}
entries=[dict(name=name,account=account,role=role) for role,rows in [('main',MAINS),('wizard',WIZARDS)] for name,account in rows]


class Sessions:
    def sessions(self):
        return [dict(character='Dartwen',realm='prime',running=True,pid=42,id='42:100',attachment='Attached')]


with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);save_password('browser test password',root)
    config={'accounts':accounts,'weekly_rotation':{'account_roles':{'DRAKON6':'utility'},'characters':entries}}
    app=create_app(config,Sessions(),root)
    store=app.state.telemetry;now=time.time()
    fixtures=[('Eggable',3,12000,now+5000),('Saxx','expired',50000,now+90000),('Renwaldo','expired',32450,now+6000),
              ('Celdiseth','expired',50000,now-60),('Nikorasu','ready',0,now+150000),('Tumerok','expired',50000,now+200000)]
    with store.lock,store.db:
        store.profiles.ingest('prime','Voxy',dict(character={'name':'Voxy','profession':'Bard'}),now)
        for name,stage,weekly,reset in fixtures:
            data=dict(character={'name':name,'profession':'Wizard'},
                      bonuses={'lumnis_stage':stage,'lumnis_reset_at':reset,'fashlonae_state':'expended'},
                      resources={'type':'Essence','weekly':weekly,'total':145223,'max_weekly':50000})
            store.profiles.ingest('prime',name,data,now)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    while not server.started:time.sleep(.02)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1720,'height':1100},locale='en-US',timezone_id='Europe/London',reduced_motion='reduce')
            page.set_default_timeout(10000)
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}')
            page.locator('#login input[name=password]').fill('browser test password');page.locator('#loginButton').click()
            page.locator('#rotationTab').click()
            page.wait_for_selector('.rotation-card')
            assert page.locator('.rotation-card').count()==8
            assert page.locator('.rotation-main').count()==3
            voxy=page.locator('.rotation-main').filter(has_text='Voxy')
            assert voxy.get_by_role('button',name='Add Voxy in rotation',exact=True).is_visible()
            assert voxy.get_by_role('button',name='Profile for Voxy in rotation',exact=True).is_visible()
            assert page.locator('#rotation').is_visible() and page.locator('#sessions').is_hidden()
            assert page.locator('#rotationDone').inner_text()=='2 / 8'
            ren=page.locator('.rotation-card[data-character=Renwaldo]')
            assert ren.locator('.rotation-earned').inner_text()=='32,450'
            assert ren.locator('.rotation-stored').inner_text()=='145,223'
            assert '17,550 to cap' in ren.inner_text()
            assert 'PDT' in ren.inner_text() or 'PST' in ren.inner_text()
            assert 'Reset passed' in page.locator('.rotation-card[data-character=Celdiseth]').inner_text()
            assert 'Not reported' in page.locator('.rotation-card[data-character=Bubbage]').inner_text()
            assert page.locator('.rotation-card[data-character=Eggable] .rotation-launch').is_disabled()
            assert 'Dartwen' in page.locator('.rotation-card[data-character=Eggable] .rotation-occupant').inner_text()
            page.screenshot(path='/tmp/gempy-rotation-desktop.png',full_page=True)
            page.locator('#rotationState').select_option('done')
            assert page.locator('.rotation-card').count()==2
            page.locator('#rotationState').select_option('all')
            page.locator('#rotationAccount').select_option('DRAKON6')
            assert page.locator('.rotation-card').count()==5
            page.locator('#rotationAccount').select_option('')
            page.locator('#rotationGroup').check()
            assert page.locator('.rotation-account-group').count()==4
            page.locator('#rotationGroup').uncheck()
            ren.locator('.rotation-profile').click()
            page.wait_for_function("() => document.querySelector('#detailContent').textContent.includes('145,223')")
            page.locator('#detailClose').click()
            for width in (1280,1024,768,390,320):
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow at {width}'
                assert ren.locator('.rotation-earned').is_visible()
                assert ren.locator('.rotation-stored').is_visible()
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path='/tmp/gempy-rotation-mobile.png',full_page=True)
            page.locator('#rotationRealm').select_option('test')
            page.wait_for_function("() => document.querySelector('#rotationDone').textContent==='0 / 8'")
            page.locator('#rotationRealm').select_option('prime')
            page.wait_for_function("() => document.querySelector('#rotationDone').textContent==='2 / 8'")
            page.locator('#rotationSearch').fill('Renwaldo')
            assert page.locator('.rotation-card').count()==1
            page.locator('#rotationRefresh').click()
            assert page.locator('#rotationSearch').input_value()=='Renwaldo'
            page.locator('#sessionsTab').click();assert page.locator('#rotation').is_hidden()
            assert not errors,errors
            browser.close()
            print('Rotation browser checks passed: eight wizards, mains, exact balances, deadlines, account occupancy, filters, grouping, profiles, realm isolation and mobile layout')
    finally:
        server.should_exit=True;thread.join(timeout=5)
