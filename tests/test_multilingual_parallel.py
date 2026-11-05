"""Concurrency changes scheduling, never the model gates or Office writer."""
import json
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from backend import multilingual_documents as documents, task_resume
from backend.multilingual_parallel import ordered_pages
from backend.translation import Cancelled
from backend.glossary.loader import Glossary
from backend.extract import extract
import test_document_languages as fixtures
from test_document_languages import Model, SAMPLES


class SlowModel(Model):
    def __init__(self):
        super().__init__(SAMPLES['ja-JP'])
        self.lock=threading.Lock();self.active=0;self.maximum=0

    def chat_json(self,prompt,system='',**options):
        with self.lock:
            self.active+=1;self.maximum=max(self.maximum,self.active)
        try:
            time.sleep(.025)
            return super().chat_json(prompt,system,**options)
        finally:
            with self.lock:self.active-=1


class ParallelTests(unittest.TestCase):
    setUp=fixtures.DocumentLanguageTests.setUp
    restore=fixtures.DocumentLanguageTests.restore

    def deck(self):
        from pptx import Presentation
        from pptx.util import Inches
        deck=Presentation()
        for _ in range(3):
            slide=deck.slides.add_slide(deck.slide_layouts[6])
            for row in range(2):
                box=slide.shapes.add_textbox(Inches(1),Inches(1+row*2),Inches(8),Inches(1.5))
                box.text=SAMPLES['en-US']
        path=self.root/'pages.pptx';deck.save(path);return path

    def translate(self,path,workers,model):
        return documents.translate_file(str(path),Glossary([]),None,str(self.root/f'out-{workers}'),
            client=model,workers=workers,direction='en-US>ja-JP')

    def test_page_parallelism_keeps_gates_source_order_and_owner_xml_writer(self):
        path=self.deck();before=path.read_bytes();owner=threading.get_ident()
        original=documents.write_styled;writes=[]
        def write(*args):
            writes.append(threading.get_ident());self.assertEqual(writes[-1],owner)
            return original(*args)
        model=SlowModel()
        with patch.object(documents,'write_styled',side_effect=write):result=self.translate(path,3,model)
        self.assertTrue(result['translation_complete'],result['review_items'])
        self.assertGreaterEqual(model.maximum,2);self.assertLessEqual(model.maximum,3)
        self.assertEqual(model.translations,6)
        self.assertEqual(sum('译文' in json.loads(p) for p,_ in model.requests),6)
        self.assertEqual(len(writes),6);self.assertEqual(path.read_bytes(),before)
        self.assertEqual([s.slide for s in extract(result['path']) if s.editable],[1,1,2,2,3,3])
        self.assertEqual([s.text for s in extract(result['path']) if s.editable],[SAMPLES['ja-JP']]*6)

    def test_workers_one_remains_serial_and_identical_to_parallel(self):
        path=self.deck();serial=SlowModel();parallel=SlowModel()
        with task_resume.activate('serial'):a=self.translate(path,1,serial)
        with task_resume.activate('parallel'):b=self.translate(path,3,parallel)
        self.assertEqual(serial.maximum,1);self.assertGreaterEqual(parallel.maximum,2)
        self.assertEqual(serial.translations,parallel.translations)
        self.assertEqual([s.text for s in extract(a['path'])],[s.text for s in extract(b['path'])])

    def test_review_honors_workers_and_returns_findings_in_source_order(self):
        path=self.deck();segments=extract(path)
        for s in segments:s.text=SAMPLES['ja-JP']+' TEST TEST'
        model=SlowModel();owner=threading.get_ident();emitted=[]
        def finding(items):
            self.assertEqual(threading.get_ident(),owner);emitted.extend(items)
        findings,stats=documents.check_segments(segments,Glossary([]),client=model,
            target_language='ja-JP',workers=3,on_finding=finding)
        self.assertEqual(stats['model_status'],'complete');self.assertGreaterEqual(model.maximum,2)
        self.assertEqual([f.segment_id for f in findings],[s.id for s in segments])
        self.assertEqual([f['segment_id'] for f in emitted],[s.id for s in segments])

    def test_parallel_checkpoints_reuse_only_on_explicit_same_session(self):
        path=self.deck()
        with task_resume.activate('original'):first=self.translate(path,3,SlowModel())
        reused=SlowModel()
        with task_resume.activate('original'):second=self.translate(path,3,reused)
        fresh=SlowModel()
        with task_resume.activate('new-task'):third=self.translate(path,3,fresh)
        self.assertEqual(first['resumed_segments'],0);self.assertEqual(second['resumed_segments'],6)
        self.assertEqual(reused.translations,0);self.assertEqual(third['resumed_segments'],0)
        self.assertEqual(fresh.translations,6)

    def test_worker_context_is_copied_and_source_order_survives_reverse_completion(self):
        from types import SimpleNamespace
        items=[SimpleNamespace(file_path='one',slide=i) for i in range(6)]
        identities=[]
        def work(item):
            identities.append(task_resume.checkpoint_identity({})[0].get('task_session'))
            time.sleep(.01*(3-item.slide%3));return item.slide
        with task_resume.activate('explicit-session'):
            result=list(ordered_pages(items,work,3,threading.Event(),lambda i:i))
        self.assertEqual(result,list(range(6)));self.assertEqual(identities,['explicit-session']*6)

    def test_cancel_stops_submission_and_no_page_work_outlives_the_task(self):
        from types import SimpleNamespace
        cancel=threading.Event();started=[];finished=[]
        items=[SimpleNamespace(file_path='one',slide=i) for i in range(20)]
        def work(item):
            started.append(item.slide)
            if item.slide==0:cancel.set()
            time.sleep(.01);finished.append(item.slide);return item.slide
        with self.assertRaises(Cancelled):list(ordered_pages(items,work,3,cancel,lambda i:i))
        self.assertLessEqual(len(started),3);self.assertCountEqual(started,finished)

    def test_writer_failure_restores_that_paragraph_and_preserves_other_pages(self):
        path=self.deck();owner=threading.get_ident();original=documents.write_styled;calls=[]
        def write(paragraph,groups,runs):
            self.assertEqual(threading.get_ident(),owner);calls.append(1)
            if len(calls)==1:
                paragraph._p.clear();raise ValueError('synthetic local writer failure')
            return original(paragraph,groups,runs)
        with patch.object(documents,'write_styled',side_effect=write):result=self.translate(path,3,SlowModel())
        self.assertEqual(result['untranslated'],1);self.assertEqual(result['translated'],5)
        texts=[s.text for s in extract(result['path']) if s.editable]
        self.assertEqual(texts[0],SAMPLES['en-US']);self.assertEqual(texts[1:],[SAMPLES['ja-JP']]*5)

    def test_completed_future_timeout_is_not_an_endless_wait(self):
        from types import SimpleNamespace
        items=[SimpleNamespace(file_path='one',slide=i) for i in range(3)]
        def work(item):raise TimeoutError('completed model call failed')
        with self.assertRaisesRegex(TimeoutError,'completed model call failed'):
            list(ordered_pages(items,work,3,threading.Event(),lambda i:i))


if __name__=='__main__':unittest.main()
