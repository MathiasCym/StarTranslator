"""Page cohorts, original geometry and the private image-review delivery gate."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pptx import Presentation
from pptx.util import Inches,Pt
from backend import pptx_visual_review as visual
from backend.replacer.pptx_layout import capture_layout,fit_document,_frames,_paragraph_data,FONT_STEPS
from backend.replacer.pptx_package import save_office
from backend.llm.client import LLMClient
from backend.translation import translate_file,translation_system,Cancelled
from backend.glossary.loader import Glossary


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.folder/'profile')});self.env.start()
        self.addCleanup(self.env.stop);self.addCleanup(self.temp.cleanup)
    def deck(self,pages=2):
        deck=Presentation()
        for number in range(pages):
            slide=deck.slides.add_slide(deck.slide_layouts[6])
            for x,y,w,text in ((.5,.5,4,'简短标题'),(.5,2,2,'技术说明')):
                shape=slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(.7))
                shape.text=text
                run=shape.text_frame.paragraphs[0].runs[0];run.font.name='Arial';run.font.size=Pt(24)
        source=self.folder/'source.pptx';deck.save(source)
        return deck,source
    def renderer(self,path,folder,cancel=None):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        from PIL import Image
        pages=[]
        for i in range(len(Presentation(path).slides)):
            png=folder/f'page-{i+1}.png';Image.new('RGB',(128,72),'white').save(png)
            pages.append({'image':png,'file':png.name,'shapes':[]})
        return {'pages':pages,'native':False}
    def test_same_source_style_uses_one_clean_size_on_each_page_including_english_peers(self):
        deck,source=self.deck();original=capture_layout(deck,[])
        short=deck.slides[0].shapes[0];long=deck.slides[0].shapes[1]
        short.text_frame.paragraphs[0].runs[0].text='Title'
        long.text_frame.paragraphs[0].runs[0].text='Full technical explanation for cinema display processing'
        changed=['slide1/shape1/p0'];fit_document(deck,changed,original)
        sizes=[s.text_frame.paragraphs[0].runs[0].font.size.pt for s in deck.slides[0].shapes]
        self.assertEqual(len(set(sizes)),1);self.assertIn(sizes[0],FONT_STEPS);self.assertLess(sizes[0],24)
        self.assertEqual(deck.slides[1].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt,24)
        self.assertIn('slide1/shape0/p0',changed)
        output=self.folder/'output.pptx';save_office(source,deck,output,changed)
        with ZipFile(source) as a,ZipFile(output) as b:
            self.assertEqual(a.read('ppt/slides/slide2.xml'),b.read('ppt/slides/slide2.xml'))
        self.assertEqual(long.text,'Full technical explanation for cinema display processing')
    def test_group_dimensions_scale_but_font_points_do_not(self):
        deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6]);group=slide.shapes.add_group_shape()
        shape=group.shapes.add_textbox(Inches(1),Inches(1),Inches(4),Inches(1));shape.text='Example'
        shape.text_frame.paragraphs[0].runs[0].font.size=Pt(20)
        xf=group._element.grpSpPr.xfrm;xf.ext.cx=xf.chExt.cx//2;xf.ext.cy=xf.chExt.cy//2
        frame=list(_frames(deck,['slide1/shape0/shape0/p0']))[0]
        self.assertEqual(frame[4],shape.width//2);self.assertEqual(frame[5],shape.height//2)
        self.assertEqual(_paragraph_data(shape.text_frame,shape,slide,deck)[0][1][0][1][1],20)
    def test_tracking_is_measured_in_hundredths_of_a_point(self):
        deck,_=self.deck(1);shape=deck.slides[0].shapes[0]
        shape.text_frame.paragraphs[0].runs[0]._r.get_or_add_rPr().set('spc','1000')
        self.assertEqual(_paragraph_data(shape.text_frame,shape,deck.slides[0],deck)[0][1][0][1][4],10)
    def test_translated_tracking_is_adapted_before_font_reduction_without_moving_textbox(self):
        deck,_=self.deck(1);shape=deck.slides[0].shapes[0];run=shape.text_frame.paragraphs[0].runs[0]
        run._r.get_or_add_rPr().set('spc','300');snapshot=capture_layout(deck,['slide1/shape0/p0'])
        geometry=(shape.left,shape.top,shape.width,shape.height);run.text='A clear English title'
        fit_document(deck,['slide1/shape0/p0'],snapshot)
        self.assertEqual((shape.left,shape.top,shape.width,shape.height),geometry)
        self.assertLessEqual(float(run._r.rPr.get('spc'))/100,.72)
        self.assertEqual(run.text,'A clear English title')
    def test_package_guard_refuses_alignment_and_margin_changes(self):
        from pptx.enum.text import PP_ALIGN
        for mode in ('margin','alignment'):
            deck,source=self.deck(1);shape=deck.slides[0].shapes[0]
            if mode=='margin':shape.text_frame.margin_left=Pt(30)
            else:shape.text_frame.paragraphs[0].alignment=PP_ALIGN.CENTER
            with self.assertRaisesRegex(ValueError,'对象结构'):
                save_office(source,deck,self.folder/'bad.pptx',['slide1/shape0/p0'])
    def test_scaled_numbers_keep_special_font_size_and_bold_on_page_two(self):
        from backend.replacer.styled_text import style_groups,anchored_runs,write_styled,response_runs,StyleMappingError
        deck=Presentation();deck.slides.add_slide(deck.slide_layouts[6]);slide=deck.slides.add_slide(deck.slide_layouts[6])
        shape=slide.shapes.add_textbox(Inches(.5),Inches(.5),Inches(7),Inches(1.2));para=shape.text_frame.paragraphs[0]
        r=para.add_run();r.text='21.4万';r.font.name='Arial';r.font.size=Pt(24);r.font.bold=True
        r=para.add_run();r.text='块，市场体量庞大';r.font.name='Arial';r.font.size=Pt(14);r.font.bold=False
        groups=style_groups(para);snapshot=capture_layout(deck,['slide2/shape0/p0'])
        translated='214,000 screens offer a large market.'
        styled,unresolved=anchored_runs(translated,groups)
        self.assertFalse(unresolved);self.assertEqual(styled[0]['text'],'214,000')
        write_styled(para,groups,styled);fit_document(deck,['slide2/shape0/p0'],snapshot)
        self.assertEqual(para.runs[0].font.size.pt,24);self.assertTrue(para.runs[0].font.bold)
        self.assertEqual(para.runs[0].font.name,'Arial');self.assertEqual(para.runs[1].font.size.pt,14)
        with self.assertRaises(StyleMappingError):
            response_runs({'runs':[{'id':1,'text':'214,000 screens offer a '},{'id':0,'text':'large market.'}]},translated,groups)
    def test_package_guard_refuses_geometry_changes(self):
        deck,source=self.deck();deck.slides[0].shapes[0].left+=Inches(1)
        with self.assertRaisesRegex(ValueError,'对象结构'):
            save_office(source,deck,self.folder/'bad.pptx',['slide1/shape0/p0'])
    def test_every_page_is_reviewed_and_private_images_are_removed(self):
        deck,source=self.deck(3);out=self.folder/'out.pptx';save_office(source,deck,out,[])
        calls=[]
        class Vision:
            def chat_images_json(_,prompt,images,**kwargs):
                calls.append((prompt,list(images)))
                self.assertEqual(len(images),2);self.assertTrue(all(Path(p).is_file() for p in images))
                return {'reviewed':True,'issues':[]}
        with patch.object(visual,'render_pages',side_effect=self.renderer):
            issues,fixes=visual.review_pptx(source,out,deck,[],capture_layout(deck,[]),Vision())
        self.assertEqual(issues,[]);self.assertEqual(len(calls),3)
        self.assertTrue(all(not Path(p).exists() for _,images in calls for p in images))
        self.assertNotIn('image',json.dumps(issues))
    def test_visual_repair_changes_only_typography_and_rereviews_affected_page(self):
        deck,source=self.deck();changed=['slide1/shape0/p0'];snapshot=capture_layout(deck,changed)
        out=self.folder/'out.pptx';save_office(source,deck,out,[]);text=deck.slides[0].shapes[0].text
        answers=iter([{'reviewed':True,'issues':[{'shape_id':deck.slides[0].shapes[0].shape_id,'kind':'crowded','reason':'文字拥挤'}]},
                      {'reviewed':True,'issues':[]},{'reviewed':True,'issues':[]}]);calls=[]
        class Vision:
            def chat_images_json(_,prompt,images,**kwargs):calls.append(prompt);return next(answers)
        with patch.object(visual,'render_pages',side_effect=self.renderer):
            issues,fixes=visual.review_pptx(source,out,deck,changed,snapshot,Vision())
        self.assertFalse(issues);self.assertEqual(len(calls),3);self.assertIn('第 1 页',calls[-1])
        self.assertEqual(deck.slides[0].shapes[0].text,text)
        self.assertEqual(deck.slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt,22)
        self.assertEqual(deck.slides[0].shapes[1].text_frame.paragraphs[0].runs[0].font.size.pt,22)
        self.assertTrue(fixes)
    def test_unavailable_or_invalid_image_review_cannot_claim_success(self):
        deck,source=self.deck();out=self.folder/'out.pptx';save_office(source,deck,out,[])
        class Vision:
            def chat_images_json(_,prompt,**kwargs):return {'reviewed':False,'issues':[]}
        with patch.object(visual,'render_pages',side_effect=self.renderer):
            issues,_=visual.review_pptx(source,out,deck,[],capture_layout(deck,[]),Vision())
        self.assertTrue(issues)
        self.assertTrue(visual.review_pptx(source,out,deck,[],{},object())[0])
    def test_worse_visual_repairs_keep_the_best_complete_file(self):
        deck,source=self.deck(1);out=self.folder/'out.pptx';save_office(source,deck,out,[])
        original=out.read_bytes();sid=deck.slides[0].shapes[0].shape_id;count=[0]
        class Vision:
            def chat_images_json(_,prompt,images,**kwargs):
                count[0]+=1
                return {'reviewed':True,'issues':[{'shape_id':sid,'kind':'overlap','reason':'重叠'}]*count[0]}
        with patch.object(visual,'render_pages',side_effect=self.renderer):
            issues,fixes=visual.review_pptx(source,out,deck,['slide1/shape0/p0'],capture_layout(deck,[]),Vision())
        self.assertEqual(out.read_bytes(),original);self.assertEqual(len(issues),1)
        self.assertEqual(count[0],3);self.assertEqual(fixes,[])
    def test_cancellation_exits_and_cleans_private_images(self):
        deck,source=self.deck();out=self.folder/'out.pptx';save_office(source,deck,out,[]);cancel=threading.Event();paths=[]
        class Vision:
            def chat_images_json(_,prompt,images,**kwargs):paths.extend(images);cancel.set();return {'reviewed':True,'issues':[]}
        with patch.object(visual,'render_pages',side_effect=self.renderer),self.assertRaises(Cancelled):
            visual.review_pptx(source,out,deck,[],capture_layout(deck,[]),Vision(),cancel)
        self.assertTrue(all(not p.exists() for p in paths))
    def test_incomplete_image_review_still_exports_without_exposing_internal_files(self):
        deck,source=self.deck(1)
        class Model:
            def chat_json(_,prompt,**kwargs):return {'translation':'Technical explanation'}
        original=source.read_bytes()
        result=translate_file(str(source),Glossary([]),None,client=Model())
        self.assertEqual(source.read_bytes(),original)
        self.assertTrue(Path(result['path']).is_file())
        self.assertEqual(result['status'],'complete')
        self.assertFalse(result['layout_checked'])
        self.assertNotIn('.png',json.dumps(result));self.assertEqual(result['layout_warnings'],[])
    def test_translation_modes_are_explicit_and_isolated_per_call(self):
        self.assertIn('不得为适应版面',translation_system('faithful'))
        self.assertIn('用户选择文案压缩',translation_system('compressed'))
        with self.assertRaises(ValueError):translation_system('automatic')
    def test_vision_payload_supports_both_configured_api_formats(self):
        png=self.folder/'p.png'
        from PIL import Image
        Image.new('RGB',(10,10),'white').save(png)
        for fmt in ('openai','anthropic'):
            client=LLMClient.__new__(LLMClient);client.api_format=fmt;client.provider='compatible';client.model='fixture'
            payloads=[]
            def post(endpoint,body):
                payloads.append(body)
                content='{"reviewed":true,"issues":[]}'
                return {'content':[{'type':'text','text':content}],'stop_reason':'end_turn'} if fmt=='anthropic' else {'choices':[{'message':{'content':content},'finish_reason':'stop'}]}
            client._post=post
            self.assertTrue(client.chat_images_json('Compare pages',[png,png])['reviewed'])
            contents=payloads[0]['messages'][0]['content'];self.assertEqual(len(contents),3)
            self.assertEqual(contents[1]['type'],'image' if fmt=='anthropic' else 'image_url')


if __name__=='__main__':unittest.main()
