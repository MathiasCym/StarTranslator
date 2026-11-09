"""Editable supported-language terminology, isolated from the bilingual file.

An exact Chinese/English anchor identifies a concept, not an official row number.
Official updates never overwrite local translations, aliases or confirmed errors.
"""
import copy,hashlib,json,shutil,threading
from pathlib import Path
from . import store,catalog

LANGUAGES={'zh-Hant-TW':'繁体中文','ja-JP':'日语','ko':'韩语'}
FIELDS=['zh','en','note','variants','machine_variants','wrong_variants','priority','source','category','_id','_english','_official','_conflict']
LISTS=('variants','machine_variants','wrong_variants')
LOCK=threading.RLock()

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def identity(zh,en):return digest([zh,en])[:32]
def path():return store.data_dir()/'lexicon-languages.json'
def scope():return str(Path(store.active_path()).resolve()).casefold()
def supported(language):
    if language not in LANGUAGES:raise ValueError('主术语库目前只支持繁体中文、日语和韩语维护。其他语言请在多语言词库中查阅。')
    return language
def read_data():
    if not path().exists():return {'schema':1,'sources':{}}
    try:data=json.loads(path().read_text('utf-8'))
    except (OSError,ValueError) as error:raise ValueError('小语种维护文件无法读取，原文件未改动；请检查备份。') from error
    if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('sources'),dict):raise ValueError('小语种维护文件格式不正确，原文件未改动。')
    return data
def records(data,source,language):
    group=data['sources'].get(source,{})
    if not isinstance(group,dict):raise ValueError('小语种维护记录格式不正确。')
    value=group.get(language,{})
    if not isinstance(value,dict):raise ValueError('小语种维护记录格式不正确。')
    for key,item in value.items():
        if not isinstance(key,str) or not isinstance(item,dict) or not isinstance(item.get('zh'),str) or not item['zh']:
            raise ValueError('小语种维护记录格式不正确，原文件未改动。')
        if key!=identity(item['zh'],item.get('english','')):raise ValueError('小语种条目身份与原文不符，原文件未改动。')
        if item.get('deleted'):continue
        if not isinstance(item.get('translation'),str) or item.get('priority') not in (1,2,3) or any(not isinstance(item.get(k),list) or any(not isinstance(v,str) for v in item[k]) for k in LISTS):
            raise ValueError('小语种译法或别名格式不正确，原文件未改动。')
    return value

def bases(reference,entries,language):
    rows={}
    for item in reference.get('entries',[]):
        terms=item.get('terms',{});zh=terms.get('zh-CN','').strip();en=terms.get('en-US','').strip()
        if not zh:continue
        guidance=item.get('guidance',{})
        key=identity(zh,en);row=rows.setdefault(key,{'zh':zh,'english':en,'official':[],'category':'term','curated':bool(item.get('source')),
            'source':item.get('source','官方多语言词库'),'note':guidance.get('note','')})
        if guidance.get('source') and guidance['source'] not in row['source']:row['source']+='\n'+guidance['source']
        value=terms.get(language,'')
        if value and value not in row['official']:row['official'].append(value)
    for entry in entries:
        entry=entry.to_dict() if hasattr(entry,'to_dict') else entry
        zh,en=entry.get('zh',''),entry.get('en','')
        if not zh:continue
        key=identity(zh,en)
        if key not in rows:rows[key]={'zh':zh,'english':en,'official':[],'category':entry.get('category','term'),'source':'本机中英词库'}
        elif entry.get('category')=='person':rows[key]['category']='person'
    return rows
def base_value(base):
    choices=base['official'];target=choices[0] if len(choices)==1 else ''
    return {'zh':base['zh'],'english':base['english'],'translation':target,'note':base.get('note',''),'variants':[],
        'machine_variants':[],'wrong_variants':[],'priority':1 if target else 2,'category':base['category'],'source':base['source'],'baseline':choices}

def table(language):
    supported(language);source=scope();reference=catalog.reference();english=store.read()
    data=read_data();saved=records(data,source,language);base=bases(reference,english['entries'],language);rows=[]
    # An obsolete official anchor with personal work remains a visible local row.
    for key,item in saved.items():
        if key not in base and not item.get('deleted'):base[key]={'zh':item['zh'],'english':item.get('english',''),'official':[],'category':item.get('category','term'),'source':'保留的本机维护条目'}
    for key,item in base.items():
        own=saved.get(key);default=base_value(item)
        if own and own.get('deleted'):continue
        value=own or default
        conflict=('官方译法已变化，当前保留本机译法；请核对后确认。' if own and own.get('baseline')!=item['official'] else
            '原表存在多个不同译法，请结合英文参考确认标准。' if len(item['official'])>1 else '')
        row={**value,'en':value.get('translation',''),'_id':key,'_english':item['english'],
             '_official':'' if item.get('curated') else ' / '.join(item['official']),'_conflict':conflict}
        rows.append(['\n'.join(row.get(k,[])) if k in LISTS else str(row.get(k,'')) for k in FIELDS])
    binding={'file':store.fingerprint(path()) if path().exists() else '', 'english':english['fingerprint'],
        'official':digest(reference),'scope':source,'language':language}
    return {'path':str(path()),'language':language,'columns':FIELDS,'header':FIELDS,'rows':rows,'fingerprint':digest(binding),
        'maintenance_note':'当前语种独立维护，不改写英文词库；官方缺译不会自动猜补。标准设为“已确认”后用于术语覆盖校对。'}

def parse_row(row,columns,index):
    if not isinstance(row,list):raise ValueError(f'第 {index} 行格式不正确。')
    raw=dict(zip(columns,row));result={}
    for key in ('zh','en','note','source','_id','_english'):
        value=raw.get(key,'')
        if not isinstance(value,str) or len(value)>12000:raise ValueError(f'第 {index} 行 {key} 内容不正确。')
        result[key]=value.strip()
    for key in LISTS:
        value=raw.get(key,'')
        if not isinstance(value,str):raise ValueError(f'第 {index} 行别名格式不正确。')
        values=list(dict.fromkeys(v.strip() for v in value.splitlines() if v.strip()))
        if len(values)>100 or any(len(v)>300 for v in values):raise ValueError('别名或错译条目过长。')
        result[key]=values
    if str(raw.get('priority','2')) not in ('1','2','3'):raise ValueError('确认状态不正确。')
    result['priority']=int(raw.get('priority','2'));result['category']=raw.get('category') or 'term'
    if result['category'] not in ('term','person'):raise ValueError('分类不正确。')
    if not result['zh']:raise ValueError(f'第 {index} 行需填写中文术语。')
    return result

def save(language,rows,columns,fingerprint):
    supported(language)
    if not isinstance(rows,list) or len(rows)>20000 or columns!=FIELDS:raise ValueError('小语种词库表格格式不正确。')
    with LOCK:
        path().parent.mkdir(parents=True,exist_ok=True)
        with store.edit_lock(path()):
            current=table(language)
            if not fingerprint or current['fingerprint']!=fingerprint:raise store.FileChanged('小语种词库、官方资料或中英词库已变化，请重新读取后保存，现有内容未覆盖。')
            source=scope();data=read_data();old=records(data,source,language)
            reference=catalog.reference();english=store.read();base=bases(reference,english['entries'],language)
            known={r[FIELDS.index('_id')]:dict(zip(FIELDS,r)) for r in current['rows']}
            output={};seen=set()
            for index,row in enumerate(rows,1):
                value=parse_row(row,columns,index);key=value.pop('_id')
                if key:
                    if key not in known:raise ValueError('条目身份已变化，请重新读取。')
                    if value['zh']!=known[key]['zh'] or value['_english']!=known[key]['_english']:raise ValueError('已有条目的中文和英文参考不可在其他语种中改写；请新增独立条目。')
                else:
                    if not value['en']:raise ValueError('新增条目需填写所选语种的标准译法。')
                    key=identity(value['zh'],value['_english'])
                if key in seen:raise ValueError('同一中文及英文参考出现重复条目，请合并后保存。')
                seen.add(key);value['english']=value.pop('_english');value['translation']=value.pop('en')
                value['baseline']=base.get(key,{}).get('official',old.get(key,{}).get('baseline',[]))
                comparison={**value,'source':base[key]['source']} if key in base else value
                if key not in base or comparison!=base_value(base[key]):
                    value['source']='本机维护';output[key]=value
            for key,value in known.items():
                if key not in seen:output[key]={'deleted':True,'zh':value['zh'],'english':value['_english']}
            data['sources'].setdefault(source,{})[language]=output
            if table(language)['fingerprint']!=fingerprint:raise store.FileChanged('词库在保存期间发生变化，请重新读取。')
            if path().exists():shutil.copy2(path(),str(path())+'.bak')
            store.atomic_json(path(),data)
            fresh=table(language)
            return {'ok':True,'count':len(fresh['rows']),'fingerprint':fresh['fingerprint'],'path':fresh['path']}

def overlay(reference,glossary=None):
    """Review/free-text only. Document translation does not call this function."""
    if not path().exists():return reference
    data=read_data();source=scope();local=data['sources'].get(source,{})
    if not local:return reference
    result=copy.deepcopy(reference);by_id={}
    for row in result.get('entries',[]):
        key=identity(row.get('terms',{}).get('zh-CN',''),row.get('terms',{}).get('en-US',''))
        by_id.setdefault(key,[]).append(row)
    for language in LANGUAGES:
        for key,item in records(data,source,language).items():
            rows=by_id.get(key,[])
            if item.get('deleted'):
                for row in rows:row['terms'].pop(language,None)
                continue
            if not rows:
                row={'id':'local-'+key,'terms':{'zh-CN':item['zh'],'en-US':item.get('english','')}};rows=[row];by_id[key]=rows;result['entries'].append(row)
            for row in rows:
                if item.get('translation'):row['terms'][language]=item['translation']
                else:row['terms'].pop(language,None)
                row.setdefault('maintenance',{})[language]={k:item.get(k,[] if k in LISTS else '') for k in ('note','priority','source',*LISTS)}
    result['_maintenance']=digest(local)
    return result
