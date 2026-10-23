"""Cross-process launch exclusion; credentials never enter these records."""
import hashlib
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def host_lock(directory, identity, blocking=True):
    root=Path(directory)/'session-locks'
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=root/(hashlib.sha256(identity.encode()).hexdigest()+'.lock')
    with path.open('a+b') as stream:
        if os.name=='nt':
            import msvcrt
            stream.seek(0,2)
            if stream.tell()==0: stream.write(b'0');stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK,1)
            try: yield
            finally:
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            try: yield
            finally: fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def account_for(config, character):
    aliases=config.get('daily_checkin',{}).get('account_ids',{})
    matches=[str(aliases.get(label,label)).casefold() for label,names in config.get('accounts',{}).items()
             if any(name.casefold()==character.casefold() for name in names)]
    if len(matches)!=1: raise ValueError('Character must belong to exactly one account.')
    return matches[0]


def reservation(directory, account):
    path=Path(directory)/'telemetry.sqlite3'
    if not path.exists(): return None
    # An error reading existing state must fail closed, not bypass exclusion.
    connection=sqlite3.connect(str(path),timeout=5)
    try:
        exists=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkin_reservations'").fetchone()
        if not exists: return None
        row=connection.execute('SELECT job_id FROM checkin_reservations WHERE account=?',(account,)).fetchone()
        return row[0] if row else None
    finally: connection.close()
