"""Durable last-observed profile sections, independent of live session expiry."""
import json
import math
import time

SECTIONS = ('character', 'stats', 'skills', 'bonuses', 'resources')


def validate_profile(data):
    """Validate optional version-one extensions before ingest changes any state."""
    for section in SECTIONS:
        value = data.get(section)
        if value is not None and not isinstance(value, dict):
            # Legacy reporters may send just the character name.
            if section == 'character' and isinstance(value, str):
                continue
            raise ValueError(f'{section} must be an object')
    metadata = data.get('metadata')
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError('Metadata must be an object')
    availability = (metadata or {}).get('availability', {})
    if not isinstance(availability, dict):
        raise ValueError('Availability must be an object')
    for value in availability.values():
        if not isinstance(value, dict):
            raise ValueError('Availability entries must be objects')
        if 'available' in value and type(value['available']) is not bool:
            raise ValueError('Invalid availability flag')
        numeric(value.get('collected_at'), 'collection time')
    for section in ('stats', 'skills'):
        for name, entry in (data.get(section) or {}).items():
            if not isinstance(entry, dict):
                raise ValueError(f'{section} entries must be objects')
            allowed = ('value', 'bonus', 'base_value', 'base_bonus', 'enhanced_value', 'enhanced_bonus') if section == 'stats' else ('ranks', 'bonus')
            for key in allowed:
                numeric(entry.get(key), f'{section}.{name}.{key}', signed=section == 'stats')
            if 'category' in entry and entry['category'] not in ('skill', 'spell_research'):
                raise ValueError('Unknown skill category')
    for section, keys in [('resources', ('weekly', 'total', 'max_weekly', 'max_total', 'observed_at')),
                          ('bonuses', ('lumnis_points_remaining', 'lumnis_donations', 'lumnis_reset_at',
                                       'observed_at', 'donations_observed_at', 'fashlonae_days_remaining',
                                       'fashlonae_observed_at', 'fashlonae_days_observed_at'))]:
        for key in keys:
            numeric((data.get(section) or {}).get(key), f'{section}.{key}')
    resource_type = (data.get('resources') or {}).get('type')
    if resource_type is not None and not isinstance(resource_type, str):
        raise ValueError('Resource type must be text')
    stage = (data.get('bonuses') or {}).get('lumnis_stage')
    if stage is not None and not (type(stage) is int and 2 <= stage <= 5) and stage not in ('ready', 'expired', 'unavailable', 'unknown'):
        raise ValueError('Invalid Lumnis stage')
    tutelage = (data.get('bonuses') or {}).get('fashlonae_state')
    if tutelage is not None and tutelage not in ('active', 'inactive', 'expended', 'unavailable', 'eligible', 'ineligible', 'unknown'):
        raise ValueError('Invalid Tutelage state')


def numeric(value, label, signed=False):
    if value is not None and (type(value) not in (int, float) or abs(value) > 10**15
                              or not math.isfinite(value) or (not signed and value < 0)):
        raise ValueError(f'Invalid {label}')


def merge_known(previous, incoming):
    result = dict(previous)
    for key, value in incoming.items():
        if value is None:
            continue
        result[key] = merge_known(result.get(key, {}) if isinstance(result.get(key), dict) else {}, value) if isinstance(value, dict) else value
    return result


class ProfileRepository:
    """Uses TelemetryStore's existing connection, lock and ingest transaction."""
    def __init__(self, db):
        self.db = db
        db.execute('''CREATE TABLE IF NOT EXISTS profile_sections (
            realm TEXT, character TEXT COLLATE NOCASE, section TEXT,
            payload TEXT NOT NULL, field_times TEXT NOT NULL, received REAL NOT NULL,
            PRIMARY KEY (realm, character, section))''')

    def ingest(self, realm, character, data, received):
        availability = (data.get('metadata') or {}).get('availability', {})
        for section in SECTIONS:
            incoming = data.get(section)
            info = availability.get(section, {})
            if not isinstance(incoming, dict) or info.get('available') is False:
                continue
            row = self.db.execute('SELECT * FROM profile_sections WHERE realm=? AND character=? AND section=?',
                                  (realm, character, section)).fetchone()
            previous, times = (json.loads(row['payload']), json.loads(row['field_times'])) if row else ({}, {})
            was_not_redeemed = previous.get('fashlonae_state') == 'unavailable'
            # Collector times belong to the data, not the three-second transport heartbeat.
            observed = incoming.get('observed_at') or info.get('collected_at') or received
            observed = min(observed, received)
            if section == 'skills':
                if observed < max(times.values(), default=0):
                    continue
                # SKILL is committed by the reporter only after its closing line.
                previous, times = {}, {}
            changed = section == 'skills'
            for key, value in incoming.items():
                if value is None or key.endswith('observed_at') or key == 'observed_at':
                    continue
                stamp = (incoming.get('donations_observed_at') or observed) if section == 'bonuses' and key == 'lumnis_donations' else observed
                if section == 'bonuses' and key.startswith('fashlonae_'):
                    stamp = incoming.get('fashlonae_days_observed_at' if key == 'fashlonae_days_remaining' else 'fashlonae_observed_at') or observed
                stamp = min(stamp, received)
                if stamp < times.get(key, 0):
                    continue
                previous[key] = merge_known(previous.get(key, {}) if isinstance(previous.get(key), dict) else {}, value) if isinstance(value, dict) else value
                times[key] = stamp
                changed = True
            if section == 'bonuses' and previous.get('lumnis_stage') in ('expired', 'ready', 'unavailable'):
                previous.pop('lumnis_points_remaining', None)
                times.pop('lumnis_points_remaining', None)
            if section == 'bonuses' and previous.get('fashlonae_state') == 'unavailable' and times.get('fashlonae_state', 0) >= times.get('fashlonae_days_remaining', 0):
                previous['fashlonae_days_remaining'] = 0
                times['fashlonae_days_remaining'] = times['fashlonae_state']
            elif section == 'bonuses' and was_not_redeemed and previous.get('fashlonae_state') in ('active', 'inactive', 'expended', 'eligible') and incoming.get('fashlonae_days_remaining') is None:
                previous.pop('fashlonae_days_remaining', None)
                times.pop('fashlonae_days_remaining', None)
            if changed:
                self.db.execute('INSERT OR REPLACE INTO profile_sections VALUES (?,?,?,?,?,?)',
                                (realm, character, section, json.dumps(previous), json.dumps(times), received))

    def get(self, realm, character):
        rows = self.db.execute('SELECT * FROM profile_sections WHERE realm=? AND character=?',
                               (realm, character)).fetchall()
        if not rows:
            return None
        snapshot = {row['section']: json.loads(row['payload']) for row in rows}
        field_times = {row['section']: json.loads(row['field_times']) for row in rows}
        return dict(character=rows[0]['character'], realm=realm, snapshot=snapshot,
                    updated_at=max(row['received'] for row in rows),
                    observed_at={section: max(times.values(), default=0) for section, times in field_times.items()},
                    field_observed_at=field_times)
