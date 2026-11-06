"""Reviewed replacements retain meaningful styles and explicit resolution state."""
import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.replacer.run_utils import replace_spans

class ReviewReplacementTests(unittest.TestCase):
    def test_spacer_only_styles_cannot_create_visible_text_in_any_target_language(self):
        from backend.replacer.styled_text import response_runs,dominant_runs,StyleMappingError
        groups=[{'id':0,'text':'网口带载','key':('yellow',)}, {'id':1,'text':' ','key':('dark',)},
                {'id':2,'text':' × ','key':('white',)}, {'id':3,'text':'刷新率','key':('white',)}]
        for label in ('Port capacity','网口带载','網路埠帶載','ポート負荷容量','포트 부하 용량'):
            with self.subTest(label=label):
                text=label+' × Rate'
                bad=[{'id':0,'text':label[:1]},{'id':1,'text':label[1:]+' '},{'id':2,'text':'× '},{'id':3,'text':'Rate'}]
                with self.assertRaisesRegex(StyleMappingError,'只用于空白'):response_runs({'runs':bad},text,groups)
                good=[{'id':0,'text':label},{'id':1,'text':' '},{'id':2,'text':'× '},{'id':3,'text':'Rate'}]
                self.assertEqual(response_runs({'runs':good},text,groups),good)
        # A space may share a genuinely visible body style; it is not a new,
        # unauthored dark/default style and remains valid for natural grammar.
        ordinary=[{**g,'key':('white',)} if g['id']==1 else g for g in groups]
        self.assertEqual(response_runs({'runs':bad},text,ordinary),bad)
        crowded=groups+[{'id':i,'text':' ','key':('dark',)} for i in range(4,20)]
        self.assertIn(dominant_runs('Visible body',crowded)[0]['id'],(2,3))

    def test_shared_style_writer_keeps_whole_translated_term_yellow(self):
        from pptx import Presentation
        from pptx.util import Inches
        from pptx.dml.color import RGBColor
        from backend.replacer.styled_text import style_groups,response_runs,write_styled
        deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6])
        p=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(8),Inches(1)).text_frame.paragraphs[0]
        for value,color in [('网口带载','FFC000'),(' ','000000'),(' × 刷新率','FFFFFF')]:
            r=p.add_run();r.text=value;r.font.color.rgb=RGBColor.from_string(color)
        groups=style_groups(p);text='포트 부하 용량 × 주파수'
        runs=response_runs({'runs':[{'id':0,'text':'포트 부하 용량'},{'id':1,'text':' '},{'id':2,'text':'× 주파수'}]},text,groups)
        write_styled(p,groups,runs)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'written.pptx';deck.save(path)
            p=Presentation(path).slides[0].shapes[0].text_frame.paragraphs[0]
            self.assertEqual(p.text,text)
            self.assertEqual(str(next(r for r in p.runs if '용량' in r.text).font.color.rgb),'FFC000')
            self.assertEqual(str(next(r for r in p.runs if '주파수' in r.text).font.color.rgb),'FFFFFF')

    def test_rgb_revisions_do_not_inherit_unstyled_separators(self):
        from pptx import Presentation
        from pptx.util import Inches
        from pptx.dml.color import RGBColor
        from pptx.enum.dml import MSO_THEME_COLOR
        from backend.replacer.text_runs import text_runs
        for theme in (False,True):
            deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6])
            paragraph=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(8),Inches(1)).text_frame.paragraphs[0]
            letters={'R':'FF0000','G':'00B050','B':'00B0F0'}
            for letter,color in letters.items():
                r=paragraph.add_run();r.text=letter;r.font.color.rgb=RGBColor.from_string(color)
                paragraph.add_run().text=' '
                word=paragraph.add_run();word.text='Bit depth + '
                if theme:word.font.color.theme_color=MSO_THEME_COLOR.BACKGROUND_1
                else:word.font.color.rgb=RGBColor(255,255,255)
                word.font.bold=True
            original=paragraph.text
            from difflib import SequenceMatcher
            target=original.replace(' Bit depth','ビット深度')
            spans=[(a,b,target[c:d]) for op,a,b,c,d in SequenceMatcher(None,original,target,autojunk=False).get_opcodes() if op!='equal']
            replace_spans(text_runs(paragraph),spans)
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'rgb.pptx';deck.save(path)
                saved=Presentation(path).slides[0].shapes[0].text_frame.paragraphs[0]
                self.assertEqual(saved.text,target)
                words=[r for r in saved.runs if 'ビット深度' in r.text]
                self.assertEqual(len(words),3)
                for run in words:
                    self.assertTrue(run.font.bold)
                    if theme:self.assertEqual(run.font.color.theme_color,MSO_THEME_COLOR.BACKGROUND_1)
                    else:self.assertEqual(str(run.font.color.rgb),'FFFFFF')
                for letter,color in letters.items():
                    self.assertEqual(str(next(r for r in saved.runs if r.text==letter).font.color.rgb),color)

    def test_word_replacement_inherits_the_word_and_keeps_outer_style(self):
        from docx import Document
        doc=Document();p=doc.add_paragraph();p.add_run('Label').bold=True;p.add_run(' ')
        word=p.add_run('old');word.italic=True;p.add_run(' suffix').underline=True
        replace_spans(list(p.runs),[(5,9,'新词')])
        self.assertEqual(p.text,'Label新词 suffix')
        self.assertTrue(next(r for r in p.runs if r.text=='新词').italic)
        self.assertTrue(p.runs[0].bold);self.assertTrue(p.runs[-1].underline)

class ConflictTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'profile')});env.start();self.addCleanup(env.stop)

    def report(self,unsafe=False):
        from docx import Document
        from backend import workflow
        from backend.extract import extract
        from backend.glossary.store import fingerprint
        from backend.models import Finding
        doc=Document();doc.add_paragraph('This is an ordinary use rate.');path=self.root/'source.docx';doc.save(path)
        segments=extract(str(path));segment=segments[0]
        def finding(old,new,standard=False):
            return Finding(segment_id=segment.id,file=path.name,file_path=str(path),slide=None,para=1,source='text',found_text=old,suggested=new,
                kind='term' if standard else 'grammar',reason='Confirmed standard' if standard else 'Wording preference',terminology_standard=standard)
        findings=[finding(segment.text,'This is an ordinary usage rate.'),finding('ordinary use rate','normal utilization rate'+(' 99' if unsafe else ''),True)]
        ident='conflict-'+str(id(self));workflow.REPORTS[ident]={'segments':segments,'hashes':{str(path):fingerprint(path)},'findings':findings}
        self.addCleanup(lambda:workflow.REPORTS.pop(ident,None))
        return ident,path,findings

    def apply(self,ident,path,findings,indices):
        from backend import workflow
        return workflow.apply_report({'report_id':ident,'path':str(path),'edits':[{'index':i,'text':findings[i].suggested} for i in indices]})

    def test_selected_standard_wins_over_conflicting_wording_in_both_orders(self):
        from docx import Document
        for order in ([0,1],[1,0]):
            with self.subTest(order=order):
                ident,path,findings=self.report();before=path.read_bytes();result=self.apply(ident,path,findings,order)
                self.assertEqual(Document(result['output']).paragraphs[0].text,'This is an normal utilization rate.')
                self.assertEqual(result['failed'],[]);self.assertEqual(path.read_bytes(),before)
                self.assertTrue(findings[1].applied);self.assertFalse(findings[0].applied)
                self.assertEqual(findings[0].review_status,'superseded');self.assertFalse(findings[0].editable)

    def test_unselected_standard_is_not_silently_applied_or_marked_done(self):
        from docx import Document
        ident,path,findings=self.report();result=self.apply(ident,path,findings,[0])
        self.assertEqual(Document(result['output']).paragraphs[0].text,'This is an ordinary usage rate.')
        self.assertFalse(findings[1].applied);self.assertFalse(findings[1].editable)
        self.assertEqual(findings[1].review_status,'stale');self.assertIn('未应用',findings[1].not_editable_reason)

    def test_unsafe_standard_still_fails_and_does_not_suppress_valid_grammar(self):
        from docx import Document
        ident,path,findings=self.report(unsafe=True)
        # Reverse/multilingual revision validation checks added quantities.
        from backend import workflow
        workflow.REPORTS[ident]['direction']='en-zh'
        from unittest.mock import patch
        def check(old,new):
            if '99' in new:raise ValueError('number changed')
        with patch('backend.reverse_translation.validate_revision',side_effect=check):result=self.apply(ident,path,findings,[0,1])
        self.assertTrue(result['failed']);self.assertTrue(findings[0].applied);self.assertFalse(findings[1].applied)
        self.assertNotEqual(findings[0].review_status,'superseded')
        self.assertIn('ordinary usage rate',Document(result['output']).paragraphs[0].text)

if __name__=='__main__':unittest.main()
