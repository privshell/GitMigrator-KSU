'use strict';
const MOD = '/data/adb/modules/gitmigrator';
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------- bridge to the shell (KernelSU WebUI API) ----------
function sh(cmd) {
  return new Promise((resolve) => {
    if (window.GM_EXEC) return window.GM_EXEC(cmd).then(resolve);          // test hook
    if (!window.ksu || !ksu.exec) return resolve({ errno: 1, stdout: '', stderr: 'این صفحه باید داخل KernelSU Manager باز شود.' });
    const cb = 'gm_cb_' + Date.now() + '_' + Math.random().toString(36).slice(2);
    window[cb] = (errno, stdout, stderr) => { resolve({ errno, stdout, stderr }); delete window[cb]; };
    ksu.exec(cmd, '{}', cb);
  });
}
async function call(cmd, args) {
  const b64 = btoa(unescape(encodeURIComponent(JSON.stringify({ cmd, args: args || {} }))));
  const r = await sh(`sh ${MOD}/bin/gm.sh '${b64}'`);
  const line = (r.stdout || '').trim().split('\n').pop();
  try { return JSON.parse(line); } catch { return { ok: false, error: ((r.stderr || r.stdout || 'پاسخ نامعتبر از بک‌اند').trim()).slice(0, 400) }; }
}
function toast(t) { const e = $('#toast'); e.textContent = t; e.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (e.hidden = true), 2600); }

// ---------- state ----------
const S = { page: 'home', cfg: null, folder: null, browse: null, mirrors: [], chat: [], job: null, lastLog: '', ls: '/storage/emulated/0' };
try { S.chat = JSON.parse(localStorage.getItem('gm_chat') || '[]'); } catch {}

function setPage(p) {
  S.page = p;
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('on', b.dataset.p === p));
  render();
}
$('#nav').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setPage(b.dataset.p); });

// ---------- sheet ----------
function openSheet(html) { $('#sheet').innerHTML = html; $('#sheetWrap').hidden = false; }
function closeSheet() { $('#sheetWrap').hidden = true; }
$('#backdrop').addEventListener('click', closeSheet);

// ---------- pages ----------
async function loadCfg() { const r = await call('config'); if (r.ok) S.cfg = r; return r; }
function chip(label, login) { return `<span class="chip ${login ? 'on' : ''}"><i class="dot"></i>${label}: ${login ? '@' + esc(login) : '—'}</span>`; }

function render() {
  const app = $('#app');
  if (S.page === 'home') return renderHome(app);
  if (S.page === 'files') return renderFiles(app);
  if (S.page === 'repos') return renderRepos(app);
  if (S.page === 'ai') return renderAI(app);
}

function renderHome(app) {
  const c = S.cfg;
  app.innerHTML = `<div class="page">
    <div class="hero"><span class="glyph">◈</span><div><h1>Git Migrator</h1></div></div>
    <p class="lead">بکاپ، انتقال و مرتب‌سازی پروژه‌های GitHub با دسترسی روت.</p>
    <div class="row wrap" style="margin-bottom:14px">${chip('مبدأ', c && c.src && c.src.login)}${chip('مقصد', c && c.dst && c.dst.login)}</div>
    <div class="card"><h3>شروع سریع</h3><p class="sub">مسیر پیشنهادی برای انتقال پروژه‌ها به اکانت جدید:</p>
      <div class="grid2">
        <button class="btn ghost" data-go="repos">۱. حساب‌ها و بکاپ</button>
        <button class="btn ghost" data-go="repos">۲. انتقال به اکانت جدید</button>
        <button class="btn ghost" data-go="files">۳. آپلود پوشه</button>
        <button class="btn ghost" data-go="files">۴. اصلاح لینک‌ها</button>
      </div></div>
    <div class="card"><h3>بررسی محیط</h3><p class="sub">مطمئن می‌شه Termux (git و python) و اینترنت برای ماژول آماده‌ان.</p>
      <button class="btn ghost" id="doctor">اجرای بررسی</button><div id="doctorOut" style="margin-top:12px"></div></div>
  </div>`;
  app.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => setPage(b.dataset.go)));
  $('#doctor').addEventListener('click', async () => {
    $('#doctorOut').innerHTML = '<div class="empty">در حال بررسی...</div>';
    const r = await call('doctor');
    $('#doctorOut').innerHTML = r.ok ? r.checks.map((k) => `<div class="row" style="padding:7px 0"><span style="color:${k.ok ? 'var(--mint)' : 'var(--coral)'}">${k.ok ? '✓' : '✗'}</span><span class="grow">${esc(k.name)}</span><span class="msg" style="margin:0">${esc(k.detail)}</span></div>`).join('')
      : `<div class="msg err">${esc(r.error)}</div><div class="note" style="margin-top:10px">اگه پیام درباره‌ی python یا git بود، توی Termux بزن:<br><code>pkg install python git</code></div>`;
  });
}

// ----- files -----
const FALLBACKS = ['/storage/emulated/0', '/sdcard', '/data/data/com.termux/files/home', '/data/adb/gitmigrator', '/'];
async function browse(path, fb) {
  const r = await call('ls', { path });
  if (!r.ok) {
    toast(r.error);
    if (!S.browse) {                       // first load: try other starting points
      const next = FALLBACKS.slice(fb == null ? 0 : fb + 1).find((x) => x !== path);
      if (next) return browse(next, FALLBACKS.indexOf(next));
    }
    return;
  }
  S.browse = r; S.ls = r.path; renderFiles($('#app'));
}
function renderFiles(app) {
  if (!S.browse) { app.innerHTML = '<div class="page"><div class="empty">در حال بارگذاری...</div></div>'; browse(S.ls); return; }
  const b = S.browse;
  const rows = (b.parent ? `<div class="fr" data-open="${esc(b.parent)}"><span class="ic">↰</span><span class="nm">..</span></div>` : '') +
    b.dirs.map((d) => `<div class="fr ${d.git ? 'git' : ''}" data-open="${esc(b.path.replace(/\/$/, '') + '/' + d.name)}"><span class="ic">${d.git ? '⎇' : '▤'}</span><span class="nm">${esc(d.name)}</span>${d.git ? '<span class="tag">git</span>' : ''}</div>`).join('') +
    b.files.slice(0, 80).map((f) => `<div class="fr file"><span class="ic">·</span><span class="nm">${esc(f.name)}</span></div>`).join('');
  app.innerHTML = `<div class="page">
    <h1>فایل‌ها</h1><p class="lead">پوشه‌ی پروژه یا ریپو رو پیدا کن و انتخاب کن.</p>
    <div class="pathbar"><button class="icbtn" id="up">↑</button><input type="text" id="pathIn" value="${esc(b.path)}" spellcheck="false"><button class="icbtn" id="go">↵</button></div>
    <div class="row wrap" style="margin-bottom:10px">
      <button class="link" data-q="/storage/emulated/0">حافظه داخلی</button>
      <button class="link" data-q="/storage/emulated/0/Download">Download</button>
      <button class="link" data-q="/data/data/com.termux/files/home">Termux</button></div>
    <div class="flist">${rows || '<div class="empty">پوشه خالی است</div>'}</div>
    <button class="btn" id="pick">انتخاب این پوشه${b.git ? ' (ریپوی git)' : ''}</button>
    ${S.folder ? `<div class="card selcard" style="margin-top:14px"><h3>پوشه‌ی انتخاب‌شده</h3><div class="selpath">${esc(S.folder.path)}</div>
      <div class="grid2"><button class="btn" id="aPush">آپلود به ریپو</button><button class="btn ghost" id="aLinks">اصلاح لینک‌ها</button></div></div>` : ''}
  </div>`;
  app.querySelectorAll('[data-open]').forEach((e) => e.addEventListener('click', () => browse(e.dataset.open)));
  app.querySelectorAll('[data-q]').forEach((e) => e.addEventListener('click', () => browse(e.dataset.q)));
  $('#up').addEventListener('click', () => b.parent && browse(b.parent));
  $('#go').addEventListener('click', () => browse($('#pathIn').value.trim()));
  $('#pathIn').addEventListener('keydown', (e) => e.key === 'Enter' && browse(e.target.value.trim()));
  $('#pick').addEventListener('click', () => { S.folder = { path: b.path, git: b.git }; toast('پوشه انتخاب شد'); renderFiles(app); });
  if (S.folder) { $('#aPush').addEventListener('click', pushSheet); $('#aLinks').addEventListener('click', linksSheet); }
}

function pushSheet() {
  const base = S.folder.path.replace(/\/$/, '').split('/').pop().replace(/[^A-Za-z0-9._-]/g, '-');
  const dst = S.cfg && S.cfg.dst && S.cfg.dst.login;
  openSheet(`<h2>آپلود پوشه به ریپو</h2>
    <div class="selpath">${esc(S.folder.path)}</div>
    ${dst ? '' : '<div class="note">اول حساب مقصد رو توی تب «مخزن‌ها» وصل کن.</div>'}
    <label class="f">نام ریپو در اکانت ${dst ? '@' + esc(dst) : 'مقصد'}</label><input type="text" id="pName" class="mono" value="${esc(base)}">
    <label class="f">برنچ</label><input type="text" id="pBranch" class="mono" value="main">
    <label class="f">پیام کامیت</label><input type="text" id="pMsg" class="mono" value="Upload via Git Migrator">
    <label class="f">روش</label>
    <select id="pMode"><option value="snapshot">فایل‌ها (یک کامیت جدید روی برنچ)</option>${S.folder.git ? '<option value="history">با تاریخچه (همه‌ی برنچ‌ها و تگ‌ها)</option>' : ''}</select>
    <label class="check"><input type="checkbox" id="pPriv"><span>اگه ریپو ساخته می‌شه private باشه</span></label>
    <button class="btn" id="pGo">شروع</button>`);
  $('#pGo').addEventListener('click', async () => {
    const params = { folder: S.folder.path, name: $('#pName').value.trim(), branch: $('#pBranch').value.trim(), message: $('#pMsg').value.trim(), mode: $('#pMode').value, priv: $('#pPriv').checked };
    closeSheet(); startJob('push_folder', params, 'آپلود پوشه');
  });
}

function linksSheet() {
  const lastOld = localStorage.getItem('gm_old') || '', lastNew = (S.cfg && S.cfg.dst && S.cfg.dst.login) || localStorage.getItem('gm_new') || '';
  openSheet(`<h2>اصلاح لینک‌های اکانت قدیمی</h2>
    <div class="selpath">${esc(S.folder.path)}</div>
    <div class="grid2"><div><label class="f">اکانت قدیمی</label><input type="text" id="lOld" class="mono" value="${esc(lastOld)}" placeholder="old-user"></div>
    <div><label class="f">اکانت جدید</label><input type="text" id="lNew" class="mono" value="${esc(lastNew)}" placeholder="new-user"></div></div>
    <label class="f">تغییر نام ریپوها (اختیاری، هر خط: قدیمی=جدید)</label><textarea id="lMap" class="mono" placeholder="old-repo=new-repo"></textarea>
    <label class="check"><input type="checkbox" id="lAll"><span>همه‌ی اشاره‌ها (نه فقط لینک‌ها) عوض بشن</span></label>
    <label class="check"><input type="checkbox" id="lCommit" checked><span>بعد از اعمال، توی هر ریپوی git کامیت کن</span></label>
    <button class="btn ghost" id="lPrev">پیش‌نمایش</button><div id="lOut" style="margin-top:12px"></div>`);
  const args = (apply) => ({ path: S.folder.path, old: $('#lOld').value, new: $('#lNew').value, map: $('#lMap').value, all: $('#lAll').checked, commit: $('#lCommit').checked, apply });
  $('#lPrev').addEventListener('click', async () => {
    localStorage.setItem('gm_old', $('#lOld').value); localStorage.setItem('gm_new', $('#lNew').value);
    $('#lOut').innerHTML = '<div class="empty">در حال اسکن...</div>';
    const r = await call('linkfix', args(false));
    if (!r.ok) { $('#lOut').innerHTML = `<div class="msg err">${esc(r.error)}</div>`; return; }
    $('#lOut').innerHTML = `<div class="sum ${r.total ? '' : 'bad'}">${r.total} جایگزینی در ${r.files.length} فایل</div>` +
      (r.files.length ? `<div class="res" style="margin-top:10px">${r.files.map((f) => `<div><span class="c">${f.count}</span> ${esc(f.path)}</div>`).join('')}</div>` : '') +
      (r.leftovers.length ? `<p class="lead" style="margin:10px 0 6px">هنوز اسم قدیمی توی این خط‌ها هست (لینک نیستن، دست نخوردن):</p><div class="res">${r.leftovers.slice(0, 25).map((l) => `<div><span class="m">${esc(l.path)}:${l.line}</span> ${esc(l.text)}</div>`).join('')}</div>` : '') +
      (r.total ? '<button class="btn" id="lApply">اعمال تغییرات</button>' : '');
    const ap = $('#lApply');
    if (ap) ap.addEventListener('click', async () => {
      if (!confirm('تغییرات روی فایل‌ها نوشته می‌شه. ادامه؟')) return;
      ap.disabled = true; const x = await call('linkfix', args(true));
      $('#lOut').innerHTML = x.ok ? `<div class="sum">✓ ${x.total} جایگزینی اعمال شد${x.committed.length ? ` — ${x.committed.filter((k) => k.ok).length} کامیت ساخته شد` : ''}</div>` : `<div class="msg err">${esc(x.error)}</div>`;
    });
  });
}

// ----- repos -----
async function loadMirrors() { const r = await call('mirrors'); S.mirrors = r.ok ? r.mirrors : []; }
async function renderRepos(app) {
  const c = S.cfg || {};
  app.innerHTML = `<div class="page"><h1>مخزن‌ها</h1><p class="lead">حساب‌ها، بکاپ کامل و انتقال با همه‌ی برنچ‌ها و تاریخچه.</p>
    <div class="card"><h3>حساب‌ها</h3><p class="sub">توکن classic با دسترسی <code>repo</code> و <code>workflow</code>. مبدأ فقط برای بکاپ مستقیم از اکانت قدیمی لازمه.</p>
      <label class="f">مقصد (اکانت جدید) ${c.dst && c.dst.login ? '— @' + esc(c.dst.login) : ''}</label>
      <div class="row"><input type="password" id="tDst" class="mono" placeholder="ghp_..." style="margin:0"><button class="btn sm" id="bDst">اتصال</button></div>
      <label class="f" style="margin-top:12px">مبدأ (اکانت قدیمی) ${c.src && c.src.login ? '— @' + esc(c.src.login) : ''}</label>
      <div class="row"><input type="password" id="tSrc" class="mono" placeholder="ghp_..." style="margin:0"><button class="btn sm" id="bSrc">اتصال</button></div>
      <div class="msg" id="accMsg"></div></div>
    <div class="card"><h3>بکاپ کامل</h3><p class="sub">همه‌ی ریپوهای اکانت مبدأ (کد، برنچ‌ها، تگ‌ها، ویکی) رو mirror می‌کنه. اجرای دوباره فقط آپدیت می‌کنه.</p>
      <label class="check"><input type="checkbox" id="oForks" checked><span>ریپوهای fork هم باشن</span></label>
      <div class="grid2"><button class="btn" id="bBackup">شروع بکاپ</button><button class="btn ghost" id="bVerify">بررسی سلامت</button></div></div>
    <div class="card"><h3>انتقال به اکانت جدید</h3>
      <label class="check"><input type="checkbox" id="oPriv"><span>ریپوهای جدید private باشن</span></label>
      <label class="f">فاصله بین ریپوها (ثانیه)</label><input type="text" id="oDelay" class="mono" value="30" inputmode="numeric">
      <div class="note">فاصله‌ی زیاد خطر فلگ‌شدن دوباره‌ی اکانت جدید رو کم می‌کنه. ریپوی موجود با همین محتوا جایگزین می‌شه.</div>
      <div class="row" style="justify-content:space-between;margin-bottom:8px"><b style="font-size:13.5px">بکاپ‌های موجود</b>
        <span><button class="link" id="sAll">همه</button><button class="link" id="sNone">هیچ</button><button class="link" id="sReload">⟳</button></span></div>
      <div id="mList"><div class="empty">در حال بارگذاری...</div></div>
      <button class="btn" id="bMigrate" style="margin-top:6px">انتقال انتخاب‌شده‌ها</button></div>
    <div class="card"><h3>مرجع تاریخچه</h3><p class="sub">برای هر پروژه <code>HISTORY.txt</code> و فایل <code>.bundle</code> می‌سازه (یک کپی توی GitHubBackup حافظه‌ی گوشی).</p>
      <div id="xList"></div><div class="msg" id="xMsg"></div></div>
    <div class="card"><h3>پوشه‌ی بکاپ</h3><input type="text" id="dirIn" class="mono" value="${esc(c.dir || '')}"><button class="btn ghost" id="bDir">ذخیره‌ی مسیر</button></div>
  </div>`;
  const acc = async (role) => {
    const inp = $(role === 'src' ? '#tSrc' : '#tDst'); const token = inp.value.trim(); const m = $('#accMsg');
    if (!token) { m.textContent = 'توکن رو وارد کن.'; m.className = 'msg err'; return; }
    m.textContent = '...'; m.className = 'msg';
    const r = await call('account', { role, token });
    m.textContent = r.ok ? '✓ متصل شد: @' + r.login : '✗ ' + r.error; m.className = 'msg ' + (r.ok ? 'ok' : 'err');
    if (r.ok) { inp.value = ''; await loadCfg(); }
  };
  $('#bDst').addEventListener('click', () => acc('dst')); $('#bSrc').addEventListener('click', () => acc('src'));
  $('#bBackup').addEventListener('click', () => startJob('backup', { forks: $('#oForks').checked }, 'بکاپ از GitHub'));
  $('#bVerify').addEventListener('click', () => startJob('verify', {}, 'بررسی سلامت'));
  $('#bDir').addEventListener('click', async () => { const r = await call('setdir', { dir: $('#dirIn').value }); toast(r.ok ? 'ذخیره شد' : r.error); if (r.ok) { await loadCfg(); await loadMirrors(); drawMirrors(); } });
  $('#sAll').addEventListener('click', () => setAll(true)); $('#sNone').addEventListener('click', () => setAll(false));
  $('#sReload').addEventListener('click', async () => { await loadMirrors(); drawMirrors(); });
  $('#bMigrate').addEventListener('click', () => {
    const items = [...document.querySelectorAll('#mList .mrow')].filter((r) => r.querySelector('.pk').checked).map((r) => ({ file: S.mirrors[r.dataset.i].file, name: r.querySelector('.tn').value.trim() }));
    if (!items.length) return toast('حداقل یک پروژه انتخاب کن');
    const bad = items.find((i) => !/^[A-Za-z0-9._-]+$/.test(i.name));
    if (bad) return toast('نام ریپو نامعتبر: ' + bad.name);
    if (!confirm(`${items.length} پروژه به اکانت مقصد منتقل می‌شه. ریپوهای موجود جایگزین می‌شن. ادامه؟`)) return;
    startJob('migrate', { items, priv: $('#oPriv').checked, delay: Number($('#oDelay').value) || 0 }, 'انتقال به اکانت جدید');
  });
  await loadMirrors(); drawMirrors();
}
function setAll(v) { document.querySelectorAll('#mList .pk').forEach((c) => { c.checked = v; c.closest('.mrow').classList.toggle('sel', v); }); }
function drawMirrors() {
  const box = $('#mList'); if (!box) return;
  box.innerHTML = S.mirrors.length ? S.mirrors.map((m, i) => `<div class="mrow" data-i="${i}"><div class="mtop"><input type="checkbox" class="pk"><span class="mname">${esc(m.file.slice(0, -4))}</span></div>
    <div class="stats"><span class="stat">${m.branches} برنچ</span><span class="stat">${m.tags} تگ</span><span class="stat">${m.commits} کامیت</span>${m.head ? `<span class="stat">HEAD: ${esc(m.head)}</span>` : ''}${m.last ? `<span class="stat">${esc(m.last)}</span>` : ''}</div>
    <input type="text" class="tn mono" value="${esc(m.name)}" spellcheck="false"></div>`).join('')
    : '<div class="empty">بکاپی نیست. اول «شروع بکاپ» رو بزن.</div>';
  box.querySelectorAll('.pk').forEach((c) => c.addEventListener('change', () => c.closest('.mrow').classList.toggle('sel', c.checked)));
  const x = $('#xList');
  if (x) { x.innerHTML = S.mirrors.length ? S.mirrors.map((m, i) => `<div class="row" style="padding:6px 0"><span class="mname grow">${esc(m.file.slice(0, -4))}</span><button class="btn ghost sm" data-x="${i}">ساخت</button></div>`).join('') : '<div class="empty">بکاپی نیست.</div>';
    x.querySelectorAll('[data-x]').forEach((b) => b.addEventListener('click', async () => { b.disabled = true; const r = await call('export', { file: S.mirrors[b.dataset.x].file }); $('#xMsg').textContent = r.ok ? '✓ ' + r.paths.join('  |  ') : '✗ ' + r.error; $('#xMsg').className = 'msg ' + (r.ok ? 'ok' : 'err'); b.disabled = false; })); }
}

// ----- AI assistant -----
function renderAI(app) {
  const has = S.cfg && S.cfg.ai && S.cfg.ai.has_key;
  app.innerHTML = `<div class="page"><h1>دستیار</h1><p class="lead">خطاها رو توضیح می‌ده و قدم بعدی رو پیشنهاد می‌کنه. خودش چیزی اجرا نمی‌کنه.</p>
    ${has ? '' : `<div class="card"><h3>تنظیم دستیار</h3><p class="sub">این بخش از API شرکت Anthropic با کلید خودت کار می‌کنه (جدا از اشتراک اپ Claude حساب می‌شه). کلید فقط روی همین گوشی ذخیره می‌شه.</p>
      <input type="password" id="aiKey" class="mono" placeholder="sk-ant-..."><input type="text" id="aiModel" class="mono" value="${esc((S.cfg && S.cfg.ai && S.cfg.ai.model) || 'claude-sonnet-5-5')}"><button class="btn" id="aiSave">ذخیره</button></div>`}
    <div class="quick">${['چرا آخرین عملیات خطا داد؟', 'ترتیب انتقال امن چیه؟', 'توکن چه دسترسی‌هایی لازم داره؟'].map((q) => `<button class="q">${q}</button>`).join('')}</div>
    <div class="chat" id="chat">${S.chat.map((m) => `<div class="bub ${m.role === 'user' ? 'u' : 'a'}">${esc(m.content)}</div>`).join('') || '<div class="empty">سؤالت رو بپرس.</div>'}</div>
    <div class="chatin"><textarea id="aiIn" placeholder="پیام..."></textarea><button class="btn" id="aiSend">➤</button></div>
    <div class="row" style="justify-content:space-between;margin-top:10px"><button class="link" id="aiClear">پاک کردن گفتگو</button>${has ? '<button class="link" id="aiKeyDel">حذف کلید</button>' : ''}</div></div>`;
  const send = async (text) => {
    if (!text.trim()) return;
    S.chat.push({ role: 'user', content: text }); S.chat.push({ role: 'assistant', content: '...' }); saveChat(); renderAI(app);
    const ctx = [S.folder ? 'پوشه‌ی انتخاب‌شده: ' + S.folder.path : '', S.lastLog ? 'لاگ آخرین عملیات:\n' + S.lastLog : ''].filter(Boolean).join('\n');
    const r = await call('ai', { messages: S.chat.slice(0, -1), context: ctx });
    S.chat[S.chat.length - 1].content = r.ok ? r.text : '✗ ' + r.error; saveChat(); renderAI(app);
    const c = $('#chat'); if (c) c.lastElementChild.scrollIntoView({ block: 'end' });
  };
  $('#aiSend').addEventListener('click', () => { const t = $('#aiIn').value; send(t); });
  app.querySelectorAll('.q').forEach((q) => q.addEventListener('click', () => send(q.textContent)));
  $('#aiClear').addEventListener('click', () => { S.chat = []; saveChat(); renderAI(app); });
  const sv = $('#aiSave'); if (sv) sv.addEventListener('click', async () => { const r = await call('setai', { key: $('#aiKey').value, model: $('#aiModel').value }); toast(r.ok ? 'ذخیره شد' : r.error); await loadCfg(); renderAI(app); });
  const kd = $('#aiKeyDel'); if (kd) kd.addEventListener('click', async () => { await call('setai', { clear: true }); await loadCfg(); renderAI(app); });
}
function saveChat() { try { localStorage.setItem('gm_chat', JSON.stringify(S.chat.slice(-30))); } catch {} }

// ---------- jobs ----------
let poll = null;
async function startJob(type, params, title) {
  const r = await call('job_start', { type, params });
  if (!r.ok && !r.id) return toast(r.error || 'خطا');
  openJob(r.id, title);
}
function jobHTML(title) {
  return `<h2>${esc(title)}</h2><div class="bar"><div class="fill" id="jFill"></div></div><div class="jitems" id="jItems"></div><div class="log" id="jLog"></div><div class="sum" id="jSum" hidden></div>
    <div class="row" style="margin-top:12px"><button class="btn danger sm grow" id="jCancel">توقف</button><button class="btn ghost sm grow" id="jHide">بستن</button><button class="btn ghost sm grow" id="jAsk">پرسش از دستیار</button></div>`;
}
function openJob(id, title) {
  clearInterval(poll);
  S.job = { id, title, next: 0, total: 0, done: 0, items: {}, logs: [], finished: false };
  openSheet(jobHTML(title)); $('#jobbar').hidden = true;
  $('#jHide').addEventListener('click', () => { closeSheet(); if (!S.job.finished) showBar(); });
  $('#jCancel').addEventListener('click', async () => { await call('job_cancel', { id }); toast('درخواست توقف ارسال شد'); });
  $('#jAsk').addEventListener('click', () => { closeSheet(); setPage('ai'); });
  const tick = async () => {
    const r = await call('job_events', { id, since: S.job.next });
    if (!r.ok) { clearInterval(poll); return; }
    S.job.next = r.next; r.events.forEach(applyEvent);
    if (r.done) { clearInterval(poll); S.job.finished = true; const cb = $('#jCancel'); if (cb) cb.hidden = true; $('#jobbar').hidden = true; if (S.page === 'repos') renderRepos($('#app')); }
  };
  tick(); poll = setInterval(tick, 1500);
}
function showBar() { if (S.job && S.job.finished) return; $('#jobbar').hidden = false; $('#jobbarText').textContent = S.job.title + ' — در حال اجرا'; }
$('#jobbar').addEventListener('click', () => { if (S.job) { openSheet(jobHTML(S.job.title)); rebuildJob(); } });
function rebuildJob() {
  const j = S.job; $('#jHide').addEventListener('click', () => { closeSheet(); if (!j.finished) showBar(); });
  $('#jCancel').addEventListener('click', async () => { await call('job_cancel', { id: j.id }); toast('درخواست توقف ارسال شد'); });
  $('#jAsk').addEventListener('click', () => { closeSheet(); setPage('ai'); });
  $('#jItems').innerHTML = Object.values(j.items).map(itemHTML).join(''); $('#jLog').innerHTML = j.logs.map((l) => `<div>${esc(l)}</div>`).join('');
  $('#jFill').style.width = (j.total ? j.done / j.total * 100 : 0) + '%'; if (j.finished) $('#jCancel').hidden = true;
}
function itemHTML(it) { return `<div class="ji ${it.status}" data-k="${esc(it.key)}"><i class="jd"></i><div><div class="jl">${esc(it.label)}</div><div class="jn">${esc(it.note || '')}</div></div></div>`; }
function applyEvent(ev) {
  const j = S.job, ui = !$('#sheetWrap').hidden && $('#jItems');
  if (ev.type === 'plan') { j.total = ev.items.length; j.items = {}; ev.items.forEach((i) => (j.items[i.key] = { key: i.key, label: i.label, status: '', note: '' })); if (ui) $('#jItems').innerHTML = Object.values(j.items).map(itemHTML).join(''); }
  else if (ev.type === 'item') {
    const it = j.items[ev.key]; if (!it) return; it.status = ev.status; if (ev.note != null) it.note = ev.note;
    if (ev.status === 'ok' || ev.status === 'fail') j.done = Object.values(j.items).filter((x) => x.status === 'ok' || x.status === 'fail').length;
    if (ui) { const el = [...document.querySelectorAll('.ji')].find((x) => x.dataset.k === ev.key); if (el) el.outerHTML = itemHTML(it); $('#jFill').style.width = (j.total ? j.done / j.total * 100 : 0) + '%'; }
  } else if (ev.type === 'log') { j.logs.push(ev.text); if (ui) { const d = document.createElement('div'); d.textContent = ev.text; $('#jLog').appendChild(d); } }
  else if (ev.type === 'error') { j.logs.push('✗ ' + ev.text); S.lastLog = j.logs.join('\n'); if (ui) { const s = $('#jSum'); s.hidden = false; s.className = 'sum bad'; s.textContent = '✗ ' + ev.text; } }
  else if (ev.type === 'summary') { S.lastLog = `${j.title}: موفق ${ev.ok}، ناموفق ${ev.fail}\n` + Object.values(j.items).filter((x) => x.status === 'fail').map((x) => `${x.label}: ${x.note}`).join('\n'); if (ui) { const s = $('#jSum'); s.hidden = false; s.className = 'sum' + (ev.fail ? ' bad' : ''); s.textContent = `✓ موفق: ${ev.ok}   ✗ ناموفق: ${ev.fail}`; } }
}

// ---------- init ----------
(async function init() {
  await loadCfg(); render();
  const cur = await call('job_current');
  if (cur && cur.ok && cur.id && cur.running) { S.job = { id: cur.id, title: 'عملیات', next: 0, total: 0, done: 0, items: {}, logs: [], finished: false }; openJob(cur.id, 'عملیات در حال اجرا'); closeSheet(); showBar(); }
})();
