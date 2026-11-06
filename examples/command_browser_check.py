"""Command console browser verification: fake sessions/transport, temporary state only."""
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import uvicorn
from playwright.sync_api import sync_playwright

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from web_app import create_app,save_password
from test_command_service import Sessions,Bridge

with tempfile.TemporaryDirectory() as directory:
    save_password('browser test password',directory)
    service=Sessions(directory)
    for row in service.rows: row.update(attachment='Headless',running=True,started_at=time.time()-60)
    app=create_app(service.config,service,directory)
    bridge=Bridge();app.state.commands.transport=bridge
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    while not server.started:time.sleep(.02)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000},locale='en-US')
            page.set_default_timeout(10000);errors=[];page.on('pageerror',lambda error: (errors.append(str(error)),print('BROWSER ERROR:',error.stack)))
            page.goto(f'http://127.0.0.1:{port}/?view=sessions')
            page.locator('#login input[name=password]').fill('browser test password');page.locator('#loginButton').click()
            page.wait_for_function("() => document.querySelector('#commandRosterCount').textContent.includes('2 available')")
            page.locator('#commandToggle').click();page.locator('#commandAll').click()
            assert page.locator('#commandRecipients .command-chip').count()==2
            page.locator('#commandInput').fill('  ;pause  all;look  ')
            page.locator('#commandInput').press('Enter');assert not bridge.calls
            page.evaluate("document.querySelector('#commandInput').setSelectionRange(3,6)")
            page.evaluate('refresh()');page.wait_for_timeout(300)
            assert page.locator('#commandInput').input_value()=='  ;pause  all;look  '
            assert page.evaluate('document.activeElement.id')=='commandInput'
            assert page.evaluate('document.activeElement.selectionStart')==3
            page.locator('#commandInput').evaluate("el=>{const e=new Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(e,'clipboardData',{value:{getData:()=> 'look\\nquit'}});el.dispatchEvent(e)}")
            assert 'single command' in page.locator('#commandError').inner_text()
            assert page.locator('#commandInput').input_value()=='  ;pause  all;look  '
            preparations=[]
            page.route('**/api/command-batches/prepare',lambda route: preparations.append(route),times=1)
            page.locator('#commandInput').press('Control+Enter');page.wait_for_timeout(100)
            assert len(preparations)==1
            for selector in ['#commandInput','#commandAll','#commandClear','.command-select','.command-card-button']:
                assert page.locator(selector).first.is_disabled(),selector
            preparations[0].continue_()
            page.wait_for_function("() => document.querySelector('#commandLatest').textContent.includes('Sent to Lich')")
            assert len([r for _,r in bridge.calls if r['action']=='dispatch'])==2
            assert page.locator('#commandInput').input_value()==''
            assert page.locator('.command-select:checked').count()==2
            page.locator('#commandLatest button',has_text='Use command again').focus()
            page.evaluate('window.savedDeliveryAction=document.activeElement')
            first_batch=app.state.commands.recent()[0]['request_id']
            app.state.commands._update(first_batch,0,state='not_sent',reason='Connection unavailable.')
            page.evaluate('refresh()');page.wait_for_timeout(300)
            assert page.evaluate('window.savedDeliveryAction===document.activeElement'), 'delivery polling replaced the focused action'
            app.state.commands._update(first_batch,0,state='sent',reason='')
            page.locator('#commandLatest button',has_text='Use command again').click()
            assert page.locator('#commandInput').input_value()=='  ;pause  all;look  '
            assert len([r for _,r in bridge.calls if r['action']=='dispatch'])==2
            check=page.locator('.command-select').first;check.focus();page.evaluate('window.savedCommandCheck=document.activeElement')
            page.evaluate('refresh()');page.wait_for_timeout(300)
            assert page.evaluate('window.savedCommandCheck===document.activeElement')
            page.screenshot(path='/tmp/gempy-command-desktop.png',full_page=True)
            # Replacement bridge invalidates old selections, without dropping names.
            bridge.generation='replacement';page.evaluate('refresh()')
            page.wait_for_function("() => document.querySelectorAll('#commandRecipients .command-unavailable').length===2")
            assert page.locator('#commandRecipients .command-chip').count()==2
            page.locator('[aria-label="Send command to Hero on prime"]').click()
            assert 'Recipients changed to Hero' in page.locator('#commandNotice').inner_text()
            assert page.locator('#commandRecipients .command-chip').count()==1
            # Ambiguous HTTP response: server accepts, browser sees an error, no replay.
            def lose_response(route):
                route.fetch();route.abort('failed')
            page.route('**/api/command-batches',lose_response,times=1)
            page.locator('#commandInput').fill('look');page.locator('#commandSend').click()
            page.wait_for_function("() => document.querySelector('#commandInput').value==='' && document.querySelector('#commandLatest pre').textContent==='look'")
            assert len([r for _,r in bridge.calls if r['action']=='dispatch'])==3
            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(100)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),page.evaluate('document.documentElement.scrollWidth')
            assert page.locator('#commandInput').bounding_box()['width']>200
            page.screenshot(path='/tmp/gempy-command-mobile.png',full_page=True)
            page.locator('#charactersTab').click();page.locator('#sessionsTab').click()
            assert page.locator('#commandPanel').is_hidden()
            page.locator('#commandToggle').click();assert page.locator('#commandRecipients .command-chip').count()==0
            page.locator('#commandAll').click();page.locator('#commandInput').fill('look')
            page.locator('#logout').click();page.locator('#login input[name=password]').fill('browser test password');page.locator('#loginButton').click()
            page.locator('#commandToggle').click();assert page.locator('#commandRecipients .command-chip').count()==0
            assert page.locator('#commandInput').input_value()==''
            assert not errors,errors
            browser.close()
            print('PASS: desktop/mobile, literal sends, polling focus/cursor, multiline paste, generation binding, lost HTTP receipt, history, navigation and logout; fake dispatches only.')
    finally:
        server.should_exit=True;thread.join(10)
