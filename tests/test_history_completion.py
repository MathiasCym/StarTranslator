import os,sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import history


class HistoryCompletionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':temp.name});env.start();self.addCleanup(env.stop)
        self.data={'kind':'translate_review','paths':['source.pptx']}
    def finish(self,**changes):
        job={'id':'task','status':'complete','can_resume':False,'result':{
            'stats':{'model_status':'complete','review_processing_status':'complete','findings':8,'errors':0},
            'outputs':[{'path':'draft.pptx','source':'source.pptx','staged':True,'needs_review':175}]}}
        job.update(changes);history.finish(job,self.data)
        return history.query()['records'][0]
    def test_warnings_and_partial_or_no_acceptance_are_completed_processing(self):
        row=self.finish();self.assertEqual(row['status'],'complete');self.assertTrue(row['awaiting_confirmation'])
        history.exported('task','source.pptx','saved.pptx',5,[],False)
        row=history.query()['records'][0]
        self.assertEqual(row['status'],'complete');self.assertEqual(row['counts']['replaced'],5)
        self.assertFalse(row['awaiting_confirmation'])
        history.exported('task','source.pptx','saved-again.pptx',0,[],False)
        self.assertEqual(history.query()['records'][0]['status'],'complete')
    def test_real_partial_workflow_and_failed_exports_stay_partial(self):
        self.assertEqual(self.finish(status='partial',can_resume=True)['status'],'partial')
        self.finish();history.exported('task','source.pptx','saved.pptx',0,[{'error':'Write failed'}],False)
        self.assertEqual(history.query()['records'][0]['status'],'partial')
    def test_legacy_warning_only_record_is_presented_without_changing_the_log(self):
        row=self.finish();row.pop('processing_status');row['status']='partial'
        original=json.dumps(row)
        with history.connection() as db:db.execute('UPDATE tasks SET status=?,payload=? WHERE id=?',('partial',original,'task'))
        self.assertEqual(history.query()['records'][0]['status'],'complete')
        with history.connection() as db:self.assertEqual(db.execute('SELECT payload FROM tasks WHERE id=?',('task',)).fetchone()[0],original)
        for changes in [{'errors':[{'error':'interrupted'}]},{'can_resume':True},{'counts':{'model_status':'partial'}},{'counts':{'model_status':'complete','truncated':1}},{'counts':{'model_status':'complete','residual_chinese':1}}]:
            self.assertEqual(history.display_record({**row,**changes})['status'],'partial')


if __name__=='__main__':unittest.main()
