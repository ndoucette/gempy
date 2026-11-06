"""Bank totals and zero resources against isolated profiles; no game logins."""
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
    service = FakeService()
    app = create_app({'accounts': {'Main': ['Hero', 'Liviloo'], 'Other': ['Gringott']}}, service, directory)
    store = app.state.telemetry
    now = int(time.time())

    def report(name, bank, realm='prime', observed=now):
        with store.lock, store.db:
            store.profiles.ingest(realm, name, {
                'wealth': {'bank_balance': bank, 'bank_balance_observed_at': observed},
                'resources': {'weekly': 0, 'total': 0, 'suffused': 0, 'observed_at': observed,
                              'suffused_observed_at': observed}}, observed)

    report('Hero', 1234567)
    report('Liviloo', 0)
    report('Retired', 99999999)
    report('Hero', 999, 'test')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    while not server.started: time.sleep(.02)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000}, locale='en-US')
            page.set_default_timeout(10000)
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{port}/?view=status')
            page.locator('#login input[name=password]').fill('browser test password')
            page.locator('#loginButton').click()
            page.locator('#statusTab').click()
            page.wait_for_function("() => document.querySelector('#statusBankTotal').textContent==='1,234,567'")
            assert page.locator('#statusBankCoverage').inner_text() == '2 of 3 characters reported · 1 missing'
            assert 'Oldest report:' in page.locator('#statusBankAge').inner_text()
            assert page.locator('#statusRows [data-character=Liviloo] [data-column=total]').inner_text() == '0'
            page.locator('#statusSearch').fill('Liviloo')
            assert page.locator('#statusRows tr').count() == 1
            assert page.locator('#statusBankTotal').inner_text() == '1,234,567'
            page.locator('#statusClear').click()
            report('Gringott', 2000, observed=now+1)
            page.wait_for_function("() => document.querySelector('#statusBankTotal').textContent==='1,236,567'")
            assert page.locator('#statusBankCoverage').inner_text() == '3 of 3 characters reported'
            page.screenshot(path='/tmp/gempy-status-bank-desktop.png', full_page=True)
            for width in (320, 390, 768):
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), width
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path='/tmp/gempy-status-bank-mobile.png', full_page=True)
            page.locator('#statusRealm').select_option('test')
            page.wait_for_function("() => document.querySelector('#statusBankTotal').textContent==='999'")
            assert 'Test' in page.locator('#statusBankScope').inner_text()
            report('Hero', 0, 'test', now+2)
            page.locator('#statusRefresh').click()
            page.wait_for_function("() => document.querySelector('#statusBankTotal').textContent==='0'")
            page.locator('#logout').click()
            assert page.locator('#statusBankTotal').inner_text() == ''
            assert service.started == []
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True; thread.join(timeout=5)
print('Bank total, coverage, filters, polling, realms, zero resources, logout and mobile checks passed')
