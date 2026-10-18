"""Task-based UX regressions against a real, isolated FastAPI application."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from ux_fixture import dashboard_fixture, PASSWORD

OUTPUT = Path(__file__).resolve().parents[1] / 'docs/ux/screenshots'


def run():
    with dashboard_fixture() as (url, app), sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page.set_default_timeout(8000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        page.locator('input[name=password]').fill(PASSWORD)
        page.locator('#loginButton').click()
        page.wait_for_selector('.live-card')
        page.locator('#charactersTab').click()
        page.get_by_role('button', name='Profile for Aster on prime', exact=True).click()
        page.locator('[data-detail=stats]').click()
        page.wait_for_selector('.profile-table')
        # Switching must keep the question (Stats), not return to Overview.
        expect(page.get_by_label('Character to inspect', exact=True)).to_be_visible()
        page.get_by_label('Character to inspect', exact=True).select_option('prime:Cinder')
        expect(page.locator('#detailTitle')).to_have_text('Cinder')
        expect(page.locator('[data-detail=stats]')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('.profile-table tbody tr').first).to_contain_text('73')
        # Two same-name identities in different realms must never be merged.
        page.get_by_label('Compare with', exact=True).select_option('test:Aster')
        expect(page.locator('.comparison-table')).to_contain_text('Cinder · Prime')
        expect(page.locator('.comparison-table')).to_contain_text('Aster · Test')
        page.get_by_label('Stat values', exact=True).select_option('base')
        expect(page.locator('.comparison-table tbody tr').first).to_contain_text('73')
        expect(page.locator('.comparison-table tbody tr').first).to_contain_text('72')
        page.screenshot(path=str(OUTPUT / 'after-comparison.png'))
        page.locator('[data-detail=skills]').click()
        page.get_by_label('Show untrained', exact=True).check()
        page.get_by_label('Find a skill', exact=True).fill('swimming')
        expect(page.locator('.comparison-table tbody tr')).to_have_count(1)
        expect(page.locator('.comparison-table tbody tr')).to_contain_text('0')
        page.get_by_label('Character to inspect', exact=True).select_option('prime:Dusk')
        expect(page.get_by_label('Find a skill', exact=True)).to_have_value('swimming')
        page.get_by_label('Compare with', exact=True).select_option('prime:Unreported')
        expect(page.locator('.comparison-table')).to_contain_text('—')
        expect(page.locator('#detailContent')).to_contain_text('Not yet reported')
        page.locator('[data-detail=stats]').click()
        saved_url = page.url
        page.reload()
        expect(page.locator('#characterDetails')).to_be_visible()
        expect(page.locator('#detailTitle')).to_have_text('Dusk')
        expect(page.get_by_label('Compare with', exact=True)).to_have_value('prime:Unreported')
        expect(page.locator('[data-detail=stats]')).to_have_attribute('aria-pressed', 'true')
        assert page.url == saved_url
        expect(page.get_by_label('Stat values', exact=True)).to_have_value('base')
        page.locator('#detailClose').click()
        expect(page.locator('#characters')).to_be_visible()
        page.locator('#search').fill('Cinder')
        page.reload()
        expect(page.locator('#search')).to_have_value('Cinder')
        expect(page.locator('#accounts .character')).to_have_count(1)
        page.locator('#search').fill('Nobody')
        page.get_by_role('button', name='Clear roster filters', exact=True).click()
        expect(page.locator('#accounts .character')).to_have_count(6)
        page.screenshot(path=str(OUTPUT / 'after-roster.png'), full_page=True)
        disclosure = page.get_by_text('Cycle & resource details for Cinder', exact=True)
        disclosure.click()
        expect(page.locator('.roster-disclosure[open]')).to_contain_text('118,753')
        page.evaluate('refresh()')
        expect(page.locator('.roster-disclosure[open]')).to_contain_text('118,753')
        disclosure.click()
        page.locator('#progressTab').click()
        page.locator('#progressPeriod').select_option('year')
        page.locator('.progress-character').filter(has_text='Briar').click()
        expect(page.get_by_label('Character history period')).to_have_value('year')
        page.locator('#detailClose').click()
        page.locator('#progressPeriod').select_option('custom')
        page.locator('#progressStart').fill('2026-01-01')
        page.locator('#progressEnd').fill('2026-12-31')
        page.locator('.progress-character').filter(has_text='Briar').click()
        expect(page.locator('#detailContent')).to_contain_text('2026-01-01')
        page.get_by_label('Compare with', exact=True).select_option('prime:Aster')
        expect(page.locator('.comparison-table')).to_contain_text('Combined XP')
        expect(page.locator('#detailContent')).to_contain_text('2026-12-31')
        page.locator('#detailClose').click()
        page.locator('#rotationTab').click()
        page.go_back()
        expect(page.locator('#progress')).to_be_visible()
        page.go_forward()
        expect(page.locator('#rotation')).to_be_visible()
        # Navigation bounds, not only document overflow, catch clipped controls.
        for width in (320, 390, 768, 1024, 1440, 1920):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
            for name in ['sessions', 'rotation', 'progress', 'characters', 'settings']:
                box = page.locator('#'+name+'Tab').bounding_box()
                assert box['x'] >= 0 and box['x']+box['width'] <= width+1, (width, name, box)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('#charactersTab').click()
        page.screenshot(path=str(OUTPUT / 'after-roster-mobile.png'), full_page=True)
        height = page.locator('.character').first.bounding_box()['height']
        assert height < 280, height
        print(f'Mobile roster entry: {height:.1f}px (baseline 395.5px)')
        page.get_by_role('button', name='Profile for Aster on prime', exact=True).click()
        page.get_by_label('Compare with', exact=True).select_option('prime:Cinder')
        page.locator('[data-detail=stats]').click()
        expect(page.locator('.comparison-table')).to_be_visible()
        page.screenshot(path=str(OUTPUT / 'after-comparison-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.keyboard.press('Escape')
        expect(page.locator('#characterDetails')).not_to_be_visible()
        assert page.evaluate('document.activeElement !== document.body')
        assert not errors, errors
        browser.close()
        print('UX workflows passed: switching, comparisons, unknown/zero, realms, persistence, history scope, Back/Forward, disclosure, mobile, keyboard return')


if __name__ == '__main__':
    run()
