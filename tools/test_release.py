import importlib.util
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('release', Path(__file__).with_name('curseforge_release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
    root = Path(directory)
    assert root.resolve().is_relative_to(Path(__file__).resolve().parent)
    (root / '.release').mkdir()
    (root / 'release-config.json').write_text(json.dumps({'source_version':'1.1.2','display_name':'Vertius kleiner Knüppel','addon_folder':'VertiusKleinerKnueppel','game_version':'1.60.1','game_version_type_id':88568}))
    (root / '.release' / 'cf_result.json').write_text('{"id":12345}')
    os.environ.update(CF_PROJECT_ID='1792113',GITHUB_REF_NAME='v1.1.2',CF_API_TOKEN='MOCK_NOT_A_REAL_TOKEN',GITHUB_STEP_SUMMARY=str(root / 'summary'),GITHUB_OUTPUT=str(root / 'output'),GITHUB_REPOSITORY='jkortum-git/VertiusKleinerKnueppel',GITHUB_RUN_ID='98765',GH_TOKEN='MOCK_NOT_A_REAL_TOKEN')
    release.receipt(root, stamp=True)
    def fake_update(request, timeout):
        assert request.full_url == 'https://wow.curseforge.com/api/projects/1792113/update-file'
        assert request.method == 'POST'
        assert 'Vertius kleiner Knüppel v1.1.2 - WoW Forever' in request.data.decode()
        assert '"fileID": 12345' in request.data.decode()
        assert b'filename=' not in request.data
        return Response(b'{"id":12345}')
    release.finalize(root, opener=fake_update)
    assert 'files/12345' in (root / 'summary').read_text()
    def artifacts(request, timeout):
        return Response(json.dumps({'artifacts':[{'name':'curseforge-receipt-v1.1.2','expired':False}]}).encode())
    release.existing_artifact(opener=artifacts)
    assert 'found=true' in (root / 'output').read_text()
    os.environ['CF_PROJECT_ID']='1792129'
    try: release.receipt(root)
    except RuntimeError: pass
    else: raise AssertionError('Wrong project receipt accepted')
    os.environ['CF_PROJECT_ID']='1792113'
    (root / '.release' / 'cf_result.json').unlink()
    (root / 'RELEASE_NOTES.md').write_text('# Current release\n\n- Example change.\n')
    (root / '.release' / 'upload-intent.json').write_text(json.dumps({'project_id':1792113,'tag':'v1.1.2'}))
    with zipfile.ZipFile(root / '.release' / 'VertiusKleinerKnueppel-v1.1.2-forever.zip','w') as package:
        package.writestr('VertiusKleinerKnueppel/Example.lua','return true')
    posts=[]
    def fake_upload(request, timeout):
        if request.get_method() == 'GET':
            return Response(b'[{"id":6789,"gameVersionTypeID":88568,"name":"1.60.1"}]')
        posts.append(request)
        assert request.full_url.endswith('/1792113/upload-file')
        data=request.data.decode('utf-8',errors='replace')
        assert 'Vertius kleiner Knüppel v1.1.2 - WoW Forever' in data
        assert '"gameVersions": [6789]' in data
        assert '"releaseType": "release"' in data
        assert 'Current release' in data and 'filename="VertiusKleinerKnueppel-v1.1.2-forever.zip"' in data
        return Response(b'{"id":45678}')
    release.upload(root,opener=fake_upload)
    release.upload(root,opener=fake_upload)
    assert len(posts)==1
    assert release.receipt(root)[1]==45678
    (root / '.release' / 'cf_result.json').unlink()
    try: release.upload(root,opener=fake_upload)
    except RuntimeError: pass
    else: raise AssertionError('Unknown upload outcome was retried')
    assert len(posts)==1
print('PASS: receipt identity, existing-run reuse and metadata-only API request; no ZIP sent by finalizer')
print('PASS: direct upload sends exact readable label, version, notes and ZIP once; receipt reuses and uncertain attempts block')
