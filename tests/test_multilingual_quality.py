"""Never confuse shared Japanese Kanji with untranslated Chinese prose."""
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend import multilingual_documents as documents,text_languages,task_resume,workflow
from backend.multilingual_quality import LanguageReview,IncompleteLanguageReview,script_positions
from backend.glossary.loader import Glossary
from backend.extract import extract
from backend.checkpoints import open_checkpoint,translation_key
from backend.glossary import store
import test_document_languages as fixtures


def certificate(source,target):
    q=LanguageReview('zh-CN','ja-JP')
    return {'ok':True,'issues':[],'unchanged_source_spans':[
        {'text':word,'target_language':'ja-JP','valid':True,'reason':'Established Japanese term in this context.'}
        for word in q.candidates(source,target)]}


class LanguageModel(fixtures.Model):
    def chat_json(self,prompt,system='',**options):
        data=json.JSONDecoder().raw_decode(prompt)[0]
        if '译文' in data:
            self.requests.append((prompt,system))
            return certificate(data['原文'],data['译文'])
        return super().chat_json(prompt,system,**options)


class QualityTests(unittest.TestCase):
    setUp=fixtures.DocumentLanguageTests.setUp
    restore=fixtures.DocumentLanguageTests.restore
    source=fixtures.DocumentLanguageTests.source
    job=fixtures.DocumentLanguageTests.job
    options=fixtures.DocumentLanguageTests.options

    @unittest.skipUnless(sys.platform=='win32','Windows script conversion')
    def test_traditional_repair_preserves_runs_links_and_count(self):
        from pptx import Presentation
        from pptx.util import Inches
        from backend.multilingual_quality import faithful_traditional_conversion
        from backend import document_translation_policy
        deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6])
        shape=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(7),Inches(1))
        paragraph=shape.text_frame.paragraphs[0]
        run=paragraph.add_run();run.text='每一块 LED 屏幕';run.font.bold=True
        run=paragraph.add_run();run.text='必须有统一的标准。'
        shape=slide.shapes.add_textbox(Inches(1),Inches(2),Inches(7),Inches(1))
        shape.text='2021《“十四五”规划》：影院装备和电影技术升级。'
        shape=slide.shapes.add_textbox(Inches(1),Inches(3),Inches(7),Inches(1))
        shape.text='案例展示'
        source=self.root/'script-repair.pptx';deck.save(source)
        def refuse(*args,**kwargs):raise ValueError('模型复核重复拒绝同一位置')
        model=fixtures.Model('')
        with patch('backend.multilingual_documents.mapped',side_effect=refuse),document_translation_policy.combined_processing(False):
            output=documents.translate_file(str(source),Glossary([]),None,self.root/'translated',
                client=model,workers=1,direction='zh-CN>zh-Hant-TW',defer_visual=True)
        self.assertEqual(output['untranslated'],0);self.assertEqual(output['output_audit']['status'],'complete')
        translated=Presentation(output['path']).slides[0].shapes
        self.assertEqual(translated[0].text,'每一塊 LED 屏幕必須有統一的標準。')
        self.assertEqual(translated[0].text_frame.paragraphs[0].runs[0].text,'每一塊 LED 屏幕')
        self.assertTrue(translated[0].text_frame.paragraphs[0].runs[0].font.bold)
        self.assertIn('規劃',translated[1].text);self.assertEqual(translated[2].text,'案例展示')
        self.assertEqual(faithful_traditional_conversion('显示 https://example.com/简体 `显示`'),'顯示 https://example.com/简体 `显示`')
        self.assertIsNone(faithful_traditional_conversion('头发与发展'))

    def test_short_term_review_uses_page_context_and_requires_actionable_errors(self):
        context='8 bit / 10 bit / 12 bit 表格字段'
        class ReviewModel:
            def __init__(self):self.calls=[]
            def chat_json(inner,prompt,**options):
                data=json.JSONDecoder().raw_decode(prompt)[0];inner.calls.append(data)
                if '待译原文' in data:return {'translation':'色深度'}
                self.assertEqual(data['相邻原文（仅供理解）'],context)
                if len(inner.calls)==2:return {'ok':False,'issues':['色深度是正确日语，但需要确认原文省略。']}
                return certificate('色深','色深度')
        model=ReviewModel()
        result=text_languages.translate_piece(model,'色深',None,'zh-CN','ja-JP',threading.Event(),
            context=context,quality=LanguageReview('zh-CN','ja-JP'),terminology=False)
        self.assertEqual(result,'色深度');self.assertEqual(len(model.calls),3)
        self.assertEqual(sum('待译原文' in row for row in model.calls),1)

    def test_document_rejected_wording_is_independently_adjudicated_without_weakening_review(self):
        class ReviewModel:
            supports_thinking_mode=True
            def __init__(self,inconclusive=False):self.calls=[];self.inconclusive=inconclusive
            def chat_json(inner,prompt,**options):
                data=json.JSONDecoder().raw_decode(prompt)[0];inner.calls.append((data,options))
                if '待译原文' in data:return {'translation':'送信カードの駆動能力'}
                if '待独立裁定的复核意见' not in data:
                    return {'ok':False,'issues':['Meaning correct, but prefer literal wording.'],'corrected_translation':'送信カードの帯載'}
                if inner.inconclusive and not options.get('thinking'):
                    return {'ok':False,'issues':['No actionable correction.'],'corrected_translation':data['译文']}
                return certificate('发送卡带载','送信カードの駆動能力')
        model=ReviewModel()
        result=text_languages.translate_piece(model,'发送卡带载',None,'zh-CN','ja-JP',threading.Event(),
            context='LED表示のピクセル容量',quality=LanguageReview('zh-CN','ja-JP'),terminology=False)
        self.assertEqual(result,'送信カードの駆動能力');self.assertEqual(len(model.calls),3)
        self.assertNotIn('thinking',model.calls[0][1]);self.assertNotIn('thinking',model.calls[1][1])
        self.assertNotIn('thinking',model.calls[2][1])
        model=ReviewModel(inconclusive=True)
        result=text_languages.translate_piece(model,'发送卡带载',None,'zh-CN','ja-JP',threading.Event(),
            quality=LanguageReview('zh-CN','ja-JP'),terminology=False)
        self.assertEqual(result,'送信カードの駆動能力');self.assertEqual(len(model.calls),4)
        self.assertTrue(model.calls[3][1]['thinking'])

    def test_mixed_english_notes_keep_exact_counts_without_language_selector_guessing(self):
        for src in ('zh-CN','en-US'):
            for target in ('1つの出力ポートに接続します。','一つの出力ポートに接続します。'):
                text_languages.validate('Connect to one output port.',target,src,'ja-JP')
            for bad in ('2つの出力ポートに接続します。','出力ポートに接続します。','1つの出力ポートと1台の装置に接続します。'):
                with self.assertRaisesRegex(ValueError,'数字'):
                    text_languages.validate('Connect to one output port.',bad,src,'ja-JP')
        text_languages.validate('Twenty-four controllers use 60 Hz.','24台のコントローラーは60 Hzを使用します。','zh-CN','ja-JP')
        text_languages.validate('Use one of the options.','選択肢から選びます。','zh-CN','ja-JP')
        with self.assertRaisesRegex(ValueError,'数字'):
            text_languages.validate('Use someone else’s output port.','1つの出力ポートを使用します。','zh-CN','ja-JP')
        self.assertEqual(text_languages.written_counts('一两台、两三台、one another、X-one output port'),'一两台、两三台、one another、X-one output port')

    def test_shared_kanji_are_candidates_not_automatic_chinese_and_addresses_are_opaque(self):
        q=LanguageReview('zh-CN','ja-JP');source='使用率、温度。https://example.com/中文 `控制系统`'
        target='使用率と温度。https://example.com/中文 `控制系统`'
        self.assertEqual(set(q.candidates(source,target)),{'使用率','温度'})
        with self.assertRaises(IncompleteLanguageReview):q.validate_review(source,target,{'ok':True,'issues':[]})
        q.validate_review(source,target,certificate(source,target));proof=q.proof(source,target)
        self.assertTrue(q.reusable(source,target,proof))
        self.assertFalse(q.reusable(source,target+' 使用率',proof))
        self.assertFalse(q.reusable(source,target,{**proof,'version':0}))
        self.assertEqual(LanguageReview('en-US','ja-JP').candidates('ABC','ABC'),[])

    def test_review_must_cover_every_candidate_once_with_a_reason(self):
        q=LanguageReview('zh-CN','ja-JP');source='使用率和温度';target='使用率と温度'
        good=certificate(source,target)
        for mutate in (lambda r:r.pop(),lambda r:r.append(r[0]),lambda r:r[0].update(valid=False),
                       lambda r:r[0].update(target_language='zh-CN'),lambda r:r[0].update(reason='')):
            bad=json.loads(json.dumps(good));mutate(bad['unchanged_source_spans'])
            with self.subTest(bad=bad),self.assertRaises(IncompleteLanguageReview):q.validate_review(source,target,bad)

    def test_partial_chinese_cannot_pass_with_a_few_japanese_characters(self):
        source='请检查 A8 控制系统。';bad='A8 を確認します。请检查控制系统。';good='A8 の制御システムを確認してください。'
        class Repair(LanguageModel):
            def chat_json(inner,prompt,system='',**options):
                data=json.JSONDecoder().raw_decode(prompt)[0]
                if '待译原文' in data:
                    inner.translations+=1;return {'translation':bad if inner.translations==1 else good}
                if data.get('译文')==bad:return {'ok':True,'issues':[]}  # Old false-positive review.
                return super().chat_json(prompt,system,**options)
        model=Repair(good);q=LanguageReview('zh-CN','ja-JP')
        result=text_languages.translate_piece(model,source,{},'zh-CN','ja-JP',threading.Event(),quality=q)
        self.assertEqual(result,good);self.assertEqual(model.translations,2)

    def test_corrected_translation_still_gets_independent_review(self):
        # The copied clause uses only shared glyphs, so semantic review still
        # has work even after the deterministic simplified-glyph check.
        source='確認 A8 控制機能。';bad='A8 を確認します。確認控制機能。';good='A8 の制御機能を確認してください。'
        class Repair(LanguageModel):
            def chat_json(inner,prompt,system='',**options):
                data=json.JSONDecoder().raw_decode(prompt)[0]
                if '待译原文' in data:inner.translations+=1;return {'translation':bad}
                if data.get('译文')==bad:return {'ok':False,'issues':['Chinese sentence remains.'],'corrected_translation':good}
                return super().chat_json(prompt,system,**options)
        model=Repair(good)
        result=text_languages.translate_piece(model,source,{},'zh-CN','ja-JP',threading.Event(),quality=LanguageReview('zh-CN','ja-JP'))
        self.assertEqual(result,good);self.assertEqual(model.translations,1)
        self.assertTrue(any(json.loads(p).get('译文')==good for p,_ in model.requests))

    def test_spelling_error_flag_does_not_create_fake_emphasis_work(self):
        from pptx import Presentation
        from pptx.util import Inches
        from backend.replacer.styled_text import style_groups
        deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6])
        p=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(8),Inches(2)).text_frame.paragraphs[0]
        run=p.add_run();run.text='请检查端口配置';run._r.get_or_add_rPr().set('err','1')
        p.add_run().text='。';self.assertEqual(len(style_groups(p)),1)
        path=self.root/'proofing.pptx';deck.save(path);target='ポート設定を確認してください。';model=LanguageModel(target)
        job=self.job(self.options(path,'zh-CN','ja-JP','translate'),model)
        self.assertEqual(job['status'],'complete',job);self.assertEqual(model.translations,1)
        self.assertEqual(len(model.requests),2)  # Translation plus independent content review, no style call.
        self.assertNotIn('请检查',''.join(s.text for s in extract(job['result']['outputs'][0]['path'])))

    def test_real_color_bold_and_superscript_remain_distinct_from_proofing(self):
        from pptx import Presentation
        from pptx.util import Inches
        from backend.replacer.styled_text import style_groups,slice_groups
        deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6])
        p=slide.shapes.add_textbox(Inches(1),Inches(1),Inches(8),Inches(2)).text_frame.paragraphs[0]
        p.add_run().text='1 Gbps (10'
        run=p.add_run();run.text='9';run._r.get_or_add_rPr().set('baseline','30000')
        p.add_run().text=') × 使用率'
        groups=style_groups(p);self.assertEqual(len(groups),3)
        evidence=script_positions(slice_groups(groups,0,len(p.text),visual_keys=True))
        self.assertEqual(evidence,[{'start':10,'end':11,'text':'9','baseline':'30000'}])
        model=LanguageModel(p.text)
        def chat(prompt,system='',**options):
            payload=json.JSONDecoder().raw_decode(prompt)[0]
            if '已复核的完整译文' in payload:
                if '译文样式片段' in payload:return {'ok':True,'issues':[]}
                return {'runs':[{'id':i,'text':g['text']} for i,g in enumerate(groups)]}
            if '待译原文' in payload or '译文' in payload:self.assertEqual(payload['原文上下标'],evidence)
            return original(prompt,system,**options)
        original=model.chat_json;model.chat_json=chat
        path=self.root/'exponent.pptx';deck.save(path)
        job=self.job(self.options(path,'zh-CN','ja-JP','translate'),model)
        self.assertEqual(job['status'],'complete',job)
        output=Presentation(job['result']['outputs'][0]['path']).slides[0].shapes[0].text_frame.paragraphs[0]
        superscript=[r.text for r in output.runs if r._r.get_or_add_rPr().get('baseline')=='30000']
        self.assertEqual(superscript,['9']);self.assertEqual(output.text,p.text)

    def test_ppt_soft_break_in_report_edit_is_valid_and_other_controls_stay_invalid(self):
        path=self.source('.pptx',fixtures.SAMPLES['ja-JP']+' TEST TEST')
        model=LanguageModel(fixtures.SAMPLES['ja-JP'])
        job=self.job(self.options(path,'en-US','ja-JP','check'),model)
        report=job['result'];self.assertEqual(len(report['findings']),1)
        for value in ('TEST\x00TEST','TEST\x01TEST','TEST\x0cTEST'):
            with self.subTest(value=repr(value)),self.assertRaisesRegex(ValueError,'无效字符'):
                workflow.apply_report({'report_id':report['report_id'],'path':str(path),'edits':[{'index':0,'text':value}]},client=model)
        saved=workflow.apply_report({'report_id':report['report_id'],'path':str(path),'edits':[{'index':0,'text':'TEST\vTEST'}]},client=model)
        self.assertFalse(saved['failed']);self.assertIn('TEST\vTEST',''.join(s.text for s in extract(saved['output'])))

    def test_word_still_rejects_vertical_tab_controls(self):
        path=self.source('.docx',fixtures.SAMPLES['ja-JP']+' TEST TEST');model=LanguageModel(fixtures.SAMPLES['ja-JP'])
        job=self.job(self.options(path,'en-US','ja-JP','check'),model)
        with self.assertRaisesRegex(ValueError,'无效字符'):
            workflow.apply_report({'report_id':job['result']['report_id'],'path':str(path),'edits':[{'index':0,'text':'TEST\vTEST'}]},client=model)

    def test_old_shared_kanji_checkpoint_is_reviewed_once_without_retranslation(self):
        import sqlite3
        path=self.source('.txt','使用率');glossary=Glossary([])
        def translate(model):
            with task_resume.activate('same-session'):
                return documents.translate_file(str(path),glossary,None,str(self.root/'saved'),
                    client=model,direction='zh-CN>ja-JP')
        first=translate(LanguageModel('使用率'));self.assertTrue(first['translation_complete'])
        db=store.data_dir()/'task-checkpoints.sqlite3'
        with sqlite3.connect(db) as c:
            for scope,stage,key,raw in c.execute('SELECT scope,stage,item_key,value FROM checkpoints').fetchall():
                value=json.loads(raw);value.pop('language_review',None)
                c.execute('UPDATE checkpoints SET value=? WHERE scope=? AND stage=? AND item_key=?',(json.dumps(value),scope,stage,key))
        c.close()
        upgrade=LanguageModel('使用率');second=translate(upgrade)
        self.assertEqual(second['resumed_segments'],1);self.assertEqual(upgrade.translations,0)
        self.assertEqual(len(upgrade.requests),1)
        again=LanguageModel('使用率');third=translate(again)
        self.assertEqual(third['resumed_segments'],1);self.assertEqual(again.requests,[])

    def test_reordered_chinese_fragments_and_long_text_are_still_detected(self):
        q=LanguageReview('zh-CN','ja-JP')
        source='请检查控制系统，然后更新固件。'
        target='更新固件。コントローラーを確認します。请检查控制系统。'
        values=q.candidates(source,target)
        self.assertTrue(any('控制系统' in v for v in values));self.assertTrue(any('更新固件' in v for v in values))
        self.assertEqual(q.candidates('使用率。'*5000,'使用率。'*5000),['使用率'])

    def test_repeated_soft_break_replacements_keep_native_nodes_and_literal_escape_text(self):
        from pptx import Presentation
        from pptx.util import Inches
        from backend.replacer.text_runs import text_runs
        from backend.replacer.run_utils import replace_in_runs
        d=Presentation();p=d.slides.add_slide(d.slide_layouts[6]).shapes.add_textbox(Inches(1),Inches(1),Inches(8),Inches(2)).text_frame.paragraphs[0]
        r=p.add_run();r.text='A B C _x000B_';r.font.bold=True;runs=text_runs(p)
        self.assertTrue(replace_in_runs(runs,'A B','A\vB'))
        self.assertTrue(replace_in_runs(runs,'B C','B\vC'))
        self.assertEqual(p.text,'A\vB\vC _x000B_')
        self.assertEqual(len(p._p.findall('{http://schemas.openxmlformats.org/drawingml/2006/main}br')),2)
        self.assertTrue(all(r.font.bold for r in p.runs))

    def test_failed_ppt_style_retries_only_mapping_after_verified_translation(self):
        from pptx import Presentation
        from pptx.util import Inches
        from backend.llm.client import LLMUnavailable
        d=Presentation();p=d.slides.add_slide(d.slide_layouts[6]).shapes.add_textbox(Inches(1),Inches(1),Inches(8),Inches(2)).text_frame.paragraphs[0]
        r=p.add_run();r.text='Do not';r.font.bold=True
        p.add_run().text=fixtures.SAMPLES['en-US'][6:]
        path=self.root/'style-retry.pptx';d.save(path)
        class StyleModel(LanguageModel):
            def chat_json(inner,prompt,system='',**options):
                data=json.JSONDecoder().raw_decode(prompt)[0]
                if '已复核的完整译文' in data:
                    if inner.fail_style:raise LLMUnavailable('synthetic style stage disconnect')
                    if '译文样式片段' in data:return {'ok':True,'issues':[]}
                    first,last=inner.target.split('ないでください')
                    return {'runs':[{'id':1,'text':first},{'id':0,'text':'ないでください'},{'id':1,'text':last}]}
                return super().chat_json(prompt,system,**options)
        def run(model):
            with task_resume.activate('style-session'):
                return documents.translate_file(str(path),Glossary([]),None,str(self.root/'saved'),
                    client=model,direction='en-US>ja-JP',workers=3)
        first=StyleModel(fixtures.SAMPLES['ja-JP']);first.fail_style=True
        a=run(first);self.assertEqual(a['untranslated'],0);self.assertTrue(a['style_warnings']);self.assertEqual(first.translations,1)
        second=StyleModel(fixtures.SAMPLES['ja-JP']);second.fail_style=False
        b=run(second);self.assertTrue(b['translation_complete']);self.assertEqual(second.translations,0)
        self.assertEqual(b['resumed_segments'],1)
        self.assertFalse(any('译文' in json.loads(prompt) for prompt,_ in second.requests))
        result=Presentation(b['path']).slides[0].shapes[0].text_frame.paragraphs[0]
        self.assertEqual(''.join(r.text for r in result.runs if r.font.bold),'ないでください')

    def test_note_style_failure_does_not_revert_verified_japanese_back_to_english(self):
        from pptx import Presentation
        from pptx.util import Inches
        from backend.llm.client import LLMUnavailable
        d=Presentation();s=d.slides.add_slide(d.slide_layouts[6]);s.shapes.add_textbox(Inches(1),Inches(1),Inches(6),Inches(1)).text=''
        frame=s.notes_slide.notes_text_frame;frame.clear();p=frame.paragraphs[0]
        p.add_run().text='Connect to '
        r=p.add_run();r.text='one output port.';r.font.bold=True
        path=self.root/'notes.pptx';d.save(path)
        class NoteModel(LanguageModel):
            def chat_json(inner,prompt,system='',**options):
                data=json.JSONDecoder().raw_decode(prompt)[0]
                if '已复核的完整译文' in data:raise LLMUnavailable('synthetic note style disconnect')
                return super().chat_json(prompt,system,**options)
        model=NoteModel('1つの出力ポートに接続します。')
        result=documents.translate_file(str(path),Glossary([]),None,str(self.root/'saved'),client=model,direction='zh-CN>ja-JP',workers=1,include_ppt_notes=True)
        self.assertTrue(result['translation_complete'],result['review_items'])
        self.assertTrue(any('局部强调' in w['reason'] for w in result['style_warnings']))
        from backend.speaker_notes import processing
        with processing(True):texts=[s.text for s in extract(result['path']) if s.source=='notes' and s.editable]
        self.assertIn('1つの出力ポートに接続します。',texts)


if __name__=='__main__':unittest.main()
