"""PPT notes are an explicit task-local opt-in, including save and resume."""
import json,sys,threading,unittest
from pathlib import Path
from zipfile import ZipFile
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend import workflow,comparison,history
from backend.translation import translate_file
from backend.glossary.loader import Glossary
from backend.extract import extract
from backend.speaker_notes import processing,enabled
import test_document_languages as fixtures
SAMPLES=fixtures.SAMPLES
from test_cross_language_quality import Model as BaseModel

class Model(BaseModel):
    def chat_json(self,prompt,system='',**options):
        try:data=json.JSONDecoder().raw_decode(prompt)[0]
        except json.JSONDecodeError:
            self.requests.append((prompt,system));self.translations+=1;return {'translation':self.target}
        if '候选及英文原文语境' in data:return {'people':[]}
        return super().chat_json(prompt,system,**options)

class SpeakerNotesTests(unittest.TestCase):
    setUp=fixtures.DocumentLanguageTests.setUp
    restore=fixtures.DocumentLanguageTests.restore
    source=fixtures.DocumentLanguageTests.source
    job=fixtures.DocumentLanguageTests.job
    options=fixtures.DocumentLanguageTests.options

    def deck(self,src='zh-CN',name='fixture'):
        from pptx import Presentation
        path=self.source('.pptx',SAMPLES[src],name);d=Presentation(path)
        d.slides[0].notes_slide.notes_text_frame.text=('补充说明。' if src=='zh-CN' else 'Additional instructions. ')+SAMPLES[src]
        d.save(path);return path

    def notes(self,path):
        with ZipFile(path) as z:return {n:z.read(n) for n in z.namelist() if n.startswith('ppt/notesSlides/')}

    def test_translation_notes_default_off_and_explicit_on_for_all_document_targets(self):
        for dst in ('en-US','zh-CN','zh-Hant-TW','ja-JP','ko'):
            src='en-US' if dst=='zh-CN' else 'zh-CN'
            for include in (False,True):
                with self.subTest(dst=dst,include=include):
                    path=self.deck(src,dst+str(include));original=path.read_bytes();notes=self.notes(path);model=Model(SAMPLES[dst])
                    result=translate_file(path,Glossary([]),None,output_dir=self.root/(dst+str(include)+'-output'),client=model,
                        direction=src+'>'+dst if (src,dst) not in [('zh-CN','en-US'),('en-US','zh-CN')] else 'zh-en' if dst=='en-US' else 'en-zh',
                        include_ppt_notes=include,defer_visual=True)
                    self.assertTrue(result['translation_complete'],result.get('review_items'))
                    self.assertEqual(result['translated'],2 if include else 1);self.assertEqual(result['resumed_segments'],0)
                    self.assertEqual(path.read_bytes(),original)
                    if include:self.assertNotEqual(self.notes(result['path']),notes)
                    else:self.assertEqual(self.notes(result['path']),notes)
                    rows=comparison.read(result['comparison_id'])['rows']
                    self.assertEqual(sum('/notes/' in r['locator'] for r in rows),int(include))
                    comparison.update(result['comparison_id'],result['path'])
                    self.assertEqual(sum('/notes/' in r['locator'] for r in comparison.read(result['comparison_id'])['rows']),int(include))

    def test_combined_review_and_final_save_obey_the_same_scope(self):
        for include in (False,True):
            path=self.deck('en-US','combined'+str(include));notes=self.notes(path);data=self.options(path,'en-US','ja-JP')
            data['include_ppt_notes']=include;model=Model(SAMPLES['ja-JP']);job=self.job(data,model)
            self.assertEqual(job['status'],'complete',job.get('result'))
            report=workflow.REPORTS[job['id']]
            self.assertEqual(report['include_ppt_notes'],include)
            self.assertEqual(sum(s.source=='notes' for s in report['segments']),int(include))
            out=job['result']['outputs'][0]
            saved=workflow.apply_report({'report_id':job['id'],'path':out['path'],'save_unchanged':True},client=model)
            self.assertEqual(saved['output_audit']['status'],'complete')
            if not include:self.assertEqual(self.notes(saved['output']),notes)
            self.assertFalse(enabled())

    def test_context_isolated_and_checkpoint_scope_cannot_mix_notes(self):
        from concurrent.futures import ThreadPoolExecutor
        from backend.checkpoints import Checkpoint
        from backend.task_resume import guard
        path=self.deck();identity={'source':str(path),'fingerprint':'fixture'}
        off=Checkpoint('notes-test',identity).scope
        with processing(True):
            on=Checkpoint('notes-test',identity).scope
            self.assertEqual(sum(s.source=='notes' for s in extract(str(path))),1)
        self.assertNotEqual(off,on);self.assertFalse(any(s.source=='notes' for s in extract(str(path))))
        def worker(flag):
            with processing(flag):return sum(s.source=='notes' for s in extract(str(path)))
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(list(pool.map(worker,[True,False])),[1,0])
        with self.assertRaisesRegex(ValueError,'备注'):guard({}, {'include_ppt_notes':False})
        guard({}, {'include_ppt_notes':True})

    def test_history_remembers_new_scope_and_preserves_legacy_resume(self):
        path=self.deck();data={'kind':'translate','paths':[str(path)]}
        history.begin('new-notes',data)
        self.assertIs(history.resume_options('new-notes')['include_ppt_notes'],False)
        with history.connection() as db:
            row=history.record('new-notes');row['resume_options'].pop('include_ppt_notes')
            db.execute('UPDATE tasks SET payload=? WHERE id=?',(json.dumps(row),'new-notes'))
        self.assertIs(history.resume_options('new-notes')['include_ppt_notes'],True)
        with self.assertRaisesRegex(ValueError,'备注'):workflow.start({**data,'include_ppt_notes':'false'})

if __name__=='__main__':unittest.main()
