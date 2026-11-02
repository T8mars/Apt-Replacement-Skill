"""RunningHub immutable requests and a private account-wide SQLite ledger.

No cloud call occurs without `tick`, a production authorization, and a digest-bound
semantic review. POST uncertainty is never treated as permission to resubmit.
"""
from __future__ import annotations
import argparse
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
from fractions import Fraction
import random
import sqlite3
import subprocess
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ACTIVE = ('SUBMITTING', 'SUBMISSION_UNKNOWN', 'QUEUED', 'RUNNING')
POLLABLE = ('QUEUED', 'RUNNING', 'SUCCESS_RESULTS_PENDING', 'RESULTS_MISSING', 'DOWNLOAD_FAILED', 'RESULTS_READY')
DEFERRED_CODES = ('415', '421', '429', '1003', '1010', '1011')
BASE = 'https://www.runninghub.ai'
OBSERVED_RESULT_HOST = 'rh-hk-images-1252422369.cos.ap-hongkong.myqcloud.com'


def codex_home():
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')


def default_private():
    return codex_home() / 'private' / 'video-replacement-skill-factory'


def default_key():
    return codex_home() / 'private' / 'r2va-character-replacement' / 'api_key.txt'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def digest_object(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def same_profile_route(profile, private_request):
    """Compare submitted adapter/settings, excluding per-window identities and timing."""
    if not private_request:
        return False
    request = json.loads(private_request)
    body = request.get('body') or {}
    if profile['kind'] == 'legacy-ai-app':
        return (request['path'] == '/openapi/v2/run/ai-app/' + profile['app_id'] and
                body.get('instanceType') == profile.get('instance_type', 'plus') and
                sorted((n['nodeId'],n['fieldName'],str(n['fieldValue'])) for n in body.get('nodeInfoList',[]) if n.get('nodeId') in ('115','214')) ==
                sorted((n['nodeId'],n['fieldName'],str(n['fieldValue'])) for n in legacy_resolution_nodes(profile)))
    return (request['path'] == '/openapi/v2/minimax/hailuo-h3/multimodal-to-video' and
            body.get('resolution') == profile.get('resolution', '2K') and body.get('ratio') == profile.get('ratio', 'adaptive'))


def legacy_resolution_nodes(profile):
    """Explicit documented ResolutionSelector inputs; absent config preserves legacy requests."""
    value=profile.get('resolution_selector')
    if value is None:
        return []
    ratios={'1:1 (Square)','2:3 (Portrait Photo)','3:2 (Photo)','3:4 (Portrait Standard)',
            '4:3 (Standard)','9:16 (Portrait Widescreen)','16:9 (Widescreen)','21:9 (Ultrawide)'}
    if not isinstance(value,dict) or not {'aspect_ratio','megapixels'} <= set(value) or set(value)-{'aspect_ratio','megapixels','aspect_node_ids'}:
        raise ValueError('Resolution selector needs explicit aspect_ratio and megapixels; optional aspect_node_ids')
    ratio,mp=value['aspect_ratio'],value['megapixels']
    if not isinstance(ratio,str) or ratio not in ratios:
        raise ValueError('Unsupported documented ResolutionSelector aspect_ratio')
    if type(mp) not in (int,float) or not math.isfinite(mp) or not 0.1<=mp<=16:
        raise ValueError('ResolutionSelector megapixels must be finite and within 0.1..16')
    ids=value.get('aspect_node_ids',['115'])
    if (not isinstance(ids,list) or not ids or any(type(n) is not str or n not in ('115','214') for n in ids)
        or len(set(ids))!=len(ids) or '115' not in ids):
        raise ValueError('Aspect node IDs must be unique documented selectors including115')
    if '214' in ids and profile.get('app_id') not in ('2107844752011010050','2107845954833907713'):
        raise ValueError('Selector214 is only documented for the verified single/two-image applications')
    return ([{'nodeId':n,'fieldName':'aspect_ratio','fieldValue':ratio} for n in sorted(ids)] +
            [{'nodeId':'115','fieldName':'megapixels','fieldValue':format(mp,'g')}])


def validate_legacy_canvas(entry):
    legacy_resolution_nodes(entry['profile'])
    canvas=(entry.get('source_contract') or {}).get('window',{}).get('source_projection',{}).get('display_canvas')
    if not canvas or not canvas.get('width') or not canvas.get('height'):
        return
    ratio=Fraction(canvas['width'],canvas['height'])*Fraction(canvas.get('sample_aspect_ratio','1'))
    selected=entry['profile'].get('resolution_selector')
    if ratio<1 and not selected:
        raise ValueError('Portrait source requires an explicit verified ResolutionSelector aspect; the legacy default may be landscape')
    if selected:
        w,h=map(int,selected['aspect_ratio'].split(' ',1)[0].split(':'))
        if Fraction(w,h)!=ratio:
            raise ValueError('Explicit legacy aspect differs from the source display canvas; select a source-matching backend or reviewed projection')


def asset(project, rel):
    root = Path(project).resolve()
    p = (root / rel).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise ValueError('Request asset is missing or outside the project')
    return p


class ApiFailure(Exception):
    def __init__(self, code, message='API request rejected'):
        self.code = str(code)
        super().__init__(message)


class Transport:
    """Response details stay private; exceptions expose only API/HTTP codes."""
    def __init__(self, key, base=BASE):
        if base != BASE:
            raise ValueError('Use a separately reviewed adapter for another provider host')
        self.key, self.base = key, base

    def request(self, path, body=None, file=None):
        if file is None:
            data = json.dumps(body or {}, ensure_ascii=False).encode()
            content_type = 'application/json'
        else:
            boundary = '----factory' + uuid.uuid4().hex
            name = Path(file).name.replace('"', '_').replace('\r', '_').replace('\n', '_')
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                    'Content-Type: application/octet-stream\r\n\r\n').encode()
            data += Path(file).read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
            content_type = 'multipart/form-data; boundary=' + boundary
        req = urllib.request.Request(self.base + path, data=data, method='POST', headers={
            'Authorization': 'Bearer ' + self.key, 'Content-Type': content_type})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            # Read body privately; do not expose keys, node inputs or signed URLs.
            try:
                payload = json.loads(e.read().decode('utf-8'))
                code = payload.get('errorCode') or payload.get('code') or e.code
            except Exception:
                code = e.code
            raise ApiFailure(code) from None

    def upload(self, path):
        obj = self.request('/openapi/v2/media/upload/binary', file=path)
        if str(obj.get('code', 0)) not in ('0', '200'):
            raise ApiFailure(obj.get('code'))
        data = obj.get('data') or {}
        name = data.get('filename') or data.get('fileName')
        url = data.get('download_url') or data.get('downloadUrl')
        if not name:
            raise ValueError('Upload response has no filename')
        return {'filename': name, 'url': url}

    def submit(self, path, body):
        return self.request(path, body)

    def query(self, task_id):
        return self.request('/openapi/v2/query', {'taskId': task_id})

    def download(self, url, dest):
        if not str(url).startswith('https://'):
            raise ValueError('Expected HTTPS result URL')
        p = Path(dest)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            raise FileExistsError('Candidate output already exists')
        # Independent recovery workers must never share a partially written file.
        temp = p.with_name(p.name + '.' + uuid.uuid4().hex + '.part')
        try:
            self._download_https(url, temp)
        except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError):
            # This host actually exhibited a local DNS/TLS EOF failure. Retry only
            # inbound transfer; keep the task, HTTPS hostname/SNI and certificates.
            self._download_agreed_dns(url, temp)
        self._verify_download(temp)
        if os.name == 'nt':
            # Windows rename is atomic and refuses an existing destination.
            os.rename(temp, p)
        else:
            # POSIX rename overwrites; link instead atomically claims a new name.
            os.link(temp, p)
            temp.unlink()

    def _download_https(self, url, temp):
        began = time.monotonic()
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r, temp.open('wb') as f:
            expected = r.headers.get('Content-Length')
            written = 0
            while True:
                if time.monotonic() - began > 120:
                    raise TimeoutError('Download total deadline')
                b = r.read(1024 * 1024)
                if not b:
                    break
                f.write(b)
                written += len(b)
            if written == 0 or (expected is not None and written != int(expected)):
                raise ValueError('Incomplete download')

    def _download_agreed_dns(self, url, temp):
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme != 'https' or parts.hostname != OBSERVED_RESULT_HOST or
                parts.port not in (None,443) or parts.username or parts.password):
            raise ValueError('DNS recovery is restricted to the observed HTTPS result host')
        answers = []
        for base in ('https://dns.google/resolve?name=', 'https://cloudflare-dns.com/dns-query?name='):
            req = urllib.request.Request(base+OBSERVED_RESULT_HOST+'&type=A',
                                         headers={'Accept':'application/dns-json'})
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.load(response)
            addresses = set()
            for item in data.get('Answer', []):
                if item.get('type') != 1:
                    continue
                try:
                    address = ipaddress.ip_address(item['data'])
                except (KeyError, ValueError):
                    continue
                if address.version == 4 and address.is_global:
                    addresses.add(str(address))
            answers.append(addresses)
        agreed = answers[0] & answers[1]
        if not agreed:
            raise ValueError('Independent HTTPS DNS sources did not agree on a public address')
        result = subprocess.run([
            'curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
            '--resolve', OBSERVED_RESULT_HOST+':443:'+sorted(agreed)[0],
            '--connect-timeout','20','--max-time','120','--output',str(temp),
            '--silent','--show-error',url], capture_output=True, timeout=125)
        if result.returncode or not temp.exists() or not temp.stat().st_size:
            raise ValueError('Verified-DNS HTTPS result download failed')

    @staticmethod
    def _verify_download(temp):
        # Full independent decode before promotion from .part. No visual verdict.
        check = subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-threads', '1', '-i', str(temp),
                                '-map', '0:v:0', '-f', 'null', '-'], capture_output=True, timeout=120)
        if check.returncode or check.stderr.strip():
            raise ValueError('Downloaded candidate failed complete decode; preserved .part')


class Ledger:
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.db = sqlite3.connect(str(self.path), timeout=20, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS accounts(alias TEXT PRIMARY KEY, stopped INTEGER NOT NULL DEFAULT 0,
          cooldown REAL NOT NULL DEFAULT 0, cap INTEGER NOT NULL DEFAULT 3);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, account TEXT NOT NULL,
          project TEXT NOT NULL, window TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL,
          task_id TEXT, request TEXT, receipt TEXT, result_url TEXT, output TEXT,
          created REAL, updated REAL, next_poll REAL DEFAULT 0, query_errors INTEGER DEFAULT 0,
          missing_results INTEGER DEFAULT 0, download_errors INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS uploads(account TEXT, sha TEXT, semantics TEXT, data TEXT, expires REAL,
          PRIMARY KEY(account,sha,semantics));
        CREATE TABLE IF NOT EXISTS failures(account TEXT, project TEXT, window TEXT, count INTEGER DEFAULT 0,
          PRIMARY KEY(account,project,window));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, attempt TEXT, time REAL, kind TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS model_key_denials(account TEXT, key_fingerprint TEXT, code TEXT,
          PRIMARY KEY(account,key_fingerprint));
        ''')

    def close(self):
        self.db.close()

    def event(self, attempt, kind, data=None):
        self.db.execute('INSERT INTO events(attempt,time,kind,data) VALUES(?,?,?,?)',
                        (attempt, self.clock(), kind, json.dumps(data or {}, ensure_ascii=False)))

    def account(self, alias):
        self.db.execute('INSERT OR IGNORE INTO accounts(alias) VALUES(?)', (alias,))
        return dict(self.db.execute('SELECT * FROM accounts WHERE alias=?', (alias,)).fetchone())

    def reserve(self, alias, project, window, digest, retry_after=None):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            a = self.account(alias)
            if a['stopped'] or a['cooldown'] > self.clock():
                self.db.execute('COMMIT')
                return None
            prior = self.db.execute('SELECT * FROM attempts WHERE account=? AND project=? AND window=? ORDER BY created DESC,rowid DESC LIMIT 1',
                                    (alias, str(Path(project).resolve()), window)).fetchone()
            if prior and prior['state'] in ACTIVE:
                # A different digest is a new input revision, but old cloud work is still active.
                self.db.execute('COMMIT')
                return None
            same = self.db.execute('SELECT * FROM attempts WHERE account=? AND project=? AND window=? AND digest=? ORDER BY created DESC,rowid DESC LIMIT 1',
                                   (alias, str(Path(project).resolve()), window, digest)).fetchone()
            if same and same['state'] not in ('EXECUTION_FAILED', 'DEFERRED'):
                # Visual retry must explicitly refer to its failed immutable candidate.
                if same['state'] != 'VISUAL_FAILED' or retry_after != same['id']:
                    self.db.execute('COMMIT')
                    return None
            f = self.db.execute('SELECT count FROM failures WHERE account=? AND project=? AND window=?',
                                (alias, str(Path(project).resolve()), window)).fetchone()
            if f and f['count'] >= 3:
                self.db.execute('COMMIT')
                return None
            used = self.db.execute('SELECT count(*) FROM attempts WHERE account=? AND state IN (?,?,?,?)', (alias, *ACTIVE)).fetchone()[0]
            if used >= a['cap']:
                self.db.execute('COMMIT')
                return None
            aid = uuid.uuid4().hex
            now = self.clock()
            self.db.execute('INSERT INTO attempts(id,account,project,window,digest,state,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                            (aid, alias, str(Path(project).resolve()), window, digest, 'SUBMITTING', now, now))
            self.event(aid, 'INTENT_RECORDED', {'input_digest': digest})
            self.db.execute('COMMIT')
            return aid
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def update(self, aid, **values):
        allowed = {'state', 'task_id', 'request', 'receipt', 'result_url', 'output', 'next_poll', 'query_errors', 'missing_results', 'download_errors'}
        if not set(values).issubset(allowed):
            raise ValueError('Unknown ledger column')
        values['updated'] = self.clock()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('UPDATE attempts SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?', (*values.values(), aid))
            self.event(aid, 'UPDATE', {'state': values.get('state')})
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def row(self, aid):
        r = self.db.execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone()
        if not r:
            raise ValueError('Unknown attempt')
        return dict(r)

    def execution_failure(self, aid, code):
        r = self.row(aid)
        self.update(aid, state='EXECUTION_FAILED')
        self.db.execute('INSERT INTO failures(account,project,window,count) VALUES(?,?,?,1) ON CONFLICT(account,project,window) DO UPDATE SET count=count+1',
                        (r['account'], r['project'], r['window']))
        if str(code) in ('401', '402', '403', '1913'):
            self.stop(r['account'])
        elif str(code) == '421':
            self.db.execute('UPDATE accounts SET cooldown=? WHERE alias=?', (self.clock() + 60, r['account']))
        self.event(aid, 'EXECUTION_FAILURE', {'code': str(code)})

    def defer_submission(self, aid, code):
        row = self.row(aid)
        if row['task_id']:
            raise ValueError('An accepted task must keep its ID; only a new submission can be deferred')
        self.update(aid, state='DEFERRED')
        self.cooldown(row['account'])
        self.event(aid, 'SUBMISSION_DEFERRED', {'code':str(code)})

    def defer_query(self, aid, code, receipt=None):
        row = self.row(aid)
        if not row['task_id']:
            raise ValueError('Query deferral requires an accepted task ID')
        # A busy query is not a terminal execution verdict or permission to POST.
        values = {'next_poll': self.clock() + 60}
        if receipt is not None:
            values['receipt'] = json.dumps(receipt)
        self.update(aid, **values)
        self.cooldown(row['account'])
        self.event(aid, 'QUERY_DEFERRED', {'code': str(code)})

    def cooldown(self, alias):
        self.db.execute('UPDATE accounts SET cooldown=MAX(cooldown,?) WHERE alias=?',
                        (self.clock()+60, alias))

    def stop(self, alias):
        self.account(alias)
        self.db.execute('UPDATE accounts SET stopped=1 WHERE alias=?', (alias,))

    def summary(self, alias):
        a = self.account(alias)
        rows = self.db.execute('SELECT id,project,window,state,task_id,output FROM attempts WHERE account=? ORDER BY created', (alias,)).fetchall()
        return {'account': alias, 'stopped': bool(a['stopped']), 'cap': a['cap'],
                'cooldown_remaining': max(0, int(a['cooldown'] - self.clock())),
                'active': sum(r['state'] in ACTIVE for r in rows), 'attempts': [dict(r) for r in rows]}


def preflight(project, entry):
    raise ValueError('Use the APT adapter with its current digest-bound validator')


class Runner:
    def __init__(self, ledger, transport, account='default'):
        self.ledger, self.transport, self.account = ledger, transport, account
        self.ledger.account(account)

    def key_fingerprint(self):
        return hashlib.sha256(getattr(self.transport, 'key', 'offline-test-transport').encode()).hexdigest()

    def submission_rejected(self, aid, code):
        if str(code) in DEFERRED_CODES:
            self.ledger.defer_submission(aid, code)
            return
        self.ledger.execution_failure(aid, code)
        if str(code) == '1014':
            self.ledger.db.execute('INSERT OR REPLACE INTO model_key_denials VALUES(?,?,?)',
                                  (self.account, self.key_fingerprint(), '1014'))

    def upload(self, path, semantics):
        h = sha(path)
        row = self.ledger.db.execute('SELECT data,expires FROM uploads WHERE account=? AND sha=? AND semantics=?', (self.account, h, semantics)).fetchone()
        if row and row['expires'] > self.ledger.clock():
            return json.loads(row['data'])
        data = self.transport.upload(path)
        self.ledger.db.execute('INSERT OR REPLACE INTO uploads VALUES(?,?,?,?,?)', (self.account, h, semantics, json.dumps(data), self.ledger.clock() + 21600))
        return data

    def submit_one(self, project, entry, validator=None):
        validator = validator or preflight
        digest = validator(project, entry)
        account = self.ledger.account(self.account)
        if account['stopped'] or account['cooldown'] > self.ledger.clock():
            return None
        if entry['profile']['kind'] == 'standard-h3' and self.ledger.db.execute(
            'SELECT 1 FROM model_key_denials WHERE account=? AND key_fingerprint=?',
            (self.account, self.key_fingerprint())).fetchone():
            return None
        # Uploads do not reserve a cloud execution slot and are cached by bytes.
        kind = entry['profile']['kind']
        if kind=='legacy-ai-app':
            validate_legacy_canvas(entry)
        resolution_nodes=legacy_resolution_nodes(entry['profile']) if kind=='legacy-ai-app' else []
        refs = [self.upload(asset(project, p), kind) for p in entry['reference_paths']]
        video = self.upload(asset(project, entry['video_path']), kind)
        prompt = asset(project, entry['prompt_path']).read_text(encoding='utf-8')
        p = entry['profile']
        if kind == 'legacy-ai-app':
            nodes = [{'nodeId': '137', 'fieldName': 'image', 'fieldValue': refs[0]['filename']},
                     {'nodeId': '138', 'fieldName': 'value', 'fieldValue': prompt},
                     {'nodeId': '321', 'fieldName': 'video', 'fieldValue': video['filename']},
                     {'nodeId': '326', 'fieldName': 'value', 'fieldValue': str(entry['generation_frames'])}]
            if len(refs) == 2:
                nodes.append({'nodeId': '139', 'fieldName': 'image', 'fieldValue': refs[1]['filename']})
            nodes.extend(resolution_nodes)
            path = '/openapi/v2/run/ai-app/' + p['app_id']
            body = {'nodeInfoList': nodes, 'instanceType': p.get('instance_type', 'plus'), 'usePersonalQueue': False}
        else:
            if not video.get('url') or any(not x.get('url') for x in refs):
                raise ValueError('Standard endpoint needs upload download_url values')
            path = '/openapi/v2/minimax/hailuo-h3/multimodal-to-video'
            body = {'prompt': prompt, 'imageUrls': [x['url'] for x in refs], 'videoUrls': [video['url']],
                    'resolution': p.get('resolution', '2K'), 'duration': str(entry['duration']),
                    'ratio': p.get('ratio', 'adaptive'), 'aigc_watermark': False}
        # Recheck after uploads: another process might change any input.
        if validator(project, entry) != digest:
            raise ValueError('Inputs changed during upload')
        aid = self.ledger.reserve(self.account, project, entry['window_id'], digest, entry.get('retry_after'))
        if not aid:
            return None
        self.ledger.update(aid, request=json.dumps({'path': path, 'body': body}, ensure_ascii=False))
        try:
            res = self.transport.submit(path, body)
        except ApiFailure as e:
            # An HTTP 5xx can occur after the server accepted the job.
            if e.code in ('400', '401', '402', '403', '1913', '1014') + DEFERRED_CODES:
                self.submission_rejected(aid, e.code)
            else:
                self.ledger.update(aid, state='SUBMISSION_UNKNOWN')
            return aid
        except Exception:
            self.ledger.update(aid, state='SUBMISSION_UNKNOWN')
            return aid
        tid = res.get('taskId') or (res.get('data') or {}).get('taskId')
        if not tid:
            code = res.get('errorCode') or res.get('code')
            if str(code) in ('400', '401', '402', '403', '1913', '1014') + DEFERRED_CODES:
                self.submission_rejected(aid, code)
                self.ledger.update(aid, receipt=json.dumps(res))
            else:
                self.ledger.update(aid, state='SUBMISSION_UNKNOWN', receipt=json.dumps(res))
            return aid
        self.ledger.update(aid, task_id=str(tid), receipt=json.dumps(res), state='RUNNING', next_poll=self.ledger.clock() + 5)
        return aid

    def recover(self, aid, defer_download=False):
        row = self.ledger.row(aid)
        if row['state'] not in POLLABLE or not row['task_id']:
            return
        if row['state'] == 'RESULTS_MISSING':
            return
        if row['next_poll'] > self.ledger.clock():
            return
        try:
            res = self.transport.query(row['task_id'])
        except ApiFailure as e:
            if e.code in DEFERRED_CODES:
                self.ledger.defer_query(aid, e.code)
                return
            if e.code in ('401', '402', '403', '1913'):
                self.ledger.stop(self.account)
            self.ledger.update(aid, query_errors=row['query_errors'] + 1, next_poll=self.ledger.clock() + 60)
            return
        except Exception:
            self.ledger.update(aid, query_errors=row['query_errors'] + 1, next_poll=self.ledger.clock() + min(60, 5 * 2 ** min(4, row['query_errors'])))
            return
        state = str(res.get('status') or '')
        code = str(res.get('errorCode') or res.get('code') or '')
        if code in DEFERRED_CODES and state != 'SUCCESS':
            self.ledger.defer_query(aid, code, res)
            return
        if state == 'FAILED':
            self.ledger.execution_failure(aid, code)
            self.ledger.update(aid, receipt=json.dumps(res))
            return
        if code and code not in ('0', '200') and state != 'SUCCESS':
            if code in ('401', '402', '403', '1913'):
                self.ledger.stop(self.account)
            self.ledger.update(aid, next_poll=self.ledger.clock() + 60)
            return
        if state in ('QUEUED', 'RUNNING'):
            self.ledger.update(aid, state=state, receipt=json.dumps(res), next_poll=self.ledger.clock() + 10 + random.random() * 2)
            return
        if state != 'SUCCESS':
            self.ledger.update(aid, next_poll=self.ledger.clock() + 30)
            return
        # Execution success frees generation capacity even while URLs/download need recovery.
        self.ledger.db.execute('DELETE FROM failures WHERE account=? AND project=? AND window=?', (self.account, row['project'], row['window']))
        results = res.get('results') or []
        videos = [r for r in results if r.get('url') and (str(r.get('outputType', '')).lower() in ('mp4', 'mov', 'video') or '.mp4' in r['url'].split('?')[0].lower())]
        if len(videos) != 1:
            n = row['missing_results'] + 1
            self.ledger.update(aid, state='RESULTS_MISSING' if n >= 3 else 'SUCCESS_RESULTS_PENDING',
                               receipt=json.dumps(res), missing_results=n, next_poll=self.ledger.clock() + 30)
            return
        url = videos[0]['url']
        dest = Path(row['project']) / 'candidates' / row['window'] / aid / 'output.mp4'
        self.ledger.update(aid, state='RESULTS_READY', result_url=url, receipt=json.dumps(res), output=str(dest))
        if defer_download:
            return
        try:
            if not dest.exists():
                self.transport.download(url, dest)
            if not dest.exists() or dest.stat().st_size == 0:
                raise ValueError('Candidate output missing')
            self.ledger.update(aid, state='DOWNLOADED', download_errors=0, next_poll=0)
        except Exception:
            self.ledger.update(aid, state='DOWNLOAD_FAILED', download_errors=row['download_errors'] + 1, next_poll=self.ledger.clock() + 30)

