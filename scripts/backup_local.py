"""Create a consistent SQLite snapshot and copy immutable generated scripts."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def backup(database: Path, generated: Path, destination: Path):
    if not database.is_file():
        raise ValueError('Source database does not exist')
    destination.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(destination / 'loadpilot.db') as target:
        source.backup(target)
    scripts = destination / 'scripts'
    scripts.mkdir()
    manifest = {}
    # Copy only scripts referenced by the snapshot, never growing points/log files.
    with sqlite3.connect(destination / 'loadpilot.db') as snapshot:
        for row in snapshot.execute('SELECT body FROM runs'):
            for artifact in json.loads(row[0]).get('artifacts', []):
                if artifact['kind'] != 'k6-script':
                    continue
                path = Path(artifact['uri']).resolve()
                if not path.is_relative_to(generated.resolve()):
                    raise ValueError('Snapshot references a script outside the configured directory')
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if digest != artifact['sha256']:
                    raise ValueError('Script integrity check failed during backup')
                (scripts / path.name).write_bytes(raw)
                manifest[path.name] = digest
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    from loadpilot.settings import Settings
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    settings = Settings()
    result = backup(Path(settings.db), Path(settings.generated_dir), args.destination)
    print(f'Snapshot saved with {len(result)} verified scripts. Restore only while API and worker are stopped.')
