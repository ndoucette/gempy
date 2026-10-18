"""Recovery, delayed responses, polling and keyboard checks for the workspace."""
from playwright.sync_api import sync_playwright, expect
from ux_fixture import dashboard_fixture, PASSWORD


def login(page, url):
    page.goto(url)
    page.locator('input[name=password]').fill(PASSWORD)
    page.locator('#loginButton').click()
    page.wait_for_selector('.live-card')


with dashboard_fixture() as (url, app), sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.set_default_timeout(8000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    login(page, url)
    # A late default-view request must not replace the restored period.
    page.evaluate("api('settings','POST',{default_view:'progress'})")
    page.locator('#progressTab').click()
    page.locator('#progressPeriod').select_option('year')
    page.wait_for_function("() => progressData?.period_key === String(new Date().getFullYear())")
    page.add_init_script("""const originalFetch=window.fetch;
        window.fetch=async function(url,...args){
          if(String(url).includes('progress?period=day'))await new Promise(r=>setTimeout(r,800));
          return originalFetch.call(this,url,...args);
        };""")
    page.reload()
    page.wait_for_selector('.progress-character')
    page.wait_for_timeout(1200)  # Deliberately let the older delayed response arrive.
    expect(page.locator('#progressPeriod')).to_have_value('year')
    assert page.evaluate('progressData.period_key === String(new Date().getFullYear())'), 'Late Today response overwrote Year'
    page.locator('.progress-character').filter(has_text='Briar').click()
    page.locator('[data-detail=stats]').click()
    page.reload()
    page.wait_for_selector('.profile-table')
    page.locator('[data-detail=history]').click()
    expect(page.get_by_label('Character history period')).to_have_value('year')
    page.locator('#detailClose').click()
    page.locator('#rotationTab').click()
    page.wait_for_selector('.rotation-card')
    page.locator('#rotationAccount').select_option('Enchanters')
    page.reload()
    page.wait_for_selector('.rotation-card')
    expect(page.locator('#rotationAccount')).to_have_value('Enchanters')
    # Comparison errors remain recoverable without discarding identity/scope.
    page.locator('#sessionsTab').click()
    page.get_by_role('button', name='Inspect Aster on prime', exact=True).click()
    page.locator('[data-detail=stats]').click()
    page.route('**/api/profiles/prime/Cinder', lambda route: route.fulfill(status=503, json={'detail': 'Fixture unavailable'}))
    page.get_by_label('Compare with', exact=True).select_option('prime:Cinder')
    expect(page.locator('#detailContent')).to_contain_text('Could not load comparison')
    expect(page.get_by_label('Compare with', exact=True)).to_have_value('prime:Cinder')
    page.unroute('**/api/profiles/prime/Cinder')
    page.get_by_role('button', name='Retry comparison').click()
    expect(page.locator('.comparison-table')).to_contain_text('Cinder · Prime')
    # A slower old comparison must not overwrite a newer target.
    page.get_by_label('Compare with', exact=True).select_option('')
    page.evaluate("""() => {const fetchBeforeDelay=window.fetch;window.fetch=async function(url,...args){
        if(String(url).includes('/profiles/prime/Cinder'))await new Promise(resolve=>setTimeout(resolve,500));
        return fetchBeforeDelay.call(this,url,...args);
    };}""")
    page.get_by_label('Compare with', exact=True).select_option('prime:Cinder')
    page.get_by_label('Compare with', exact=True).select_option('prime:Dusk')
    expect(page.locator('.comparison-table')).to_contain_text('Dusk · Prime')
    page.wait_for_timeout(700)
    expect(page.locator('.comparison-table')).not_to_contain_text('Cinder · Prime')
    # Keyboard selection and live refresh cannot discard a skill query/focus.
    page.locator('[data-detail=skills]').click()
    search = page.get_by_label('Find a skill', exact=True)
    search.fill('arcane')
    page.evaluate('refresh()')
    expect(search).to_have_value('arcane')
    expect(search).to_be_focused()
    page.get_by_label('Compare with', exact=True).focus()
    page.keyboard.press('Home')
    page.keyboard.press('Tab')
    expect(page.get_by_label('Compare with', exact=True)).to_have_value('')
    expect(page.get_by_label('Find a skill', exact=True)).to_have_value('arcane')
    page.keyboard.press('Escape')
    expect(page.locator('#characterDetails')).not_to_be_visible()
    expect(page.get_by_role('button', name='Inspect Aster on prime', exact=True)).to_be_focused()
    # Local filters remain local, and empty-filter recovery exposes existing data.
    page.locator('#sessionsTab').click()
    expect(page.locator('#sessions .live-filters')).to_have_count(0)
    expect(page.locator('.live-card')).to_have_count(3)
    expect(page.locator('.row-resources')).to_have_count(3)
    page.locator('#progressTab').click()
    page.locator('#progressSearch').fill('Nobody')
    expect(page.get_by_role('button', name='Clear progress filters')).to_be_visible()
    page.get_by_role('button', name='Clear progress filters').click()
    expect(page.locator('.progress-character')).to_have_count(3)
    # Invalid fragments and unknown profiles produce usable recovery.
    page.goto(url+'/#view=invalid&character=bogus&section=bogus')
    page.wait_for_selector('#app:not([hidden])')
    expect(page.locator('#characterDetails')).not_to_be_visible()
    page.goto(url+'/#view=characters&character=prime:Unknown&section=stats')
    expect(page.locator('#detailContent')).to_contain_text('Could not load profile')
    page.locator('#detailClose').click()
    expect(page.locator('#characters')).to_be_visible()
    assert not errors, errors
    browser.close()
    print('UX resilience passed: delayed responses, history scope, rotation filters, retry, polling, keyboard, empty results and invalid URLs')
