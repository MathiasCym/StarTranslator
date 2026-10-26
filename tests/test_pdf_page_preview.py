"""Original PDF pages are read-only images, not extracted text reflow."""
import base64
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pypdf import PdfWriter, PdfReader
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
from PIL import Image
from lxml import html
from docx import Document
from backend import comparison, document_preview, pdf_page_preview
from backend.glossary import store


class PdfPagePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'NOVATERM_DATA_DIR': str(self.root/'data')})
        self.env.start()
        self.source = self.root/'source.pdf'
        self.cache = self.root/'cache'
        self.make_pdf()
        self.renderer=patch.object(pdf_page_preview,'_render',side_effect=self.fake_render)
        self.render_mock=self.renderer.start();self.addCleanup(self.renderer.stop)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def make_pdf(self, color=(.1,.5,.9), rotated=False):
        document=PdfWriter()
        for number in range(2):
            page=document.add_blank_page(width=600,height=800)
            content=DecodedStreamObject()
            content.set_data((f"{color[0]} {color[1]} {color[2]} rg 40 680 510 70 re f\n"
                              "0.9 0.2 0.1 RG 5 w 40 200 m 550 650 l S").encode())
            page[NameObject('/Contents')]=document._add_object(content)
            if rotated:
                page.cropbox.lower_left=(20,30);page.cropbox.upper_right=(580,760);page.rotate(90)
        with self.source.open('wb') as target:document.write(target)

    def fake_render(self, source, target, page):
        # Geometry tests verify the renderer's image passes through unchanged;
        # the real Windows engine is exercised separately on the maintainer PC.
        Image.new('RGB',(1200,1600),('red' if page==1 else 'blue')).save(target)

    def image(self, raw):
        node=html.fromstring(raw).xpath('//img')[0]
        return Image.open(io.BytesIO(base64.b64decode(node.get('src').split(',',1)[1]))).convert('RGB')

    def test_renderer_image_is_embedded_unchanged(self):
        before=self.source.read_bytes()
        raw,total=pdf_page_preview.preview(self.source,self.cache,store.fingerprint(self.source),2)
        actual=self.image(raw)
        self.assertEqual(total,2)
        self.assertEqual(actual.size,(1200,1600))
        self.assertEqual(actual.getpixel((0,0)),(0,0,255))
        self.assertEqual(self.source.read_bytes(),before)

    def test_crop_and_rotation_do_not_reflow_pdf_before_rendering(self):
        self.source.unlink();self.make_pdf(rotated=True)
        raw,_=pdf_page_preview.preview(self.source,self.cache,store.fingerprint(self.source),1)
        self.render_mock.assert_called_once_with(self.source,unittest.mock.ANY,1)
        self.assertEqual(PdfReader(self.source).pages[0].rotation,90)
        self.assertEqual(self.image(raw).size,(1200,1600))

    def test_warm_page_uses_cache_and_new_page_is_lazy(self):
        digest=store.fingerprint(self.source)
        first=pdf_page_preview.preview(self.source,self.cache,digest,1)
        self.assertFalse((self.cache/'page-2.png').exists())
        with patch.object(pdf_page_preview,'_render',side_effect=AssertionError('Warm page rerendered')):
            self.assertEqual(pdf_page_preview.preview(self.source,self.cache,digest,1),first)
        pdf_page_preview.preview(self.source,self.cache,digest,2)
        self.assertTrue((self.cache/'page-2.png').is_file())

    def test_changed_document_invalidates_all_old_pages(self):
        for page in (1,2):pdf_page_preview.preview(self.source,self.cache,store.fingerprint(self.source),page)
        self.assertTrue((self.cache/'page-2.png').exists())
        self.source.unlink();self.make_pdf(color=(.8,.2,.2))
        pdf_page_preview.preview(self.source,self.cache,store.fingerprint(self.source),1)
        self.assertIn(store.fingerprint(self.source),(self.cache/'manifest.json').read_text())
        self.assertFalse((self.cache/'page-2.png').exists())

    def test_invalid_pages_are_rejected(self):
        for page in (0,-1,3,True,1.5,'2'):
            with self.subTest(page=page),self.assertRaisesRegex(ValueError,'页码'):
                pdf_page_preview.preview(self.source,self.cache,store.fingerprint(self.source),page)

    def test_corrupt_cache_is_reported_and_recoverable(self):
        digest=store.fingerprint(self.source)
        pdf_page_preview.preview(self.source,self.cache,digest,1)
        (self.cache/'page-1.png').write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'缓存'):
            pdf_page_preview.preview(self.source,self.cache,digest,1)
        raw,_=pdf_page_preview.preview(self.source,self.cache,digest,1)
        self.assertGreater(self.image(raw).width,0)

    def test_encrypted_original_is_not_silently_replaced_by_text(self):
        locked=self.root/'locked.pdf'
        document=PdfWriter(clone_from=self.source);document.encrypt('user')
        with locked.open('wb') as target:document.write(target)
        with self.assertRaisesRegex(ValueError,'加密'):
            pdf_page_preview.preview(locked,self.cache,store.fingerprint(locked),1)

    def test_comparison_uses_pdf_snapshot_without_office_or_extraction(self):
        output=self.root/'output.docx';Document().save(output)
        ident=comparison.create([],{},str(self.source),str(output))
        before=store.fingerprint(output);self.source.unlink()
        with patch.object(document_preview,'text_preview',side_effect=AssertionError('Text reflow used')),patch.object(document_preview.officecli_bridge,'ensure_component',side_effect=AssertionError('Office used')):
            raw=document_preview.preview(ident,'source',2)
        self.assertIn('data-star-renderer="original-pdf"',raw)
        self.assertIn('data-star-page="2"',raw)
        self.assertIn('data-star-total="2"',raw)
        self.assertNotIn('正文阅读预览',raw)
        self.assertIn('原 PDF 第 2 页',raw)
        self.assertEqual(store.fingerprint(output),before)

    def test_page_without_text_can_be_previewed(self):
        scan=self.root/'scan.pdf';document=PdfWriter();document.add_blank_page(width=300,height=400)
        with scan.open('wb') as target:document.write(target)
        raw,total=pdf_page_preview.preview(scan,self.cache,store.fingerprint(scan),1)
        self.assertEqual(total,1)
        self.assertEqual(PdfReader(scan).pages[0].extract_text(),'')
        self.assertGreater(self.image(raw).width,0)


if __name__=='__main__':unittest.main()
