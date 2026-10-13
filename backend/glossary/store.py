"""Editable, attributed glossary with atomic writes and shared-folder conflicts."""
import contextlib
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .loader import Glossary, _load_any
from ..models import GlossaryEntry

FIELDS = set(GlossaryEntry.__dataclass_fields__)


class Conflict(ValueError):
    pass


class FileChanged(Conflict):
    """表格主词库在打开后被外部改动过，拒绝覆盖。"""


def data_dir():
    return Path(os.environ.get('NOVATERM_DATA_DIR') or Path.home() / '.startranslator')


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# 以表格文件（Excel/CSV）作为共享主词库时，读写走 writer 模块。
TABLE_SUFFIXES = ('.xlsx', '.xlsm', '.csv', '.tsv')


def is_table(path) -> bool:
    return Path(path).suffix.lower() in TABLE_SUFFIXES


def _entries_to_rows(entries, columns):
    """把词条按 columns 排成表格行；列表字段在格内用换行 join。"""
    from .writer import LIST_FIELDS
    rows = []
    for entry in entries:
        row = []
        for field in columns:
            value = entry.get(field, "") if field else ""
            if field in LIST_FIELDS:
                value = "\n".join(value) if isinstance(value, list) else (value or "")
            elif field == 'priority':
                value = str(value if value not in (None, "") else 2)
            else:
                value = "" if value is None else str(value)
            row.append(value)
        rows.append(row)
    return rows


def validate(entries):
    if not isinstance(entries, list) or len(entries) > 20000:
        raise ValueError('术语库应为列表，最多 20000 条。')
    result = []
    for i, raw in enumerate(entries, 1):
        if not isinstance(raw, dict):
            raise ValueError(f'第 {i} 条格式不正确')
        item = {k: v for k,v in raw.items() if k in FIELDS}
        for key in ('zh', 'en', 'note', 'source'):
            value = item.get(key, '')
            if not isinstance(value, str) or len(value) > 12000:
                raise ValueError(f'第 {i} 条的 {key} 内容不正确')
            item[key] = value.strip()
        if not item['zh'] or not item['en']:
            raise ValueError(f'第 {i} 条需填写中文和英文')
        if item.get('priority', 2) not in (1, 2, 3):
            raise ValueError(f'第 {i} 条确认状态不正确')
        for key in ('variants', 'machine_variants', 'wrong_variants'):
            values = item.get(key, [])
            if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v,str) or len(v)>300 for v in values):
                raise ValueError(f'第 {i} 条变体应为文本列表')
            item[key] = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        result.append(GlossaryEntry(**item).to_dict())
    return result


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextlib.contextmanager
def edit_lock(path):
    lock = str(path) + '.lock'
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        raise Conflict('术语库正在被另一位用户保存。请稍后刷新；若有遗留 .lock 文件，请联系维护者确认后清理。')
    try:
        os.close(fd)
        yield
    finally:
        os.unlink(lock)


def generated_forms(entry):
    """Surface variants aid retrieval, never establish that a phrase is wrong."""
    en = entry.en
    forms = list(entry.machine_variants)
    for variant in (en.replace('-', ' '), en.replace(' ', '-'),
                    en.replace('color', 'colour').replace('Color', 'Colour'),
                    en.replace('grayscale', 'grey scale').replace('Grayscale', 'Grey scale')):
        if variant.casefold() != en.casefold() and variant not in forms:
            forms.append(variant)
    return forms


def seed_entries():
    g = Glossary.load()
    from .loader import DEFAULT_PATH
    snapshot=Path(DEFAULT_PATH).parent/'team.json'
    if snapshot.exists():
        g=Glossary([GlossaryEntry(**entry) for entry in validate(json.loads(snapshot.read_text(encoding='utf-8-sig')))])
    known = {'点间距': ['dot spacing', 'point spacing', 'point distance'],
             '接收卡': ['receiving board card', 'reception card'],
             '发送卡': ['sending board card', 'transmission board card'],
             '逐点校正': ['point by point proofreading'],
             '刷新率': ['refreshing ratio'], '驱动IC': ['driving integrated circuit chip']}
    for e in g.entries:
        e.machine_variants = generated_forms(e)
        if e.priority == 1 and e.zh in known:
            # Deliberately keep acceptable aliases out of the confirmed list.
            aliases = {v.casefold() for v in e.variants}
            e.wrong_variants = [v for v in known[e.zh] if v.casefold() not in aliases]
            e.note += '\n规则种子：LED 技术语境下的常见非标准机翻，请按团队规范维护。'
    from .audit import merge
    return merge([e.to_dict() for e in g.entries])[0]


def active_path():
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    settings = folder / 'lexicon-settings.json'
    if settings.exists():
        selected = json.loads(settings.read_text(encoding='utf-8')).get('path')
        if selected:
            if not Path(selected).is_file():
                raise ValueError('共享术语库不可访问，请连接共享目录或切回本机词库。')
            return Path(selected)
    path = folder / 'lexicon.json'
    if not path.exists():
        atomic_json(path, seed_entries())
    from .audit import upgrade_local
    upgrade_local(path)
    from .formats import upgrade_local as upgrade_formats
    upgrade_formats(path)
    from .corrections import upgrade_local as upgrade_corrections
    upgrade_corrections(path)
    from .bit_depth import upgrade_local as upgrade_bit_depth
    upgrade_bit_depth(path)
    return path


def read(path=None):
    path = Path(path) if path else active_path()
    if is_table(path):
        return _read_table(path)
    raw = path.read_bytes()
    entries = validate(json.loads(raw.decode('utf-8-sig')))
    return {'path': str(path), 'entries': entries, 'fingerprint': hashlib.sha256(raw).hexdigest()}


def _read_table(path):
    """从 Excel/CSV 主词库读词条。指纹用 writer 的文件指纹，与写回配对。"""
    from . import writer
    from .loader import _rows_to_entries
    table = writer.load_table(str(path))
    columns = table['columns']
    entries = [e.to_dict() for e in _rows_to_entries(
        [writer.header_for(columns), *table['rows']])]
    return {'path': str(path), 'entries': validate(entries),
            'fingerprint': table['fingerprint'], 'columns': columns, 'header': table['header']}


def load_glossary(imports=None):
    result = read()
    glossary = Glossary([GlossaryEntry(**e) for e in result['entries']])
    for path in imports or []:
        glossary.merge(_load_any(path))
    return glossary


def save(entries, expected, path=None):
    entries = validate(entries)
    path = Path(path) if path else active_path()
    if not expected:
        raise Conflict('缺少打开时的版本，请重新打开术语库后保存。')
    if is_table(path):
        return _save_table(path, entries, expected)
    with edit_lock(path):
        if fingerprint(path) != expected:
            raise Conflict('术语库已被同事或其他程序修改。请重新读取后合并改动，避免覆盖。')
        shutil.copy2(path, str(path) + '.bak')
        atomic_json(path, entries)
    return read(path)


def table_rows(result):
    """把 read 的结果排成可供界面编辑的网格行。

    JSON 词库没有列布局概念，统一按 8 列标准布局暴露，避免界面编辑时
    把变体/优先度等富字段丢掉。Excel/CSV 则沿用文件自身列布局。
    """
    from .writer import HEADER_FIELDS
    return _entries_to_rows(result['entries'], result.get('columns') or HEADER_FIELDS)


def table_columns(result):
    """界面应展示的列：JSON 用标准 8 列，表格文件用其自身列。"""
    from .writer import HEADER_FIELDS
    return result.get('columns') or HEADER_FIELDS


def edit_table(path, rows, columns=None, expected=None):
    """界面网格编辑器：直接按「表格行」写回。

    rows 与 columns 对齐；列表字段在格内用换行分隔，由 loader 的表头驱动
    逻辑解析回富字段。指纹不一致 → FileChanged。
    """
    from . import writer
    from .loader import _rows_to_entries
    if not expected:
        raise Conflict('缺少打开时的版本，请重新打开表格后保存。')
    exists = os.path.exists(path)
    current = read(path) if exists else {}
    columns = columns or current.get('columns') or writer.HEADER_FIELDS
    old_columns = current.get('columns') or writer.HEADER_FIELDS
    old_header = current.get('header') or writer.header_for(old_columns)
    # Detail editing may append rich fields to a legacy table. Keep existing
    # custom headers, and generate matching headers for the newly added fields.
    header = [old_header[i] if i < len(old_columns) and old_columns[i] == c
              else old_header[old_columns.index(c)] if c in old_columns
              else writer.header_for([c])[0] for i, c in enumerate(columns)]
    width = len(columns)
    norm = [(list(r[:width]) + [""] * width)[:width] for r in rows]
    for number, row in enumerate(norm, 1):
        if any(str(v).strip() for v in row) and any(not str(row[columns.index(f)]).strip() for f in ('zh', 'en')):
            raise ValueError(f'第 {number} 行需同时填写中文和英文；要删除条目请使用删除按钮。')
    entries = [e.to_dict() for e in _rows_to_entries([header, *norm])]
    validate(entries)  # 提前校验，避免写坏共享文件
    if is_table(path):
        try:
            with edit_lock(path):
                written = writer.save_table(str(path), norm, expected, columns=columns, header=header)
        except writer.FileChanged as e:
            raise FileChanged(str(e)) from None
        return {'count': written['count'], 'fingerprint': written['fingerprint'],
                'total': len(entries)}
    saved = save(entries, expected, path=path)
    return {'count': len(entries), 'fingerprint': saved['fingerprint'],
            'total': len(saved['entries'])}


def _save_table(path, entries, expected):
    """按「词条」写回表格主词库（供 save() 调用）。writer 自做指纹校验。"""
    from . import writer
    columns = read(path).get('columns') or writer.HEADER_FIELDS
    rows = _entries_to_rows(entries, columns)
    try:
        with edit_lock(path):
            writer.save_table(str(path), rows, expected, columns=columns)
    except writer.FileChanged as e:
        raise Conflict(str(e)) from None
    return read(path)


def select(path=None, create=False):
    if not path:
        atomic_json(data_dir() / 'lexicon-settings.json', {})
        return read()
    path = Path(path).resolve()
    if path.suffix.lower() not in ('.json',) + TABLE_SUFFIXES:
        raise ValueError('共享主词库使用 JSON 或 Excel/CSV 文件。')
    if create:
        entries = read()['entries']
        with edit_lock(path):
            if path.exists():
                raise Conflict('文件已存在，请选择新文件名或连接已有词库。')
            if is_table(path):
                from . import writer
                writer.save_table(str(path), _entries_to_rows(entries, writer.HEADER_FIELDS),
                                  None, columns=writer.HEADER_FIELDS)
            else:
                atomic_json(path, entries)
    result = read(path)
    atomic_json(data_dir() / 'lexicon-settings.json', {'path': str(path)})
    return result
