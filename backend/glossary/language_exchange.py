"""Exchange editable language pairs without writing to the bilingual glossary."""
import csv
import json
from pathlib import Path

from ..document_input import validate_document_input
from . import exchange, language_pairs as pairs, store


COLUMNS = [field for field in pairs.FIELDS if not field.startswith('_') or field=='_english']
HEADERS = ['中文术语', '', '备注', '正确别名', '机翻候选', '已确认错译', '确认状态', '来源', '分类', '英文术语']
TARGET_HEADERS = {'ja-JP': {'日语', '日文', '日本語'}, 'ko': {'韩语', '韩文', '韓語', '한국어'},
                  'zh-Hant-TW': {'繁体中文', '繁體中文', '中文（繁体）', '中文（繁體）'}}


def _header(language):
    return [HEADERS[0], '标准' + pairs.LANGUAGES[language], *HEADERS[2:]]


def _read_table(records, language):
    records = iter(records)
    names = [str(v or '').strip() for v in next(records, ())]
    aliases = dict(zip(_header(language), COLUMNS))
    aliases.update(dict.fromkeys(TARGET_HEADERS[language], 'en'))
    aliases.update({'中文':'zh','简体中文':'zh','英文':'_english','英语':'_english','英文参考':'_english'})
    columns = [aliases.get(name) for name in names]
    fields = [c for c in columns if c]
    if not {'zh', 'en'} <= set(fields) or len(fields) != len(set(fields)):
        raise ValueError('表头需包含中文术语和所选语言的标准译法。')
    for row in records:
        values={column:str(value) for column,value in zip(columns,row) if column and value is not None}
        if '_english' in fields:values.setdefault('_english','')
        yield values


def _read_file(path, language):
    validate_document_input(path)
    path = Path(path)
    if path.stat().st_size > 20*1024*1024:
        raise ValueError(f'{path.name}超过 20 MB，请拆分词库。')
    suffix = path.suffix.lower()
    if suffix == '.json':
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value,dict) or value.get('schema') != 1 or value.get('language') != language or not isinstance(value.get('entries'),list):
            raise ValueError('该文件不属于当前对照语言，请切换语言后导入。')
        yield from value['entries']
    elif suffix in {'.xlsx', '.xlsm'}:
        from openpyxl import load_workbook
        book = load_workbook(path,read_only=True,data_only=True)
        try:
            for sheet in book.worksheets:
                yield from _read_table(sheet.iter_rows(values_only=True),language)
        finally:
            book.close()
    elif suffix in {'.csv', '.tsv'}:
        with path.open(encoding='utf-8-sig',newline='') as stream:
            yield from _read_table(csv.reader(stream,delimiter='\t' if suffix == '.tsv' else ','),language)
    else:
        raise ValueError('请选择 JSON、Excel、CSV 或 TSV 术语库。')


def _row(entry, columns=pairs.FIELDS):
    return ['\n'.join(entry.get(field,[])) if field in pairs.LISTS else str(entry.get(field,'')) for field in columns]


def export_file(language,path,expected,rows,columns):
    pairs.supported(language)
    entries = editor_entries(rows,columns)
    def write(temp,suffix):
        if suffix == '.json':
            data = {'schema':1,'language':language,'entries':[{field:item[field] for field in COLUMNS} for item in entries]}
            temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        else:
            from .excel_format import workbook
            book = workbook([_row(item,COLUMNS) for item in entries], COLUMNS, _header(language))
            try:
                book.save(temp)
            finally:
                book.close()
    return exchange.write_export(path,expected,len(entries),write,protected=(pairs.path(),))


def editor_entries(rows,columns):
    if not isinstance(rows,list) or len(rows)>20000 or columns!=pairs.FIELDS:
        raise ValueError('术语表格式不正确。')
    return [pairs.parse_row(row,columns,index) for index,row in enumerate(rows,1)]


def import_files(language,paths,expected,rows,columns):
    paths = exchange.import_paths(paths)
    current = pairs.table(language)
    if expected != current['fingerprint']:
        raise store.FileChanged('词库已更新，请重新读取再导入；当前编辑内容仍保留。')
    incoming = (entry for path in paths for entry in _read_file(path,language))
    merged,report = merge_rows(current,incoming,rows,columns)
    result = pairs.save(language,merged,columns,expected)
    return {**result,**report}


def merge_rows(current,incoming_rows,rows,columns,hidden=()):
    active = {}
    by_chinese = {}
    for item in editor_entries(rows,columns):
        key = pairs.identity(item['zh'],item['_english'])
        if key in active:
            raise ValueError('同一中文及英文参考出现重复条目，请合并后导入。')
        active[key] = item
        by_chinese.setdefault(item['zh'],[]).append(key)
    saved = {row[columns.index('_id')] for row in current['rows']} | set(hidden)
    report = {'added':0,'updated':0,'unchanged':0,'conflicts':[]}
    changed = set()
    imported = 0
    for raw in incoming_rows:
        if not isinstance(raw,dict):
            raise ValueError('导入词条格式不正确。')
        if not any(raw.values()):
            continue
        imported += 1
        if imported > 20000:
            raise ValueError('本次导入超过 20000 条，请分批导入。')
        data = {**raw,'priority':raw.get('priority') or 2}
        data = {field:'\n'.join(str(v) for v in value) if field in pairs.LISTS and isinstance(value,list) else str(value)
                for field,value in data.items() if value is not None}
        incoming = pairs.parse_row([data.get(field,'') for field in COLUMNS],COLUMNS,imported)
        zh,translation = incoming['zh'],incoming['en']
        candidates = by_chinese.get(zh,[])
        key = pairs.identity(zh,incoming['_english'])
        if '_english' not in raw and len(candidates)>1:
            report['conflicts'].append({'zh':zh,'incoming':translation,'existing':[active[k]['en'] for k in candidates],
                                        'reason':'同一中文有多个词义，请填写对应的英文术语。'})
            continue
        if '_english' not in raw and candidates:
            key = candidates[0]
        existing = active.get(key)
        if not existing:
            if translation and key not in saved:
                active[key] = incoming
                by_chinese.setdefault(zh,[]).append(key)
                report['added'] += 1
            else:
                report['unchanged'] += 1
            continue
        if not translation:
            report['unchanged'] += 1
            continue
        base = existing if existing['en'] else {**existing,'en':translation,'priority':incoming['priority']}
        merged,summary = exchange.merge_entries([{k:base[k] for k in COLUMNS if k!='_english'}],
                                                   [{k:incoming[k] for k in COLUMNS if k!='_english'}])
        report['conflicts'].extend(summary['conflicts'])
        updated = {**existing,**merged[0]}
        if updated != existing:
            active[key] = updated
            changed.add(key)
        elif not summary['conflicts']:
            report['unchanged'] += 1
    if not imported:
        raise ValueError('文件中没有可导入的词条。')
    report['updated'] = len(changed)
    return [_row(item) for item in active.values()],report
