"""Locator-aligned text comparison. Keeps document geometry untouched."""
import uuid
import shutil
import threading
from pathlib import Path
from .glossary import store
from .extract import extract

RECORD_LOCK = threading.RLock()


def folder():
    return store.data_dir() / 'comparisons'


def create(segments, paragraphs, source, output):
    comparison_id = uuid.uuid4().hex
    rows = []
    for segment in segments:
        paragraph = paragraphs.get(segment.locator)
        rows.append({'locator':segment.locator, 'slide':segment.slide, 'para':segment.para,
            'source':segment.text, 'translation':paragraph.text if paragraph is not None else segment.text,
            'editable':segment.editable, 'note':segment.not_editable_reason})
    value = {'id':comparison_id, 'source_name':Path(source).name, 'output_name':Path(output).name,
        'output_path':str(output), 'output_hash':store.fingerprint(output), 'rows':rows,
        '_source_path':str(Path(source).absolute()), '_source_hash':store.fingerprint(source)}
    snapshot_source(value,source)
    store.atomic_json(folder() / (comparison_id + '.json'), value)
    return comparison_id


def snapshot_source(value,source):
    """A private immutable original supports page comparison after moving the input."""
    source=Path(source)
    from .formats import SUPPORTED
    if source.suffix.lower() not in SUPPORTED: raise ValueError('不支持此文档格式。')
    target=folder()/value['id']/('source'+source.suffix.lower())
    target.parent.mkdir(parents=True,exist_ok=True)
    before=store.fingerprint(source)
    shutil.copyfile(source,target)
    if store.fingerprint(target)!=before or store.fingerprint(source)!=before:
        target.unlink(missing_ok=True)
        raise ValueError('原稿在读取期间发生变化，请重新生成对照。')
    value.update(_source_path=str(source.absolute()),_source_hash=before,_source_snapshot=str(target))
    return target


def source_for_preview(value):
    target=folder()/value['id']/('source'+Path(value['source_name']).suffix.lower())
    if target.is_file(): return target
    candidates=[]
    if value.get('_source_path'): candidates.append(value['_source_path'])
    else:
        # Migrate 1.9.0 text-only records using the existing task's original path.
        import json
        from . import history
        with history.connection() as db:
            for raw, in db.execute('SELECT payload FROM tasks ORDER BY started DESC'):
                row=json.loads(raw)
                if any(o.get('comparison_id')==value['id'] for o in row.get('outputs',[])):
                    candidates.extend(p for p in row.get('paths',[]) if Path(p).name==value['source_name'])
    candidates=list(dict.fromkeys(p for p in candidates if Path(p).is_file()))
    if len(candidates)!=1: raise ValueError('这份旧对照没有可用的原稿。文字对照仍可查看；重新翻译后将保留完整原稿。')
    if value.get('_source_hash') and store.fingerprint(candidates[0])!=value['_source_hash']:
        raise ValueError('原稿已被外部修改，不能冒充翻译时的原稿。文字对照仍可查看。')
    target=snapshot_source(value,candidates[0])
    with RECORD_LOCK:
        latest=read(value['id'])
        latest.update({k:v for k,v in value.items() if k.startswith('_')})
        store.atomic_json(folder()/(value['id']+'.json'),latest)
    return target


def remove(comparison_id):
    read(comparison_id)  # validate the opaque ID before touching its directory
    target=folder()/comparison_id
    if target.exists(): shutil.rmtree(target)
    (folder()/(comparison_id+'.json')).unlink(missing_ok=True)


def safe_create(*args):
    try: return create(*args)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Could not save text comparison; translated document is retained')
        return None


def read(comparison_id):
    if not isinstance(comparison_id, str) or len(comparison_id) != 32 or any(c not in '0123456789abcdef' for c in comparison_id):
        raise ValueError('对照记录不存在')
    import json
    path = folder() / (comparison_id + '.json')
    if not path.is_file(): raise ValueError('对照记录不存在')
    value = json.loads(path.read_text(encoding='utf-8'))
    output = Path(value['output_path'])
    value['output_changed'] = not output.is_file() or store.fingerprint(output) != value['output_hash']
    return value


def update(comparison_id, output):
    translated = {segment.locator:segment.text for segment in extract(str(output))}
    with RECORD_LOCK:
        value = read(comparison_id)
        for row in value['rows']:
            if row['locator'] in translated: row['translation'] = translated[row['locator']]
        value.update(output_name=Path(output).name, output_path=str(output), output_hash=store.fingerprint(output), output_changed=False)
        store.atomic_json(folder() / (comparison_id + '.json'), value)
