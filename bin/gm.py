#!/usr/bin/env python3
"""Git Migrator backend (stdlib only). Called by the WebUI through bin/gm.sh.
   Usage:  gm.py call <base64-json>     ->  prints one JSON line
           gm.py _run <jobid>           (internal, detached worker)"""
import os, sys, json, base64, subprocess, time, shutil, tempfile, re, urllib.request, urllib.error

DATA = os.environ.get('GM_DATA', '/data/adb/gitmigrator')
API = os.environ.get('GH_API_BASE', 'https://api.github.com')
WEB = os.environ.get('GH_WEB_BASE', 'https://github.com')
AI_BASE = os.environ.get('AI_API_BASE', 'https://api.anthropic.com')
NAME_RE = re.compile(r'^[A-Za-z0-9._-]{1,100}$')
FILE_RE = re.compile(r'^[A-Za-z0-9._-]{1,220}\.git$')
CFG_PATH = os.path.join(DATA, 'config.json')
JOBS = os.path.join(DATA, 'jobs')
SKIP_DIRS = {'.git', 'node_modules', '.venv', '__pycache__', '.gradle'}

# ---------------- config ----------------
def load_cfg():
    try:
        c = json.load(open(CFG_PATH))
    except Exception:
        c = {}
    c.setdefault('dir', os.path.join(DATA, 'backup'))
    c.setdefault('src', None); c.setdefault('dst', None)
    c.setdefault('ai', {'key': '', 'model': 'claude-sonnet-5-5'})
    return c

def save_cfg(c):
    os.makedirs(DATA, exist_ok=True)
    fd = os.open(CFG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(c, f)

def public_cfg(c):
    return {'dir': c['dir'],
            'src': {'login': c['src'].get('login')} if c['src'] else None,
            'dst': {'login': c['dst'].get('login')} if c['dst'] else None,
            'ai': {'has_key': bool(c['ai'].get('key')), 'model': c['ai'].get('model')}}

# ---------------- GitHub API ----------------
def gh(token, method, path, body=None):
    url = path if path.startswith('http') else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'token ' + token, 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'gitmigrator-ksu',
        **({'Content-Type': 'application/json'} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'null')
        except Exception:
            return e.code, None

def whoami(token):
    try:
        st, j = gh(token, 'GET', '/user')
        return j.get('login') if st == 200 and j else None
    except Exception:
        return None

# ---------------- git ----------------
def git(args, token=None, cwd=None, env_extra=None, timeout=None):
    env = dict(os.environ)
    env['GIT_TERMINAL_PROMPT'] = '0'
    cfgs = [('safe.directory', '*')]
    secrets = []
    if token:
        b64 = base64.b64encode(('x-access-token:' + token).encode()).decode()
        cfgs.append(('http.%s/.extraheader' % WEB, 'Authorization: Basic ' + b64))
        secrets = [token, b64]
    env['GIT_CONFIG_COUNT'] = str(len(cfgs))
    for i, (k, v) in enumerate(cfgs):
        env['GIT_CONFIG_KEY_%d' % i] = k; env['GIT_CONFIG_VALUE_%d' % i] = v
    if env_extra: env.update(env_extra)
    try:
        p = subprocess.run(['git'] + args, cwd=cwd, env=env, capture_output=True, timeout=timeout)
        out = (p.stdout + p.stderr).decode(errors='replace')
        code = p.returncode
    except FileNotFoundError:
        return 127, 'git not found (install it in Termux: pkg install git)'
    except subprocess.TimeoutExpired:
        return 124, 'timeout'
    for s in secrets: out = out.replace(s, '***')
    return code, out

def last_line(s):
    ls = [x for x in s.strip().splitlines() if x.strip()]
    return ls[-1] if ls else ''

def count_lines(s): return len([x for x in s.splitlines() if x.strip()])

# ---------------- mirrors ----------------
def mirrors_root(c): return os.path.join(c['dir'], 'mirrors')

def list_mirrors(c):
    root = mirrors_root(c)
    try: names = sorted(n for n in os.listdir(root) if n.endswith('.git'))
    except OSError: return []
    out = []
    for n in names:
        d = os.path.join(root, n)
        _, b = git(['-C', d, 'for-each-ref', '--format=x', 'refs/heads'])
        _, t = git(['-C', d, 'for-each-ref', '--format=x', 'refs/tags'])
        _, cm = git(['-C', d, 'rev-list', '--count', '--branches', '--tags'])
        hc, h = git(['-C', d, 'symbolic-ref', '--short', 'HEAD'])
        _, l = git(['-C', d, 'for-each-ref', '--sort=-committerdate', '--count=1', '--format=%(committerdate:short)', 'refs/heads'])
        base = n[:-4]; i = base.find('__')
        out.append({'file': n, 'owner': base[:i] if i >= 0 else '', 'name': base[i + 2:] if i >= 0 else base,
                    'branches': count_lines(b), 'tags': count_lines(t),
                    'commits': int(cm.strip()) if cm.strip().isdigit() else 0,
                    'head': h.strip() if hc == 0 else '', 'last': l.strip()})
    return out

# ---------------- jobs ----------------
class Job:
    def __init__(self, jid):
        self.id = jid
        self.ev_path = os.path.join(JOBS, jid + '.events')
        self.cancel_path = os.path.join(JOBS, jid + '.cancel')
    def emit(self, **ev):
        with open(self.ev_path, 'a') as f: f.write(json.dumps(ev, ensure_ascii=False) + '\n')
    def log(self, text): self.emit(type='log', text=text)
    def item(self, key, status, note=None): self.emit(type='item', key=key, status=status, note=note)
    @property
    def cancelled(self): return os.path.exists(self.cancel_path)
    def sleep(self, s):
        for _ in range(int(s * 10)):
            if self.cancelled: return
            time.sleep(0.1)

def retry(fn, tries, j):
    r = None
    for i in range(tries):
        r = fn()
        if r[0] == 0 or j.cancelled: return r
        if i < tries - 1: j.sleep((i + 1) * 3)
    return r

def job_backup(j, p, c):
    if not c['src']: raise Exception('حساب مبدأ تنظیم نشده است.')
    tok = c['src']['token']
    os.makedirs(mirrors_root(c), exist_ok=True); os.makedirs(os.path.join(c['dir'], 'wikis'), exist_ok=True)
    j.log('دریافت لیست ریپوها...')
    repos = []
    for page in range(1, 20):
        st, js = gh(tok, 'GET', '/user/repos?per_page=100&page=%d&affiliation=owner&sort=full_name' % page)
        if st != 200: raise Exception('GitHub: %s' % ((js or {}).get('message') or st))
        repos += js
        if len(js) < 100: break
    if not p.get('forks', True): repos = [r for r in repos if not r.get('fork')]
    j.emit(type='plan', items=[{'key': r['full_name'], 'label': r['full_name']} for r in repos])
    ok = fail = 0
    for r in repos:
        if j.cancelled: j.log('متوقف شد.'); break
        full = r['full_name']; d = os.path.join(mirrors_root(c), full.replace('/', '__') + '.git')
        j.item(full, 'run')
        exists = os.path.isdir(d)
        res = retry(lambda: git(['-C', d, 'remote', 'update', '--prune'], tok) if exists
                    else git(['clone', '--mirror', '--quiet', '%s/%s.git' % (WEB, full), d], tok), 3, j)
        if res[0] != 0: fail += 1; j.item(full, 'fail', last_line(res[1])); continue
        note = 'آپدیت شد' if exists else 'کامل'
        if r.get('has_wiki'):
            wd = os.path.join(c['dir'], 'wikis', full.replace('/', '__') + '.wiki.git')
            w = git(['-C', wd, 'remote', 'update', '--prune'], tok) if os.path.isdir(wd) \
                else git(['clone', '--mirror', '--quiet', '%s/%s.wiki.git' % (WEB, full), wd], tok)
            if w[0] == 0: note += ' + ویکی'
            else: shutil.rmtree(wd, ignore_errors=True)
        ok += 1; j.item(full, 'ok', note); j.sleep(2)
    j.emit(type='summary', ok=ok, fail=fail)

def ensure_repo(tok, owner, name, private):
    st, js = gh(tok, 'GET', '/repos/%s/%s' % (owner, name))
    if st == 404:
        st2, js2 = gh(tok, 'POST', '/user/repos', {'name': name, 'private': bool(private), 'auto_init': False})
        if st2 != 201: raise Exception('ساخت ریپو ناموفق: %s' % ((js2 or {}).get('message') or st2))
    elif st != 200:
        raise Exception('دسترسی به ریپو ممکن نیست: %s' % ((js or {}).get('message') or st))

def need_dst(c):
    if not c['dst']: raise Exception('حساب مقصد تنظیم نشده است.')
    if not c['dst'].get('login'):
        c['dst']['login'] = whoami(c['dst']['token']); save_cfg(c)
    if not c['dst'].get('login'): raise Exception('توکن مقصد نامعتبر است.')
    return c['dst']['token'], c['dst']['login']

def job_migrate(j, p, c):
    tok, owner = need_dst(c)
    delay = max(0, min(600, float(p.get('delay') or 0)))
    items = [i for i in p.get('items', []) if FILE_RE.match(i.get('file', '')) and NAME_RE.match(i.get('name', ''))]
    j.emit(type='plan', items=[{'key': i['file'], 'label': '%s → %s/%s' % (i['file'][:-4], owner, i['name'])} for i in items])
    ok = fail = 0; first = True
    for it in items:
        if j.cancelled: j.log('متوقف شد.'); break
        if not first and delay:
            j.log('انتظار %d ثانیه تا ریپوی بعدی...' % delay); j.sleep(delay)
            if j.cancelled: break
        first = False
        d = os.path.join(mirrors_root(c), it['file'])
        j.item(it['file'], 'run', 'بررسی ریپوی مقصد')
        try:
            ensure_repo(tok, owner, it['name'], p.get('priv'))
            j.item(it['file'], 'run', 'در حال push (همه‌ی برنچ‌ها و تگ‌ها)')
            res = retry(lambda: git(['-C', d, 'push', '--prune', '%s/%s/%s.git' % (WEB, owner, it['name']),
                                     '+refs/heads/*:refs/heads/*', '+refs/tags/*:refs/tags/*'], tok), 2, j)
            if res[0] != 0: raise Exception(' | '.join(res[1].strip().splitlines()[-3:]))
            hc, h = git(['-C', d, 'symbolic-ref', '--short', 'HEAD'])
            if hc == 0 and h.strip(): gh(tok, 'PATCH', '/repos/%s/%s' % (owner, it['name']), {'default_branch': h.strip()})
            ok += 1; j.item(it['file'], 'ok', 'https://github.com/%s/%s' % (owner, it['name']))
        except Exception as e:
            fail += 1; j.item(it['file'], 'fail', str(e))
    j.emit(type='summary', ok=ok, fail=fail)

def job_verify(j, p, c):
    ms = list_mirrors(c)
    j.emit(type='plan', items=[{'key': m['file'], 'label': m['file']} for m in ms])
    ok = fail = 0
    for m in ms:
        if j.cancelled: break
        j.item(m['file'], 'run')
        code, _ = git(['-C', os.path.join(mirrors_root(c), m['file']), 'fsck', '--no-progress'])
        if code == 0: ok += 1; j.item(m['file'], 'ok', 'سالم')
        else: fail += 1; j.item(m['file'], 'fail', 'خراب')
    j.emit(type='summary', ok=ok, fail=fail)

def job_push_folder(j, p, c):
    """Folder -> repo. mode 'snapshot': new commit on top of the branch. mode 'history': push the folder's own .git."""
    tok, owner = need_dst(c)
    folder = p.get('folder', ''); name = p.get('name', ''); branch = p.get('branch') or 'main'
    msg = p.get('message') or 'Upload via Git Migrator'; mode = p.get('mode', 'snapshot')
    if not os.path.isdir(folder): raise Exception('پوشه پیدا نشد.')
    if not NAME_RE.match(name): raise Exception('نام ریپو نامعتبر است.')
    if not re.match(r'^[A-Za-z0-9._/-]{1,100}$', branch): raise Exception('نام برنچ نامعتبر است.')
    j.emit(type='plan', items=[{'key': 'push', 'label': '%s → %s/%s (%s)' % (os.path.basename(folder.rstrip('/')), owner, name, branch)}])
    j.item('push', 'run', 'بررسی ریپوی مقصد')
    ensure_repo(tok, owner, name, p.get('priv'))
    url = '%s/%s/%s.git' % (WEB, owner, name)
    if mode == 'history':
        if not os.path.isdir(os.path.join(folder, '.git')): raise Exception('این پوشه .git ندارد.')
        j.item('push', 'run', 'push همه‌ی برنچ‌ها و تگ‌ها')
        code, out = git(['-C', folder, 'push', '--prune', url, '+refs/heads/*:refs/heads/*', '+refs/tags/*:refs/tags/*'], tok)
        if code != 0: raise Exception(' | '.join(out.strip().splitlines()[-3:]))
    else:
        tmp = tempfile.mkdtemp(prefix='gm-', dir=os.environ.get('TMPDIR') or None)
        try:
            ident = {'GIT_AUTHOR_NAME': owner, 'GIT_COMMITTER_NAME': owner,
                     'GIT_AUTHOR_EMAIL': owner + '@users.noreply.github.com', 'GIT_COMMITTER_EMAIL': owner + '@users.noreply.github.com'}
            git(['init', '-q', '-b', branch], cwd=tmp); git(['remote', 'add', 'origin', url], cwd=tmp)
            j.item('push', 'run', 'دریافت وضعیت فعلی برنچ')
            fc, _ = git(['fetch', '--depth', '1', 'origin', branch], tok, cwd=tmp)
            if fc == 0: git(['reset', '-q', '--hard', 'FETCH_HEAD'], cwd=tmp)
            for e in os.listdir(tmp):
                if e != '.git':
                    pth = os.path.join(tmp, e)
                    shutil.rmtree(pth) if os.path.isdir(pth) else os.remove(pth)
            j.item('push', 'run', 'کپی فایل‌ها')
            for e in os.listdir(folder):
                if e == '.git': continue
                s, d = os.path.join(folder, e), os.path.join(tmp, e)
                if os.path.isdir(s) and not os.path.islink(s): shutil.copytree(s, d, ignore=shutil.ignore_patterns('.git'))
                elif os.path.isfile(s): shutil.copy(s, d)
            git(['add', '-A'], cwd=tmp)
            sc, so = git(['status', '--porcelain'], cwd=tmp)
            if not so.strip():
                j.item('push', 'ok', 'تغییری برای ارسال نبود'); j.emit(type='summary', ok=1, fail=0); return
            cc, co = git(['commit', '-q', '-m', msg], cwd=tmp, env_extra=ident)
            if cc != 0: raise Exception('commit ناموفق: ' + last_line(co))
            j.item('push', 'run', 'در حال push')
            pc, po = retry(lambda: git(['push', 'origin', 'HEAD:refs/heads/' + branch], tok, cwd=tmp), 2, j)
            if pc != 0: raise Exception(' | '.join(po.strip().splitlines()[-3:]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    j.item('push', 'ok', 'https://github.com/%s/%s' % (owner, name)); j.emit(type='summary', ok=1, fail=0)

JOB_TYPES = {'backup': job_backup, 'migrate': job_migrate, 'verify': job_verify, 'push_folder': job_push_folder}

def run_worker(jid):
    j = Job(jid); c = load_cfg()
    p = json.load(open(os.path.join(JOBS, jid + '.json')))
    open(os.path.join(JOBS, jid + '.pid'), 'w').write(str(os.getpid()))
    try:
        JOB_TYPES[p['type']](j, p.get('params', {}), c)
    except Exception as e:
        j.emit(type='error', text=str(e))
    j.emit(type='end')

def job_running(jid):
    ev = os.path.join(JOBS, jid + '.events')
    try:
        return not any('"type": "end"' in l for l in open(ev))
    except OSError:
        return True

# ---------------- link fixer ----------------
def build_regex(old):
    o = re.escape(old.encode())
    ctx = (rb'(?:github\.com[/:]|githubusercontent\.com/|api\.github\.com/(?:repos|users)/|'
           rb'shields\.io/github/[A-Za-z0-9_-]+/|ghcr\.io/|gist\.github\.com/|github\.com/sponsors/|'
           rb'github\.com/users/|uses:\s*|docker\.pkg\.github\.com/)')
    tail = rb'(?![A-Za-z0-9_.-]*[A-Za-z0-9_-])'
    p1 = re.compile(rb'(?P<ctx>' + ctx + rb')' + o + tail + rb'(?P<rest>/(?P<repo>[A-Za-z0-9_.-]+))?', re.I)
    p2 = re.compile(rb'(?P<pre>(?<![A-Za-z0-9_-]))' + o + rb'(?P<host>\.github\.io)(?P<rest>/(?P<repo>[A-Za-z0-9_.-]+))?', re.I)
    return p1, p2

def fix_data(data, old, new, repomap, replace_all):
    n = new.encode(); cnt = [0]
    def fix_repo(m):
        rest = m.group('rest')
        if not rest: return b''
        key = m.group('repo').decode(errors='ignore')
        base, suf = (key[:-4], '.git') if key.endswith('.git') else (key, '')
        if base.lower() in repomap: return b'/' + repomap[base.lower()].encode() + suf.encode()
        return rest
    def r1(m): cnt[0] += 1; return m.group('ctx') + n + fix_repo(m)
    def r2(m): cnt[0] += 1; return m.group('pre') + n + m.group('host') + fix_repo(m)
    p1, p2 = build_regex(old)
    out = p2.sub(r2, p1.sub(r1, data))
    if replace_all:
        out, k = re.compile(rb'(?<![A-Za-z0-9_-])' + re.escape(old.encode()) + rb'(?![A-Za-z0-9_-])', re.I).subn(n, out)
        cnt[0] += k
    return out, cnt[0]

def linkfix(a):
    root = a['path']; old = a['old'].strip(); new = a['new'].strip()
    if not os.path.isdir(root): raise Exception('پوشه پیدا نشد.')
    if not re.match(r'^[A-Za-z0-9-]{1,39}$', old) or not re.match(r'^[A-Za-z0-9-]{1,39}$', new):
        raise Exception('نام کاربری گیت‌هاب نامعتبر است.')
    repomap = {}
    for line in (a.get('map') or '').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            if k.strip() and NAME_RE.match(v.strip()): repomap[k.strip().lower()] = v.strip()
    files, total, left, roots = [], 0, [], set()
    pa = re.compile(rb'(?<![A-Za-z0-9_-])' + re.escape(old.encode()) + rb'(?![A-Za-z0-9_-])', re.I)
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            path = os.path.join(dp, fn)
            try:
                if os.path.islink(path) or os.path.getsize(path) > 5 * 1024 * 1024: continue
                data = open(path, 'rb').read()
            except OSError: continue
            if b'\x00' in data[:8192]: continue
            nd, cnt = fix_data(data, old, new, repomap, a.get('all'))
            rel = os.path.relpath(path, root)
            if cnt:
                files.append({'path': rel, 'count': cnt}); total += cnt
                if a.get('apply'):
                    try:
                        mode = os.stat(path).st_mode
                        open(path, 'wb').write(nd)
                        os.chmod(path, mode)
                    except OSError as e:
                        raise Exception('نوشتن %s ناموفق: %s' % (rel, e))
                    d = dp
                    while d != os.path.dirname(d):
                        if os.path.isdir(os.path.join(d, '.git')): roots.add(d); break
                        d = os.path.dirname(d)
            if len(left) < 60:
                for i, line in enumerate(nd.split(b'\n'), 1):
                    if pa.search(line): left.append({'path': rel, 'line': i, 'text': line.decode(errors='replace').strip()[:140]})
    committed = []
    if a.get('apply') and a.get('commit'):
        for r in sorted(roots):
            git(['-C', r, 'add', '-A'])
            cc, _ = git(['-C', r, 'commit', '-q', '-m', 'Update links to @' + new],
                        env_extra={'GIT_AUTHOR_NAME': new, 'GIT_COMMITTER_NAME': new,
                                   'GIT_AUTHOR_EMAIL': new + '@users.noreply.github.com', 'GIT_COMMITTER_EMAIL': new + '@users.noreply.github.com'})
            committed.append({'repo': r, 'ok': cc == 0})
    return {'ok': True, 'applied': bool(a.get('apply')), 'total': total, 'files': files[:300],
            'leftovers': left, 'committed': committed}

# ---------------- AI assistant (optional, user's own API key) ----------------
AI_SYSTEM = (
    "You are the assistant inside 'Git Migrator', a rooted-Android (KernelSU) tool that backs up GitHub repos as mirrors, "
    "pushes them (all branches, tags, history) to another GitHub account, uploads folders to repos and fixes old-username links. "
    "Answer in Persian, short and practical (the user reads on a phone). Explain errors from the job log, suggest the next step, "
    "and give exact shell commands only when truly needed. You cannot run anything yourself; never claim that you did. "
    "Warn about risky actions (force push overwrites, token scopes, rate limits / account flags).")

def ai_chat(a, c):
    key = c['ai'].get('key')
    if not key: raise Exception('کلید API تنظیم نشده است (تب دستیار → تنظیمات).')
    msgs = [m for m in a.get('messages', []) if m.get('role') in ('user', 'assistant') and str(m.get('content', '')).strip()][-12:]
    if not msgs or msgs[-1]['role'] != 'user': raise Exception('پیام خالی است.')
    ctx = str(a.get('context') or '')[:3500]
    system = AI_SYSTEM + ('\n\nCurrent context (last job / selection):\n' + ctx if ctx else '')
    body = json.dumps({'model': c['ai'].get('model') or 'claude-sonnet-5-5', 'max_tokens': 1200, 'system': system, 'messages': msgs}).encode()
    req = urllib.request.Request(AI_BASE + '/v1/messages', data=body, method='POST', headers={
        'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            js = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: msg = json.loads(e.read()).get('error', {}).get('message', '')
        except Exception: msg = ''
        raise Exception('خطای API (%s): %s' % (e.code, msg))
    return {'ok': True, 'text': ''.join(b.get('text', '') for b in js.get('content', []) if b.get('type') == 'text')}

# ---------------- commands ----------------
def cmd_config(a, c): return {'ok': True, **public_cfg(c)}

def cmd_account(a, c):
    role = 'src' if a.get('role') == 'src' else 'dst'
    tok = str(a.get('token', '')).strip()
    if not tok: raise Exception('توکن خالی است.')
    login = whoami(tok)
    if not login: raise Exception('توکن نامعتبر است یا اکانت محدود شده.')
    c[role] = {'token': tok, 'login': login}; save_cfg(c)
    return {'ok': True, 'login': login}

def cmd_setdir(a, c):
    d = str(a.get('dir', '')).strip()
    if not os.path.isabs(d): raise Exception('مسیر باید کامل (absolute) باشد.')
    c['dir'] = d; save_cfg(c); return {'ok': True}

def cmd_setai(a, c):
    if a.get('key'): c['ai']['key'] = str(a['key']).strip()
    if a.get('model'): c['ai']['model'] = str(a['model']).strip()
    if a.get('clear'): c['ai']['key'] = ''
    save_cfg(c); return {'ok': True}

def cmd_ls(a, c):
    p = a.get('path') or '/storage/emulated/0'
    if not os.path.isdir(p): raise Exception('پوشه پیدا نشد: ' + p)
    dirs, files = [], []
    try: names = sorted(os.listdir(p), key=str.lower)
    except OSError as e: raise Exception('دسترسی ممکن نیست: %s' % e)
    for n in names:
        fp = os.path.join(p, n)
        try:
            if os.path.isdir(fp): dirs.append({'name': n, 'git': os.path.isdir(os.path.join(fp, '.git'))})
            elif len(files) < 300: files.append({'name': n, 'size': os.path.getsize(fp)})
        except OSError: pass
    return {'ok': True, 'path': p, 'parent': os.path.dirname(p) if p != '/' else None,
            'dirs': dirs, 'files': files, 'git': os.path.isdir(os.path.join(p, '.git'))}

def cmd_mirrors(a, c): return {'ok': True, 'mirrors': list_mirrors(c)}

def cmd_export(a, c):
    f = str(a.get('file', ''))
    if not FILE_RE.match(f): raise Exception('نام نامعتبر.')
    d = os.path.join(mirrors_root(c), f); base = f[:-4]
    outs = [os.path.join(c['dir'], 'exports', base)]
    if os.path.isdir('/storage/emulated/0'): outs.append('/storage/emulated/0/GitHubBackup/exports/' + base)
    hc, hist = git(['-C', d, 'log', '--branches', '--tags', '--date=short', '--pretty=format:%h %ad %an: %s'])
    if hc != 0: raise Exception('خواندن تاریخچه ناموفق.')
    written = []
    for i, o in enumerate(outs):
        try:
            os.makedirs(o, exist_ok=True)
            open(os.path.join(o, 'HISTORY.txt'), 'w').write(hist + '\n')
            bc, bo = git(['-C', d, 'bundle', 'create', os.path.join(o, base + '.bundle'), '--branches', '--tags'])
            if bc != 0: raise Exception('ساخت bundle ناموفق')
            written.append(o)
        except Exception:
            if i == 0: raise
    return {'ok': True, 'paths': written}

def cmd_doctor(a, c):
    checks = []
    def add(n, ok, d=''): checks.append({'name': n, 'ok': ok, 'detail': d})
    add('root (uid 0)', os.geteuid() == 0, 'uid=%d' % os.geteuid())
    gc, gv = git(['--version']); add('git', gc == 0, gv.strip()[:60])
    add('پوشه‌ی داده', os.access(DATA, os.W_OK), DATA)
    try:
        urllib.request.urlopen(urllib.request.Request(API + '/zen', headers={'User-Agent': 'gm'}), timeout=15).read()
        add('اتصال به GitHub API', True)
    except Exception as e: add('اتصال به GitHub API', False, str(e)[:80])
    add('python', True, sys.version.split()[0])
    return {'ok': True, 'checks': checks}

def cmd_job_start(a, c):
    os.makedirs(JOBS, exist_ok=True)
    for f in sorted(os.listdir(JOBS)):
        if f.endswith('.events') and job_running(f[:-7]):
            return {'ok': False, 'error': 'یک عملیات دیگر در حال اجراست.', 'id': f[:-7]}
    if a.get('type') not in JOB_TYPES: raise Exception('نوع عملیات نامعتبر.')
    jid = str(int(time.time() * 1000))
    json.dump({'type': a['type'], 'params': a.get('params', {})}, open(os.path.join(JOBS, jid + '.json'), 'w'))
    open(os.path.join(JOBS, jid + '.events'), 'a').close()
    subprocess.Popen([sys.executable, os.path.abspath(__file__), '_run', jid], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=open(os.path.join(JOBS, jid + '.err'), 'w'))
    return {'ok': True, 'id': jid}

def cmd_job_events(a, c):
    jid = str(a.get('id', ''))
    if not re.match(r'^\d+$', jid): raise Exception('شناسه نامعتبر.')
    since = int(a.get('since') or 0)
    try: lines = open(os.path.join(JOBS, jid + '.events')).read().splitlines()
    except OSError: raise Exception('عملیات پیدا نشد.')
    evs = [json.loads(l) for l in lines[since:] if l.strip()]
    done = any(e.get('type') == 'end' for e in evs) or any('"type": "end"' in l for l in lines[:since])
    if not done and not evs:
        pidf = os.path.join(JOBS, jid + '.pid')
        try:
            os.kill(int(open(pidf).read()), 0)
        except Exception:
            if os.path.exists(pidf):  # worker died without 'end'
                err = ''
                try: err = open(os.path.join(JOBS, jid + '.err')).read()[-300:]
                except OSError: pass
                evs.append({'type': 'error', 'text': 'پردازش ناگهانی بسته شد. ' + err}); evs.append({'type': 'end'}); done = True
    return {'ok': True, 'events': evs, 'next': since + len(lines[since:]), 'done': done}

def cmd_job_current(a, c):
    try: ids = sorted(f[:-7] for f in os.listdir(JOBS) if f.endswith('.events'))
    except OSError: return {'ok': True, 'id': None}
    if not ids: return {'ok': True, 'id': None}
    jid = ids[-1]
    try: t = json.load(open(os.path.join(JOBS, jid + '.json')))['type']
    except Exception: t = None
    return {'ok': True, 'id': jid, 'type': t, 'running': job_running(jid)}

def cmd_job_cancel(a, c):
    jid = str(a.get('id', ''))
    if not re.match(r'^\d+$', jid): raise Exception('شناسه نامعتبر.')
    open(os.path.join(JOBS, jid + '.cancel'), 'w').close(); return {'ok': True}

COMMANDS = {'config': cmd_config, 'account': cmd_account, 'setdir': cmd_setdir, 'setai': cmd_setai, 'ls': cmd_ls,
            'mirrors': cmd_mirrors, 'export': cmd_export, 'doctor': cmd_doctor, 'job_start': cmd_job_start,
            'job_events': cmd_job_events, 'job_current': cmd_job_current, 'job_cancel': cmd_job_cancel,
            'linkfix': lambda a, c: linkfix(a), 'ai': ai_chat}

def main():
    os.makedirs(DATA, exist_ok=True)
    if len(sys.argv) >= 3 and sys.argv[1] == '_run':
        return run_worker(sys.argv[2])
    try:
        req = json.loads(base64.b64decode(sys.argv[2]).decode()) if len(sys.argv) >= 3 else {}
        fn = COMMANDS.get(req.get('cmd'))
        if not fn: raise Exception('دستور نامعتبر')
        out = fn(req.get('args') or {}, load_cfg())
    except Exception as e:
        out = {'ok': False, 'error': str(e)}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')

if __name__ == '__main__':
    main()
