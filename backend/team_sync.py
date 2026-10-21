"""GitHub-backed glossary commits, with previewed three-way merges and no Git install.

The GitHub contents API creates ordinary Git commits. Only the team glossary
path is writable; model settings, credentials, documents and reports stay local.
"""
import base64
import copy
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import request, error, parse
from .glossary import store, writer
from .llm import secret
from . import public_sources

REPOSITORY='MathiasCym/StarTranslator'
BRANCH='main'
FILE='glossary/team.json'
MAX_BYTES=4*1024*1024
LOCK=threading.RLock()
LIST_FIELDS=('variants','machine_variants','wrong_variants')


class RemoteChanged(store.Conflict): pass


def folder():
    result=store.data_dir()/'team-sync';result.mkdir(parents=True,exist_ok=True);return result


def read_json(name,default):
    path=folder()/name
    if not path.exists(): return copy.deepcopy(default)
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError): raise ValueError('团队同步记录无法读取，请导出日志后重试。') from None


def timestamp(): return datetime.now(timezone.utc).isoformat()


def settings():
    value=read_json('settings.json',{});base=read_json('base.json',{})
    return {'repository':REPOSITORY,'url':'https://github.com/'+REPOSITORY,
            'has_token':bool(value.get('token')),'encryption_available':secret.available(),
            'read_sources':[s['name'] for s in public_sources.configured()]+['GitHub'],
            'last_sync':base.get('saved_at',''),'revision':base.get('sha','')}


def configure(data):
    with LOCK:
        value=read_json('settings.json',{})
        if data.get('clear_token') is True: value.pop('token',None)
        token=data.get('token','')
        if not isinstance(token,str) or len(token)>255 or any(c.isspace() for c in token):
            raise ValueError('请输入有效的维护授权。')
        if token:
            encrypted=secret.encrypt(token)
            if not secret.is_encrypted(encrypted):
                raise ValueError('当前环境无法安全保存维护授权，请在 Windows 中配置。')
            value['token']=encrypted
        store.atomic_json(folder()/'settings.json',value)
        return settings()


class GitHub:
    def __init__(self,public=False):
        value=read_json('settings.json',{}).get('token','')
        self.token=secret.decrypt(value) if value and not public else ''
        self.last_commit_date='';self.last_commit=''

    def call(self,method,path,body=None):
        url='https://api.github.com/repos/'+REPOSITORY+'/'+path
        headers={'Accept':'application/vnd.github+json','User-Agent':'StarTranslator-Glossary',
                 'X-GitHub-Api-Version':'2022-11-28'}
        if self.token: headers['Authorization']='Bearer '+self.token
        payload=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None
        if payload: headers['Content-Type']='application/json'
        req=request.Request(url,data=payload,headers=headers,method=method)
        try:
            with request.urlopen(req,timeout=30) as response:
                raw=response.read(MAX_BYTES*2+1)
                if len(raw)>MAX_BYTES*2: raise ValueError('团队词库过大，未修改本机词库。')
                return json.loads(raw.decode('utf-8'))
        except error.HTTPError as e:
            if e.code==404 and method=='GET' and path.startswith('contents/'): return None
            if e.code in (409,422): raise RemoteChanged('团队词库已被其他人更新，请重新获取差异后再提交。') from None
            if e.code==401: raise ValueError('维护授权无效或已失效，请重新保存授权。') from None
            if e.code==403:
                text='访问过于频繁，请稍后重试。' if e.headers.get('X-RateLimit-Remaining')=='0' else '维护授权没有所需权限，请检查仓库的内容读写权限。'
                raise ValueError(text) from None
            if e.code==404: raise ValueError('团队仓库不可访问，请稍后重试。') from None
            raise ValueError('团队服务暂不可用，请稍后重试。') from None
        except (error.URLError,TimeoutError,OSError):
            raise ValueError('未能连接团队仓库，请检查网络后重试。本机词库保持不变。') from None
        except (json.JSONDecodeError,UnicodeError):
            raise ValueError('团队服务返回了无法读取的数据，本机词库保持不变。') from None

    def read(self):
        source_info={};ref=BRANCH
        if public_sources.configured():
            records=self.call('GET','commits?sha=main&path='+FILE+'&per_page=1')
            if isinstance(records,list) and records:
                record=records[0];ref=record.get('sha','');published=record.get('commit',{}).get('committer',{}).get('date')
                if not re.fullmatch('[a-f0-9]{40}',ref): raise ValueError('团队词库版本信息无效。')
                public_sources.date(published);source_info={'source':'github','source_date':published,'source_commit':ref}
        data=self.call('GET','contents/'+FILE+'?ref='+parse.quote(ref,safe=''))
        if data is None: return {'entries':[],'sha':'','missing':True}
        if not isinstance(data,dict) or data.get('type')!='file' or not re.fullmatch('[0-9a-f]{40}',str(data.get('sha',''))):
            raise ValueError('团队词库版本信息无效。')
        if not isinstance(data.get('size',0),int) or data.get('size',0)>MAX_BYTES: raise ValueError('团队词库过大，本机词库保持不变。')
        if data.get('encoding')=='none': data={**data,**self.call('GET','git/blobs/'+data['sha'])}
        try:
            raw=base64.b64decode(data['content'])
            if len(raw)>MAX_BYTES: raise ValueError()
            entries=store.validate(json.loads(raw.decode('utf-8-sig')))
        except (KeyError,TypeError,ValueError,UnicodeError):
            raise ValueError('团队词库格式不正确，本机词库保持不变。') from None
        return {'entries':entries,'sha':data['sha'],'missing':False,**source_info}

    def commit(self,entries,sha,message):
        if not self.token: raise ValueError('提交修改需要维护授权，可先获取团队最新词库。')
        content=(json.dumps(store.validate(entries),ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        if len(content)>MAX_BYTES: raise ValueError('词库内容过大，未提交修改。')
        body={'message':message,'content':base64.b64encode(content).decode('ascii'),'branch':BRANCH}
        if sha: body['sha']=sha
        result=self.call('PUT','contents/'+FILE,body)
        if not isinstance(result,dict) or not result.get('content',{}).get('sha'):
            raise ValueError('未能确认提交结果，请重新获取团队词库核对。')
        self.last_commit_date=result.get('commit',{}).get('committer',{}).get('date','')
        self.last_commit=result.get('commit',{}).get('sha','')
        return result['content']['sha']

    def history(self):
        records=self.call('GET','commits?path='+parse.quote(FILE,safe='')+'&per_page=10')
        if not isinstance(records,list): raise ValueError('维护记录无法读取。')
        return [{'message':r.get('commit',{}).get('message','')[:1000],
                 'author':r.get('author',{}).get('login','') if r.get('author') else r.get('commit',{}).get('author',{}).get('name',''),
                 'date':r.get('commit',{}).get('author',{}).get('date','')} for r in records]


def read_remote(action,base,client,preferred=None):
    if action=='push': return client.read()
    sources=public_sources.configured()
    if preferred=='github' or not sources: return GitHub(public=True).read()
    candidates=[s for s in sources if not preferred or s['id']==preferred]
    if preferred and not candidates: raise ValueError('公开来源已变化，请重新获取词库差异。')
    for source in candidates:
        try: return public_sources.guard(public_sources.PublicMirror(source).read(),base)
        except ValueError:
            if preferred: raise
    return GitHub(public=True).read()


def history():
    for source in public_sources.configured():
        try: return public_sources.PublicMirror(source).history()
        except ValueError: pass
    return GitHub(public=True).history()


def groups(entries):
    result={}
    for entry in entries: result.setdefault(entry['zh'].casefold(),[]).append(copy.deepcopy(entry))
    return {k:sorted(v,key=lambda e:e['en']) for k,v in result.items()}


def merge(base,local,remote):
    b,l,r=map(groups,(base,local,remote));merged={};conflicts=[]
    for key in sorted(b.keys()|l.keys()|r.keys()):
        before,ours,theirs=b.get(key),l.get(key),r.get(key)
        if ours==theirs: value=ours
        elif ours==before: value=theirs
        elif theirs==before: value=ours
        elif len(ours or [])==len(theirs or [])==1 and len(before or [])<=1:
            old=(before or [{}])[0];a=ours[0];z=theirs[0];entry={}
            for field in a.keys()|z.keys():
                default='term' if field=='category' else None
                original,x,y=old.get(field,default),a.get(field,default),z.get(field,default)
                if x==y: entry[field]=x
                elif x==original: entry[field]=y
                elif y==original: entry[field]=x
                elif field in LIST_FIELDS:
                    previous=set(original or []);left=set(x or []);right=set(y or [])
                    entry[field]=sorted((previous-((previous-left)|(previous-right)))|(left-previous)|(right-previous))
                else:
                    entry[field]=x
                    conflicts.append({'id':str(len(conflicts)),'key':key,'zh':a['zh'],'field':field,'base':original,'local':x,'remote':y})
            value=[entry]
        else:
            value=ours
            label=(ours or theirs or before)[0]['zh']
            conflicts.append({'id':str(len(conflicts)),'key':key,'zh':label,'field':'entry','base':before,'local':ours,'remote':theirs})
        if value is not None: merged[key]=value
    return merged,conflicts


def flatten(merged): return [e for key in sorted(merged) for e in merged[key]]


def preview(data):
    action=data.get('action')
    if action not in ('pull','push'): raise ValueError('请选择获取最新词库或提交修改。')
    with LOCK:
        local=store.read()
        if data.get('fingerprint')!=local['fingerprint']: raise store.Conflict('本机词库已变化，请保存并重新读取后再同步。')
        client=GitHub()
        if action=='push' and not client.token: raise ValueError('请先保存维护授权，再提交词库修改。')
        base=read_json('base.json',{})
        if base.get('path')!=local['path']: base={}
        remote=read_remote(action,base,client)
        merged,conflicts=merge(base.get('entries',[]),local['entries'],remote['entries'])
        old=groups(remote['entries'] if action=='push' else local['entries']);new=merged
        changes=[{'zh':(new.get(k) or old[k])[0]['zh'],'kind':'added' if k not in old else 'deleted' if k not in new else 'changed'}
                 for k in sorted(old.keys()|new.keys()) if old.get(k)!=new.get(k)]
        plan={'id':str(uuid.uuid4()),'created_at':timestamp(),'action':action,'path':local['path'],
              'fingerprint':local['fingerprint'],'remote':remote,'merged':merged,'conflicts':conflicts,'changes':changes}
        store.atomic_json(folder()/'plan.json',plan)
        return {'id':plan['id'],'action':action,'changes':changes,'conflicts':conflicts,'count':len(flatten(merged)),
                'remote_missing':remote['missing'],'pending_upload':groups(flatten(merged))!=groups(remote['entries'])}


def save_local(path,entries,expected):
    path=str(path)
    if not store.is_table(path): return store.save(entries,expected,path=path)
    # Retain custom spreadsheet columns and the existing workbook template.
    table=writer.load_table(path);columns=list(table['columns']);remaining=list(table['rows']);rows=[]
    if 'category' not in columns and any(e.get('category')=='person' for e in entries):columns.append('category')
    zh=columns.index('zh');en=columns.index('en')
    for entry in entries:
        source=next((row for row in remaining if row[zh]==entry['zh'] and row[en]==entry['en']),None)
        candidates=[row for row in remaining if row[zh]==entry['zh']]
        if source is None and len(candidates)==1: source=candidates[0]
        row=list(source) if source is not None else ['']*len(columns)
        row+=['']*(len(columns)-len(row))
        if source is not None: remaining.remove(source)
        for i,column in enumerate(columns):
            if column=='category':row[i]=entry.get('category','term')
            elif column in entry:
                value=entry[column];row[i]='\n'.join(value) if column in LIST_FIELDS else str(value)
        rows.append(row)
    store.edit_table(path,rows,columns=columns,expected=expected)
    return store.read(path)


def apply(data):
    with LOCK:
        plan=read_json('plan.json',{})
        if not plan or data.get('id')!=plan.get('id'): raise store.Conflict('差异预览已失效，请重新获取。')
        current=store.read()
        if current['path']!=plan['path'] or current['fingerprint']!=plan['fingerprint']:
            raise store.Conflict('本机词库已变化，请重新获取差异。')
        merged=copy.deepcopy(plan['merged']);choices=data.get('choices') or {}
        for conflict in plan['conflicts']:
            choice=choices.get(conflict['id'])
            if choice not in ('local','remote'): raise ValueError('请为每一项差异选择保留本机或团队内容。')
            value=copy.deepcopy(conflict[choice]);key=conflict['key']
            if conflict['field']=='entry':
                if value is None: merged.pop(key,None)
                else: merged[key]=value
            else: merged[key][0][conflict['field']]=value
        entries=store.validate(flatten(merged));client=GitHub();latest=read_remote(plan['action'],read_json('base.json',{}),client,plan['remote'].get('source'))
        if latest['sha']!=plan['remote']['sha']:
            raise RemoteChanged('团队词库已被其他人更新，请重新获取差异；本机内容尚未更改。')
        remote_entries=latest['entries'];sha=latest['sha'];committed=False
        if plan['action']=='push' and groups(entries)!=groups(remote_entries):
            message=data.get('message','').strip() if isinstance(data.get('message',''),str) else ''
            if not message or len(message)>200: raise ValueError('请填写本次维护说明（不超过 200 字）。')
            # A filesystem lease closes the check/commit race with other editors.
            with store.edit_lock(Path(current['path'])):
                if store.read(current['path'])['fingerprint']!=plan['fingerprint']: raise store.Conflict('本机词库已变化，请重新获取差异。')
                sha=client.commit(entries,sha,message);remote_entries=entries;committed=True
        try:
            result=current if groups(entries)==groups(current['entries']) else save_local(current['path'],entries,plan['fingerprint'])
        except (OSError,ValueError) as e:
            if committed: raise store.Conflict('团队提交已成功，但本机保存未完成。请重新获取词库，不要重复提交。') from e
            raise
        source_date=getattr(client,'last_commit_date','') if committed else latest.get('source_date','')
        source_commit=getattr(client,'last_commit','') if committed else latest.get('source_commit','')
        store.atomic_json(folder()/'base.json',{'path':current['path'],'entries':remote_entries,'sha':sha,'saved_at':timestamp(),'source_date':source_date,'source_commit':source_commit})
        (folder()/'plan.json').unlink(missing_ok=True)
        return {'count':len(result['entries']),'fingerprint':result['fingerprint'],'committed':committed,
                'pending_upload':groups(entries)!=groups(remote_entries),'revision':sha,'last_sync':timestamp()}
