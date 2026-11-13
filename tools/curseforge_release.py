"""Persist upload receipts and finalize file labels without uploading another ZIP."""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path


def positive(value):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]*', str(value)):
        raise ValueError('Invalid project or file ID')
    return int(value)


def existing_artifact(opener=urllib.request.urlopen):
    repo = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid repository')
    run = positive(os.environ['GITHUB_RUN_ID'])
    name = 'curseforge-receipt-' + os.environ['GITHUB_REF_NAME']
    intent_name = 'curseforge-intent-' + os.environ['GITHUB_REF_NAME']
    found = False
    intent = False
    for page in range(1, 101):
        request = urllib.request.Request(f'https://api.github.com/repos/{repo}/actions/runs/{run}/artifacts?per_page=100&page={page}', headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
        with opener(request, timeout=30) as response:
            data = json.load(response)
        for artifact in data['artifacts']:
            if artifact['name'] == intent_name:
                intent = True
            if artifact['name'] == name:
                if artifact['expired']:
                    raise RuntimeError('Upload receipt expired. Inspect CurseForge before retrying; do not upload again.')
                found = True
        if found or len(data['artifacts']) < 100:
            break
    else:
        raise RuntimeError('Artifact listing incomplete; refusing another upload')
    value = 'true' if found else 'false'
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
        out.write('found=' + value + '\n')
        out.write('intent=' + ('true' if intent else 'false') + '\n')
    print('Existing upload receipt: ' + value)


def receipt(root, stamp=False):
    project = positive(os.environ['CF_PROJECT_ID'])
    path = root / '.release' / 'cf_result.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    file_id = positive(data['id'])
    config = json.loads((root / 'release-config.json').read_text(encoding='utf-8'))
    tag = os.environ.get('RELEASE_TAG') or os.environ['GITHUB_REF_NAME']
    if tag != 'v' + config['source_version']:
        raise RuntimeError('Release tag and version differ')
    if stamp:
        data.update(project_id=project, tag=tag)
        path.write_text(json.dumps(data) + '\n', encoding='utf-8')
    elif data.get('project_id') != project or data.get('tag') != tag:
        raise RuntimeError('Receipt does not match this project and tag; refusing metadata change')
    return project, file_id, config


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            raise RuntimeError('Refusing cross-host redirect with upload token')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def upload(root, opener=None):
    config = json.loads((root / 'release-config.json').read_text(encoding='utf-8'))
    project = positive(os.environ['CF_PROJECT_ID'])
    tag = os.environ['GITHUB_REF_NAME']
    if tag != 'v' + config['source_version']:
        raise RuntimeError('Release tag and version differ')
    if (root / '.release' / 'cf_result.json').exists():
        _, file_id, _ = receipt(root)
        print(f'Reusing accepted file {file_id}; no ZIP upload')
        return
    attempt_path = root / '.release' / 'upload-attempted.json'
    if attempt_path.exists():
        raise RuntimeError('Previous POST attempted without receipt; inspect CurseForge before another upload')
    token = os.environ.get('CF_API_TOKEN')
    if not token:
        raise RuntimeError('Missing CURSEDFORGE repository secret')
    intent = json.loads((root / '.release' / 'upload-intent.json').read_text())
    if intent != {'project_id':project,'tag':tag}:
        raise RuntimeError('Upload intent differs from project/tag')
    archive = root / '.release' / (config['addon_folder'] + '-' + tag + '-forever.zip')
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None or not all(n.startswith(config['addon_folder'] + '/') for n in package.namelist()):
            raise RuntimeError('Invalid BigWigs package')
    open_request = opener or urllib.request.build_opener(SameHostRedirect()).open
    request = urllib.request.Request('https://wow.curseforge.com/api/game/wow/versions', headers={'X-Api-Token':token})
    with open_request(request, timeout=30) as response:
        versions = json.load(response)
    matches = [v for v in versions if v['gameVersionTypeID'] == config['game_version_type_id'] and v['name'] == config['game_version']]
    if len(matches) != 1:
        raise RuntimeError('CurseForge Forever version must match exactly; no fallback upload')
    release_type = 'beta' if 'beta' in tag.lower() else 'alpha' if 'alpha' in tag.lower() else 'release'
    metadata = {
        'displayName':config['display_name'] + ' ' + tag + ' - WoW Forever',
        'changelog':(root / 'RELEASE_NOTES.md').read_text(encoding='utf-8'),
        'changelogType':'markdown', 'gameVersions':[positive(matches[0]['id'])],
        'releaseType':release_type, 'isMarkedForManualRelease':False,
    }
    boundary = '----MutroksUpload' + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n' + json.dumps(metadata,ensure_ascii=False) + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{archive.name}"\r\nContent-Type: application/zip\r\n\r\n').encode('utf-8') + archive.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    request = urllib.request.Request(f'https://wow.curseforge.com/api/projects/{project}/upload-file', data=body, headers={'X-Api-Token':token,'Content-Type':'multipart/form-data; boundary='+boundary}, method='POST')
    # Never retry this POST automatically: a lost response may still mean acceptance.
    attempt_path.write_text(json.dumps({'project_id':project,'tag':tag})+'\n',encoding='utf-8')
    try:
        with open_request(request, timeout=90) as response:
            result = json.load(response)
        positive(result['id'])
    except Exception:
        raise RuntimeError('Upload outcome uncertain or rejected. Intent is retained; inspect CurseForge before retrying. No automatic second upload.') from None
    path = root / '.release' / 'cf_result.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result)+'\n',encoding='utf-8')
    temporary.replace(path)
    _, file_id, _ = receipt(root, stamp=True)
    print(f'CurseForge accepted file {file_id} ({release_type}, {config["game_version"]})')


def finalize(root, opener=None):
    project, file_id, config = receipt(root)
    label = config['display_name'] + ' v' + config['source_version'] + ' - WoW Forever'
    link = f'https://authors.curseforge.com/#/projects/{project}/files/{file_id}'
    print(f'Previously accepted CurseForge upload: file {file_id}; {link}')
    boundary = '----MutroksRelease' + uuid.uuid4().hex
    metadata = json.dumps({'fileID': file_id, 'displayName': label}, ensure_ascii=False)
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n{metadata}\r\n--{boundary}--\r\n').encode('utf-8')
    token = os.environ.get('CF_API_TOKEN')
    if not token:
        raise RuntimeError('Missing CURSEDFORGE repository secret')
    request = urllib.request.Request(f'https://wow.curseforge.com/api/projects/{project}/update-file', data=body, headers={'X-Api-Token': token, 'Content-Type': 'multipart/form-data; boundary=' + boundary}, method='POST')
    open_request = opener or urllib.request.build_opener(SameHostRedirect()).open
    for attempt in range(3):
        try:
            with open_request(request, timeout=45) as response:
                result = json.load(response)
            if positive(result['id']) != file_id:
                raise RuntimeError('Metadata response refers to another file')
            break
        except urllib.error.HTTPError as error:
            if attempt < 2 and (error.code == 429 or error.code >= 500):
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f'File already uploaded; metadata update failed (HTTP {error.code}). Retry only finalize job.') from None
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as out:
            out.write(f'## CurseForge upload accepted\n\n**{label}**\n\n[Open file {file_id}]({link})\n\nUpload acceptance and public moderation approval are separate.\n')
    print('CurseForge display name confirmed: ' + label)
    print('File link: ' + link)


def main():
    root = Path(__file__).resolve().parents[1]
    mode = sys.argv[1]
    if mode == 'check-existing':
        existing_artifact()
    elif mode == 'stamp-receipt':
        project, file_id, _ = receipt(root, stamp=True)
        print(f'Accepted upload receipt saved: project {project}, file {file_id}')
    elif mode == 'finalize':
        finalize(root)
    elif mode == 'write-intent':
        path = root / '.release' / 'upload-intent.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'project_id':positive(os.environ['CF_PROJECT_ID']),'tag':os.environ['GITHUB_REF_NAME']})+'\n',encoding='utf-8')
    elif mode == 'upload':
        upload(root)
    elif mode == 'repair':
        config = json.loads((root / 'release-config.json').read_text(encoding='utf-8'))
        repair = config.get('metadata_repair')
        if not repair or repair['version'] != config['source_version']:
            print('No metadata repair configured for this version')
            return
        os.environ['RELEASE_TAG'] = 'v' + repair['version']
        path = root / '.release' / 'cf_result.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'id':positive(repair['file_id'])}), encoding='utf-8')
        receipt(root, stamp=True)
        finalize(root)
    else:
        raise RuntimeError('Unknown release mode')


if __name__ == '__main__':
    main()
