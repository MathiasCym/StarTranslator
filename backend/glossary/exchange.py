"""Lossless glossary copies and conservative, repeatable team imports."""
import json
import os
import tempfile
import unicodedata
from pathlib import Path
from zipfile import BadZipFile
from . import store, writer
from .loader import DEFAULT_PATH, _rows_to_entries
from ..document_input import validate_document_input


def key(text):
    return ' '.join(unicodedata.normalize('NFKC',text).split()).casefold()


def entries_from_rows(rows, columns, legacy_lists=False):
    if not isinstance(rows,list) or len(rows)>20000 or not isinstance(columns,list) or any(c is not None and not isinstance(c,str) for c in columns) or not {'zh','en'}<=set(columns):
        raise ValueError('术语表需包含中文和英文列，最多 20000 条。')
    known=[c for c in columns if c in store.FIELDS]
    if len(known)!=len(set(known)):raise ValueError('术语表中有重复字段，请检查表头。')
    clean=[]
    for i,row in enumerate(rows,1):
        if not isinstance(row,list):raise ValueError(f'第 {i} 行格式不正确。')
        row=[str(v) if v is not None else '' for v in row]
        row=(row+['']*len(columns))[:len(columns)]
        if not any(v.strip() for v in row):continue
        if any(not row[columns.index(c)].strip() for c in ('zh','en')):
            raise ValueError(f'第 {i} 行需同时填写中文和标准英文。')
        if 'priority' in columns:
            value=row[columns.index('priority')].strip()
            if value:
                try:
                    number=float(value)
                    if number not in (1,2,3):raise ValueError()
                except ValueError:raise ValueError(f'第 {i} 行的确认信息不正确。') from None
                row[columns.index('priority')]=str(int(number))
        clean.append(row)
    entries=[e.to_dict() for e in _rows_to_entries([writer.header_for(columns),*clean])]
    if not legacy_lists:
        for entry,row in zip(entries,clean):
            for field in writer.LIST_FIELDS:
                if field not in columns:continue
                text=row[columns.index(field)].strip()
                values=None
                if text.startswith('['):
                    try:
                        candidate=json.loads(text)
                        if isinstance(candidate,list) and all(isinstance(v,str) for v in candidate):values=candidate
                    except ValueError:pass
                entry[field]=values if values is not None else [v.strip() for v in text.split('\n') if v.strip()]
    return store.validate(entries)


def _table_entries(records, label):
    rows=[]
    for i,raw in enumerate(records,1):
        if i>20020:raise ValueError(f'{label}超过 20000 条限制。')
        if len(raw)>128:raise ValueError(f'{label}列数过多，请整理为术语表。')
        rows.append(['' if v is None else str(v) for v in raw])
    first=next((i for i,r in enumerate(rows) if writer._header_map(r)),None)
    if first is not None:
        columns=writer._header_map(rows[first]);data=rows[first+1:]
        data=[row for row in data if not writer._header_map(row)]
    else:
        columns=['zh','en','note'];data=rows
    try:return entries_from_rows(data,columns,legacy_lists=True)
    except ValueError as error:raise ValueError(f'{label}：{error}') from None


def load_import(path):
    validate_document_input(path)
    path=Path(path)
    if path.stat().st_size>20*1024*1024:raise ValueError(f'{path.name}超过 20 MB，请拆分词库。')
    suffix=path.suffix.lower()
    if suffix=='.json':
        return store.validate(json.loads(path.read_text(encoding='utf-8-sig')))
    if suffix in {'.csv','.tsv'}:
        import csv
        with path.open(encoding='utf-8-sig',newline='') as stream:
            return _table_entries(csv.reader(stream,delimiter='\t' if suffix=='.tsv' else ','),path.name)
    if suffix in {'.xlsx','.xlsm'}:
        import openpyxl
        from openpyxl.utils.exceptions import InvalidFileException
        try:book=openpyxl.load_workbook(path,read_only=True,data_only=True)
        except (BadZipFile,InvalidFileException):raise ValueError(f'{path.name}不是有效的 Excel 文件。') from None
        entries=[]
        try:
            for sheet in book.worksheets:
                sheet.reset_dimensions()
                entries.extend(_table_entries(sheet.iter_rows(values_only=True),f'{path.name} / {sheet.title}'))
            return store.validate(entries)
        finally:book.close()
    raise ValueError('请选择 JSON、Excel、CSV 或 TSV 术语库。')


def _combine_text(current,incoming):
    # Reflowed Excel notes are the same content with different visual line breaks.
    if ' '.join(current.split())==' '.join(incoming.split()):return current
    if not incoming or incoming==current or incoming in current.split('\n') or '\n' in incoming and incoming in current:return current
    return (current+'\n'+incoming).strip()


def merge_entries(current,incoming):
    entries=store.validate(current);incoming=store.validate(incoming)
    by_zh={}
    for entry in entries:by_zh.setdefault(key(entry['zh']),[]).append(entry)
    report={'added':0,'updated':0,'unchanged':0,'conflicts':[]}
    updated=set()
    for imported in incoming:
        candidates=by_zh.get(key(imported['zh']),[])
        exact=[e for e in candidates if key(e['en'])==key(imported['en'])]
        if candidates and len(exact)!=1:
            report['conflicts'].append({'zh':imported['zh'],'incoming':imported['en'],
                'existing':[e['en'] for e in candidates],'reason':'标准译法不同，已保留当前词库。'})
            continue
        if not candidates:
            entries.append(imported);by_zh[key(imported['zh'])]=[imported];report['added']+=1
            continue
        entry=exact[0];before=json.dumps(entry,sort_keys=True)
        correct={key(v) for v in [entry['en'],*entry['variants']]}
        wrong={key(v) for v in entry['wrong_variants']}
        conflicting={key(v) for v in imported['variants']} & {key(v) for v in imported['wrong_variants']}
        for field in ('variants','machine_variants','wrong_variants'):
            seen={key(v) for v in entry[field]}
            for value in imported[field]:
                token=key(value)
                if token in seen:continue
                if field=='variants' and (token in wrong or token in conflicting) or field=='wrong_variants' and (token in correct or token in conflicting):
                    report['conflicts'].append({'zh':entry['zh'],'incoming':value,'existing':[entry['en']],
                        'reason':'别名与错译标记有分歧，已保留当前标记。'})
                    continue
                entry[field].append(value);seen.add(token)
                if field=='variants':correct.add(token)
                if field=='wrong_variants':wrong.add(token)
        for field in ('note','source'):entry[field]=_combine_text(entry[field],imported[field])
        if json.dumps(entry,sort_keys=True)!=before:updated.add((key(entry['zh']),key(entry['en'])))
        else:report['unchanged']+=1
    report['updated']=len(updated)
    return store.validate(entries),report


def import_files(paths,expected,rows=None,columns=None):
    if not isinstance(paths,list) or not paths or len(paths)>20 or any(not isinstance(p,str) or not p for p in paths):
        raise ValueError('请选择 1–20 个术语库文件。')
    current=store.read()
    if expected!=current['fingerprint']:raise store.Conflict('术语库已更新，请重新读取再导入；当前编辑内容仍保留。')
    base=entries_from_rows(rows,columns) if rows is not None else current['entries']
    imported=[]
    for path in dict.fromkeys(paths):
        imported.extend(load_import(path))
        if len(imported)>20000:raise ValueError('本次导入超过 20000 条，请分批导入。')
    if not imported:raise ValueError('文件中没有可导入的术语，请检查中文和英文列。')
    entries,report=merge_entries(base,imported)
    # Nothing is written until every source has loaded and all rows validate.
    saved=current
    if entries!=current['entries']:
        if store.is_table(current['path']):
            table=writer.load_table(current['path'])
            target_columns=list(columns or table['columns'])
            target_columns.extend(f for f in writer.HEADER_FIELDS if f not in target_columns)
            target_rows=store._entries_to_rows(entries,target_columns)
            old_columns=columns or table['columns'];old_rows=rows if rows is not None else table['rows']
            originals={(key(str(r[old_columns.index('zh')])),key(str(r[old_columns.index('en')]))):r for r in old_rows if len(r)>max(old_columns.index('zh'),old_columns.index('en'))}
            for entry,row in zip(entries,target_rows):
                old=originals.get((key(entry['zh']),key(entry['en'])),[])
                for i,field in enumerate(target_columns):
                    if field in writer.LIST_FIELDS:row[i]=_list_cell(entry[field])
                    elif field not in store.FIELDS and i<len(old):row[i]=old[i]
            store.edit_table(current['path'],target_rows,target_columns,expected)
            saved=store.read()
        else:saved=store.save(entries,expected)
    return {**saved,**report,'imported':len(imported),'files':len(set(paths))}


def _list_cell(values):
    # JSON only where newline/comma syntax would otherwise lose a single alias.
    if any(any(char in v for char in '\n,，、') or v.startswith('[') for v in values):
        return json.dumps(values,ensure_ascii=False)
    return '\n'.join(values)


def _write_excel(path,entries):
    from .excel_format import workbook
    rows=[[_list_cell(e.get(f,[])) if f in writer.LIST_FIELDS else str(e.get(f,'')) for f in writer.HEADER_FIELDS] for e in entries]
    book=workbook(rows,writer.HEADER_FIELDS,writer.HEADER)
    try:book.save(path)
    finally:book.close()


def export_file(path,expected,rows=None,columns=None):
    if not isinstance(path,str) or not Path(path).is_absolute():raise ValueError('请选择导出文件的完整路径。')
    target=Path(path).resolve();suffix=target.suffix.lower()
    if suffix not in {'.json','.xlsx'}:raise ValueError('导出格式支持 JSON 词库和 Excel 表格。')
    current=store.read()
    if target==Path(current['path']).resolve() or target.parent==Path(DEFAULT_PATH).resolve().parent:
        raise ValueError('导出请另选文件名，不能覆盖正在编辑的词库或内置词库。')
    entries=entries_from_rows(rows,columns) if rows is not None else current['entries']
    if expected is None:raise ValueError('缺少目标文件版本，请重新选择导出位置。')
    target.parent.mkdir(parents=True,exist_ok=True)
    with store.edit_lock(target):
        def check():
            actual=store.fingerprint(target) if target.exists() else ''
            if actual!=expected:raise store.Conflict('导出目标已发生变化，请重新选择文件，避免覆盖他人的改动。')
        check()
        fd,temp=tempfile.mkstemp(dir=target.parent,suffix=suffix);os.close(fd)
        try:
            if suffix=='.xlsx':_write_excel(temp,entries)
            else:Path(temp).write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            check();os.replace(temp,target)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return {'path':str(target),'count':len(entries),'format':suffix[1:],'fingerprint':store.fingerprint(target)}
