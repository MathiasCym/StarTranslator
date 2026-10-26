"""Apply explicit bundled additions once, retaining every existing local entry."""
import copy
import functools
import hashlib
import json
import os
import re
import threading
import unicodedata
from pathlib import Path
from . import store

ROOT = Path(__file__).resolve().parents[2] / 'glossary'
LOCK = threading.RLock()
ERRORS = {}


def key(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


@functools.lru_cache(maxsize=1)
def manifest():
    value = json.loads((ROOT/'bundled-updates.json').read_text('utf-8-sig'))
    if not isinstance(value,dict) or value.get('schema') != 1 or not isinstance(value.get('batches'), list):
        raise ValueError('随包词库的补全清单无效，请校验软件完整性。')
    seen = set()
    for batch in value['batches']:
        if not isinstance(batch,dict):
            raise ValueError('随包词库的补全批次无效，请校验软件完整性。')
        ident = batch.get('id', '')
        terms = batch.get('terms')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z0-9-]{1,80}', ident) or ident in seen or not isinstance(terms, list) or not terms or len(terms)>20000 or any(not isinstance(t,str) or not t.strip() for t in terms):
            raise ValueError('随包词库的补全批次无效，请校验软件完整性。')
        if len({key(t) for t in terms}) != len(terms):
            raise ValueError('随包词库的补全清单有重复术语。')
        seen.add(ident)
    return value['batches']


@functools.lru_cache(maxsize=1)
def catalog():
    result = {}
    for entry in store.validate(json.loads((ROOT/'team.json').read_text('utf-8-sig'))):
        result.setdefault(key(entry['zh']), []).append(entry)
    return result


def local(path):
    path = Path(path)
    folder = store.data_dir().resolve()
    return path.resolve() == folder/'lexicon.json' and not path.is_symlink()


def receipt(path, ident):
    return path.parent/('lexicon-bundled-'+ident+'.json')


def read_receipt(path, ident):
    target = receipt(path, ident)
    if not target.exists():
        return None
    value = json.loads(target.read_text('utf-8-sig'))
    if not isinstance(value, dict) or value.get('id') != ident or value.get('schema') != 1 or type(value.get('completed')) is not bool:
        raise ValueError('词库自动补全记录无法读取；当前词库仍保留，可手动导入随包词库。')
    return value


def backup(path, raw, ident):
    target = Path(str(path)+'.before-bundled-'+ident+'.bak')
    if target.exists() and target.read_bytes() != raw:
        target = Path(str(target)+'.'+hashlib.sha256(raw).hexdigest()[:16])
    if not target.exists():
        with target.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    if target.read_bytes() != raw:
        raise ValueError('原词库备份未能确认，自动补全尚未写入。')
    return target


def apply_batch(path, batch):
    ident = batch['id']
    previous = read_receipt(path, ident)
    if previous and previous['completed']:
        return
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    # Recover an interrupted receipt without repeating the successful write.
    if previous and previous.get('after_hash') == digest:
        store.atomic_json(receipt(path, ident), {**previous, 'completed': True})
        return
    entries = json.loads(raw.decode('utf-8-sig'))
    store.validate(entries)
    current = {}
    for entry in entries:
        current.setdefault(key(entry['zh']), []).append(entry)
    additions, conflicts = [], []
    for term in batch['terms']:
        candidates = catalog().get(key(term), [])
        if len(candidates) != 1:
            raise ValueError('随包词库的补全术语缺失或有多种译法，请校验软件完整性。')
        incoming = candidates[0]
        existing = current.get(key(term), [])
        if not existing:
            additions.append(copy.deepcopy(incoming))
            current[key(term)] = [incoming]
        elif not any(key(incoming['en']) in {key(e['en']), *(key(v) for v in e.get('variants', []))} for e in existing):
            conflicts.append({'zh':incoming['zh'], 'existing':[e['en'] for e in existing],
                'incoming':incoming['en'], 'reason':'已保留本机译法；自动补全不会覆盖个人修改。'})
    combined = entries + additions
    store.validate(combined)
    report = {'schema':1, 'id':ident, 'completed':False, 'added':len(additions),
        'before':len(entries), 'after':len(combined), 'conflicts':conflicts,
        'before_hash':digest, 'backup':''}
    if additions:
        report['backup'] = backup(path, raw, ident).name
        if store.fingerprint(path) != digest:
            raise store.Conflict('词库在自动补全期间被修改，已保留最新内容；稍后将重试。')
        # Journal first: a crash between the two replacements is recoverable.
        encoded = json.dumps(combined, ensure_ascii=False, indent=2).replace('\n',os.linesep).encode('utf-8')
        report['after_hash'] = hashlib.sha256(encoded).hexdigest()
        store.atomic_json(receipt(path, ident), report)
        if store.fingerprint(path) != digest:
            raise store.Conflict('词库在自动补全期间被修改，已保留最新内容；稍后将重试。')
        store.atomic_json(path, combined)
    store.atomic_json(receipt(path, ident), {**report, 'completed':True})


def upgrade_local(path):
    path = Path(path)
    if not local(path):
        return
    with LOCK:
        try:
            for batch in manifest():
                previous = read_receipt(path, batch['id'])
                if previous and previous['completed']:
                    continue
                with store.edit_lock(path):
                    apply_batch(path, batch)
            ERRORS.pop(str(path.resolve()), None)
        except (OSError, ValueError) as error:
            # A failed optional migration must not block valid-file production.
            ERRORS[str(path.resolve())] = str(error)


def status(path):
    path = Path(path)
    if not local(path):
        return None
    with LOCK:
        try:
            records = [read_receipt(path, b['id']) for b in manifest()]
            records = [r for r in records if r and r['completed']]
            result = {'added':sum(r['added'] for r in records),
                'conflicts':[c for r in records for c in r['conflicts']],
                'backups':[str(path.parent/r['backup']) for r in records if r.get('backup')]}
            error = ERRORS.get(str(path.resolve()))
            if error:
                result['error'] = error
            return result if result['added'] or result['conflicts'] or error else None
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {'added':0, 'conflicts':[], 'backups':[], 'error':str(error)}
