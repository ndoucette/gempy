from datetime import datetime
import unittest

import test_dashboard_api
from weekly_rotation import build_rotation, previous_renewal


NOW=datetime.fromisoformat('2026-10-15T20:00:00+00:00').timestamp()
RESET=NOW+86400
CONFIG={'accounts':{'Main':['Hero','Wizard'],'Utility':['Other']},'weekly_rotation':{
    'account_roles':{'Main':'main','Utility':'utility'},
    'characters':[{'name':'Hero','account':'Main','role':'main'},
                  {'name':'Wizard','account':'Main','role':'wizard','weekly_target':50000},
                  {'name':'Other','account':'Utility','role':'wizard','weekly_target':50000}]}}


def profile(name='Wizard',stage='expired',weekly=50000,reset=RESET,observed=NOW):
    return dict(character=name,realm='prime',snapshot={
        'character':{'profession':'Wizard','level':100},
        'bonuses':{'lumnis_stage':stage,'lumnis_reset_at':reset,'fashlonae_state':'expended'},
        'resources':{'type':'Essence','weekly':weekly,'total':145223,'max_weekly':50000}},
        field_observed_at={'bonuses':{'lumnis_stage':observed,'lumnis_reset_at':observed},
                           'resources':{'weekly':observed,'total':observed}},updated_at=observed)


class RotationTests(unittest.TestCase):
    def row(self,profiles,now=NOW):
        return next(row for row in build_rotation(CONFIG,profiles,[],now)['wizards'] if row['character']=='Wizard')

    def test_done_requires_both_current_cycle_goals(self):
        row=self.row([profile()]);self.assertEqual(row['state'],'done')
        self.assertEqual(row['resources']['total'],145223)
        self.assertEqual(self.row([profile(stage=3)])['state'],'needs_hunting')
        self.assertEqual(self.row([profile(weekly=0)])['state'],'needs_hunting')
        self.assertEqual(self.row([profile(stage='ready')])['state'],'needs_hunting')

    def test_missing_and_previous_cycle_values_do_not_complete(self):
        self.assertEqual(self.row([])['state'],'needs_update')
        self.assertEqual(self.row([profile(reset=NOW-1)])['state'],'needs_update')
        self.assertEqual(self.row([profile(observed=NOW-8*86400)])['state'],'needs_update')
        old=profile();old['field_observed_at']['resources']['weekly']=NOW-8*86400
        self.assertEqual(self.row([old])['state'],'needs_update')
        missing=profile();missing['snapshot']['resources']['weekly']=None
        self.assertEqual(self.row([missing])['state'],'needs_update')

    def test_rollover_invalidates_previous_completion_without_resetting_numbers(self):
        row=self.row([profile()],now=RESET+1)
        self.assertEqual(row['state'],'needs_update')
        self.assertEqual(row['resources']['weekly'],50000)
        self.assertTrue(row['reset_passed'])

    def test_calendar_week_handles_dst(self):
        reset=datetime.fromisoformat('2026-11-04T20:00:00+00:00').timestamp()
        expected=datetime.fromisoformat('2026-10-28T19:00:00+00:00').timestamp()
        self.assertEqual(previous_renewal(reset),expected)

    def test_deadline_order_account_occupancy_and_unregistered_main(self):
        config={**CONFIG,'weekly_rotation':{**CONFIG['weekly_rotation'],'characters':CONFIG['weekly_rotation']['characters']+[{'name':'Voxy','account':'Main','role':'main'}]}}
        sessions=[dict(character='Hero',realm='prime',running=True,id='1:100')]
        rows=[profile(weekly=2000),profile('Other',weekly=3000,reset=NOW+3600)]
        result=build_rotation(config,rows,sessions,NOW)
        self.assertEqual(result['wizards'][0]['character'],'Other')
        wizard=next(row for row in result['wizards'] if row['character']=='Wizard')
        self.assertEqual(wizard['account_occupant'],'Hero')
        self.assertFalse(wizard['can_launch'])
        voxy=next(row for row in result['mains'] if row['character']=='Voxy')
        self.assertFalse(voxy['registered'])
        self.assertEqual(voxy['state'],'needs_update')

    def test_realms_are_isolated_and_configuration_can_be_empty(self):
        other=profile();other['realm']='test'
        self.assertEqual(self.row([other])['state'],'needs_update')
        self.assertFalse(build_rotation({},[],[],NOW)['configured'])
        self.assertEqual(self.row([profile(reset=10**15)])['state'],'needs_update')

    def test_unregistered_main_still_occupies_its_verified_account(self):
        config={**CONFIG,'weekly_rotation':{**CONFIG['weekly_rotation'],'characters':CONFIG['weekly_rotation']['characters']+[{'name':'Voxy','account':'Main','role':'main'}]}}
        result=build_rotation(config,[],[dict(character='Voxy',realm='prime',running=True,id='external')],NOW)
        wizard=next(row for row in result['wizards'] if row['character']=='Wizard')
        self.assertEqual(wizard['account_occupant'],'Voxy')
        self.assertFalse(wizard['can_launch'])


class RotationApiTests(unittest.TestCase):
    setUp=test_dashboard_api.DashboardApiTests.setUp
    tearDown=test_dashboard_api.DashboardApiTests.tearDown

    def test_rotation_auth_and_defaults(self):
        result=self.client.get('/api/rotation?realm=prime')
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json()['configured'])
        self.assertEqual(self.client.get('/api/rotation?realm=bad').status_code,400)
        self.client.post('/api/logout',headers=self.headers)
        self.assertEqual(self.client.get('/api/rotation').status_code,401)
