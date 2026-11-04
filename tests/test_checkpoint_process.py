"""Kill a real worker process, then recover through saved history and SQLite.

The model is an offline deterministic fixture. PPT rendering and PDF image QA
are stubbed here: these tests verify durable text checkpoints, not visual QA.
"""
import hashlib,json,os,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
PAIRS=[('点间距为2.5mm。','The pixel pitch is 2.5 mm.'),
       ('刷新率为60Hz。','The refresh rate is 60 Hz.'),
       ('亮度为500nits。','The brightness is 500 nits.')]
CHINESE=['点间距为2.5mm。','刷新率为60Hz。','亮度为500nits。']


def worker(config_file,mode):
    config=json.loads(Path(config_file).read_text('utf-8'))
    os.environ['NOVATERM_DATA_DIR']=config['profile']
    sys.path.insert(0,config['backend_root'])
    from backend import workflow,history
    from backend.glossary.loader import Glossary
    from backend.llm.client import LLMClient
    class Model(LLMClient):
        def __init__(self):
            self.provider='compatible';self.base_url='http://127.0.0.1:1/v1'
            self.model='crash-recovery-fixture';self.api_format='openai';self.calls=[]
        def chat_json(self,prompt,system='',**options):
            if '复核' in system and '"ok"' in system:
                return {'ok':True,'issues':[]}
            if '待译原文' in prompt and prompt.startswith('{'):
                source=json.loads(prompt)['待译原文']
            else:source=prompt.split('【待译原文】\n')[-1].split('\n【需保留')[0].strip()
            table={en:zh for zh,en in PAIRS} if config['direction']=='en-zh' else dict(PAIRS)
            if source not in table:raise AssertionError('Unexpected fixture request: '+source[:100])
            if mode=='crash' and self.calls:os._exit(73)
            if mode=='cached' or (mode=='resume' and source==config['texts'][0]):
                raise AssertionError('Already committed translation was requested again')
            self.calls.append(source)
            return {'translation':table[source]}
    model=Model()
    if mode=='crash':
        data={'kind':'translate','paths':[config['source']],'direction':config['direction'],
            'workers':1,'output_dir':config['output'],'translation_mode':'faithful'}
    else:
        # A newly started process has no in-memory JOBS. This is the same saved
        # options path used by desktop history and the shared resume endpoint.
        rows=history.query()['records']
        if mode=='resume':assert rows[0]['status']=='interrupted'
        data=history.resume_options('crashed-task')
    data['_client']=model
    job={'id':'crashed-task' if mode=='crash' else mode,'kind':'translate',
        'status':'running','percent':0,'error':'','cancel':threading.Event()}
    with (patch('backend.workflow.store.load_glossary',return_value=Glossary([])),
          patch('backend.translation.review_pptx',return_value=([],[])),
          patch('backend.pptx_visual_review.review_pptx',return_value=([],[])),
          patch('backend.officecli_bridge.inspect',return_value={}),
          patch('backend.officecli_bridge.compare',return_value=[]),
          patch('backend.pdf_quality.audit',return_value={'status':'complete','issues':[]})):
        workflow.run(job,data)
    assert job['status']=='complete',job.get('error') or job.get('result')
    output=job['result']['outputs'][0]
    assert output['translation_complete'],output.get('review_items')
    from backend.extract import extract
    texts='\n'.join(s.text for s in extract(output['path']) if s.editable)
    expected=CHINESE if config['direction']=='en-zh' else [en for _,en in PAIRS]
    for text in expected:assert text in texts,(text,texts)
    result={'calls':len(model.calls),'resumed':output['resumed_segments'],'total':output['total'],
        'complete':True,'externalRequests':0,'sourceHash':hashlib.sha256(Path(config['source']).read_bytes()).hexdigest()}
    Path(config_file).with_name(mode+'-result.json').write_text(json.dumps(result),'utf-8')


class CheckpointProcessTests(unittest.TestCase):
    def source(self,folder,suffix,texts):
        file=folder/('source'+suffix)
        if suffix=='.docx':
            from docx import Document
            doc=Document()
            for text in texts:doc.add_paragraph(text)
            doc.save(file)
        elif suffix=='.pptx':
            from pptx import Presentation
            from pptx.util import Inches
            deck=Presentation()
            for text in texts:
                slide=deck.slides.add_slide(deck.slide_layouts[6])
                slide.shapes.add_textbox(Inches(1),Inches(1),Inches(6),Inches(2)).text=text
            deck.save(file)
        elif suffix=='.xlsx':
            from openpyxl import Workbook
            book=Workbook()
            for text in texts:book.active.append([text])
            book.save(file);book.close()
        elif suffix=='.pdf':
            from test_file_formats import pdf_fixture
            from pypdf import PdfReader,PdfWriter
            writer=PdfWriter()
            for i,text in enumerate(texts):
                one=folder/f'page-{i}.pdf';pdf_fixture(one,text)
                writer.add_page(PdfReader(one).pages[0])
            writer.write(file)
        else:file.write_text(('\n\n' if suffix=='.md' else '\n').join(texts),'utf-8')
        return file
    def check_format(self,suffix):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for direction in ('zh-en','en-zh'):
                with self.subTest(direction=direction):
                    folder=root/direction;folder.mkdir()
                    texts=[en if direction=='en-zh' else zh for zh,en in PAIRS]
                    source=self.source(folder,suffix,texts);before=hashlib.sha256(source.read_bytes()).hexdigest()
                    import backend
                    config=folder/'config.json';config.write_text(json.dumps({'profile':str(folder/'profile'),'backend_root':str(Path(backend.__file__).resolve().parent.parent),
                        'source':str(source),'direction':direction,'output':str(folder/'output'),'texts':texts}),'utf-8')
                    for mode in ('crash','resume','cached'):
                        result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--worker',str(config),mode],
                            cwd=ROOT,capture_output=True,timeout=50,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                        self.assertEqual(result.returncode,73 if mode=='crash' else 0,result.stderr.decode('utf-8',errors='replace')[-5000:])
                    resumed=json.loads((folder/'resume-result.json').read_text('utf-8'))
                    cached=json.loads((folder/'cached-result.json').read_text('utf-8'))
                    self.assertEqual(resumed['calls'],2);self.assertEqual(resumed['resumed'],1)
                    self.assertEqual(cached['calls'],0);self.assertEqual(cached['resumed'],3)
                    self.assertEqual(resumed['sourceHash'],before);self.assertEqual(cached['sourceHash'],before)
    def test_docx(self):self.check_format('.docx')
    def test_pptx(self):self.check_format('.pptx')
    def test_pdf(self):self.check_format('.pdf')
    def test_xlsx(self):self.check_format('.xlsx')
    def test_txt(self):self.check_format('.txt')
    def test_markdown(self):self.check_format('.md')


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(sys.argv[2],sys.argv[3])
    else:unittest.main()
