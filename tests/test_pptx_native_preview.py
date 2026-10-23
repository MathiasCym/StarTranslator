import os,sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import pptx_native_preview as native
from backend.glossary.store import fingerprint


@unittest.skipUnless(os.name=='nt','Windows native preview')
class PptxNativePreviewTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.source=self.root/'source.pptx';self.source.write_bytes(b'fixture')
        self.folder=self.root/'preview';self.calls=[]
        def render(source,folder,**options):
            self.calls.append(options);folder.mkdir(parents=True,exist_ok=True)
            image=folder/f"page-{options['page']}.png";Image.new('RGB',(1280,720),'white').save(image)
            return {'native':True,'total':22,'pages':[{'image':image}]}
        mock=patch('backend.pptx_visual_review.render_pages',side_effect=render);mock.start();self.addCleanup(mock.stop)
    def test_lazy_cache_uses_model_renderer_and_real_page_count(self):
        digest=fingerprint(self.source)
        first,total=native.preview(self.source,self.folder,digest,19,22)
        native.preview(self.source,self.folder,digest,19,22)
        native.preview(self.source,self.folder,digest,20,22)
        self.assertEqual(total,22);self.assertIn('native-pptx',first);self.assertIn('width:1280px;height:720px',first)
        self.assertEqual(self.calls,[{'native_only':True,'page':19},{'native_only':True,'page':20}])
        self.assertEqual(fingerprint(self.source),digest)
        self.source.write_bytes(b'revised');native.preview(self.source,self.folder,fingerprint(self.source),19,22)
        self.assertFalse((self.folder/'page-20.png').exists());self.assertEqual(len(self.calls),3)
    def test_fallback_has_cooldown_but_a_later_page_cannot_silently_switch_renderer(self):
        digest=fingerprint(self.source)
        with patch('backend.pptx_visual_review.render_pages',side_effect=RuntimeError('unavailable')) as render:
            self.assertIsNone(native.preview(self.source,self.folder,digest,19,22))
            self.assertIsNone(native.preview(self.source,self.folder,digest,19,22));self.assertEqual(render.call_count,1)
        (self.folder/'manifest.json').unlink();native.preview(self.source,self.folder,digest,19,22)
        with patch('backend.pptx_visual_review.render_pages',side_effect=RuntimeError('unavailable')):
            with self.assertRaisesRegex(ValueError,'实际页面'):native.preview(self.source,self.folder,digest,20,22)
    def test_invalid_page_or_incomplete_manifest_cannot_show_another_page(self):
        with self.assertRaisesRegex(ValueError,'页码'):native.preview(self.source,self.folder,fingerprint(self.source),23,22)
        with patch('backend.pptx_visual_review.render_pages',return_value={'native':False,'total':22,'pages':[]}):
            self.assertIsNone(native.preview(self.source,self.folder,fingerprint(self.source),1,22))


if __name__=='__main__':unittest.main()
