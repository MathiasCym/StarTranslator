"""Language sheets shared by the Excel and JSON exchange formats."""
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from contextlib import ExitStack
from itertools import chain
from pathlib import Path
from zipfile import BadZipFile

from ..document_input import validate_document_input
from . import catalog, exchange, language_exchange, language_pairs as pairs, store, writer

FORMAT = 'startranslator-multilingual-glossary'


def _scope_tables(language,rows,columns):
    if language!='en-US':
        pairs.supported(language)
    english=store.read()
    tables={code:pairs.table(code) for code in pairs.LANGUAGES}
    draft=rows is not None
    if draft and language=='en-US':
        editable=exchange.entries_from_rows(rows,columns)
    else:
        editable=english['entries']
    return english,tables,editable


def export_file(language,path,expected,rows,columns):
    _,tables,english=_scope_tables(language,rows,columns)
    reference=catalog.lookup()
    langs={item['code']:item['name'] for item in reference['languages']}
    by_key={pairs.identity(e['zh'],e['en']):(e['zh'],e['en']) for e in english}
    for item in reference['entries']:
        zh=item['terms'].get('zh-CN','');en=item['terms'].get('en-US','')
        if zh:by_key.setdefault(pairs.identity(zh,en),(zh,en))
    sheets={}
    english_rows=[tuple(exchange._list_cell(e.get(f,[])) if f in writer.LIST_FIELDS else str(e.get(f,'')) for f in writer.HEADER_FIELDS) for e in english]
    sheets['en-US']=(writer.HEADER_FIELDS,writer.HEADER,english_rows)
    for code,table in tables.items():
        entries=language_exchange.editor_entries(rows,columns) if language==code and rows is not None else language_exchange.editor_entries(table['rows'],table['columns'])
        for item in entries:
            zh,en=item['zh'],item['_english']
            by_key.setdefault(pairs.identity(zh,en),(zh,en))
        sheets[code]=(language_exchange.COLUMNS,language_exchange._header(code),[language_exchange._row(e,language_exchange.COLUMNS) for e in entries])
    sheets['zh-CN']=(['zh','en'],['中文术语','英文术语'],list(by_key.values()))
    for code,name in langs.items():
        if code in sheets:continue
        values=[(item['terms'].get('zh-CN',''),item['terms'].get(code,''),item['terms'].get('en-US',''))
                for item in reference['entries'] if item['terms'].get('zh-CN')]
        sheets[code]=(['zh','en','_english'],['中文术语','标准'+name,'英文术语'],values)

    def write(temp,suffix):
        if suffix=='.json':
            value={'schema':1,'format':FORMAT,'sheets':[
                {'language':code,'name':name,'columns':sheets[code][1],'rows':sheets[code][2]} for code,name in langs.items()]}
            temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            return
        from .excel_format import standard_workbook
        sheets_to_write=[]
        for code,name in langs.items():
            fields,header,values=sheets[code]
            sheets_to_write.append((f'{name} ({code})',values,fields,header))
        book=standard_workbook(sheets_to_write)
        try:
            book.active=list(langs).index(language)
            book.save(temp)
        finally:
            book.close()
    result=exchange.write_export(path,expected,sum(len(sheet[2]) for sheet in sheets.values()),write,protected=(pairs.path(),))
    return {**result,'sheets':len(sheets)}


def _sheet_language(title,names):
    label=re.sub(r'\s+',' ',title.strip()).casefold()
    code=re.search(r'\(([a-z0-9-]+)\)$',label)
    token=code[1] if code else label
    return names.get(token)


def _reference_rows(records,code,name):
    records=iter(records)
    aliases={'中文':'zh','中文术语':'zh','简体中文':'zh','英文':'_english','英语':'_english','英文术语':'_english','英文参考':'_english'}
    if code!='zh-CN':
        aliases.update({name:'en','标准'+name:'en',code.casefold():'en'})
    fields=[aliases.get(str(value or '').strip().casefold()) for value in next(records,())]
    known=[field for field in fields if field]
    if 'zh' not in known or code!='zh-CN' and 'en' not in known or len(known)!=len(set(known)):
        raise ValueError('表头需包含中文术语和对应语种的译法。')
    for row in records:
        values={field:str(value).strip() for field,value in zip(fields,row) if field and value is not None}
        if '_english' in known:values.setdefault('_english','')
        yield values


def read_workbook(path,languages,selected=None,include_legacy=False):
    path=Path(path)
    suffix=path.suffix.lower()
    if suffix not in {'.xlsx','.xlsm','.json'}:
        return None
    validate_document_input(path)
    if path.stat().st_size>20*1024*1024:
        raise ValueError(f'{path.name}超过 20 MB，请拆分词库。')
    if suffix=='.json':
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value,dict) or value.get('format')!=FORMAT:
            if include_legacy and isinstance(value,list):
                return {'en-US':store.validate(value)}
            if include_legacy and isinstance(value,dict) and isinstance(value.get('language'),str) and value['language'] in pairs.LANGUAGES:
                code=value['language']
                return {code:list(language_exchange._read_file(path,code))}
            return None
        if value.get('schema')!=1 or not isinstance(value.get('sheets'),list) or not value['sheets']:
            raise ValueError(f'{path.name}的多语种词库格式不正确。')
        parsed={}
        for sheet in value['sheets']:
            if not isinstance(sheet,dict) or not isinstance(sheet.get('language'),str):
                raise ValueError('JSON 语言工作表格式不正确。')
            code=sheet['language'];header=sheet.get('columns');rows=sheet.get('rows')
            if selected and code!=selected:continue
            if code not in languages or code in parsed or not isinstance(header,list) or not isinstance(rows,list) or any(not isinstance(row,list) for row in rows):
                raise ValueError(f'{path.name}包含未知、重复或格式错误的语言工作表。')
            parsed[code]=_read_sheet(chain((header,),rows),code,languages[code],path.name)
        if selected and selected not in parsed:
            raise ValueError(f'{path.name}不包含{languages[selected]}词条。')
        return parsed
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException
    try:book=load_workbook(path,read_only=True,data_only=True)
    except (BadZipFile,InvalidFileException):raise ValueError(f'{path.name}不是有效的 Excel 文件。') from None
    names={token.casefold():code for code,name in languages.items() for token in (code,name)}
    names.update({'english':'en-US','ko-kr':'ko','日文':'ja-JP','韩文':'ko','繁體中文':'zh-Hant-TW'})
    try:
        tabs=[(sheet,_sheet_language(sheet.title,names)) for sheet in book.worksheets]
        # A generic legacy worksheet still uses the current editor language.
        if not any(code for _,code in tabs):
            return None
        if selected:
            tabs=[(sheet,code) for sheet,code in tabs if code==selected]
            if not tabs:raise ValueError(f'{path.name}不包含{languages[selected]}工作表。')
        parsed={}
        for sheet,code in tabs:
            if not code or code in parsed:
                raise ValueError(f'{path.name}的「{sheet.title}」无法匹配唯一语种。')
            sheet.reset_dimensions()
            parsed[code]=_read_sheet(sheet.iter_rows(values_only=True),code,languages[code],path.name)
        return parsed
    finally:
        book.close()


def _read_sheet(rows,code,name,filename):
    try:
        if code=='en-US':
            first=next(rows,())
            if writer._header_map([str(value or '') for value in first]) is None:
                raise ValueError('英语工作表须包含中文和英文列。')
            return exchange._table_entries(chain((first,),rows),name)
        read=language_exchange._read_table(rows,code) if code in pairs.LANGUAGES else _reference_rows(rows,code,name)
        parsed=[]
        for i,row in enumerate(read,1):
            if i>20000:raise ValueError('每种语言最多 20000 条。')
            if row and any(row.values()):parsed.append(row)
        return parsed
    except ValueError as error:
        raise ValueError(f'{filename} / {name}：{error}') from None


def import_files(paths,language,expected,rows,columns,all_languages=None):
    """Return None for older exchange files that have no language-sheet names."""
    paths=exchange.import_paths(paths)
    if not any(Path(path).suffix.lower() in {'.xlsx','.xlsm','.json'} for path in paths):
        return None
    reference=catalog.read()
    languages={item['code']:item['name'] for item in reference.get('languages',[])}
    if not languages:
        return None
    if language not in {'en-US',*pairs.LANGUAGES}:
        pairs.supported(language)
    selected=language if all_languages is False else None
    books=[read_workbook(path,languages,selected,include_legacy=all_languages is True) for path in paths]
    if not any(book is not None for book in books):
        return None
    incoming=defaultdict(list)
    for path,book in zip(paths,books):
        if book is None:
            entries=exchange.load_import(path) if language=='en-US' else language_exchange._read_file(path,language)
            book={language:entries}
        for code,entries in book.items():
            for entry in entries:
                if len(incoming[code])>=20000:
                    raise ValueError(f'{languages[code]}超过 20000 条，请分批导入。')
                incoming[code].append(entry)
    if not any(incoming.values()):
        raise ValueError('工作簿中没有可导入的术语。')
    side_path=pairs.path()
    side_fingerprint=store.fingerprint(side_path) if side_path.exists() else ''
    english,tables,editable=_scope_tables(language,rows,columns)
    active=english if language=='en-US' else tables[language]
    if expected!=active['fingerprint']:
        raise store.FileChanged('词库已更新，请重新读取再导入；当前编辑内容仍保留。')
    english_path=Path(english['path']).resolve()
    data=pairs.read_data()
    source=str(english_path).casefold()
    official=catalog.reference()
    report={'added':0,'updated':0,'unchanged':0,'conflicts':[]}

    def summarize(code,summary):
        for key in ('added','updated','unchanged'):report[key]+=summary[key]
        report['conflicts'].extend({**item,'language':code,'language_name':languages[code]} for item in summary.get('conflicts',[]))

    new_english,summary=exchange.merge_entries(editable,incoming['en-US'])
    summarize('en-US',summary)
    local=data['sources'].setdefault(source,{})
    changed=False
    for code,table in tables.items():
        draft=rows if code==language and rows is not None else table['rows']
        if incoming[code]:
            draft,summary=language_exchange.merge_rows(table,incoming[code],draft,pairs.FIELDS,
                                                      hidden={key for key,item in local.get(code,{}).items() if item.get('deleted')})
            summarize(code,summary)
        if draft!=table['rows']:
            local[code]=pairs.prepare_records(code,draft,pairs.FIELDS,table,data,source,official,english)
            changed=True
    saved_reference=data.setdefault('lookup',{}).get(source,{})
    added_reference,reference_reports=_merge_reference(reference,saved_reference,new_english,incoming,languages)
    for code,summary in reference_reports.items():summarize(code,summary)
    if added_reference!=saved_reference:
        data['lookup'][source]=added_reference
        changed=True

    _save_batch(english,side_path,side_fingerprint,new_english,data if changed else None,
                rows if language=='en-US' else None,columns if language=='en-US' else None)
    return {**report,'sheets':sum(bool(values) for values in incoming.values())}


def _merge_reference(reference,saved,english,incoming,languages):
    import copy
    known={}
    by_chinese=defaultdict(set)
    for row in [*(item['terms'] for item in reference['entries']),
                *({'zh-CN':item['zh'],'en-US':item['english'],**item['terms']} for item in saved.values()),
                *({'zh-CN':item['zh'],'en-US':item['en']} for item in english)]:
        zh=row.get('zh-CN','');en=row.get('en-US','')
        if not zh:continue
        key=pairs.identity(zh,en)
        concept=known.setdefault(key,{'zh':zh,'english':en,'terms':defaultdict(set)})
        for code,value in row.items():
            if value:concept['terms'][code].add(value)
        by_chinese[zh].add(key)
    output=copy.deepcopy(saved)
    reports={}
    for code in languages:
        if code=='en-US' or code in pairs.LANGUAGES or not incoming[code]:continue
        summary={'added':0,'updated':0,'unchanged':0,'conflicts':[]}
        reports[code]=summary
        for raw in incoming[code]:
            zh=raw.get('zh','');en=raw.get('_english','');text=raw.get('en','')
            if not zh or max(len(zh),len(en),len(text))>12000:
                raise ValueError(f'{languages[code]}工作表有空中文词条或单元格过长。')
            if code!='zh-CN' and not text:
                continue
            key=pairs.identity(zh,en)
            if '_english' not in raw:
                matches=by_chinese[zh]
                if len(matches)>1 and code!='zh-CN':
                    summary['conflicts'].append({'zh':zh,'existing':[],'incoming':text,'reason':'同一中文有多个词义，请填写英文术语。'})
                    continue
                if len(matches)==1:key=next(iter(matches))
            concept=known.get(key)
            if concept:
                old=concept['terms'].get(code,set())
                if code=='zh-CN' or text in old:
                    summary['unchanged']+=1
                    continue
                if old:
                    summary['conflicts'].append({'zh':zh,'existing':sorted(old),'incoming':text,'reason':'译法不同，已保留当前条目。'})
                    continue
                summary['updated']+=1
            else:
                concept=known[key]={'zh':zh,'english':en,'terms':defaultdict(set)}
                by_chinese[zh].add(key)
                summary['added']+=1
            record=output.setdefault(key,{'zh':concept['zh'],'english':concept['english'],'terms':{}})
            if code!='zh-CN':
                record['terms'][code]=text
                concept['terms'][code].add(text)
    return output,reports


def _save_batch(english,side,side_fingerprint,entries,data,rows,columns):
    target=Path(english['path']).resolve()
    write_english=entries!=english['entries']
    if not write_english and data is None:
        return
    side.parent.mkdir(parents=True,exist_ok=True)
    file_fingerprint=writer.file_fingerprint if store.is_table(target) else store.fingerprint

    def guard():
        if (store.active_path().resolve()!=target or file_fingerprint(target)!=english['fingerprint'] or
                (store.fingerprint(side) if side.exists() else '')!=side_fingerprint):
            raise store.FileChanged('词库在导入期间发生变化，当前编辑仍保留，请重新读取后再导入。')

    with pairs.LOCK,store.edit_lock(side),store.edit_lock(target),ExitStack() as stack:
        guard()
        if write_english:
            staging=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.star-glossary-',dir=target.parent)))
            staged_english=staging/target.name
            shutil.copy2(target,staged_english)
            exchange.save_merged(store.read(staged_english),entries,rows,columns)
        if data is not None:
            staging=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.star-glossary-',dir=side.parent)))
            staged_side=staging/side.name
            store.atomic_json(staged_side,data)
            original=staging/'previous.json'
            if side_fingerprint:shutil.copy2(side,original)
        guard()
        if write_english:shutil.copy2(target,str(target)+'.bak')
        if data is not None:
            if side_fingerprint:shutil.copy2(original,str(side)+'.bak')
            os.replace(staged_side,side)
        try:
            if write_english:os.replace(staged_english,target)
        except OSError:
            if data is not None:
                if side_fingerprint:os.replace(original,side)
                else:side.unlink()
            raise
