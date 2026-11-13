"""Validate add-on references and build an offline inspection ZIP; no network."""
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config = json.loads((root / 'release-config.json').read_text(encoding='utf-8'))
toc = root / (config['addon_folder'] + '.toc')
text = toc.read_text(encoding='utf-8-sig')
version = re.search(r'^## Version:\s*(\S+)\s*$', text, re.M).group(1)
interfaces = re.search(r'^## Interface:\s*(.+)$', text, re.M).group(1)
assert '16001' in [s.strip() for s in interfaces.split(',')], 'Forever interface missing'
ref = os.environ.get('GITHUB_REF', '')
if ref.startswith('refs/tags/'):
    assert ref == 'refs/tags/v' + version, 'Tag must equal v + TOC Version; bump version first'
for line in text.splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    assert '[' not in line, 'Conditional TOC entries require validator support'
    target = (root / line.replace('\\', '/')).resolve()
    assert target.is_relative_to(root), 'TOC entry escapes repository'
    assert target.is_file(), f'Missing TOC file: {line}'
files = []
for p in root.rglob('*'):
    if not p.is_file():
        continue
    rel = p.relative_to(root)
    if any(part in {'.git', '.github', '.release', 'tools', '__pycache__'} for part in rel.parts):
        continue
    if rel.name in {'SETUP.md', 'release-config.json', '.pkgmeta', '.gitignore'}:
        continue
    assert p.suffix.lower() in {'.lua', '.toc', '.xml', '.txt', '.md', '.tga', '.blp', '.png', '.ogg', '.mp3', '.wav', '.ttf'}, f'Unexpected payload: {rel}'
    files.append(p)
assert files, 'Empty add-on'
out = root / '.release'
out.mkdir(exist_ok=True)
archive = out / (config['addon_folder'] + '-' + version + '-inspection.zip')
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files):
        z.write(p, config['addon_folder'] + '/' + p.relative_to(root).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert all(n.startswith(config['addon_folder'] + '/') for n in z.namelist())
print(json.dumps({'addon': config['addon_folder'], 'version': version, 'files': len(files), 'zip_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))
