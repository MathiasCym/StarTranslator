"""Full-page previews are read-only, isolated, refreshable and owner-scoped."""
import os,sys,unittest,tempfile,json,shutil,io
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docx import Document
from pptx import Presentation
from pptx.util import Inches
from PIL import Image
from lxml import html
from zipfile import ZipFile
from lxml import etree
from backend import comparison,document_preview,history,workflow,lan_service
from backend.extract import extract
from backend.extract.office import open_office
from backend.glossary import store

class DocumentPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':str(self.root/'data')});self.env.start()
        self.picture=self.root/'picture.png';Image.new('RGB',(150,80),'#23a0ce').save(self.picture)
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def pair(self,kind='.docx'):
        source=self.root/('中文原稿'+kind);output=self.root/('English'+kind)
        for path,language in [(source,'中文完整页面'),(output,'Complete English page')]:
            if kind=='.pptx':
                d=Presentation();d.slide_width=Inches(12);d.slide_height=Inches(6.75)
                for i in range(2):
                    s=d.slides.add_slide(d.slide_layouts[6]);s.shapes.add_textbox(Inches(1),Inches(.5),Inches(8),Inches(1)).text=language+' '+str(i+1)
                    s.shapes.add_picture(str(self.picture),Inches(8),Inches(2),Inches(2))
                    t=s.shapes.add_table(2,2,Inches(1),Inches(2),Inches(3),Inches(1)).table;t.cell(0,0).text=language
                d.save(path)
                # Native cached chart data; no Excel writer is required at runtime.
                with ZipFile(path) as z: parts={n:z.read(n) for n in z.namelist()}
                slide=etree.fromstring(parts['ppt/slides/slide2.xml']);ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
                frame=etree.fromstring(b'<p:graphicFrame xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:nvGraphicFramePr><p:cNvPr id="990" name="Chart"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="914400" y="3657600"/><a:ext cx="5486400" cy="1828800"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart r:id="rIdPreviewChart"/></a:graphicData></a:graphic></p:graphicFrame>')
                slide.find('p:cSld/p:spTree',ns).append(frame);parts['ppt/slides/slide2.xml']=etree.tostring(slide)
                rel=etree.fromstring(parts['ppt/slides/_rels/slide2.xml.rels']);etree.SubElement(rel,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',Id='rIdPreviewChart',Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart',Target='../charts/chart1.xml');parts['ppt/slides/_rels/slide2.xml.rels']=etree.tostring(rel)
                ct=etree.fromstring(parts['[Content_Types].xml']);etree.SubElement(ct,'{http://schemas.openxmlformats.org/package/2006/content-types}Override',PartName='/ppt/charts/chart1.xml',ContentType='application/vnd.openxmlformats-officedocument.drawingml.chart+xml');parts['[Content_Types].xml']=etree.tostring(ct)
                parts['ppt/charts/chart1.xml']=b'<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart><c:plotArea><c:layout/><c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:ser><c:idx val="0"/><c:order val="0"/><c:tx><c:v>Screens</c:v></c:tx><c:cat><c:strLit><c:ptCount val="2"/><c:pt idx="0"><c:v>2025</c:v></c:pt><c:pt idx="1"><c:v>2026</c:v></c:pt></c:strLit></c:cat><c:val><c:numLit><c:formatCode>General</c:formatCode><c:ptCount val="2"/><c:pt idx="0"><c:v>261</c:v></c:pt><c:pt idx="1"><c:v>300</c:v></c:pt></c:numLit></c:val></c:ser><c:axId val="1"/><c:axId val="2"/></c:barChart><c:catAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="b"/><c:crossAx val="2"/></c:catAx><c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="l"/><c:crossAx val="1"/></c:valAx></c:plotArea></c:chart></c:chartSpace>'
                with ZipFile(path,'w') as z:
                    for name,content in parts.items():z.writestr(name,content)
            else:
                d=Document();d.add_heading(language,0);d.add_picture(str(self.picture),width=Inches(2));d.add_table(2,2).cell(0,0).text=language;d.add_page_break();d.add_heading(language+' 2',1);d.save(path)
        _,paras,_=open_office(str(output));ident=comparison.create(extract(str(source)),{loc:p for loc,p,*_ in paras},str(source),str(output))
        return source,output,ident
    def test_ppt_keeps_whole_slides_images_tables_and_chart(self):
        source,output,ident=self.pair('.pptx');before=store.fingerprint(source);out_before=store.fingerprint(output)
        text=document_preview.preview(ident,'source');dom=html.fromstring(text)
        self.assertEqual(len(dom.xpath('//*[@class="slide-container"]')),2);self.assertGreaterEqual(len(dom.xpath('//img')),2)
        self.assertIn('data:image/',text);self.assertIn('2025',text);self.assertIn('300',text);self.assertIn('中文完整页面',text)
        bars=dom.xpath('//svg/rect');self.assertEqual(len(bars),2)
        self.assertAlmostEqual(float(bars[1].get('height'))/float(bars[0].get('height')),300/261,places=2)
        self.assertTrue(dom.xpath('//table') or dom.xpath('//*[contains(@class,"table")]'))
        self.assertEqual(before,store.fingerprint(source));self.assertEqual(out_before,store.fingerprint(output))
        source.unlink();self.assertIn('中文完整页面',document_preview.preview(ident,'source'))
    def test_word_has_page_breaks_images_and_tables(self):
        _,_,ident=self.pair();text=document_preview.preview(ident,'source');dom=html.fromstring(text)
        self.assertEqual(len(dom.xpath('//*[@class="page-wrapper"]')),2);self.assertTrue(dom.xpath('//img'));self.assertTrue(dom.xpath('//table'))
        response=document_preview.response(ident,'source',shared=True)
        self.assertIn("connect-src 'none'",response.headers['Content-Security-Policy']);self.assertIn("frame-ancestors 'self'",response.headers['Content-Security-Policy'])
    def test_new_output_invalidates_only_its_cached_preview(self):
        source,output,ident=self.pair();original=document_preview.preview(ident,'source');old=document_preview.preview(ident,'output')
        d=Document(output);d.paragraphs[0].text='Confirmed corrected English';d.save(output);comparison.update(ident,str(output))
        new=document_preview.preview(ident,'output');self.assertIn('Confirmed corrected English',new);self.assertNotEqual(old,new)
        self.assertEqual(original,document_preview.preview(ident,'source'));self.assertFalse(comparison.read(ident)['output_changed'])
    def test_legacy_record_recovers_original_from_history(self):
        source,output,ident=self.pair();value=comparison.read(ident);value={k:v for k,v in value.items() if not k.startswith('_')}
        store.atomic_json(comparison.folder()/(ident+'.json'),value);shutil.rmtree(comparison.folder()/ident)
        data={'kind':'translate','paths':[str(source)]};history.begin('legacy',data);history.finish({'id':'legacy','status':'complete','result':{'outputs':[{'path':str(output),'source':str(source),'comparison_id':ident}]}},data)
        self.assertIn('中文完整页面',document_preview.preview(ident,'source'));self.assertTrue(comparison.read(ident).get('_source_snapshot'))
    def test_missing_original_shows_reason_without_discarding_text(self):
        source,_,ident=self.pair();shutil.rmtree(comparison.folder()/ident);source.unlink()
        value=comparison.read(ident);value={k:v for k,v in value.items() if not k.startswith('_')};store.atomic_json(comparison.folder()/(ident+'.json'),value)
        self.assertIn('旧对照',document_preview.response(ident,'source').get_data(as_text=True));self.assertTrue(comparison.read(ident)['rows'])
    def test_frames_strip_external_resources_and_cannot_call_host(self):
        raw='<html><head><script src="https://outside.invalid/a.js"></script><link href="file:///private.css"></head><body><div class="slide-container"><div class="slide"><img src="file:///secret.png" onerror="alert(1)"><a href="https://outside.invalid">link</a><iframe src="file:///secret"></iframe><script>alert(1)</script></div></div></body></html>'
        prepared=document_preview.prepare(raw,'.pptx');self.assertNotIn('outside.invalid',prepared);self.assertNotIn('secret',prepared);self.assertNotIn('alert(1)',prepared)
        self.assertIn('star-page-preview',prepared);self.assertIn("default-src 'none'",document_preview.CSP)
    def test_shared_preview_and_cleanup_keep_ownership(self):
        source,output,ident=self.pair();app=lan_service.create_app(True);first=app.test_client();other=app.test_client()
        csrf=first.get('/shared/session').json['csrf'];other.get('/shared/session')
        with patch('backend.workflow.JOBS',{}):
            token=first.get_cookie(lan_service.COOKIE).value;session=lan_service.SESSIONS[token]
            folder=lan_service.base_dir()/token/'owned';folder.mkdir(parents=True);session['jobs']=['owned'];session['folders']={'owned':str(folder)}
            workflow.JOBS['owned']={'id':'owned','kind':'translate','status':'complete','result':{'outputs':[{'comparison_id':ident,'path':str(output)}]}}
            url='/shared/jobs/owned/comparison/0/preview/source'
            self.assertEqual(other.get(url).status_code,400);self.assertEqual(first.get(url).status_code,200)
            value=first.get('/shared/jobs/owned/comparison/0').json;self.assertFalse(any(k.startswith('_') for k in value));self.assertNotIn(str(self.root),json.dumps(value))
            self.assertEqual(first.post('/shared/jobs/owned/cleanup',headers={'X-Star-CSRF':csrf}).status_code,200)
        self.assertTrue(source.is_file());self.assertFalse((comparison.folder()/ident).exists())

if __name__=='__main__':unittest.main()
