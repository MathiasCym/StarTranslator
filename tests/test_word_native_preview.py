"""Native page caching is content-bound, read-only and optional."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from pypdf import PdfWriter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import word_native_preview as native
from backend.glossary.store import fingerprint


class WordNativePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'input.docx';self.source.write_bytes(b'private document')
        self.folder=self.root/'native';self.calls=[]
        def render(mode,source,output,page=1):
            self.calls.append((mode,page))
            if mode=='export':
                writer=PdfWriter();writer.add_blank_page(width=600,height=800);writer.add_blank_page(width=800,height=600)
                writer.write(str(output))
            else:Image.new('RGB',(60,80),'white').save(output)
        run=patch.object(native,'_run',side_effect=render);run.start();self.addCleanup(run.stop)
    @unittest.skipUnless(os.name=='nt','Windows native preview')
    def test_pages_cache_the_same_pdf_and_keep_actual_page_dimensions(self):
        before=fingerprint(self.source)
        first,total=native.preview(self.source,self.folder,before,1)
        second,_=native.preview(self.source,self.folder,before,2)
        self.assertEqual(total,2);self.assertIn('width:800.0px;height:1066.',first)
        self.assertIn('width:1066.',second);self.assertIn('native-word',first)
        native.preview(self.source,self.folder,before,1)
        self.assertEqual(self.calls,[('export',1),('page',1),('page',2)])
        self.assertEqual(fingerprint(self.source),before)
    @unittest.skipUnless(os.name=='nt','Windows native preview')
    def test_changed_output_discards_previous_page_images(self):
        native.preview(self.source,self.folder,fingerprint(self.source),1)
        self.source.write_bytes(b'revised document')
        native.preview(self.source,self.folder,fingerprint(self.source),1)
        self.assertEqual(self.calls,[('export',1),('page',1),('export',1),('page',1)])
    @unittest.skipUnless(os.name=='nt','Windows native preview')
    def test_out_of_range_is_an_error_instead_of_showing_a_different_page(self):
        with self.assertRaisesRegex(ValueError,'页码'):
            native.preview(self.source,self.folder,fingerprint(self.source),3)
        self.assertFalse((self.folder/'page-3.png').exists())
    @unittest.skipUnless(os.name=='nt','Windows native preview')
    def test_unavailable_native_renderer_does_not_repeatedly_launch_office(self):
        with patch.object(native,'_run',side_effect=RuntimeError('not installed')) as run:
            self.assertIsNone(native.preview(self.source,self.folder,fingerprint(self.source),1))
            self.assertIsNone(native.preview(self.source,self.folder,fingerprint(self.source),1))
        self.assertEqual(run.call_count,1)
    @unittest.skipUnless(os.name=='nt','Windows native preview')
    def test_page_failure_never_silently_changes_renderer_or_page_count(self):
        native.preview(self.source,self.folder,fingerprint(self.source),1)
        with patch.object(native,'_run',side_effect=RuntimeError('rasterizer unavailable')):
            with self.assertRaisesRegex(ValueError,'实际页面图像'):
                native.preview(self.source,self.folder,fingerprint(self.source),2)
        self.assertTrue(json.loads((self.folder/'manifest.json').read_text())['available'])


if __name__=='__main__':unittest.main()
