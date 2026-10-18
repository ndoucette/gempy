"""Isolated, realistic dashboard data for UX checks; never connects to Lich."""
from contextlib import contextmanager
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
import yaml
from web_app import create_app, save_password

PASSWORD = 'isolated browser password'


class FixtureService:
    def sessions(self):
        return [dict(id=f'{42+i}:100', pid=42+i, character=name, realm=realm,
                     running=True, attachment='Attached' if i == 0 else 'Headless')
                for i, (name, realm) in enumerate([
                    ('Aster', 'prime'), ('Briar', 'prime'), ('Aster', 'test')])]

    def launch(self, *args, **kwargs):
        return {'message': 'Fixture launch complete'}

    def attach(self, *args, **kwargs):
        return {'message': 'Fixture client attached'}


@contextmanager
def dashboard_fixture():
    with tempfile.TemporaryDirectory(prefix='gempy-ux-') as directory:
        root = Path(directory)
        save_password(PASSWORD, root)
        config = {'accounts': {'Main': ['Aster', 'Briar'],
                               'Enchanters': ['Cinder', 'Dusk', 'Ember', 'Unreported']},
                  'weekly_rotation': {'account_roles': {'Enchanters': 'utility'},
                      'characters': [dict(name=name, account=account, role=role)
                          for name, account, role in [('Aster', 'Main', 'main'),
                              ('Cinder', 'Enchanters', 'wizard'),
                              ('Dusk', 'Enchanters', 'wizard'),
                              ('Ember', 'Enchanters', 'wizard')]]}}
        config_path = root / 'config.yaml'
        config_path.write_text(yaml.safe_dump(config))
        service = FixtureService()
        app = create_app(config, service, root, config_path=config_path)
        store = app.state.telemetry
        now = int(time.time())
        for i, (name, realm) in enumerate([('Aster', 'prime'), ('Briar', 'prime'),
                                           ('Aster', 'test'), ('Cinder', 'prime'),
                                           ('Dusk', 'prime'), ('Ember', 'prime')]):
            observation = now - (86400 if name == 'Ember' else 0)
            snapshot = dict(schema_version=1, pid=42+i, realm=realm,
                reporter_id='ux-fixture', sequence=1,
                character=dict(name=name, level=80+i, profession='Sorcerer' if i == 1 else 'Wizard', race='Elf'),
                stats={stat: dict(base_value=70+i, base_bonus=10+i, value=80+i,
                                 bonus=15+i, enhanced_value=90+i, enhanced_bonus=20+i)
                       for stat in ['strength', 'constitution', 'dexterity', 'agility',
                                    'discipline', 'aura', 'logic', 'intuition', 'wisdom', 'influence']},
                skills=dict(arcane_symbols=dict(ranks=180+i, bonus=280+i, category='skill'),
                            wizard=dict(ranks=80+i, bonus=None, category='spell_research'),
                            swimming=dict(ranks=0, bonus=0, category='skill')),
                bonuses=dict(lumnis_stage='expired' if name in ('Dusk', 'Ember') else 3,
                    lumnis_points_remaining=4500, lumnis_donations=2,
                    lumnis_reset_at=now-60 if name == 'Ember' else now+86400,
                    observed_at=observation, fashlonae_state='inactive'),
                resources=dict(type='Necrotic Energy' if i == 1 else 'Essence',
                    weekly=50000 if name == 'Dusk' else 12000+i, total=118750+i,
                    max_weekly=50000, max_total=200000, observed_at=observation),
                vitals={key: dict(current=9 if i == 1 else 90, max=100)
                        for key in ['health', 'mana', 'stamina', 'spirit']},
                location=dict(room_title='Town Square Central', room_id=228),
                status=dict(mindstate=dict(text='Clear', value=0), stance=dict(text='Defensive')),
                experience=dict(lifetime_exp=1000000, ascension_exp=50000, hourly_rate=1234),
                injuries=dict(wounds={'head': 1}, scars={}),
                effects=dict(spells=[dict(name='Stone Skin', end_time=now+3600)], buffs=[], debuffs=[], cooldowns=[]))
            if i < 3:
                store.ingest(snapshot, service.sessions())
                snapshot['sequence'] = 2
                snapshot['experience']['lifetime_exp'] += 125*(i+1)
                store.ingest(snapshot, service.sessions())
            else:
                with store.lock, store.db:
                    store.profiles.ingest(realm, name, snapshot, observation)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic()+10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError('Fixture server did not start')
            time.sleep(.02)
        try:
            yield f'http://127.0.0.1:{port}', app
        finally:
            server.should_exit = True
            thread.join(timeout=5)


if __name__ == '__main__':
    with dashboard_fixture() as (url, app):
        print(url, flush=True)
        threading.Event().wait()
