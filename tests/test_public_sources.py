import base64,copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import public_sources as public,team_sync as sync

SOURCE={'id':'gitcode:synthetic/StarTranslator','name':'AtomGit / GitCode','api':'https://api.gitcode.com/api/v5/repos/synthetic/StarTranslator/'}
COMMIT='a'*40
def payload():
    raw=json.dumps([{'zh':'色深','en':'color depth'}],ensure_ascii=False).encode('utf-8')
    return {'type':'file','encoding':'base64','size':len(raw),'content':base64.b64encode(raw).decode('ascii'),'sha':public.git_blob(raw)}
class PublicSourceTests(unittest.TestCase):
    def reader(self):
        value=public.PublicMirror(SOURCE);data=payload();calls=[]
        def call(path):
            calls.append(path)
            return [{'sha':COMMIT,'commit':{'committer':{'date':'2026-10-14T01:00:00Z'}}}] if path.startswith('commits?') else copy.deepcopy(data)
        value.call=call;return value,data,calls
    def test_commit_pins_content_and_checks_exact_git_blob(self):
        reader,data,calls=self.reader();result=reader.read()
        self.assertEqual(result['sha'],data['sha']);self.assertEqual(result['entries'][0]['en'],'color depth')
        self.assertEqual(calls[1],'contents/glossary/team.json?ref='+COMMIT)
        data['sha']='b'*40
        with self.assertRaisesRegex(ValueError,'校验'):reader.read()
    def test_stale_mirror_cannot_roll_back_previously_synced_or_committed_library(self):
        remote={'sha':'b'*40,'source_date':'2026-10-13T01:00:00Z'}
        for base in [{'sha':'a'*40,'source_date':'2026-10-14T01:00:00Z'},{'sha':'a'*40,'saved_at':'2026-10-14T01:00:00Z'},{'sha':'a'*40}]:
            with self.assertRaisesRegex(ValueError,'尚未同步'):public.guard(remote,base)
        self.assertEqual(public.guard(remote,{'sha':'b'*40,'source_date':'2026-10-14T01:00:00Z'}),remote)
    def test_large_content_uses_the_pinned_blob_and_retains_file_hash_validation(self):
        reader,data,calls=self.reader();blob=copy.deepcopy(data);blob.pop('type');data['encoding']='none';data['content']=''
        original=reader.call
        reader.call=lambda path:copy.deepcopy(blob) if path.startswith('git/blobs/') else original(path)
        self.assertEqual(reader.read()['sha'],blob['sha'])
        blob['sha']='b'*40
        with self.assertRaisesRegex(ValueError,'校验'):reader.read()
    def test_pull_fallback_is_public_and_push_reads_authoritative_github_only(self):
        client=Mock();client.read.return_value={'sha':'c'*40}
        with patch.object(public,'configured',return_value=[SOURCE]),patch.object(public.PublicMirror,'read',side_effect=ValueError('offline')),patch.object(sync,'GitHub') as github:
            github.return_value.read.return_value={'sha':'d'*40}
            self.assertEqual(sync.read_remote('pull',{},client)['sha'],'d'*40);github.assert_called_with(public=True)
            self.assertEqual(sync.read_remote('push',{},client)['sha'],'c'*40);client.read.assert_called_once()
    def test_previewed_mirror_cannot_silently_change_provider_during_apply(self):
        with patch.object(public,'configured',return_value=[SOURCE]),patch.object(public.PublicMirror,'read',side_effect=ValueError('offline')),patch.object(sync,'GitHub') as github:
            with self.assertRaisesRegex(ValueError,'offline'):sync.read_remote('pull',{},Mock(),SOURCE['id'])
            github.assert_not_called()
    def test_mirror_requests_never_contain_saved_github_authorization(self):
        response=Mock();response.read.return_value=b'[]';response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with patch.object(public.request,'build_opener',return_value=opener):public.PublicMirror(SOURCE).call('commits')
        req=opener.open.call_args.args[0]
        self.assertFalse(req.has_header('Authorization'));self.assertNotIn('token',req.full_url)
    def test_redirects_cannot_escape_owned_api(self):
        redirect=public.ScopedRedirect(SOURCE['api']);req=public.request.Request(SOURCE['api']+'contents/glossary/team.json')
        for target in ['http://api.gitcode.com/x','https://evil.example/x','https://api.gitcode.com/api/v5/repos/other/repo/contents/x']:
            with self.assertRaises(ValueError):redirect.redirect_request(req,None,302,'',{},target)
    def test_config_rejects_unknown_hosts_credentials_and_malformed_repositories(self):
        configs=[{'schema':1,'mirrors':[{'provider':'proxy','repository':'a/b'}]},{'schema':1,'mirrors':[{'provider':'gitcode','repository':'a/b','token':'secret'}]},{'schema':1,'mirrors':[{'provider':'gitcode','repository':'a/../b'}]}]
        for config in configs:
            with patch.object(Path,'read_text',return_value=json.dumps(config)):
                with self.assertRaises(ValueError):public.configured()
if __name__=='__main__':unittest.main()
