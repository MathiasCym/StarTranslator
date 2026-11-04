"""User actions distinguish a new run from explicit, context-bound recovery."""
import asyncio,json,os,sqlite3,sys,tempfile,threading,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx import Document
from backend import workflow,history,task_queue
from backend.glossary.loader import Glossary
from backend.models import GlossaryEntry
from backend.llm.client import LLMClient

PAIRS={'点间距为2.5mm。':'The pixel pitch is 2.5 mm.','刷新率为60Hz。':'The refresh rate is 60 Hz.'}


class Model(LLMClient):
    def __init__(self,cancel=False,model='original'):
        self.provider='compatible';self.base_url='http://127.0.0.1:1/v1';self.model=model;self.api_format='openai'
        self.calls=[];self.interrupt=cancel
    def chat_json(self,prompt,system='',**options):
        if '复核' in system and '"ok"' in system:return {'ok':True,'issues':[]}
        if '待译原文' in prompt and prompt.startswith('{'):source=json.loads(prompt)['待译原文']
        else:source=prompt.split('【待译原文】\n')[-1].split('\n【需保留')[0].strip()
        if self.interrupt and self.calls:
            self.cancel.set();raise workflow.Cancelled('Fixture cancellation after the first committed paragraph')
        self.calls.append(source)
        return {'translation':{**PAIRS,**{en:zh for zh,en in PAIRS.items()}}[source]}


class TaskResumeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'profile')});env.start();self.addCleanup(env.stop)
        self.glossary=Glossary([])
        stub=patch('backend.workflow.store.load_glossary',side_effect=lambda *args:self.glossary);stub.start();self.addCleanup(stub.stop)
        self.jobs=dict(workflow.JOBS);self.reports=dict(workflow.REPORTS)
        workflow.JOBS.clear();workflow.REPORTS.clear();self.addCleanup(self.restore)
    def restore(self):
        workflow.JOBS.clear();workflow.JOBS.update(self.jobs);workflow.REPORTS.clear();workflow.REPORTS.update(self.reports)
    def doc(self,direction='zh-en'):
        path=self.root/(direction+'.docx');doc=Document()
        for zh,en in PAIRS.items():doc.add_paragraph(en if direction=='en-zh' else zh)
        doc.save(path);return path
    def run_job(self,data,model):
        with patch('backend.workflow.LLMClient',return_value=model):
            job=workflow.start(data)
            return asyncio.run(task_queue.wait(job['id'],.005))
    def options(self,path,direction='zh-en'):
        return {'kind':'translate','paths':[str(path)],'workers':1,'direction':direction,'output_dir':str(self.root/'output')}
    def test_cancel_then_new_start_is_fresh_but_explicit_resume_reuses_only_its_own_task(self):
        for direction in ('zh-en','en-zh'):
            with self.subTest(direction=direction):
                path=self.doc(direction);data=self.options(path,direction)
                cancelled=self.run_job(data,Model(cancel=True));self.assertEqual(cancelled['status'],'cancelled')
                original=history.record(cancelled['id']);self.assertEqual(original['checkpoint_session'],cancelled['id'])
                fresh_model=Model();fresh=self.run_job(data,fresh_model)
                self.assertEqual(fresh['status'],'complete');self.assertEqual(len(fresh_model.calls),2)
                self.assertEqual(fresh['result']['outputs'][0]['resumed_segments'],0)
                resume_model=Model();resume=self.run_job(history.resume_options(cancelled['id']),resume_model)
                self.assertEqual(resume['status'],'complete',resume.get('error'));self.assertTrue(resume['resuming'])
                self.assertEqual(len(resume_model.calls),1);self.assertEqual(resume['result']['outputs'][0]['resumed_segments'],1)
                self.assertEqual(history.record(resume['id'])['checkpoint_session'],cancelled['id'])
                self.assertEqual(history.record(resume['id'])['counts']['resumed_translation'],1)
                self.assertEqual(sum(resume['resume_counts'].values()),1)
    def test_context_changes_never_silently_turn_resume_into_a_fresh_translation(self):
        for change in ('model','glossary','source'):
            with self.subTest(change=change):
                self.glossary=Glossary([]);path=self.doc();data=self.options(path)
                first=self.run_job(data,Model(cancel=True));self.assertEqual(first['status'],'cancelled')
                model=Model(model='different' if change=='model' else 'original')
                if change=='glossary':self.glossary=Glossary([GlossaryEntry('点间距','pixel pitch',priority=1)])
                if change=='source':
                    doc=Document(path);doc.add_paragraph('原稿已变化');doc.save(path)
                resumed=self.run_job(history.resume_options(first['id']),model)
                self.assertEqual(resumed['status'],'failed');self.assertIn('无法按原断点继续',resumed['error'])
                self.assertEqual(model.calls,[])
                retried=Model(model=model.model)
                again=self.run_job(history.resume_options(resumed['id']),retried)
                self.assertEqual(again['status'],'failed');self.assertEqual(retried.calls,[])
    def test_legacy_model_mismatch_is_explained_without_stealing_other_model_results(self):
        from backend.translation import translate_file,Cancelled
        from backend.task_resume import activate
        path=self.doc();original=Model(cancel=True);original.cancel=threading.Event()
        with activate(None),self.assertRaises(Cancelled):translate_file(path,self.glossary,None,client=original,workers=1)
        history.begin('old-task',self.options(path))
        profile={key:getattr(original,key) for key in ('provider','base_url','model','api_format')}
        with patch('backend.model_profiles._load',return_value={'profiles':[profile]}):
            other=Model(model='other');failed=self.run_job(history.resume_options('old-task'),other)
        self.assertEqual(failed['status'],'failed');self.assertIn('旧断点属于模型 original',failed['error'])
        self.assertEqual(other.calls,[])
        with patch('backend.model_profiles._load',return_value={'profiles':[profile]}):
            still_wrong=Model(model='other');again=self.run_job(history.resume_options(failed['id']),still_wrong)
        self.assertEqual(again['status'],'failed');self.assertEqual(still_wrong.calls,[])
        correct=Model();resumed=self.run_job(history.resume_options('old-task'),correct)
        self.assertEqual(resumed['status'],'complete',resumed.get('error'))
        self.assertEqual(resumed['result']['outputs'][0]['resumed_segments'],1);self.assertEqual(len(correct.calls),1)
    def test_readonly_checkpoint_probe_does_not_write_or_create_a_database(self):
        from backend.checkpoints import Checkpoint
        folder=self.root/'profile';folder.mkdir()
        checkpoint=Checkpoint('translation',{'source':'fixture'},read_only=True)
        checkpoint.put('key','value');self.assertFalse((folder/'task-checkpoints.sqlite3').exists())
        Checkpoint('translation',{'source':'fixture'}).put('key','value')
        db_path=folder/'task-checkpoints.sqlite3';before=db_path.read_bytes()
        probe=Checkpoint('translation',{'source':'fixture'},read_only=True)
        self.assertEqual(probe.get('key'),'value');probe.put('key','different')
        self.assertEqual(db_path.read_bytes(),before)
    def test_resume_uses_canonical_history_settings_and_rejects_active_origin(self):
        path=self.doc();first=self.run_job(self.options(path),Model(cancel=True))
        options=history.resume_options(first['id']);options.update(direction='en-zh',paths=['untrusted.docx'])
        resumed=self.run_job(options,Model());self.assertEqual(resumed['status'],'complete')
        self.assertEqual(history.resume_options(resumed['id'])['direction'],'zh-en')
        workflow.JOBS[first['id']]['status']='running'
        with self.assertRaisesRegex(ValueError,'仍在处理'):workflow.start(history.resume_options(first['id']))


if __name__=='__main__':unittest.main()
