"""GitHub-backed glossary commits, with previewed three-way merges and no Git install.

The GitHub contents API creates ordinary Git commits scoped to one glossary.
"""
import base64
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from urllib import request, error, parse
from .glossary import language_pairs, store, team_language, writer
from .llm import secret
from . import public_sources

REPOSITORY='MathiasCym/StarTranslator'
BRANCH='main'
DEFAULT=team_language.DEFAULT
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


def base_file(language):
    return 'base.json' if language==DEFAULT else f'base-{team_language.supported(language)}.json'


def settings(language=DEFAULT):
    value=read_json('settings.json',{})
    bases=[read_json(base_file(code),{}) for code in team_language.NAMES] if language=='all' else [read_json(base_file(language),{})]
    base=max(bases,key=lambda item:item.get('saved_at',''))
    return {'repository':REPOSITORY,'url':'https://github.com/'+REPOSITORY,
            'has_token':bool(value.get('token')),'encryption_available':secret.available(),
            'read_sources':[s['name'] for s in public_sources.configured()]+['GitHub'],
            'last_sync':base.get('saved_at',''),'revision':base.get('sha',''),
            'language':language,'language_name':team_language.NAMES.get(language,'团队词库')}


def configure(data):
    language=data.get('language',DEFAULT)
    if language!='all':team_language.supported(language)
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
        return settings(language)


class GitHub:
    def __init__(self,public=False,language=DEFAULT):
        self.language=team_language.supported(language)
        self.file=team_language.remote_path(language)
        value=read_json('settings.json',{}).get('token','')
        self.token=secret.decrypt(value) if value and not public else ''
        self.last_commit_date='';self.last_commit=''

    def call(self,method,path,body=None):
        url='https://api.github.com/graphql' if path=='graphql' else 'https://api.github.com/repos/'+REPOSITORY+'/'+path
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

    def head(self):
        result=self.call('GET','git/ref/heads/'+BRANCH)
        sha=result.get('object',{}).get('sha','') if isinstance(result,dict) else ''
        if not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('团队词库版本信息无效。')
        return sha

    def read(self,ref=None):
        source_info={}
        if ref is None and public_sources.configured():
            records=self.call('GET','commits?sha=main&path='+self.file+'&per_page=1')
            if isinstance(records,list) and records:
                record=records[0];ref=record.get('sha','');published=record.get('commit',{}).get('committer',{}).get('date')
                if not re.fullmatch('[a-f0-9]{40}',ref): raise ValueError('团队词库版本信息无效。')
                public_sources.date(published);source_info={'source':'github','source_date':published,'source_commit':ref}
        data=self.call('GET','contents/'+self.file+'?ref='+parse.quote(ref or BRANCH,safe=''))
        if data is None: return {'entries':[],'sha':'','missing':True}
        if not isinstance(data,dict) or data.get('type')!='file' or not re.fullmatch('[0-9a-f]{40}',str(data.get('sha',''))):
            raise ValueError('团队词库版本信息无效。')
        if not isinstance(data.get('size',0),int) or data.get('size',0)>MAX_BYTES: raise ValueError('团队词库过大，本机词库保持不变。')
        if data.get('encoding')=='none': data={**data,**self.call('GET','git/blobs/'+data['sha'])}
        try:
            raw=base64.b64decode(data['content'])
            if len(raw)>MAX_BYTES: raise ValueError()
            entries=team_language.decode(self.language,json.loads(raw.decode('utf-8-sig')))
        except (KeyError,TypeError,ValueError,UnicodeError):
            raise ValueError('团队词库格式不正确，本机词库保持不变。') from None
        return {'entries':entries,'sha':data['sha'],'missing':False,**source_info}

    @staticmethod
    def encoded(language,entries):
        content=(json.dumps(team_language.encode(language,entries),ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        if len(content)>MAX_BYTES: raise ValueError('词库内容过大，未提交修改。')
        return content

    def commit(self,entries,sha,message):
        if not self.token: raise ValueError('提交修改需要维护授权，可先获取团队最新词库。')
        content=self.encoded(self.language,entries)
        body={'message':message,'content':base64.b64encode(content).decode('ascii'),'branch':BRANCH}
        if sha: body['sha']=sha
        result=self.call('PUT','contents/'+self.file,body)
        if not isinstance(result,dict) or not result.get('content',{}).get('sha'):
            raise ValueError('未能确认提交结果，请重新获取团队词库核对。')
        self.last_commit_date=result.get('commit',{}).get('committer',{}).get('date','')
        self.last_commit=result.get('commit',{}).get('sha','')
        return result['content']['sha']

    def commit_batch(self,head,changes,message):
        if not self.token:raise ValueError('提交修改需要维护授权。')
        raw={language:self.encoded(language,entries) for language,entries in changes.items()}
        additions=[{'path':team_language.remote_path(language),'contents':base64.b64encode(content).decode('ascii')}
                   for language,content in raw.items()]
        payload={'branch':{'repositoryNameWithOwner':REPOSITORY,'branchName':BRANCH},'expectedHeadOid':head,
                 'message':{'headline':message},'fileChanges':{'additions':additions}}
        query='mutation TeamGlossary($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) { commit { oid committedDate } } }'
        result=self.call('POST','graphql',{'query':query,'variables':{'input':payload}})
        data=result.get('data') or {} if isinstance(result,dict) else {}
        commit=(data.get('createCommitOnBranch') or {}).get('commit') or {}
        if not re.fullmatch('[a-f0-9]{40}',str(commit.get('oid',''))):
            if self.head()!=head:raise RemoteChanged('团队仓库已更新，请重新获取差异后再核对提交。')
            raise ValueError('团队词库未能提交，请检查维护授权和仓库写入规则。')
        return commit['oid'],commit.get('committedDate',''),{lang:public_sources.git_blob(value) for lang,value in raw.items()}

    def history(self):
        records=self.call('GET','commits?path='+parse.quote(self.file,safe='')+'&per_page=10')
        if not isinstance(records,list): raise ValueError('维护记录无法读取。')
        return [{'message':r.get('commit',{}).get('message','')[:1000],
                 'sha':r.get('sha',''),
                 'author':r.get('author',{}).get('login','') if r.get('author') else r.get('commit',{}).get('author',{}).get('name',''),
                 'date':r.get('commit',{}).get('author',{}).get('date','')} for r in records]


def public_client(language):
    return GitHub(public=True) if language==DEFAULT else GitHub(public=True,language=language)


def read_remote(action,base,client,preferred=None,language=DEFAULT):
    if action=='push': return client.read()
    sources=public_sources.configured()
    if preferred=='github' or not sources: return public_client(language).read()
    candidates=[s for s in sources if not preferred or s['id']==preferred]
    if preferred and not candidates: raise ValueError('公开来源已变化，请重新获取词库差异。')
    for source in candidates:
        try: return public_sources.guard(public_sources.PublicMirror(source,language).read(),base)
        except ValueError:
            if preferred: raise
    return public_client(language).read()


def history(language=DEFAULT):
    if language=='all':
        with ThreadPoolExecutor(max_workers=len(team_language.NAMES)) as pool:
            histories=list(pool.map(history,team_language.NAMES))
        unique={item.get('sha') or (item['message'],item['author'],item['date']):item for records in histories for item in records}
        return sorted(unique.values(),key=lambda item:item['date'],reverse=True)[:10]
    team_language.supported(language)
    for source in public_sources.configured():
        try: return public_sources.PublicMirror(source,language).history()
        except ValueError: pass
    return public_client(language).history()


def groups(entries):
    result={}
    for entry in entries: result.setdefault(entry['zh'].casefold(),[]).append(copy.deepcopy(entry))
    return {k:sorted(v,key=lambda e:e['en']) for k,v in result.items()}


def merge(base,local,remote,group=groups):
    b,l,r=map(group,(base,local,remote));merged={};conflicts=[]
    for key in sorted(b.keys()|l.keys()|r.keys()):
        before,ours,theirs=b.get(key),l.get(key),r.get(key)
        if ours==theirs: value=ours
        elif ours==before: value=theirs
        elif theirs==before: value=ours
        elif (len(ours or [])==len(theirs or [])==1 and len(before or [])<=1
              and not any(entry[0].get('deleted') for entry in (before,ours,theirs) if entry)):
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


def merged_item(action,language,local,base,remote,include_incoming=False):
    group=groups if language==DEFAULT else team_language.groups
    if language!=DEFAULT and base.get('sha') and remote['missing']:
        raise RemoteChanged('团队词库暂不可用，请稍后重新获取差异。')
    before=base.get('entries',[])
    if language!=DEFAULT:
        before=team_language.common_ancestors(before,local,remote['entries'])
    merged,conflicts=merge(before,local['entries'],remote['entries'],group)
    remote_groups=group(remote['entries'])
    local_groups=group(local['entries'])
    old=remote_groups if action=='push' else local_groups
    changes=[]
    additional=local_groups if include_incoming else {}
    for key in sorted(old.keys()|merged.keys()|additional.keys()):
        previous,current=old.get(key),merged.get(key)
        if previous==current and include_incoming:previous=local_groups.get(key)
        if previous==current: continue
        kind='deleted' if current is None or current[0].get('deleted') else 'added' if previous is None else 'changed'
        if language!=DEFAULT and local['bases'].get(key,{}).get('official') and (previous is None or current is None):
            if not (current and current[0].get('deleted')):kind='changed'
        changes.append({'zh':(current or previous)[0]['zh'],'kind':kind})
    return {'path':local['path'],'language':language,'fingerprint':local['fingerprint'],'remote':remote,'merged':merged,
            'conflicts':conflicts,'changes':changes,'pending_upload':merged!=remote_groups}


def preview(data):
    action=data.get('action')
    if action not in ('pull','push'): raise ValueError('请选择获取最新词库或提交修改。')
    with LOCK:
        if data.get('all_languages') is True:
            return preview_batch(action)
        language=team_language.supported(data.get('language',DEFAULT))
        local=team_language.snapshot(language)
        if data.get('fingerprint')!=local['fingerprint']: raise store.Conflict('本机词库已变化，请保存并重新读取后再同步。')
        client=GitHub(language=language)
        if action=='push' and not client.token: raise ValueError('请先保存维护授权，再提交词库修改。')
        base=base_for(language,local)
        remote=read_remote(action,base,client,language=language)
        plan={'id':str(uuid.uuid4()),'created_at':timestamp(),'action':action,**merged_item(action,language,local,base,remote)}
        store.atomic_json(folder()/'plan.json',plan)
        return {'id':plan['id'],'action':action,'language':language,'changes':plan['changes'],'conflicts':plan['conflicts'],
                'count':len(flatten(plan['merged'])),'remote_missing':remote['missing'],'pending_upload':plan['pending_upload']}


def base_for(language,local):
    base=read_json(base_file(language),{})
    return base if base.get('path')==local['path'] else {}


def snapshots():
    return {language:team_language.snapshot(language) for language in team_language.NAMES}


def read_batch(action,bases,preferred=None):
    languages=tuple(team_language.NAMES)
    if action=='pull' and preferred!='github':
        sources=[source for source in public_sources.configured() if not preferred or source['id']==preferred]
        if preferred and not sources:raise ValueError('团队词库来源已变化，请重新获取差异。')
        for source in sources:
            try:
                revision=public_sources.PublicMirror(source).revision()
                with ThreadPoolExecutor(max_workers=len(languages)) as pool:
                    files=list(pool.map(lambda lang:public_sources.PublicMirror(source,lang).read(revision),languages))
                remote={lang:public_sources.guard(value,bases[lang]) for lang,value in zip(languages,files)}
                if any(value['missing'] and bases[lang].get('sha') for lang,value in remote.items()):
                    raise RemoteChanged('团队词库尚未同步，请重新获取差异。')
                return source['id'],revision[0],remote
            except ValueError:
                if preferred:raise
    client=GitHub(public=action=='pull')
    if action=='push' and not client.token:raise ValueError('请先保存维护授权，再提交词库修改。')
    head=client.head()
    with ThreadPoolExecutor(max_workers=len(languages)) as pool:
        files=list(pool.map(lambda lang:GitHub(public=action=='pull',language=lang).read(head),languages))
    return 'github',head,dict(zip(languages,files))


def preview_batch(action):
    local=snapshots()
    bases={lang:base_for(lang,value) for lang,value in local.items()}
    source,_,remote=read_batch(action,bases)
    items={lang:merged_item(action,lang,value,bases[lang],remote[lang],include_incoming=True) for lang,value in local.items()}
    for lang,item in items.items():
        for entry in item['changes']+item['conflicts']:
            entry.update(language=lang,language_name=team_language.NAMES[lang])
        for conflict in item['conflicts']:
            conflict['id']=lang+'-'+conflict['id']
    plan={'id':str(uuid.uuid4()),'action':action,'source':source,'items':items}
    store.atomic_json(folder()/'plan.json',plan)
    return {'id':plan['id'],'action':action,
            'changes':[entry for item in items.values() for entry in item['changes']],
            'conflicts':[entry for item in items.values() for entry in item['conflicts']],
            'remote_missing':all(value['missing'] for value in remote.values()),
            'pending_upload':any(item['pending_upload'] for item in items.values())}


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


def resolve_entries(item,choices):
    merged=copy.deepcopy(item['merged'])
    for conflict in item['conflicts']:
        choice=choices.get(conflict['id'])
        if choice not in ('local','remote'):raise ValueError('请为每一项差异选择保留本机或团队内容。')
        value=copy.deepcopy(conflict[choice]);key=conflict['key']
        if conflict['field']!='entry':merged[key][0][conflict['field']]=value
        elif value is None:merged.pop(key,None)
        else:merged[key]=value
    validate=store.validate if item.get('language',DEFAULT)==DEFAULT else team_language.validate
    return validate(flatten(merged))


def differs(language,first,second):
    group=groups if language==DEFAULT else team_language.groups
    return group(first)!=group(second)


def stage_local(stack,local,changes):
    staged=[]

    def prepare(target,write):
        directory=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.star-team-',dir=target.parent)))
        previous=directory/'previous.bytes'
        if target.exists():shutil.copy2(target,previous)
        candidate=directory/target.name
        write(candidate,previous)
        staged.append((target,candidate,previous))

    overrides={lang:entries for lang,entries in changes.items() if lang!=DEFAULT}
    if overrides:
        data=language_pairs.read_data()
        for lang,entries in overrides.items():team_language.update_data(lang,entries,local[lang],data)
        prepare(language_pairs.path(),lambda candidate,_:store.atomic_json(candidate,data))
    if DEFAULT in changes:
        english=local[DEFAULT]

        def write_english(candidate,previous):
            shutil.copy2(previous,candidate)
            save_local(candidate,changes[DEFAULT],store.read(candidate)['fingerprint'])

        prepare(Path(english['path']),write_english)

    def install():
        applied=[]
        try:
            for target,candidate,previous in staged:
                if previous.exists():shutil.copy2(previous,str(target)+'.bak')
                os.replace(candidate,target)
                applied.append((target,previous))
        except OSError:
            for target,previous in reversed(applied):
                if previous.exists():os.replace(previous,target)
                else:target.unlink()
            raise

    return install


def apply_batch(plan,data):
    items=plan['items']
    choices=data.get('choices') or {}
    proposed={lang:resolve_entries(item,choices) for lang,item in items.items()}

    def check_local():
        current=snapshots()
        if any(value['path']!=items[lang]['path'] or value['fingerprint']!=items[lang]['fingerprint'] for lang,value in current.items()):
            raise store.Conflict('本机词库已变化，请重新获取差异。')
        return current

    local=check_local()
    bases={lang:base_for(lang,value) for lang,value in local.items()}
    _,head,remote=read_batch(plan['action'],bases,plan['source'])
    if any(remote[lang]['sha']!=item['remote']['sha'] for lang,item in items.items()):
        raise RemoteChanged('团队词库已被其他人更新，请重新获取差异。')
    pending={lang:entries for lang,entries in proposed.items() if differs(lang,entries,remote[lang]['entries'])}
    local_changes={lang:entries for lang,entries in proposed.items() if differs(lang,entries,local[lang]['entries'])}
    committed=False
    with language_pairs.LOCK,store.edit_lock(language_pairs.path()),store.edit_lock(Path(local[DEFAULT]['path'])),ExitStack() as stack:
        check_local()
        install=stage_local(stack,local,local_changes)
        if plan['action']=='push' and pending:
            message=data.get('message')
            if not isinstance(message,str) or not message.strip() or len(message.strip())>200:
                raise ValueError('请填写本次维护说明（不超过 200 字）。')
            commit,date,revisions=GitHub().commit_batch(head,pending,message.strip())
            committed=True
            for lang,entries in pending.items():
                remote[lang]={'entries':entries,'sha':revisions[lang],'source_date':date,'source_commit':commit}
        try:
            install()
            for lang,value in remote.items():
                store.atomic_json(folder()/base_file(lang),{'path':local[lang]['path'],'entries':value['entries'],
                    'sha':value['sha'],'saved_at':timestamp(),'source_date':value.get('source_date',''),'source_commit':value.get('source_commit','')})
        except (OSError,ValueError) as exc:
            if committed:raise store.Conflict('团队提交已成功，但本机保存未完成。请重新获取词库。') from exc
            raise
    (folder()/'plan.json').unlink(missing_ok=True)
    return {'committed':committed,'pending_upload':bool(pending) and not committed,'changed_languages':len(local_changes|pending)}


def apply(data):
    with LOCK:
        plan=read_json('plan.json',{})
        if not plan or data.get('id')!=plan.get('id'): raise store.Conflict('差异预览已失效，请重新获取。')
        if 'items' in plan:return apply_batch(plan,data)
        language=team_language.supported(plan.get('language',DEFAULT))
        group=groups if language==DEFAULT else team_language.groups

        def checked_local():
            current=team_language.snapshot(language)
            if current['path']!=plan['path'] or current['fingerprint']!=plan['fingerprint']:
                raise store.Conflict('本机词库已变化，请重新获取差异。')
            return current

        current=checked_local()
        entries=resolve_entries(plan,data.get('choices') or {})
        client=GitHub(language=language)
        base=read_json(base_file(language),{})
        latest=read_remote(plan['action'],base if base.get('path')==current['path'] else {},client,
                           plan['remote'].get('source'),language)
        if latest['sha']!=plan['remote']['sha']:
            raise RemoteChanged('团队词库已被其他人更新，请重新获取差异；本机内容尚未更改。')
        remote_entries=latest['entries'];sha=latest['sha'];committed=False
        with ExitStack() as locks:
            if language!=DEFAULT:
                locks.enter_context(language_pairs.LOCK)
                locks.enter_context(store.edit_lock(language_pairs.path()))
                current=checked_local()
            if plan['action']=='push' and group(entries)!=group(remote_entries):
                message=data.get('message','').strip() if isinstance(data.get('message',''),str) else ''
                if not message or len(message)>200: raise ValueError('请填写本次维护说明（不超过 200 字）。')
                lock=store.edit_lock(Path(current['path'])) if language==DEFAULT else nullcontext()
                with lock:
                    if language==DEFAULT: checked_local()
                    sha=client.commit(entries,sha,message);remote_entries=entries;committed=True
            try:
                result=current
                if group(entries)!=group(current['entries']):
                    if language==DEFAULT:
                        result=save_local(current['path'],entries,plan['fingerprint'])
                    else:
                        result=team_language.save(language,entries,current)
            except (OSError,ValueError) as e:
                if committed: raise store.Conflict('团队提交已成功，但本机保存未完成。请重新获取词库。') from e
                raise
        source_date=getattr(client,'last_commit_date','') if committed else latest.get('source_date','')
        source_commit=getattr(client,'last_commit','') if committed else latest.get('source_commit','')
        store.atomic_json(folder()/base_file(language),{'path':current['path'],'entries':remote_entries,'sha':sha,'saved_at':timestamp(),'source_date':source_date,'source_commit':source_commit})
        (folder()/'plan.json').unlink(missing_ok=True)
        return {'count':len(result['entries']),'fingerprint':result['fingerprint'],'committed':committed,'language':language,
                'pending_upload':group(entries)!=group(remote_entries),'revision':sha,'last_sync':timestamp()}
