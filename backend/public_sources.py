"""Anonymous reads from bundled, owned public mirrors. No write credentials."""
import base64
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib import request, error, parse
from .glossary import store

FILE='glossary/team.json'
MAX_BYTES=4*1024*1024
PLATFORMS={
    'atomgit':('AtomGit','https://api.atomgit.com/api/v5/repos/'),
    'gitcode':('AtomGit / GitCode','https://api.gitcode.com/api/v5/repos/'),
    'gitee':('Gitee','https://gitee.com/api/v5/repos/'),
}


def configured():
    try: value=json.loads(Path(__file__).with_name('distribution.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): raise ValueError('公开来源配置无法读取，请校验软件完整性。') from None
    if not isinstance(value,dict) or set(value)!= {'schema','mirrors'} or value.get('schema')!=1 or not isinstance(value.get('mirrors'),list) or len(value['mirrors'])>2:
        raise ValueError('公开来源配置无效。')
    result=[];seen=set()
    for item in value['mirrors']:
        if not isinstance(item,dict) or set(item)!= {'provider','repository'} or item.get('provider') not in PLATFORMS:
            raise ValueError('公开来源配置不得包含授权或自定义网址。')
        repo=item['repository'];provider=item['provider']
        family='atomgit' if provider=='gitcode' else provider
        if not isinstance(repo,str) or len(repo)>200 or len(repo.split('/'))!=2 or not all(re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*',p) and '..' not in p for p in repo.split('/')) or family in seen:
            raise ValueError('公开镜像仓库地址无效。')
        seen.add(family);name,api=PLATFORMS[provider]
        result.append({'id':provider+':'+repo,'name':name,'api':api+repo+'/'})
    return result


def git_blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode('ascii')+b'\0'+raw).hexdigest()


def date(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result
    except (ValueError,AttributeError,TypeError): raise ValueError('团队词库的发布时间无效。') from None


def guard(remote,base):
    # A lagging mirror must not roll back a library already synced or committed.
    if not base.get('sha') or remote['sha']==base['sha']: return remote
    previous=base.get('source_date') or base.get('saved_at')
    if not previous or date(remote.get('source_date'))<=date(previous):
        raise ValueError('国内词库尚未同步到本机已获取的版本，请稍后重试。')
    return remote


class ScopedRedirect(request.HTTPRedirectHandler):
    def __init__(self,prefix): self.prefix=prefix
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        value=parse.urlsplit(newurl);base=parse.urlsplit(self.prefix)
        if value.scheme!='https' or value.netloc!=base.netloc or not value.path.startswith(base.path) or value.username or value.password:
            raise ValueError('团队服务返回了无效的跳转，本机词库保持不变。')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class PublicMirror:
    def __init__(self,source): self.source=source
    def call(self,path):
        req=request.Request(self.source['api']+path,headers={'Accept':'application/json','User-Agent':'StarTranslator-Glossary'})
        try:
            with request.build_opener(ScopedRedirect(self.source['api'])).open(req,timeout=12) as response:
                raw=response.read(MAX_BYTES*2+1)
                if len(raw)>MAX_BYTES*2: raise ValueError('团队词库过大，本机词库保持不变。')
                return json.loads(raw.decode('utf-8'))
        except (error.URLError,TimeoutError,OSError): raise ValueError('未能连接国内团队词库，本机词库保持不变。') from None
        except (ValueError,UnicodeError): raise ValueError('国内团队词库无法读取，本机词库保持不变。') from None

    def read(self):
        # Pin the content to the same immutable commit as its timestamp.
        records=self.call('commits?sha=main&path='+FILE+'&per_page=1')
        if not isinstance(records,list) or not records: raise ValueError('国内词库尚未发布。')
        record=records[0]
        if not isinstance(record,dict) or not isinstance(record.get('commit'),dict) or not isinstance(record['commit'].get('committer'),dict): raise ValueError('国内词库版本信息无效。')
        commit=record.get('sha','');published=record['commit']['committer'].get('date')
        if not re.fullmatch('[a-f0-9]{40}',commit): raise ValueError('国内词库版本信息无效。')
        date(published)
        data=self.call('contents/'+FILE+'?ref='+commit)
        try:
            if isinstance(data,dict) and data.get('encoding')=='none' and re.fullmatch('[a-f0-9]{40}',str(data.get('sha',''))):
                blob=self.call('git/blobs/'+data['sha'])
                if not isinstance(blob,dict) or blob.get('sha')!=data['sha']: raise ValueError()
                data={**data,**blob}
            if not isinstance(data,dict) or data.get('type')!='file' or data.get('encoding')!='base64': raise ValueError()
            raw=base64.b64decode(data['content'])
            if len(raw)>MAX_BYTES or type(data.get('size')) is not int or len(raw)!=data['size'] or git_blob(raw)!=data['sha']: raise ValueError()
            entries=store.validate(json.loads(raw.decode('utf-8-sig')))
        except (KeyError,TypeError,ValueError,UnicodeError):
            raise ValueError('国内团队词库格式或校验信息不正确，本机词库保持不变。') from None
        return {'entries':entries,'sha':data['sha'],'missing':False,'source':self.source['id'],'source_date':published,'source_commit':commit}

    def history(self):
        records=self.call('commits?sha=main&path='+FILE+'&per_page=10')
        if not isinstance(records,list): raise ValueError('维护记录无法读取。')
        return [{'message':r.get('commit',{}).get('message','')[:1000],
                 'author':(r.get('author') or {}).get('login','') or r.get('commit',{}).get('author',{}).get('name',''),
                 'date':r.get('commit',{}).get('author',{}).get('date','')} for r in records]
