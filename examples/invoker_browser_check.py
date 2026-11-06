"""Invoker strips against isolated data; never connects to game sessions."""
from pathlib import Path
import re
import sys
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.ux_fixture import dashboard_fixture, PASSWORD

with dashboard_fixture() as (url, app), sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width':1440,'height':1100})
    page.set_default_timeout(5000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url+'/?view=sessions')
    page.locator('#login input[name=password]').fill(PASSWORD)
    page.locator('#loginButton').click()
    page.wait_for_selector('.live-card')
    page.wait_for_timeout(500)
    page.evaluate("""() => {
      clearInterval(pollTimer);
      invokerCountdown.state=()=>({remaining:0,nextIn:3600,nextAt:Date.now()+3600000});
      const now=Date.now()/1000;
      const names=['Natural Colors','Resist Elements','Mobility','Mass Blur','Foresight'];
      sessions=['Aster','Briar','Cinder','Dusk','Ember'].map((character,i)=>({
        id:'invoker-'+i,character,realm:'prime',running:true,attachment:'Headless',
        telemetry:{status:i===4?'stale':'fresh',received_at:new Date().toISOString(),
          snapshot:{collected_at:now,character:{profession:'Sorcerer',level:100},
            skills:{sorcerer:{ranks:100}},effects:{buffs:[],spells:
              (i===2?names.slice(0,3):i===3?['Mass Blur','Fortitude Song','Song of Mirrors']:names).map(name=>({name,end_time:now+(i===1?1920:8280)}))}}}
      }));
      renderSessions();
    }""")
    strips=page.locator('.invoker-buff-strip')
    expect(strips).to_have_count(5)
    cards=lambda name: page.locator('.live-card').filter(has=page.get_by_role('button',name='Inspect '+name+' on prime',exact=True))
    aster=cards('Aster');briar=cards('Briar');cinder=cards('Cinder');dusk=cards('Dusk');ember=cards('Ember')
    expect(aster.locator('.invoker-buff-strip')).to_have_attribute('data-state','covered')
    expect(aster.locator('.invoker-buff-status')).to_be_hidden()
    expect(briar.locator('.invoker-buff-strip')).to_have_attribute('data-state','gap')
    expect(briar.locator('.invoker-buff-status')).to_be_hidden()
    expect(cinder.locator('.invoker-buff-strip')).to_have_attribute('data-state','covered')
    expect(cinder.locator('.invoker-buff-strip')).not_to_contain_text('Partial')
    expect(dusk.locator('.invoker-buff-strip')).to_contain_text('Missing')
    expect(ember.locator('.invoker-buff-strip')).to_contain_text('Unknown')
    assert aster.locator('.live-sub + .invoker-buff-strip').count()==1

    # Click and keyboard use the same detail surface; dialog remains open through polling.
    button=aster.locator('.invoker-buff-strip button')
    expect(button).to_have_accessible_description(re.compile(r'2h .*Covers next invoker'))
    button.focus();button.press('Enter')
    dialog=page.locator('#invokerBuffDetails')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('Natural Colors')
    expect(dialog).to_contain_text('Covers next invoker')
    expect(dialog).to_contain_text('Foresight')
    expect(dialog).not_to_contain_text('Spirit Defense')
    page.evaluate('renderSessions()')
    expect(dialog).to_be_visible()
    dialog.get_by_role('button',name='Close').click()
    expect(button).to_be_focused()
    page.evaluate('renderSessions()')
    expect(button).to_be_focused()

    cinder.locator('.invoker-buff-strip button').click()
    expect(dialog).not_to_contain_text('Partial')
    expect(dialog).to_contain_text('Covers next invoker')
    expect(dialog.locator('.invoker-marker-missing')).to_have_count(2)
    expect(dialog.locator('.invoker-marker-missing').first).to_contain_text('Not active')
    dialog.get_by_role('button',name='Close').click()
    page.screenshot(path='/tmp/gempy-invoker-desktop.png',full_page=True)

    for width in (768,390,320):
        page.set_viewport_size({'width':width,'height':950})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        assert strips.evaluate_all('(els)=>els.every(el=>el.scrollWidth<=el.clientWidth+1)'), width
    aster.locator('.invoker-buff-strip button').click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path='/tmp/gempy-invoker-mobile.png',full_page=True)
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()

    # Timer and stale-state changes must happen without a new API render.
    page.evaluate("""() => {
      const s=sessions.find(s=>s.character==='Aster');
      s.telemetry.received_at=new Date().toISOString();
      s.telemetry.snapshot.effects.spells.forEach(e=>e.end_time=Date.now()/1000+2);
    }""")
    expect(aster.locator('.invoker-buff-strip')).to_have_attribute('data-state','gap')
    expect(aster.locator('.invoker-buff-strip')).to_contain_text('<1m')
    expect(aster.locator('.invoker-buff-strip')).to_have_attribute('data-state','missing')
    page.evaluate("sessions.find(s=>s.character==='Briar').telemetry.received_at=new Date(Date.now()-3600000).toISOString()")
    expect(briar.locator('.invoker-buff-strip')).to_have_attribute('data-state','unknown')
    assert not errors, errors
    print('PASS: renewal states, spellburst omissions, marker details, focus/polling, live expiry, stale data, and 768/390/320px layouts')
    browser.close()
