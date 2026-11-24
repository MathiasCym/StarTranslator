import base64,copy,json,os,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import team_sync as sync
from backend.glossary import catalog, language_pairs as pairs, store, team_language
from backend.llm import secret

def term(zh,en,**kw):return store.validate([{'zh':zh,'en':en,**kw}])[0]
class Remote:
    token='synthetic-maintainer'
    def __init__(self,entries):self.entries=copy.deepcopy(entries);self.sha='a'*40;self.calls=[]
    def read(self,ref=None):return {'entries':copy.deepcopy(self.entries),'sha':self.sha,'missing':not self.sha}
    def commit(self,entries,sha,message):
        if sha!=self.sha:raise sync.RemoteChanged('concurrent edit')
        self.calls.append((entries,message));self.entries=copy.deepcopy(entries);self.sha='b'*40;return self.sha

class TeamSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'lexicon.json'
        self.env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root)});self.env.start()
        self.sources=patch('backend.public_sources.configured',return_value=[]);self.sources.start()
        self.active=patch('backend.glossary.store.active_path',return_value=self.path);self.active.start()
        self.base=[term('色深','color depth'),term('点间距','pixel pitch',variants=['pixel spacing'])]
        store.atomic_json(self.path,self.base);store.atomic_json(sync.folder()/'base.json',{'path':str(self.path),'entries':self.base,'sha':'a'*40})
        self.remote=Remote(self.base);self.client=patch('backend.team_sync.GitHub',return_value=self.remote);self.client.start()
    def tearDown(self):self.client.stop();self.active.stop();self.sources.stop();self.env.stop();self.temp.cleanup()
    def preview(self,action='pull'):return sync.preview({'action':action,'fingerprint':store.read()['fingerprint']})
    def test_preview_does_not_write_and_independent_additions_are_merged(self):
        local=self.base+[term('本机新词','local term')];store.atomic_json(self.path,local);before=self.path.read_bytes()
        self.remote.entries.append(term('团队新词','team term'));p=self.preview()
        self.assertEqual(before,self.path.read_bytes());sync.apply({'id':p['id']})
        self.assertEqual(len(store.read()['entries']),4);self.assertEqual(self.remote.calls,[])
    def test_scalar_conflict_requires_choice_and_keeps_original_until_confirmed(self):
        local=copy.deepcopy(self.base);local[0]['en']='local depth';store.atomic_json(self.path,local);self.remote.entries[0]['en']='team depth'
        p=self.preview();self.assertEqual(len(p['conflicts']),1);before=self.path.read_bytes()
        with self.assertRaises(ValueError):sync.apply({'id':p['id']})
        self.assertEqual(before,self.path.read_bytes());sync.apply({'id':p['id'],'choices':{'0':'remote'}})
        self.assertEqual(next(e for e in store.read()['entries'] if e['zh']=='色深')['en'],'team depth')
    def test_alias_changes_merge_deletions_and_additions(self):
        local=copy.deepcopy(self.base);local[1]['variants']=['local alias'];store.atomic_json(self.path,local)
        self.remote.entries[1]['variants'].append('remote alias');p=self.preview();self.assertFalse(p['conflicts']);sync.apply({'id':p['id']})
        e=next(e for e in store.read()['entries'] if e['zh']=='点间距');self.assertEqual(set(e['variants']),{'local alias','remote alias'})
    def test_deleted_term_and_parallel_edit_are_not_silently_lost(self):
        store.atomic_json(self.path,self.base[1:]);self.remote.entries[0]['note']='new definition';p=self.preview()
        self.assertEqual(p['conflicts'][0]['field'],'entry');sync.apply({'id':p['id'],'choices':{'0':'remote'}})
        self.assertEqual(len(store.read()['entries']),2)
    def test_remote_changed_since_preview_refuses_write(self):
        p=self.preview('push');self.remote.sha='c'*40;before=self.path.read_bytes()
        with self.assertRaises(sync.RemoteChanged):sync.apply({'id':p['id'],'message':'update'})
        self.assertEqual(before,self.path.read_bytes());self.assertFalse(self.remote.calls)
    def test_local_changed_since_preview_refuses_remote_commit(self):
        p=self.preview('push');store.atomic_json(self.path,self.base+[term('新词','new')])
        with self.assertRaises(store.Conflict):sync.apply({'id':p['id'],'message':'update'})
        self.assertFalse(self.remote.calls)
    def test_put_conflict_does_not_retry_or_overwrite(self):
        store.atomic_json(self.path,self.base+[term('新词','new')]);p=self.preview('push');before=self.path.read_bytes()
        with patch.object(self.remote,'commit',side_effect=sync.RemoteChanged('parallel commit')):
            with self.assertRaises(sync.RemoteChanged):sync.apply({'id':p['id'],'message':'add term'})
        self.assertEqual(before,self.path.read_bytes())
    def test_push_is_one_normal_commit_and_persists_base(self):
        store.atomic_json(self.path,self.base+[term('新词','new')]);p=self.preview('push');self.assertEqual(p['changes'][0]['kind'],'added')
        result=sync.apply({'id':p['id'],'message':'补充新词'});self.assertTrue(result['committed']);self.assertEqual(len(self.remote.calls),1)
        self.assertEqual(sync.settings()['revision'],'b'*40);self.assertFalse(self.preview()['conflicts'])
    def test_initial_publication_keeps_local_library_and_reports_additions(self):
        self.remote.entries=[];self.remote.sha='';(sync.folder()/'base.json').unlink();p=self.preview('push')
        self.assertTrue(p['remote_missing']);self.assertEqual(len(p['changes']),2);sync.apply({'id':p['id'],'message':'初始化词库'})
        self.assertEqual(len(self.remote.entries),2)
    def test_credential_is_encrypted_never_returned_and_plain_fallback_refused(self):
        key='github_pat_synthetic_only_123456789';value=sync.configure({'token':key});self.assertNotIn(key,json.dumps(value));self.assertTrue(secret.is_encrypted(sync.read_json('settings.json',{})['token']))
        with patch('backend.team_sync.secret.encrypt',return_value='plain:'+key):
            with self.assertRaises(ValueError):sync.configure({'token':key})
        self.assertEqual(secret.decrypt(sync.read_json('settings.json',{})['token']),key)
        sync.configure({'clear_token':True});self.assertFalse(sync.settings()['has_token'])
    def test_network_failure_is_readable_and_keeps_local_bytes(self):
        self.client.stop();before=self.path.read_bytes()
        with patch('backend.team_sync.request.urlopen',side_effect=URLError('offline')):
            with self.assertRaisesRegex(ValueError,'本机词库保持不变'):self.preview()
        self.assertEqual(before,self.path.read_bytes());self.client.start()
    def test_excel_sync_preserves_custom_columns_and_column_width(self):
        from openpyxl import Workbook,load_workbook
        p=self.root/'team.xlsx';w=Workbook();s=w.active;s.append(['中文术语','标准英文','部门']);s.append(['色深','color depth','研发']);s.column_dimensions['C'].width=42;w.save(p)
        current=store.read(p);save=sync.save_local(str(p),[term('色深','colour depth')],current['fingerprint'])
        self.assertEqual(save['entries'][0]['en'],'colour depth');w=load_workbook(p)
        self.assertEqual(w.active['C2'].value,'研发');self.assertEqual(w.active.column_dimensions['C'].width,42)


class LanguageTeamSyncTests(unittest.TestCase):
    TRANSLATIONS={'zh-Hant-TW':'網路連接埠','ja-JP':'イーサネットポート','ko':'이더넷 포트'}

    def setUp(self):
        workspace=tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root=Path(workspace.name)
        self.profile=self.root/'writer'
        self.anchor={'zh':'网口','english':'Ethernet port'}
        self.official={'entries':[{'terms':{'zh-CN':'网口','en-US':'Ethernet port',**self.TRANSLATIONS}}]}
        for fixture in (patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.profile)}),
                        patch.object(catalog,'reference',return_value=self.official),
                        patch.object(sync.public_sources,'configured',return_value=[])):
            fixture.start();self.addCleanup(fixture.stop)
        self.remote={language:Remote([]) for language in pairs.LANGUAGES}
        for remote in self.remote.values():remote.sha=''
        client=patch.object(sync,'GitHub',side_effect=lambda language,**_:self.remote[language])
        client.start();self.addCleanup(client.stop)

    def change(self,language,**fields):
        table=pairs.table(language)
        row=next(row for row in table['rows'] if row[0]==self.anchor['zh'])
        if fields.get('deleted'):
            table['rows'].remove(row)
        else:
            for field,value in fields.items():row[pairs.FIELDS.index(field)]=value
        return pairs.save(language,table['rows'],pairs.FIELDS,table['fingerprint'])

    def preview(self,language,action='pull'):
        return sync.preview({'language':language,'action':action,'fingerprint':pairs.table(language)['fingerprint']})

    def test_all_supported_languages_push_only_their_edits_and_pull_in_another_profile(self):
        from backend.server import app
        client=app.test_client()
        english=store.read()
        for language,translation in self.TRANSLATIONS.items():
            self.change(language,en=translation+' A',variants='团队别名',wrong_variants='团队错译',note=language,category='person')
            plan=client.post('/api/team/preview',json={'language':language,'action':'push','fingerprint':pairs.table(language)['fingerprint']})
            self.assertEqual(plan.status_code,200,plan.json)
            self.assertEqual(plan.json['language'],language)
            self.assertTrue(plan.json['pending_upload'])
            self.assertEqual(len(plan.json['changes']),1)
            response=client.post('/api/team/apply',json={'id':plan.json['id'],'message':'补充该语言词条'})
            self.assertEqual(response.status_code,200,response.json)
            self.assertTrue(response.json['committed'])
            self.assertEqual(len(self.remote[language].calls),1)
            item=self.remote[language].entries[0]
            self.assertEqual((item['translation'],item['note']),(translation+' A',language))
            self.assertNotIn('source',item)
            self.assertNotIn('baseline',item)
            self.assertEqual(client.get('/api/team/settings',query_string={'language':language}).json['revision'],'b'*40)
        self.assertEqual(store.read()['fingerprint'],english['fingerprint'])
        self.assertFalse((sync.folder()/'base.json').exists())

        with patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'reader')}):
            self.assertFalse(pairs.path().exists())
            for language,translation in self.TRANSLATIONS.items():
                with self.subTest(language=language):
                    self.remote[language].token=''
                    plan=self.preview(language)
                    self.assertFalse(plan['pending_upload'])
                    sync.apply({'id':plan['id']})
                    value=next(item for item in pairs.table(language)['rows'] if item[0]==self.anchor['zh'])
                    self.assertEqual(value[1],translation+' A')
                    self.assertEqual(value[2:4],[language,'团队别名'])
                    self.assertEqual(value[5:9],['团队错译','1','团队维护','person'])
            effective=pairs.overlay(self.official)
            self.assertEqual({k:effective['entries'][0]['terms'][k] for k in self.TRANSLATIONS},
                             {k:v+' A' for k,v in self.TRANSLATIONS.items()})

    def test_conflict_is_bound_to_language_and_restoring_official_removes_team_override(self):
        language='ja-JP'
        self.change(language,en='本機表記')
        self.remote[language].entries=team_language.validate([{**self.anchor,'translation':'チーム表記','priority':1}])
        self.remote[language].sha='a'*40
        plan=self.preview(language,'push')
        self.assertEqual([item['field'] for item in plan['conflicts']],['translation'])
        before=pairs.path().read_bytes()
        with self.assertRaises(ValueError):sync.apply({'id':plan['id'],'message':'选择团队译法'})
        self.assertEqual(before,pairs.path().read_bytes())
        sync.apply({'id':plan['id'],'choices':{'0':'remote'}})
        self.assertEqual(self.remote[language].calls,[])
        self.change(language,en=self.TRANSLATIONS[language])
        plan=self.preview(language,'push')
        self.assertTrue(plan['pending_upload'])
        sync.apply({'id':plan['id'],'message':'恢复官方译法'})
        self.assertEqual(self.remote[language].entries,[])

    def test_deletion_is_syncable_and_remote_or_local_changes_invalidate_review(self):
        language='ko'
        self.change(language,deleted=True)
        plan=self.preview(language,'push')
        self.assertEqual(plan['changes'],[{'zh':'网口','kind':'deleted'}])
        self.remote[language].sha='a'*40
        with self.assertRaises(sync.RemoteChanged):sync.apply({'id':plan['id'],'message':'撤下旧词条'})
        self.assertFalse(self.remote[language].calls)
        plan=self.preview(language,'push')
        self.change('zh-Hant-TW',en='網口')
        with self.assertRaises(store.Conflict):sync.apply({'id':plan['id'],'message':'撤下旧词条'})
        self.assertFalse(self.remote[language].calls)
        plan=self.preview(language,'push')
        sync.apply({'id':plan['id'],'message':'撤下旧词条'})
        self.assertEqual(self.remote[language].entries,[{**self.anchor,'deleted':True}])
        with patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'reader')}):
            sync.apply({'id':self.preview(language)['id']})
            self.assertFalse(any(row[0]=='网口' for row in pairs.table(language)['rows']))
            self.assertTrue(any(row[0]=='网口' for row in pairs.table('zh-Hant-TW')['rows']))

    def test_pronunciation_or_note_edits_merge_with_a_separate_first_translation_override(self):
        language='zh-Hant-TW'
        self.change(language,note='技術備註')
        self.remote[language].entries=team_language.validate([{**self.anchor,'translation':'以太網路連接埠','priority':1}])
        self.remote[language].sha='a'*40
        plan=self.preview(language,'push')
        self.assertFalse(plan['conflicts'])
        sync.apply({'id':plan['id'],'message':'補上技術備註'})
        self.assertEqual(self.remote[language].entries[0]['translation'],'以太網路連接埠')
        self.assertEqual(self.remote[language].entries[0]['note'],'技術備註')

    def test_github_transport_uses_only_the_fixed_language_file_and_comment(self):
        github=self._real_client('ja-JP')
        data=[{**self.anchor,'translation':'イーサネットポート'}]
        with patch.object(github,'call',return_value={'content':{'sha':'b'*40}}) as call:
            self.assertEqual(github.commit(data,'','修订日语术语'),'b'*40)
            method,path,body=call.call_args.args
            self.assertEqual((method,path,body['message']),('PUT','contents/glossary/team-languages/ja-JP.json','修订日语术语'))
            content=json.loads(base64.b64decode(body['content']))
            self.assertEqual(team_language.decode('ja-JP',content)[0]['translation'],data[0]['translation'])
            with self.assertRaises(ValueError):team_language.decode('ko',content)
        with self.assertRaises(ValueError):team_language.supported('../fr')

    def _real_client(self,language):
        github=RealGitHub(public=True,language=language)
        github.token='synthetic-maintainer'
        return github

    def batch_client(self):
        self.remote['en-US']=Remote(store.read()['entries'])
        self.batch_commits=[]
        self.remote['en-US'].head=lambda:'c'*40

        def commit_batch(head,changes,message):
            self.assertEqual(head,'c'*40)
            self.batch_commits.append((changes,message))
            hashes={}
            for language,entries in changes.items():
                remote=self.remote[language]
                hashes[language]=remote.sha='d'*40
                remote.entries=copy.deepcopy(entries)
            return 'e'*40,'2026-11-23T08:00:00Z',hashes

        self.remote['en-US'].commit_batch=commit_batch
        fake=patch.object(sync,'GitHub',side_effect=lambda language='en-US',**_:self.remote[language])
        fake.start();self.addCleanup(fake.stop)

    def test_batch_push_one_comment_for_all_languages_and_batch_pull(self):
        from backend.server import app
        self.batch_client()
        client=app.test_client()
        current=store.read()
        store.save(current['entries']+[term('批量同步测试','batch sync test')],current['fingerprint'])
        for lang,translation in self.TRANSLATIONS.items():self.change(lang,en=translation+' A')
        response=client.post('/api/team/preview',json={'action':'push','all_languages':True})
        self.assertEqual(response.status_code,200,response.json)
        plan=response.json
        self.assertEqual({entry['language'] for entry in plan['changes']},set(team_language.NAMES))
        self.assertEqual(len(plan['changes']),4)
        self.assertEqual(client.post('/api/team/apply',json={'id':plan['id']}).status_code,400)
        self.assertFalse(self.batch_commits)
        result=client.post('/api/team/apply',json={'id':plan['id'],'message':'统一维护四语种'})
        self.assertEqual(result.status_code,200,result.json)
        self.assertTrue(result.json['committed'])
        self.assertEqual(len(self.batch_commits),1)
        changes,message=self.batch_commits[0]
        self.assertEqual(set(changes),set(team_language.NAMES))
        self.assertEqual(message,'统一维护四语种')
        with patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'new-reader')}):
            plan=client.post('/api/team/preview',json={'action':'pull','all_languages':True}).json
            self.assertEqual({item['language'] for item in plan['changes']},set(team_language.NAMES))
            result=client.post('/api/team/apply',json={'id':plan['id']})
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(result.json['changed_languages'],4)
            self.assertTrue(any(item['en']=='batch sync test' for item in store.read()['entries']))
            for lang,translation in self.TRANSLATIONS.items():
                self.assertEqual(team_language.snapshot(lang)['entries'][0]['translation'],translation+' A')
        self.assertEqual(len(self.batch_commits),1)

    def test_batch_blocks_stale_remote_and_rolls_back_first_local_write_if_second_fails(self):
        self.batch_client()
        self.remote['en-US'].entries.append(term('团队批量','team batch'))
        self.remote['ko'].entries=team_language.validate([{**self.anchor,'translation':'팀 용어'}])
        self.remote['ko'].sha='b'*40
        plan=sync.preview({'action':'pull','all_languages':True})
        self.remote['ko'].sha='d'*40
        with self.assertRaises(sync.RemoteChanged):sync.apply({'id':plan['id']})
        self.assertFalse(pairs.path().exists())
        plan=sync.preview({'action':'pull','all_languages':True})
        english=Path(store.read()['path'])
        before=english.read_bytes()
        replace=os.replace

        def fail_english(source,target):
            if Path(target)==english:raise OSError('simulated locked workbook')
            replace(source,target)

        with patch.object(sync.os,'replace',side_effect=fail_english):
            with self.assertRaises(OSError):sync.apply({'id':plan['id']})
        self.assertEqual(english.read_bytes(),before)
        self.assertFalse(pairs.path().exists())
        sync.apply({'id':plan['id']})
        self.assertEqual(team_language.snapshot('ko')['entries'][0]['translation'],'팀 용어')

    def test_batch_transport_sends_one_guarded_mutation_and_fixed_file_paths(self):
        github=self._real_client('en-US')
        contents={'en-US':[term('色深','color depth')],'ja-JP':[{**self.anchor,'translation':'ネットワークポート'}]}
        with patch.object(github,'call',return_value={'data':{'createCommitOnBranch':{'commit':{'oid':'b'*40,'committedDate':'2026-11-23T08:00:00Z'}}}}) as call:
            commit,_,revisions=github.commit_batch('a'*40,contents,'统一维护说明')
            self.assertEqual(commit,'b'*40)
            call.assert_called_once()
            method,path,body=call.call_args.args
            self.assertEqual((method,path),('POST','graphql'))
            request=body['variables']['input']
            self.assertEqual(request['expectedHeadOid'],'a'*40)
            self.assertEqual(request['message']['headline'],'统一维护说明')
            self.assertEqual({item['path'] for item in request['fileChanges']['additions']},
                             {'glossary/team.json','glossary/team-languages/ja-JP.json'})
            for item in request['fileChanges']['additions']:
                language='en-US' if item['path'].endswith('team.json') else 'ja-JP'
                self.assertEqual(revisions[language],sync.public_sources.git_blob(base64.b64decode(item['contents'])))

    def test_combined_history_deduplicates_the_same_commit(self):
        record={'sha':'a'*40,'message':'统一维护说明','author':'QA','date':'2026-11-23T08:00:00Z'}
        for remote in self.remote.values():remote.history=lambda:[record]
        with patch.object(sync,'GitHub',side_effect=lambda language='en-US',**_:self.remote.get(language,self.remote['ko'])):
            self.assertEqual(sync.history('all'),[record])


RealGitHub=sync.GitHub

if __name__=='__main__':unittest.main()
