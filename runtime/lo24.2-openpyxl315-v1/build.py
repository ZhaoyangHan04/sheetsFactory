#!/usr/bin/env python3
"""Build a separate parser-compatible image without changing an existing tag."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def build():
    lock = json.loads((HERE / 'requirements.lock.json').read_text())
    base = command(['docker', 'image', 'inspect', lock['base_image'], '--format', '{{.Id}}'])
    if base != lock['base_image_id']:
        raise ValueError('Pinned base image differs; never rebuild or retag it implicitly')
    exists = subprocess.run(['docker', 'image', 'inspect', lock['output_tag']], capture_output=True)
    if exists.returncode == 0:
        raise ValueError('Output tag already exists; preserve it and declare a new version')
    out = ROOT / 'outputs/research' / ('runtime_openpyxl315_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(exist_ok=False)
    context = out / 'context'
    context.mkdir()
    shutil.copy2(HERE / 'Dockerfile', context / 'Dockerfile')
    wheel = context / lock['package']['filename']
    with urllib.request.urlopen(lock['package']['url'], timeout=60) as response:
        wheel.write_bytes(response.read())
    if sha(wheel) != lock['package']['sha256'] or wheel.stat().st_size != lock['package']['bytes']:
        raise ValueError('Downloaded parser package differs from its pinned public SHA256')
    base_layers = json.loads(command(['docker', 'image', 'inspect', base, '--format', '{{json .RootFS.Layers}}']))
    args = ['docker', 'build', '--network', 'none', '--build-arg', 'BASE_IMAGE=' + lock['base_image'],
            '-t', lock['output_tag'], str(context)]
    completed = subprocess.run(args, capture_output=True, text=True)
    (out / 'build.stdout.txt').write_text(completed.stdout)
    (out / 'build.stderr.txt').write_text(completed.stderr)
    if completed.returncode:
        raise RuntimeError('Isolated image build failed; inspect its preserved logs')
    def inspect(image):
        script = ('import openpyxl,importlib.metadata,hashlib,json; '
                  'p="/opt/uno_recalculate.py"; '
                  'print(json.dumps({"openpyxl_version":openpyxl.__version__, '
                  '"openpyxl_path":openpyxl.__file__, '
                  '"et_xmlfile_version":importlib.metadata.version("et-xmlfile"), '
                  '"uno_recalculate_sha256":hashlib.sha256(open(p,"rb").read()).hexdigest()}))')
        value = json.loads(command(['docker', 'run', '--rm', '--user', '0', '--workdir', '/tmp',
            '--network', 'none', '--entrypoint', '/usr/bin/python3', image, '-c', script]))
        value['libreoffice_version'] = command(['docker', 'run', '--rm', '--user', '0', '--workdir', '/tmp',
            '--network', 'none', '--entrypoint', '/usr/bin/libreoffice', image, '--version'])
        return value
    image = command(['docker', 'image', 'inspect', lock['output_tag'], '--format', '{{.Id}}'])
    image_layers = json.loads(command(['docker', 'image', 'inspect', image, '--format', '{{json .RootFS.Layers}}']))
    if image_layers[:len(base_layers)] != base_layers:
        raise ValueError('Built image does not retain the exact pinned base filesystem layers')
    before, after = inspect(base), inspect(image)
    if (after['openpyxl_version'] != lock['package']['version']
            or before['uno_recalculate_sha256'] != after['uno_recalculate_sha256']
            or before['libreoffice_version'] != after['libreoffice_version']
            or before['et_xmlfile_version'] != after['et_xmlfile_version']):
        raise ValueError('Parser runtime proof failed; the base financial engine must remain unchanged')
    if command(['docker', 'image', 'inspect', lock['base_image'], '--format', '{{.Id}}']) != base:
        raise ValueError('The original runtime tag changed during construction')
    report = {'schema_version': 1, 'tag': lock['output_tag'], 'image_id': image,
        'base_image': lock['base_image'], 'base_image_id': base,
        'base_rootfs_layers': base_layers, 'image_rootfs_layers': image_layers,
        'created_at': datetime.now(timezone.utc).isoformat(), 'base_preserved': True,
        'package': lock['package'], 'before': before, 'after': after,
        'recipe': {str(p): sha(p) for p in [HERE / 'Dockerfile', HERE / 'requirements.lock.json', Path(__file__)]},
        'model_calls': 0, 'dataset_qualification_claimed': False}
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(out), 'tag': lock['output_tag'], 'image_id': image}), flush=True)
    return report


if __name__ == '__main__':
    build()
