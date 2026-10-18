"""Project durable, source-timed profiles into a weekly hunting rotation."""
from datetime import datetime, timedelta
import math
from zoneinfo import ZoneInfo


def previous_renewal(next_renewal):
    """Calendar week in game time, including Eastern daylight-saving changes."""
    return (datetime.fromtimestamp(next_renewal, ZoneInfo('America/New_York')) - timedelta(days=7)).timestamp()


def _number(value):
    return type(value) in (int, float) and abs(value) <= 10**15 and math.isfinite(value) and value >= 0


def build_rotation(config, profiles, sessions, now, realm='prime'):
    settings=config.get('weekly_rotation') or {}
    entries=settings.get('characters') or []
    roster={name.casefold():account for account,names in config.get('accounts',{}).items() for name in names}
    account_lookup={entry['name'].casefold():entry.get('account','') for entry in entries
                    if isinstance(entry,dict) and isinstance(entry.get('name'),str)}
    account_lookup.update(roster)
    profile_map={p['character'].casefold():p for p in profiles if p.get('realm')==realm}
    roles={account.casefold():role for account,role in settings.get('account_roles',{}).items()}
    records=[]
    for entry in entries:
        if not isinstance(entry,dict) or entry.get('role') not in ('main','wizard') or not isinstance(entry.get('name'),str):
            continue
        name=entry['name'];account=roster.get(name.casefold(),entry.get('account',''))
        profile=profile_map.get(name.casefold(),{})
        data=profile.get('snapshot') or {};times=profile.get('field_observed_at') or {}
        bonus=data.get('bonuses') or {};resources=data.get('resources') or {}
        reset=bonus.get('lumnis_reset_at');reset=reset if _number(reset) and reset>0 else None
        passed=reset is not None and reset<=now
        try:
            floor=previous_renewal(reset)-60 if reset and not passed else None
        except (ValueError,OverflowError,OSError):
            reset=None;floor=None;passed=False
        def current(section,field):
            observed=times.get(section,{}).get(field)
            return floor is not None and _number(observed) and floor<=observed<=now+60
        lumnis=bonus.get('lumnis_stage')
        lumnis_known=current('bonuses','lumnis_stage') and (type(lumnis) is int and 2<=lumnis<=5 or lumnis in ('expired','ready'))
        lumnis_done=lumnis=='expired' if lumnis_known else None
        configured_target=entry.get('weekly_target',50000)
        if not _number(configured_target) or configured_target<=0:configured_target=50000
        target=resources.get('max_weekly')
        target=target if _number(target) and target>0 else configured_target
        earned=resources.get('weekly');stored=resources.get('total')
        resource_known=_number(earned) and current('resources','weekly')
        resource_done=earned>=target if resource_known else None
        goals=[lumnis_done]+([resource_done] if entry['role']=='wizard' else [])
        if reset is None or passed:
            state='needs_update';reason='Renewal passed; refresh the game report.' if passed else 'Next renewal has not been reported.'
        elif all(goal is True for goal in goals):
            state='done';reason='Both weekly goals are complete.' if entry['role']=='wizard' else 'Lumnis is spent for this cycle.'
        elif any(goal is False for goal in goals):
            state='needs_hunting';reason='Weekly goals remain.'
        else:
            state='needs_update';reason='A current-cycle game report is needed.'
        live=next((s for s in sessions if s.get('running') and s.get('realm')==realm and s['character'].casefold()==name.casefold()),None)
        occupant=next((s['character'] for s in sessions if s.get('running') and s.get('realm')==realm
                       and s['character'].casefold()!=name.casefold()
                       and account_lookup.get(s['character'].casefold(),'').casefold()==account.casefold()),None)
        remaining=reset-now if reset else None
        urgency='overdue' if passed else 'soon' if state!='done' and remaining is not None and remaining<=86400 else 'normal'
        records.append(dict(character=name,realm=realm,account=account,account_role=roles.get(account.casefold(),'main'),role=entry['role'],
                            state=state,reason=reason,reset_at=reset,reset_passed=passed,seconds_remaining=remaining,urgency=urgency,
                            lumnis=dict(stage=lumnis,done=lumnis_done,points_remaining=bonus.get('lumnis_points_remaining')),
                            resources=dict(type=resources.get('type') or ('Essence' if entry['role']=='wizard' else 'Resources'),
                                           weekly=earned if _number(earned) else None,total=stored if _number(stored) else None,
                                           target=target,done=resource_done,current=resource_known),
                            bonuses=bonus,observed_at=times,updated_at=profile.get('updated_at'),has_profile=bool(data),
                            registered=name.casefold() in roster,running=bool(live),session_id=live.get('id') if live else None,
                            account_occupant=occupant,can_launch=name.casefold() in roster and occupant is None))
    order={'needs_hunting':0,'needs_update':1,'done':2}
    wizards=sorted((r for r in records if r['role']=='wizard'),key=lambda r:(order[r['state']],r['reset_at'] or math.inf,r['character'].casefold()))
    mains=[r for r in records if r['role']=='main']
    return dict(configured=bool(records),realm=realm,as_of=now,mains=mains,wizards=wizards,
                summary=dict(total=len(wizards),done=sum(r['state']=='done' for r in wizards),
                             needs_hunting=sum(r['state']=='needs_hunting' for r in wizards),needs_update=sum(r['state']=='needs_update' for r in wizards),
                             due_soon=sum(r['urgency']=='soon' for r in wizards),
                             weekly_earned=sum(r['resources']['weekly'] for r in wizards if r['resources']['current']),
                             resource_reports=sum(r['resources']['current'] for r in wizards),weekly_target=sum(r['resources']['target'] for r in wizards)))
