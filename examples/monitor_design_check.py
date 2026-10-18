"""Visual and interaction checks for the redesigned monitoring workspace."""
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright
from web_app import create_app, save_password


class Sessions:
    def sessions(self):
        return [dict(id=f'{42+i}:100', pid=42+i, character=name, realm='prime',
                     running=True, attachment='Attached')
                for i, name in enumerate(['Liviloo', 'Dartwen', 'Prepotente', 'Renwaldo'])]


with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);save_password('browser test password',root)
    service=Sessions()
    app=create_app({'accounts':{'Main':['Liviloo','Dartwen','Prepotente','Renwaldo']}},service,root)
    store=app.state.telemetry;now=int(time.time())
    for i, session in enumerate(service.sessions()):
        data=dict(schema_version=1,pid=session['pid'],realm='prime',reporter_id='design',sequence=1,
            character=dict(name=session['character'],level=20 if i==0 else 100,profession=['Wizard','Sorcerer','Bard','Wizard'][i]),
            vitals={name:dict(current=value,max=maximum) for name,value,maximum in
                    [('health',2 if i==0 else 138,152 if i==0 else 138),('mana',0 if i==0 else 225,340),('stamina',16 if i==0 else 101,101),('spirit',2 if i==0 else 11,11)]},
            status=dict(mindstate=dict(text='Clear as a bell' if i==0 else 'Becoming numbed',value=0 if i==0 else 70),stance=dict(text='Defensive')),
            location=dict(room_title=['Town Square Central','Old Ta’Faendryl, East Entrance','Wehnimer’s, East Jetty','Old Ta’Faendryl, Southeast'][i],room_id=228+i),
            experience=dict(hourly_rate=153480,last_hour_gain=7600,eta_next_level_seconds=4,next_level_percent=42.5,percent_capped=12.49,
                            experience_to_next_level=15200,ascension_exp=80000,exp_to_next_atp=20000),
            bonuses=dict(lumnis_stage=3 if i==3 else 'expired',lumnis_donations=0 if i==3 else 2,observed_at=now,lumnis_reset_at=now+3*86400+20*3600+1800),
            resources=dict(type=['Essence','Necrotic Energy','Luck Inspiration','Essence'][i],weekly=5440 if i==3 else 50000,total=145223 if i==3 else 128220,observed_at=now))
        if i==0:data['resources']={}
        if i in (0,3):data['experience'].update(physical_training_points=0,mental_training_points=1234)
        data['bonuses'].update(fashlonae_state=['inactive','expended','active','unknown'][i],
                              fashlonae_observed_at=now)
        if i in (1,2):data['bonuses'].update(fashlonae_days_remaining=121,fashlonae_days_observed_at=now)
        store.ingest(data,service.sessions())
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
            page.add_init_script("localStorage.setItem('gempy.pins',JSON.stringify({'Renwaldo:prime':['hourly_rate','last_hour_gain']}))")
            page.goto(f'http://127.0.0.1:{port}')
            page.locator('#login input[name=password]').fill('browser test password');page.locator('#loginButton').click()
            page.wait_for_selector('.live-card')
            assert page.locator('#quickCharacter').count()==0
            assert page.locator('#sessions .live-filters').count()==0
            assert page.locator('#sessions .page-heading, #refreshButton').count()==0
            assert page.locator('.live-card').count()==4
            # Collapse keeps navigation usable, frees space, and survives reloads.
            sidebar_width=page.locator('.sidebar').bounding_box()['width']
            main_left=page.locator('main').bounding_box()['x']
            toggle=page.get_by_role('button',name='Collapse sidebar',exact=True)
            toggle.focus();page.keyboard.press('Enter')
            assert page.locator('.sidebar').bounding_box()['width']<sidebar_width
            assert page.locator('main').bounding_box()['x']<main_left
            assert page.get_by_role('button',name='Expand sidebar',exact=True).get_attribute('aria-expanded')=='false'
            page.reload();page.wait_for_selector('.live-card')
            assert page.get_by_role('button',name='Expand sidebar',exact=True).is_visible()
            page.locator('#settingsTab').click()
            assert page.locator('#settings').is_visible()
            page.locator('#sessionsTab').click()
            page.screenshot(path='/tmp/gempy-sidebar-collapsed.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.get_by_role('button',name='Expand sidebar',exact=True).count()==0
            assert page.locator('#charactersTab').is_visible()
            page.set_viewport_size({'width':1720,'height':1100})
            page.get_by_role('button',name='Expand sidebar',exact=True).click()
            assert page.locator('.sidebar').bounding_box()['width']==sidebar_width
            page.wait_for_function("() => document.querySelector('.row-identity .row-resources') !== null")
            assert page.locator('.monitor-heading').count()==0
            critical=page.locator('.live-card').filter(has=page.locator('.character-link',has_text='Liviloo'))
            wizard=page.locator('.live-card').filter(has=page.locator('.character-link',has_text='Renwaldo'))
            assert 'Critical health' in critical.inner_text()
            assert wizard.locator('.session-xp-rate').inner_text()=='153,480'
            assert wizard.locator('.recent-xp-rate').inner_text()=='7,600'
            assert wizard.locator('.row-xp-rates + .row-resources').count()==1
            assert wizard.locator('.row-identity .live-sub + .row-cycle').count()==1
            assert wizard.locator('.row-vitals .row-cycle').count()==0
            assert 'Not reported' in critical.locator('.row-resources').inner_text()
            assert wizard.locator('.resource-weekly').inner_text()=='5,440 / 50,000'
            assert wizard.locator('.resource-stored').inner_text()=='145,223 / 200,000'
            assert wizard.locator('.cycle-renewal').count()==1, 'Renewal must be visible alongside Lumnis status'
            assert critical.locator('.tutelage-icon').get_attribute('data-state')=='eligible'
            tutelage_active=page.locator('.live-card').filter(has=page.locator('.character-link',has_text='Prepotente'))
            assert tutelage_active.locator('.tutelage-icon').get_attribute('data-state')=='active'
            assert '121 days remaining' in tutelage_active.locator('.tutelage-icon + .bonus-tooltip').text_content()
            assert page.locator('.live-card').filter(has=page.locator('.character-link',has_text='Dartwen')).locator('.tutelage-icon').get_attribute('data-state')=='expired'
            assert wizard.locator('.tutelage-icon').count()==0
            assert wizard.locator('.lumnis-icon .bonus-multiplier').inner_text()=='3'
            assert critical.locator('.lumnis-icon .bonus-multiplier').count()==0
            assert critical.locator('.lumnis-icon img').get_attribute('src').endswith('lumnis-grayscale.webp')
            assert tutelage_active.locator('.tutelage-icon .bonus-multiplier').count()==0
            for card in (critical,wizard,tutelage_active):
                icons=card.locator('.bonus-icon')
                if icons.count()==2:
                    assert 'tutelage-icon' in icons.first.get_attribute('class')
                    assert abs(icons.nth(0).bounding_box()['y']-icons.nth(1).bounding_box()['y'])<2
                renewal=card.locator('.cycle-renewal').bounding_box()
                last_icon=icons.last.bounding_box()
                assert renewal['x']>=last_icon['x']+last_icon['width']
                assert abs(renewal['y']+renewal['height']/2-last_icon['y']-last_icon['height']/2)<2
                for img in card.locator('.bonus-icon img').all():
                    assert img.evaluate('(el)=>el.complete && el.naturalWidth>0')
            tutelage_active.locator('.tutelage-icon').focus()
            assert tutelage_active.locator('.tutelage-icon + .bonus-tooltip').is_visible()
            tutelage_active.locator('.tutelage-icon').press('Enter')
            page.wait_for_selector('#characterDetails[open]')
            page.locator('#detailClose').click()
            page.locator('#sessionsTab').focus()
            # Lumnis renews Tutelage before it can begin applying again.
            dartwen=page.locator('.live-card').filter(has=page.locator('.character-link',has_text='Dartwen'))
            for sequence, stage in enumerate([2, 3, 4, 5, 'ready', 'expired'], start=2):
                store.ingest(dict(schema_version=1,pid=43,realm='prime',reporter_id='design',sequence=sequence,
                    character=dict(name='Dartwen'),bonuses=dict(lumnis_stage=stage,observed_at=int(time.time()),
                        fashlonae_state='expended',fashlonae_observed_at=int(time.time()))),service.sessions())
                page.evaluate('refresh()')
                expected='expired' if stage=='expired' else 'eligible'
                page.wait_for_function("expected => [...document.querySelectorAll('.live-card')].find(row => row.querySelector('.character-link')?.textContent==='Dartwen')?.querySelector('.tutelage-icon')?.dataset.state===expected",arg=expected)
                assert dartwen.locator('.tutelage-icon').get_attribute('data-state')==expected
                assert '121 days remaining' in dartwen.locator('.tutelage-icon + .bonus-tooltip').text_content()
                if isinstance(stage,int):
                    assert dartwen.locator('.bonus-multiplier').inner_text()==str(stage)
                else:
                    assert dartwen.locator('.bonus-multiplier').count()==0
            # Unredeemed/unknown benefits have no icon; weekly expiration keeps it.
            for sequence,state in [(8,'unavailable'),(9,'ineligible'),(10,'expended')]:
                store.ingest(dict(schema_version=1,pid=43,realm='prime',reporter_id='design',sequence=sequence,
                    character=dict(name='Dartwen'),bonuses=dict(lumnis_stage='expired',observed_at=int(time.time()),
                        fashlonae_state=state,fashlonae_observed_at=int(time.time()))),service.sessions())
                page.evaluate('refresh()')
                expected=1 if state=='expended' else 0
                page.wait_for_function("count => [...document.querySelectorAll('.live-card')].find(row => row.querySelector('.character-link')?.textContent==='Dartwen')?.querySelectorAll('.tutelage-icon').length===count",arg=expected)
                assert dartwen.locator('.lumnis-icon').count()==1
            assert dartwen.locator('.session-xp-rate').inner_text()=='—'
            assert dartwen.locator('.recent-xp-rate').inner_text()=='—'
            assert wizard.locator('.cycle-renewal').inner_text()=='Resets in 3d 20h'
            assert 'Last observed' not in page.locator('#sessionList').inner_text()
            assert 'Level in' not in wizard.inner_text()
            assert page.locator('.row-identity .profile-summary').count()==0
            assert critical.locator('.mind-state progress').get_attribute('value')=='0'
            level_progress=critical.locator('.level-progress')
            assert level_progress.count()==1, 'Uncapped characters need next-level progress'
            assert level_progress.locator('span').all_text_contents()==['To level 21','42.5%']
            assert level_progress.locator('progress').get_attribute('value')=='42.5'
            assert critical.locator('.row-identity .level-progress').count()==0
            assert critical.locator('.row-vitals > .level-progress:first-child').count()==1
            assert 'Est. 2h to level' in level_progress.inner_text(), level_progress.inner_text()
            assert page.locator('.level-progress').count()==1, 'Level 100 characters must not show next-level progress'
            atp_progress=wizard.locator('.row-vitals > .atp-progress:first-child')
            assert atp_progress.locator('progress').get_attribute('value')=='60'
            assert '20,000 XP to next ATP' in atp_progress.inner_text()
            cards=page.locator('.live-card')
            first,second=cards.nth(0).bounding_box(),cards.nth(1).bounding_box()
            assert abs(first['y']-second['y'])<2 and second['x']>first['x'], 'Desktop cards must be two across'
            assert wizard.locator('.live-card-heading .launch-button').count()==1
            wizard.locator('.live-card-heading .icon-button').click()
            assert page.locator('#confirmTitle').inner_text()=='Disconnect Renwaldo?'
            page.locator('#confirmCancel').click()
            page.evaluate('refresh()')
            assert wizard.locator('.row-identity .live-card-heading + .room').inner_text()=='Old Ta’Faendryl, Southeast · Lich 231'
            assert wizard.locator('.row-identity .room + .live-sub').inner_text()=='Level 100 · Wizard · 0 PTP · 1,234 MTP'
            assert critical.locator('.live-sub').inner_text()=='Level 20 · Wizard · 12.49% to cap'
            assert tutelage_active.locator('.live-sub').inner_text()=='Level 100 · Bard · — PTP · — MTP'
            page.screenshot(path='/tmp/gempy-redesign-desktop.png',full_page=True)
            for width in (2560,1920,1600,1500,1499,1440,1280,1250,1166,1165,1024,768,650,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                if width in (1440,1024):page.screenshot(path=f'/tmp/gempy-live-{width}.png',full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow at {width}'
                outer,grid=page.locator('main').bounding_box(),page.locator('#sessionList').bounding_box()
                assert 0<=outer['x']+outer['width']-grid['x']-grid['width']<=24,f'Excess space beside cards at {width}'
                first,second=cards.nth(0).bounding_box(),cards.nth(1).bounding_box()
                assert (abs(first['y']-second['y'])<2)==(width>=1166),f'Incorrect card columns at {width}'
                assert level_progress.is_visible(),f'Next-level progress hidden at {width}'
                for value in wizard.locator('.resource-weekly,.resource-stored').all():
                    assert value.is_visible(),f'Balance hidden at {width}'
                    assert value.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1'),f'Balance clipped at {width}'
                if width<=650:
                    assert wizard.locator('.character-actions .launch-button').bounding_box()['height']>=44
            page.set_viewport_size({'width':1280,'height':1000})
            page.get_by_role('button',name='Collapse sidebar',exact=True).click()
            for width in (1280,1060,1059):
                page.set_viewport_size({'width':width,'height':1000})
                first,second=cards.nth(0).bounding_box(),cards.nth(1).bounding_box()
                assert (abs(first['y']-second['y'])<2)==(width>=1060),f'Incorrect collapsed-sidebar card columns at {width}'
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.get_by_role('button',name='Expand sidebar',exact=True).click()
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path='/tmp/gempy-redesign-mobile.png',full_page=True)
            wizard.locator('.level-profile').click()
            page.wait_for_function("() => document.querySelector('#detailContent').textContent.includes('145,223')")
            assert page.locator('#detailTabs button').count()==4
            assert page.locator('#detailTabs').inner_text().splitlines()==['Overview','Stats','Skills','History']
            assert 'Active ×3' in page.locator('#detailContent').inner_text()
            assert '5,440' in page.locator('#detailContent').inner_text()
            assert page.get_by_text('Live status',exact=True).is_visible()
            assert page.locator('.profile-tutelage-card').is_visible()
            assert 'Not reported' in page.locator('.profile-tutelage-card').inner_text()
            page.locator('#detailContent').get_by_text('Experience & training',exact=True).click()
            assert page.locator('.pin-options').is_visible()
            page.screenshot(path='/tmp/gempy-redesign-profile-mobile.png',full_page=True)
            page.locator('#detailClose').click()
            # Known zero balances remain visible and stale vitals are not urgent alerts.
            data['sequence']=2;data['resources'].update(weekly=0,total=0)
            data['experience'].update(hourly_rate=0,last_hour_gain=0)
            store.ingest(data,service.sessions())
            store.live['42:100']['monotonic']-=30
            store.live['44:100']['monotonic']-=30
            # Automatic polling must update the cards without a Refresh button.
            page.wait_for_function("() => document.querySelector('[data-session-id=\"45:100\"] .resource-stored').textContent==='0 / 200,000'")
            assert wizard.locator('.resource-weekly').inner_text()=='0 / 50,000'
            assert wizard.locator('.session-xp-rate').inner_text()=='0'
            assert wizard.locator('.recent-xp-rate').inner_text()=='0'
            assert critical.locator('.vital-warning').count()==0
            assert 'Last known: Active' in tutelage_active.locator('.tutelage-icon + .bonus-tooltip').text_content()
            assert 'is-stale' in tutelage_active.locator('.tutelage-icon').get_attribute('class')
            tutelage_active.locator('.character-link').click()
            page.wait_for_function("() => document.querySelector('.profile-tutelage-card')?.textContent.includes('Last known active ×5')")
            page.locator('#detailClose').click()
            wizard.locator('.inspect-button').focus()
            page.wait_for_timeout(3500)
            assert page.evaluate("document.activeElement.getAttribute('aria-label')")=='Details for Renwaldo on prime'
            # Formatting is Pacific even when the browser uses another timezone.
            # Winter/summer dates also test the previous-day conversion and AM/PM.
            for seq,utc,expected in [(3,'2027-01-15T05:30:00+00:00','Thursday 1/14 at 9:30pm PST'),
                                     (4,'2027-07-15T04:30:00+00:00','Wednesday 7/14 at 9:30pm PDT'),
                                     (5,'2027-01-15T08:05:00+00:00','Friday 1/15 at 12:05am PST')]:
                data['sequence']=seq;data['bonuses']['lumnis_reset_at']=int(datetime.fromisoformat(utc).timestamp())
                store.ingest(data,service.sessions())
                page.evaluate('refresh()')
                page.wait_for_function("expected => document.querySelector('[data-session-id=\"45:100\"] .cycle-renewal').title.includes(expected)",arg=expected)
            wizard.locator('.character-link').click()
            page.wait_for_function("() => document.querySelector('#detailContent .cycle-renewal')?.textContent.includes('12:05am PST')")
            page.locator('#detailContent').get_by_text('Cycle & donation details',exact=True).click()
            assert 'Next renewal (Pacific)' in page.locator('#detailContent').inner_text()
            page.locator('#detailClose').click()
            data['sequence']=6;data['bonuses']['lumnis_reset_at']=now-60
            store.ingest(data,service.sessions());page.evaluate('refresh()')
            page.wait_for_function("() => document.querySelector('[data-session-id=\"45:100\"] .cycle-renewal').textContent.includes('Awaiting game update')")
            for seq,remaining,expected in [(7,1800,'Resets in 0d 0h'),(8,86400+1800,'Resets in 1d 0h')]:
                data['sequence']=seq;data['bonuses']['lumnis_reset_at']=int(time.time())+remaining
                store.ingest(data,service.sessions());page.evaluate('refresh()')
                page.wait_for_function("expected => document.querySelector('[data-session-id=\"45:100\"] .cycle-renewal').textContent===expected",arg=expected)
            # Cap progress preserves two decimal places, including trailing zeroes.
            for value,expected in [(12.5,'12.50% to cap'),(0,'0.00% to cap'),(None,'— to cap')]:
                with store.lock:
                    store.live['42:100']['snapshot']['experience']['percent_capped']=value
                page.evaluate('refresh()')
                page.wait_for_function("expected => document.querySelector('[data-session-id=\"42:100\"] .live-sub').textContent.endsWith(expected)",arg=expected)
            # Zero is actual progress; absent progress must not be labeled 0%.
            for value,expected in [(0,'0%'),(None,'Not reported')]:
                with store.lock:
                    store.live['42:100']['snapshot']['experience']['next_level_percent']=value
                page.evaluate('refresh()')
                page.wait_for_function("expected => document.querySelector('[data-session-id=\"42:100\"] .level-progress').textContent.includes(expected)",arg=expected)
            for gain,remaining,expected in [(0,15200,'ETA unavailable'),(None,15200,'ETA unavailable'),
                                             (7600,None,'ETA unavailable'),(7600,0,'Est. 0s to level')]:
                with store.lock:
                    store.live['42:100']['snapshot']['experience'].update(last_hour_gain=gain,experience_to_next_level=remaining)
                page.evaluate('refresh()')
                page.wait_for_function("expected => document.querySelector('[data-session-id=\"42:100\"] .level-progress').textContent.includes(expected)",arg=expected)
            for total,remaining,expected,percent in [(100000,20000,'50,000 XP to next ATP','0'),
                                                     (None,12500,'12,500 XP to next ATP','75'),
                                                     (None,0,'0 XP to next ATP','100'),
                                                     (None,None,'XP to next ATP not reported','0')]:
                with store.lock:
                    store.live['45:100']['snapshot']['experience'].update(ascension_exp=total,exp_to_next_atp=remaining)
                page.evaluate('refresh()')
                page.wait_for_function("expected => document.querySelector('[data-session-id=\"45:100\"] .atp-progress .progress-note').textContent===expected",arg=expected)
                assert atp_progress.locator('progress').get_attribute('value')==percent
            with store.lock:
                store.live['42:100']['snapshot']['character']['level']=100
            page.evaluate('refresh()')
            page.wait_for_function("() => document.querySelectorAll('.level-progress').length===0")
            assert critical.locator('.row-vitals > .atp-progress:first-child').count()==1
            assert not errors,errors
            browser.close()
            print('Redesign checks passed: two-card desktop grid, inline client controls, level profile link, location and Lich ID, critical vitals, exact balances, four profile tabs, mobile and desktop layouts')
    finally:
        server.should_exit=True;thread.join(timeout=5)
