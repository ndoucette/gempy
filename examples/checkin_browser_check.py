"""Live-session UI checks against fake sessions and temporary state only."""
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import uvicorn
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_app import create_app, save_password
from test_daily_checkin import FakeService

with tempfile.TemporaryDirectory() as directory:
    save_password('browser test password', directory)
    service=FakeService()
    service.online=[dict(id='42:100',pid=42,character='Alpha',realm='prime',attachment='Attached',running=True,started_at=time.time()-45),
                    dict(id='43:200',pid=43,character='Beta',realm='prime',attachment='Headless',running=True,started_at=time.time()-120)]
    app=create_app({'accounts':{'Account A':['Alpha'],'Account B':['Beta']}},service,directory)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    while not server.started:time.sleep(.02)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1365,'height':1000})
            page.set_default_timeout(10000)
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}/?view=checkin')
            page.locator('#login input[name=password]').fill('browser test password')
            page.locator('#loginButton').click()
            page.locator('#checkinTab').click()
            page.wait_for_function("() => document.querySelectorAll('#ciLiveRows tr').length===2")
            assert 'Alpha' in page.locator('#ciLiveRows').inner_text()
            assert 'Client attached' in page.locator('#ciLiveRows').inner_text()
            assert 'Headless' in page.locator('#ciLiveRows').inner_text()
            assert page.locator('#ciLiveCount').inner_text()=='2 online'
            assert page.locator('.ci-live').bounding_box()['y']<page.locator('.ci-workspace').bounding_box()['y']
            def seconds():return int(page.locator('.ci-session-time').first.inner_text().split()[0].replace(',',''))
            before=seconds();page.wait_for_timeout(1200);assert seconds()>before
            page.screenshot(path='/tmp/gempy-checkin-live-desktop.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.screenshot(path='/tmp/gempy-checkin-live-mobile.png',full_page=True)
            # A dead game process disappears on the normal poll, even with no run.
            service.online=service.online[:1]
            page.wait_for_function("() => document.querySelectorAll('#ciLiveRows tr').length===1")
            service.online=[]
            page.wait_for_selector('#ciLiveEmpty:visible')
            assert page.locator('#ciLiveEmpty').inner_text()=='No characters are currently logged in.'
            # Manual login after an idle period appears without refreshing the page.
            service.online=[dict(id='44:300',pid=44,character='Beta',realm='prime',attachment='Headless',running=True,started_at=time.time()-10)]
            page.wait_for_function("() => document.querySelectorAll('#ciLiveRows tr').length===1")
            assert 'Beta' in page.locator('#ciLiveRows').inner_text()
            page.route('**/api/checkin',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":"fixture outage"}'))
            page.wait_for_selector('#ciLiveNotice:visible')
            before=seconds();page.wait_for_timeout(1200);assert seconds()==before
            page.unroute('**/api/checkin')
            page.wait_for_selector('#ciLiveNotice',state='hidden')
            assert not errors,errors
            assert service.started==[], 'Browser verification must not launch characters'
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=5)
print('Live-session placement, seconds, mobile layout, polling, logout removal, idle login, and outage checks passed')
