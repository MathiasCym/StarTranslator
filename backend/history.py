"""Local task metadata, retained across restarts without storing document text."""
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from uuid import uuid4
from .glossary.store import data_dir

RESUME_FIELDS = ('kind','paths','references','pairs','glossary_imports','output_dir',
                 'translation_mode','combined_output','use_llm','workers','direction')


@contextmanager
def connection():
    folder = data_dir(); folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'task-history.sqlite3', timeout=20)
    db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, started REAL NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS task_date ON tasks(started DESC)')
    try:
        with db: yield db
    finally: db.close()


def begin(job_id, data, status='running'):
    stamp = time.time()
    row = {'id': job_id, 'kind': data['kind'], 'status': status, 'started_at': datetime.fromtimestamp(stamp).astimezone().isoformat(),
           'finished_at': '', 'paths': list(dict.fromkeys(data.get('paths', []))),
           'output_dir': data.get('output_dir') or '', 'translation_mode':data.get('translation_mode','faithful'), 'outputs': [], 'errors': [], 'counts': {}}
    row['resume_options'] = {key:data[key] for key in RESUME_FIELDS if key in data}
    with connection() as db:
        db.execute('INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?)', (job_id, stamp, row['kind'], row['status'], json.dumps(row, ensure_ascii=False)))
        if status == 'running':
            queued = db.execute("SELECT payload FROM tasks WHERE id=? AND status='queued'",(job_id,)).fetchone()
            if queued:
                row = json.loads(queued[0]); row['status'] = 'running'; row['kind']=data['kind']
                row['resume_options']={key:data[key] for key in RESUME_FIELDS if key in data}
                db.execute('UPDATE tasks SET kind=?,status=?,payload=? WHERE id=?',(row['kind'],'running',json.dumps(row,ensure_ascii=False),job_id))
    return row


def finish(job, data):
    begin(job['id'], data)
    with connection() as db:
        raw = db.execute('SELECT payload FROM tasks WHERE id=?', (job['id'],)).fetchone()
        row = json.loads(raw[0]); result = job.get('result') or {}
        outputs = result.get('outputs') or []
        row.update(status=job['status'], finished_at=datetime.now().astimezone().isoformat(),
                   errors=[*result.get('errors', []), *([{'error': job['error']}] if job.get('error') else []),
                           *[error for item in row.get('exports', []) for error in item.get('errors', [])]],
                   counts={**result.get('stats', {}), 'translated': sum(item.get('translated', 0) for item in outputs),
                           'resumed_translation':sum(item.get('resumed_segments',0) for item in outputs),
                           'needs_review': sum(item.get('needs_review', 0) for item in outputs),
                           'replaced': sum(item.get('corrected', 0) for item in outputs) + sum(item.get('replaced', 0) for item in row.get('exports', []))})
        if 'can_resume' in job: row['can_resume'] = job['can_resume']
        row['outputs'] = unique_outputs([*({'path': item['path'], 'source': item.get('source', ''), 'comparison_id':item.get('comparison_id')} for item in outputs if not item.get('staged')), *row.get('outputs', [])])
        exported_sources = {item['source'] for item in row.get('exports',[])}
        row['drafts'] = [{'path':item['path'],'source':item['source']} for item in outputs if item.get('staged') and item['source'] not in exported_sources]
        row['awaiting_confirmation'] = bool(row['drafts'])
        row['processing_status'] = job['status']
        processing = row['counts'].get('review_processing_status', row['counts'].get('model_status'))
        if row['status'] == 'complete' and (row['errors'] or processing in ('partial', 'unavailable', 'cancelled','not_started')):
            row['status'] = 'partial'
        # Stats can contain explanatory text; keep history metadata compact.
        row['counts'] = {k: v for k, v in row['counts'].items() if isinstance(v, (int, float, str))}
        db.execute('UPDATE tasks SET status=?,payload=? WHERE id=?', (row['status'], json.dumps(row, ensure_ascii=False), job['id']))


def exported(report_id, source, output, count, failed, overwrite, comparison_id=None):
    stamp = time.time()
    event = {'id': uuid4().hex, 'at': datetime.fromtimestamp(stamp).astimezone().isoformat(),
             'source': source, 'path': output, 'replaced': count, 'errors': failed, 'overwrite': overwrite, 'comparison_id':comparison_id}
    with connection() as db:
        merge_export(db, report_id, event, stamp)


def unique_outputs(outputs):
    # Windows paths can differ in casing or slash style across old releases.
    import ntpath
    by_path = {}
    for item in outputs:
        if item.get('path'): by_path[ntpath.normcase(ntpath.normpath(item['path']))] = item
    return list(by_path.values())


def merge_export(db, report_id, event, stamp):
    raw = db.execute('SELECT payload FROM tasks WHERE id=?', (report_id,)).fetchone()
    if raw:
        row = json.loads(raw[0])
    else:
        # Retain exports whose older parent record is missing without claiming
        # that a model review completed or recreating a separate export task.
        row = {'id':report_id, 'kind':'check', 'status':'partial' if event['errors'] else 'complete',
               'started_at':event['at'], 'finished_at':event['at'], 'paths':[event['source']],
               'output_dir':'', 'outputs':[], 'errors':[], 'counts':{}, 'review_metadata_missing':True}
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', (report_id, stamp, 'check', row['status'], json.dumps(row, ensure_ascii=False)))
    events = row.setdefault('exports', [])
    if any(item['id'] == event['id'] for item in events): return
    events.append(event)
    row['drafts'] = [item for item in row.get('drafts',[]) if item['source'] != event['source']]
    row['awaiting_confirmation'] = bool(row['drafts'])
    if row.get('review_metadata_missing') and event['source'] not in row['paths']:
        row['paths'].append(event['source'])
    row['outputs'] = unique_outputs([*row.get('outputs', []), {'path':event['path'], 'source':event['source'], 'comparison_id':event.get('comparison_id')}])
    row['counts']['replaced'] = row['counts'].get('replaced', 0) + event['replaced']
    row['last_output_at'] = max(item['at'] for item in events)
    row['errors'].extend(event['errors'])
    if event['errors'] and row['status'] == 'complete': row['status'] = 'partial'
    db.execute('UPDATE tasks SET status=?,payload=? WHERE id=?', (row['status'], json.dumps(row, ensure_ascii=False), report_id))


def merge_legacy_exports(db):
    for ident, stamp, raw in db.execute("SELECT id,started,payload FROM tasks WHERE kind='export' ORDER BY started,id").fetchall():
        row = json.loads(raw)
        parent = row.get('report_id') or ('review-' + ident)
        for index, output in enumerate(row.get('outputs', [])):
            event = {'id':ident + ':' + str(index), 'at':row.get('finished_at') or row['started_at'],
                     'source':output.get('source') or next(iter(row.get('paths', [])), ''), 'path':output['path'],
                     'replaced':row.get('counts', {}).get('replaced', 0) if index == 0 else 0,
                     'errors':row.get('errors', []) if index == 0 else [], 'overwrite':row.get('overwrite', False)}
            merge_export(db, parent, event, stamp)
        db.execute('DELETE FROM tasks WHERE id=?', (ident,))


def query(preset='all', start='', end='', kind='', text='', page=0, active_ids=()):
    today = date.today()
    if preset == 'today': start = end = today.isoformat()
    elif preset == 'month': start, end = today.replace(day=1).isoformat(), today.isoformat()
    elif preset == 'year': start, end = today.replace(month=1, day=1).isoformat(), today.isoformat()
    elif preset not in ('all', 'custom'): raise ValueError('时间筛选条件不正确。')
    clauses, params = [], []
    try:
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
        if first and last and first > last: raise ValueError()
    except ValueError: raise ValueError('请选择有效的开始和结束日期，开始日期不能晚于结束日期。') from None
    if preset == 'custom' and (not first or not last): raise ValueError('请选择开始日期和结束日期。')
    if first: clauses.append('started>=?'); params.append(datetime.combine(first, datetime.min.time()).timestamp())
    if last: clauses.append('started<?'); params.append(datetime.combine(last + timedelta(days=1), datetime.min.time()).timestamp())
    if kind:
        if kind not in ('translate', 'check', 'translate_review', 'export'): raise ValueError('任务筛选条件不正确。')
        clauses.append('kind=?'); params.append('check' if kind == 'export' else kind)
    if text:
        clauses.append('payload LIKE ? ESCAPE \'\\\'')
        params.append('%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    try: page = max(0, int(page))
    except (ValueError, TypeError): raise ValueError('页码不正确。') from None
    with connection() as db:
        merge_legacy_exports(db)
        # A terminated process cannot finish its records. Detect those on read.
        for ident, raw in db.execute("SELECT id,payload FROM tasks WHERE status IN ('running','queued')").fetchall():
            if ident not in active_ids:
                row = json.loads(raw); row['status'] = 'interrupted'
                db.execute('UPDATE tasks SET status=?,payload=? WHERE id=?', ('interrupted', json.dumps(row, ensure_ascii=False), ident))
        total = db.execute('SELECT COUNT(*) FROM tasks' + where, params).fetchone()[0]
        page = min(page, max(0, (total - 1) // 30))
        rows = [json.loads(raw[0]) for raw in db.execute('SELECT payload FROM tasks' + where + ' ORDER BY started DESC,id DESC LIMIT 30 OFFSET ?', [*params, page * 30])]
    return {'records': [display_record(row) for row in rows], 'total': total, 'page': page, 'page_size': 30}


def display_record(row):
    """Correct legacy warning-only badges without rewriting the historical log.

    Never infer success merely from the existence of an output or a selection:
    old records need explicit completed processing and no resumable failure.
    New records retain the workflow's authoritative outcome.
    """
    counts = row.get('counts') or {}
    processing = counts.get('review_processing_status', counts.get('model_status'))
    if (row.get('status') == 'partial' and 'processing_status' not in row
            and row.get('can_resume') is False and processing == 'complete'
            and not row.get('errors') and not counts.get('errors') and not counts.get('truncated')
            and not counts.get('residual_chinese') and not counts.get('untranslated')):
        row = {**row, 'status':'complete'}
    return row


def resume_options(job_id):
    row = record(job_id)
    if not row.get('resume_options'): raise ValueError('该早期任务未保存恢复设置，请重新添加原文件；新版任务会自动保存断点。')
    return {key:value for key,value in row['resume_options'].items() if key in RESUME_FIELDS}


def record(job_id):
    with connection() as db:
        raw = db.execute('SELECT payload FROM tasks WHERE id=?',(job_id,)).fetchone()
    if not raw: raise ValueError('未找到该任务的本机历史记录。')
    return json.loads(raw[0])
