"""Install a built coindex update after UI exit, preserving data and rollback."""
import datetime
import argparse
import fcntl
import json
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description='Install a built update with a backup of the current application and data.')
parser.add_argument('--source', default=str(root / 'dist/coindex.app'), help='Built application bundle to install')
args = parser.parse_args()
applications = Path.home() / 'Applications'
installed = applications / 'coindex.app'
source = Path(args.source).expanduser().resolve()
stage = applications / '.coindex-update.app'
data = Path.home() / 'Library/Application Support/CodexTodo'
backup = root / 'build/backups' / datetime.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')
alias = applications / 'coindex的替身'
if not installed.is_dir() or stage.exists():
    raise RuntimeError('Expected installed coindex and no unfinished staged update')


def records(db):
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {table: db.execute('SELECT * FROM "' + table.replace('"', '""') + '" ORDER BY rowid').fetchall() for table in tables}


locks = []
try:
    for name in ('service.lock', 'sync.lock'):
        lock = open(data / name, 'a+')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locks.append(lock)
    backup.mkdir(parents=True, mode=0o700)
    with sqlite3.connect(str(data / 'todos.sqlite')) as db, sqlite3.connect(str(backup / 'todos.sqlite')) as saved:
        db.backup(saved)
        before = records(db)
    (backup / 'todos.sqlite').chmod(0o600)
    preferences = data / 'pet-preferences.json'
    before_preferences = preferences.read_bytes() if preferences.exists() else None
    if before_preferences is not None:
        (backup / 'pet-preferences.json').write_bytes(before_preferences)
        (backup / 'pet-preferences.json').chmod(0o600)
    shutil.copytree(source, stage)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(stage)], check=True)
    info = plistlib.loads((stage / 'Contents/Info.plist').read_bytes())
    assert info['CFBundleIdentifier'] == 'org.coindex.desktop'
    assert info['CFBundleName'] == 'coindex'
    assert (stage / 'Contents/Resources/CustomPets/coindex-cat/spritesheet.png').is_file()
    try:
        installed.rename(backup / 'previous.bundle')
        stage.rename(installed)
        if alias.exists():
            alias.rename(backup / 'previous.alias')
            subprocess.run([str(root / 'build/create-app-alias'), str(installed), str(alias)], check=True)
        with sqlite3.connect(str(data / 'todos.sqlite')) as db:
            assert before == records(db), 'Existing records changed during update'
        assert before_preferences == (preferences.read_bytes() if preferences.exists() else None), 'Pet preferences changed during installation'
        for path in source.rglob('*'):
            if path.is_file():
                assert (installed / path.relative_to(source)).read_bytes() == path.read_bytes()
    except Exception:
        if installed.exists():
            installed.rename(backup / 'failed.bundle')
        if (backup / 'previous.bundle').exists():
            (backup / 'previous.bundle').rename(installed)
        if (backup / 'previous.alias').exists():
            if alias.exists():
                alias.rename(backup / 'failed.alias')
            (backup / 'previous.alias').rename(alias)
        raise
    print(json.dumps({'version': info['CFBundleShortVersionString'], 'installed': str(installed),
                      'backup': str(backup), 'tasks_preserved': len(before['tasks']),
                      'all_records_and_preferences_preserved': True}, ensure_ascii=False))
finally:
    for lock in reversed(locks):
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
