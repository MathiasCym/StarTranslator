"""Repeatable PowerPoint-native table coordinate/clipping acceptance.

Requires Windows and PowerPoint. Uses synthetic files only; no model requests.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
QA=ROOT/'dist/qa';QA.mkdir(parents=True,exist_ok=True)
FOLDER=Path(tempfile.mkdtemp(prefix='native-table-contract-',dir=QA))
os.environ['NOVATERM_DATA_DIR']=str(FOLDER/'profile')
from pptx import Presentation
from pptx.util import Inches,Pt
from backend.pptx_visual_review import render_pages,_objects,_native_issues
from backend.multilingual_typography import font_for
from backend.glossary.store import fingerprint

LABELS={'en-US':('Parameters','Refresh rate','Model'),
        'zh-CN':('参数','刷新频率','型号'),
        'zh-Hant-TW':('參數','重新整理頻率','型號'),
        'ja-JP':('パラメータ','リフレッシュレート','型番'),
        'ko':('매개변수','새로 고침 빈도','모델')}
result={'passed':False,'modelRequests':0,'customerDocumentsSent':False,
        'existingProfileModified':False,'checks':[]}
try:
    paths=[]
    for bad in (False,True):
        deck=Presentation()
        for language,labels in LABELS.items():
            slide=deck.slides.add_slide(deck.slide_layouts[6])
            table=slide.shapes.add_table(3,2,Inches(2),Inches(2),Inches(5),Inches(2)).table
            table.cell(0,0).merge(table.cell(0,1));table.cell(0,0).text=labels[0]
            table.cell(1,0).text='ABCDEFGHIJKLMNOPQRSTUVWXYZ'*3 if bad else labels[1]
            table.cell(1,0).text_frame.word_wrap=not bad
            table.cell(1,1).text='60 Hz';table.cell(2,0).text=labels[2];table.cell(2,1).text='A8'
            for row in table.rows:
                for cell in row.cells:
                    if cell.is_spanned:continue
                    for paragraph in cell.text_frame.paragraphs:
                        for run in paragraph.runs:
                            run.font.size=Pt(16);run.font.name=font_for(language) or 'Arial'
        path=FOLDER/('overflow.pptx' if bad else 'fitting.pptx');deck.save(path);paths.append(path)
    before=[fingerprint(p) for p in paths]
    source,output=[render_pages(p,FOLDER/label,native_only=True) for p,label in zip(paths,('fitting','overflow'))]
    assert source['native'] and output['native']
    objects=_objects(Presentation(paths[0]))
    for index,language in enumerate(LABELS):
        page=source['pages'][index]
        cells=[shape for shape in page['shapes'] if 'row' in shape]
        assert cells,'Missing table measurements'
        for cell in cells:
            assert cell['x']>=144 and cell['y']>=144,cell
            assert cell['bound_x']>=cell['x']-1 and cell['bound_y']>=cell['y']-1,cell
            assert cell['bound_x']+cell['bound_width']<=cell['x']+cell['width']+2,cell
            assert cell['bound_y']+cell['bound_height']<=cell['y']+cell['height']+2,cell
        assert not _native_issues(page,page,index+1,objects[index])
        found=_native_issues(page,output['pages'][index],index+1,objects[index])
        assert any(issue['kind']=='clipping' and '/table/1/0/' in issue['locator'] for issue in found),found
        result['checks'].append({'language':language,'mergedAndOrdinaryCellsFit':True,
                                 'realOverflowDetected':True,'measuredCells':len(cells)})
    assert before==[fingerprint(p) for p in paths]
    result['passed']=True
except Exception as error:
    result['error']=str(error)
finally:
    (FOLDER/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'passed':result['passed'],'result':str(FOLDER/'result.json'),'error':result.get('error')},ensure_ascii=False))
sys.exit(0 if result['passed'] else 1)
