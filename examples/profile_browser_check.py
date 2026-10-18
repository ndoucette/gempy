"""Exercise real profile navigation and numeric displays against isolated fixtures."""
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


class Sessions:
    def __init__(self):
        self.running = True

    def sessions(self):
        return [dict(id='42:100', pid=42, character='Hero', realm='prime',
                     running=True, attachment='Headless')] if self.running else []


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    save_password('browser test password', root)
    service = Sessions()
    app = create_app({'accounts': {'Main': ['Hero', 'Unreported']}}, service, root)
    store = app.state.telemetry
    now = int(time.time())
    snapshot = dict(schema_version=1, pid=42, realm='prime', reporter_id='profile', sequence=1,
        character=dict(name='Hero', level=100, profession='Wizard', race='Elf'),
        stats=dict(strength=dict(base_value=75, base_bonus=12, value=80, bonus=15, enhanced_value=90, enhanced_bonus=20),
                   logic=dict(value=100, bonus=25)),
        skills=dict(arcane_symbols=dict(ranks=202, bonus=302, category='skill'),
                    wizard=dict(ranks=100, bonus=None, category='spell_research'),
                    swimming=dict(ranks=0, bonus=0, category='skill')),
        bonuses=dict(lumnis_stage=3, lumnis_points_remaining=4500, lumnis_donations=2,
                     lumnis_reset_at=now-60, observed_at=now, donations_observed_at=now),
        resources=dict(type='Essence', weekly=32450, total=118750, max_weekly=50000, max_total=200000, observed_at=now))
    store.ingest(snapshot, service.sessions())
    # New reporter has no command results yet: durable observations must still
    # appear on the default Live screen without first visiting the roster.
    startup=dict(snapshot, sequence=2, stats=None, skills=None, bonuses={},
                 resources={'weekly':None,'total':None,'voln_favor':None},
                 metadata={'availability':{'resources':{'available':False,'collected_at':now+1}}})
    store.ingest(startup, service.sessions())
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    thread=threading.Thread(target=server.run, daemon=True);thread.start()
    while not server.started:time.sleep(.02)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000}, locale='en-US', reduced_motion='reduce')
            page.set_default_timeout(10000)
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}')
            page.locator('#login input[name=password]').fill('browser test password')
            page.locator('#loginButton').click()
            page.wait_for_selector('.live-card')
            page.wait_for_function("() => document.querySelector('.live-card').textContent.includes('118,750')")
            assert page.locator('.live-card .resource-weekly').inner_text()=='32,450'
            assert page.locator('.live-card .resource-stored').inner_text()=='118,750'
            page.locator('.character-link').click()
            page.wait_for_function("() => document.querySelector('#detailContent').textContent.includes('118,750')")
            page.locator('[data-detail=stats]').click()
            assert page.locator('.profile-table tbody tr').count()==2
            assert page.locator('.profile-table tbody tr').first.inner_text().split()==['Strength','75','12','80','15','90','20']
            page.screenshot(path='/tmp/gempy-profile-stats.png', full_page=True)
            page.locator('[data-detail=skills]').click()
            assert page.locator('.profile-table tbody tr').count()==2
            page.get_by_label('Show untrained').check()
            assert page.locator('.profile-table tbody tr').count()==3
            page.get_by_label('Find a skill').fill('wizard')
            assert page.locator('.profile-table tbody tr').count()==1
            assert 'Spell research' in page.locator('.profile-table').inner_text()
            page.locator('[data-detail=overview]').click()
            page.get_by_text('Cycle & donation details',exact=True).click()
            content=page.locator('#detailContent').inner_text()
            assert 'Active ×3' in content and '118,750' in content and '32,450' in content
            assert 'Future cycles prepaid' in content and 'Not confirmed by current phase' in content
            assert 'A new game report is needed' in content
            page.screenshot(path='/tmp/gempy-profile-resources.png', full_page=True)
            # Updates should come from new observations, not a cached balance.
            snapshot['sequence']=3;snapshot['resources']['total']=100001
            store.ingest(snapshot,service.sessions())
            page.wait_for_function("() => document.querySelector('#detailContent').textContent.includes('100,001')")
            # Logging out of the game leaves the profile available from the roster.
            service.running=False;store.live.clear()
            page.locator('#detailClose').click();page.locator('#charactersTab').click()
            page.wait_for_function("() => document.querySelector('#accounts').textContent.includes('100,001')")
            page.get_by_role('button',name='Profile for Hero on prime',exact=True).click()
            page.wait_for_function("() => document.querySelector('#detailSubtitle').textContent.includes('Offline')")
            assert '100,001' in page.locator('#detailContent').inner_text()
            page.locator('[data-detail=stats]').click()
            for width in (320,390,768,1024,1920):
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), f'Page overflow at {width}'
                assert page.locator('#characterDetails').bounding_box()['width']<=width
            page.set_viewport_size({'width':390,'height':844})
            page.locator('[data-detail=overview]').click()
            page.screenshot(path='/tmp/gempy-profile-mobile.png',full_page=True)
            page.locator('#detailClose').click()
            page.locator('[data-realm=test]').click()
            page.get_by_role('button',name='Profile for Hero on test',exact=True).click()
            page.wait_for_function("() => document.querySelector('#detailContent').textContent.includes('No profile data yet')")
            assert '100,001' not in page.locator('#detailContent').inner_text()
            page.locator('#detailClose').click();page.locator('[data-realm=prime]').click()
            page.get_by_role('button',name='Profile for Unreported on prime',exact=True).click()
            page.wait_for_function("() => document.querySelector('#detailContent').textContent.includes('No profile data yet')")
            assert not errors,errors
            browser.close()
            print('Profile browser checks passed: exact balances, stats, skill search, donations, live updates, offline roster, realm isolation and responsive layouts')
    finally:
        server.should_exit=True;thread.join(timeout=5)
