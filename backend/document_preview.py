"""Read-only full-page OfficeCLI previews, isolated from the app and model workflow."""
import html as escaping
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from lxml import html
from flask import Response,request,has_request_context
from . import comparison, officecli_bridge
from .glossary import store

SLOTS=threading.BoundedSemaphore(2)
LOCK=threading.RLock()
RENDER_LOCKS={}
MAX_HTML=64*1024*1024
PREVIEW_FORMAT='pages-7'
CSP="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
FRAME_SCRIPT=r'''
(()=>{
const channel='star-page-preview',token=new URLSearchParams(location.search).get('preview_token');let pages=[],zoom='fit',muteUntil=0,ready=false,timer,currentPage=0;
const remotePage=Number(document.body.dataset.starPage)||0,remoteTotal=Number(document.body.dataset.starTotal)||0;
zoom=new URLSearchParams(location.search).get('zoom')||'fit';muteUntil=remotePage>1?Date.now()+2500:0;
function send(data){parent.postMessage({channel,token,...data},'*')}
function list(){return [...document.querySelectorAll('.slide-container,.page-wrapper')].filter(p=>p.querySelector('.slide,.page'))}
function scale(){
 if(window._starWordPaginating){setTimeout(scale,100);return;}
 pages=list();
 currentPage=Math.max(0,Math.min(pages.length-1,currentPage));
 pages.forEach((w,i)=>{w.hidden=i!==currentPage});
 pages.forEach(w=>{if(w.hidden)return;const p=w.querySelector('.slide,.page'),width=p.offsetWidth,height=p.scrollHeight;
  const factor=zoom==='fit'?Math.min(1,Math.max(.05,(document.documentElement.clientWidth-24)/width)):Number(zoom)||1;
  p.style.transformOrigin='top left';p.style.transform='scale('+factor+')';
  w.style.width=width*factor+'px';w.style.height=height*factor+'px';w.style.minHeight='0';
 });
 if(pages.length){send({type:'ready',total:remoteTotal||pages.length});ready=true;position()}
}
function position(){
 if(!ready)return;
 const p=pages[currentPage],fraction=Math.max(0,Math.min(1,(scrollY-p.offsetTop)/Math.max(1,p.offsetHeight)));
 send({type:'position',page:remotePage||currentPage+1,fraction,command:Date.now()<muteUntil})
}
addEventListener('message',e=>{
 if(e.source!==parent||e.data?.channel!==channel||e.data.token!==token)return;
 const d=e.data;
 if(d.type==='zoom'){zoom=['fit','1','1.25','1.5','2'].includes(d.value)?d.value:'fit';muteUntil=Date.now()+350;scale()}
 if(d.type==='goto'&&pages.length){const i=Math.max(0,Math.min(pages.length-1,Math.round(Number(d.page)||1)-1));
  if(remotePage){const wanted=Math.max(1,Math.min(remoteTotal,Math.round(Number(d.page)||1)));if(wanted!==remotePage){send({type:'navigate',page:wanted});return}}
  muteUntil=Date.now()+500;currentPage=i;scale();scrollTo(scrollX,pages[i].offsetTop+Math.max(0,Math.min(1,Number(d.fraction)||0))*pages[i].offsetHeight);position()}
});
addEventListener('scroll',()=>{clearTimeout(timer);timer=setTimeout(position,70)},{passive:true});
addEventListener('resize',()=>setTimeout(scale,180));
addEventListener('load',async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode().catch(()=>{})));setTimeout(scale,350);setTimeout(scale,1100)});
new MutationObserver(()=>{clearTimeout(timer);timer=setTimeout(scale,180)}).observe(document.body,{childList:true,subtree:true});
})();
'''
FRAME_CSS='''
html{height:auto!important;overflow:auto!important;background:#071422!important;scroll-behavior:auto!important}
body{display:block!important;height:auto!important;min-height:100vh;overflow:visible!important;padding:12px!important;background:#071422!important;margin:0!important}
.sidebar,.page-counter,.file-title,.slide-label,.slide-notes,.nav-bar,.toolbar,.zoom-controls{display:none!important}
.main{display:block!important;overflow:visible!important;padding:0!important;height:auto!important}
.slide-container,.page-wrapper{display:block!important;position:relative!important;margin:0 auto 18px!important;flex:none!important;overflow:hidden!important;transition:none!important}
.slide-wrapper{display:block!important;width:100%!important;height:100%!important}
.slide,.page{margin:0!important;transition:none!important;flex:none!important;transform-origin:top left!important}
a{pointer-events:none!important;color:inherit!important;text-decoration:inherit!important}
[hidden]{display:none!important}
'''


def prepare(raw,kind,page=None,total=None):
    dom=html.fromstring(raw)
    # Inline renderer scripts from the pinned compiler run only in an opaque,
    # network-free sandbox. PPT uses our page sizing; Word keeps its pagination.
    for node in list(dom.xpath('//script')):
        if kind=='.pptx' or node.get('src') or node.get('type') in ('module','importmap'): node.drop_tree()
    for node in list(dom.xpath('//iframe|//object|//embed|//form|//base|//link|//meta[@http-equiv]')): node.drop_tree()
    for node in dom.iter():
        for name in list(node.attrib):
            if name.lower().startswith('on') or name.lower() in ('href','srcdoc','action','formaction','srcset'):
                del node.attrib[name]
        if node.get('src') and not node.get('src','').lower().startswith('data:image/'):
            del node.attrib['src']
    head=dom.find('head');body=dom.find('body')
    if head is None or body is None: raise ValueError('文档组件未生成完整页面。')
    if kind=='.docx':
        # Retain the compiler's sections, footnotes and page controls, replacing
        # only its row-atomic table split. No source text is dropped or reflowed
        # into a different column; split fragments retain their colgroup.
        for node in dom.xpath('//script'):
            script=node.text or ''
            start=script.find('      // #7b00: when the overflowing child is a <table>')
            end=script.find('      // Mirror the table case',start)
            if start>=0 and end>start:
                node.text=script[:start]+'''      var firstOverflow=children[splitIdx];
      if(firstOverflow){
        var continuation=firstOverflow.tagName==='TABLE'?starSplitWordTable(firstOverflow,body,availH):starSplitWordParagraph(firstOverflow,body,availH);
        if(continuation){children=Array.from(body.children);splitIdx=children.indexOf(continuation);}
      }
'''+script[end:]
                node.text=node.text.replace('if(ch>maxBodyH-fh+2 && visibleCount>1)',
                    "if(ch>starWordAvailableHeight(p,b,maxBodyH)-fh+2 && (visibleCount>1 || starWordTableCanSplit(b)))")
                node.text=node.text.replace('var availH=maxBodyH-fnH;',
                    'var availH=starWordAvailableHeight(page,body,maxBodyH)-fnH;')
                node.text=node.text.replace('if(sch>maxBodyH-sfH+2)',
                    'if(sch>starWordAvailableHeight(sp,sb_,maxBodyH)-sfH+2)')
                node.text=node.text.replace('if(again){if(window._wpSync)paginate();else setTimeout(paginate,0);}',
                    'window._starWordPaginating=again; if(again){if(window._wpSync)paginate();else setTimeout(paginate,0);}')
                # The viewer must not hide or transform continuation pages while
                # the compiler is still measuring them for further splits.
                node.text='window._starWordPaginating=true;\n'+node.text
        helper=html.Element('script');helper.text=Path(__file__).with_name('word_preview.js').read_text('utf-8');head.append(helper)
        style=html.Element('style');style.text='th,td{overflow-wrap:break-word;word-break:normal}td.star-long-token,th.star-long-token{overflow-wrap:anywhere}.star-short-label{white-space:nowrap;overflow-wrap:normal}'
        head.append(style)
        import re
        for cell in dom.xpath('//td|//th'):
            if re.search(r'[^\s]{35}',cell.text_content()):cell.set('class',(cell.get('class','')+' star-long-token').strip())
            elif len(cell)==1 and re.fullmatch(r'[A-Za-z][A-Za-z-]{2,13}',cell.text_content().strip()):
                cell.set('class',(cell.get('class','')+' star-short-label').strip())
        for label in dom.xpath('//li/span[1]'):
            if re.fullmatch(r'\s*\d+(?:\.\d+)*[.)]\s*',label.text_content()):
                label.set('style',label.get('style','')+';padding-right:.35em')
    if page is not None:
        body.set('data-star-page',str(page));body.set('data-star-total',str(total))
    style=html.Element('style');style.text=FRAME_CSS;head.append(style)
    script=html.Element('script');script.text=FRAME_SCRIPT;body.append(script)
    return '<!doctype html>\n'+html.tostring(dom,encoding='unicode',method='html')


def text_preview(source):
    """A labelled reading view for formats without the Office page renderer."""
    from .extract import extract
    segments = [s for s in extract(str(source)) if s.editable]
    if not segments: raise ValueError('没有可预览的正文。')
    pages = {}
    for index,segment in enumerate(segments):
        pages.setdefault(segment.slide if segment.slide is not None else index//40+1, []).append(segment)
    content = []
    for number,values in pages.items():
        paragraphs = ''.join('<p>'+escaping.escape(s.text)+'</p>' for s in values)
        content.append(f'<div class="page-wrapper"><div class="page"><small>正文阅读预览 · {number}（不还原原文件版式、图像及代码）</small>{paragraphs}</div></div>')
    raw = '<html><head><meta charset="utf-8"><style>.page{box-sizing:border-box;width:900px;background:white;color:#182737;padding:36px;min-height:600px;font:18px/1.6 Arial,sans-serif}p{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#657584}</style></head><body>'+''.join(content)+'</body></html>'
    return prepare(raw,'.pptx')


def preview(comparison_id,side,page=1):
    if side not in ('source','output'): raise ValueError('页面预览不存在。')
    value=comparison.read(comparison_id)
    # The shared semaphore bounds renderer subprocesses independently of model work.
    if not SLOTS.acquire(timeout=30): raise ValueError('页面预览正在准备，请稍后重试。')
    try:
        with LOCK: render_lock=RENDER_LOCKS.setdefault((comparison_id,side),threading.Lock())
        with render_lock:
            source=comparison.source_for_preview(value) if side=='source' else Path(value['output_path'])
            if not source.is_file(): raise ValueError('处理后的文件已移动或删除，无法显示完整页面。文字对照仍可查看。')
            total=None
            if source.suffix.lower()=='.pptx':
                from zipfile import ZipFile
                from lxml import etree
                with ZipFile(source) as archive:
                    total=len(etree.fromstring(archive.read('ppt/presentation.xml')).findall('.//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId'))
                if type(page) is not int or not 1<=page<=total:raise ValueError('预览页码超出范围。')
            digest=store.fingerprint(source);folder=comparison.folder()/comparison_id;folder.mkdir(parents=True,exist_ok=True)
            name=side+(f'-page-{page}' if total is not None else '')
            cached=folder/(name+'.html');stamp=folder/(name+'.sha256')
            cache_key=PREVIEW_FORMAT+'\n'+digest
            if cached.is_file() and stamp.is_file() and stamp.read_text()==cache_key: return cached.read_text(encoding='utf-8')
            if source.suffix.lower() not in {'.docx','.pptx'}:
                prepared = text_preview(source)
                if store.fingerprint(source) != digest: raise ValueError('文件在读取期间发生变化，请重试预览。')
                cached.write_text(prepared,encoding='utf-8');stamp.write_text(cache_key)
                return prepared
            with tempfile.TemporaryDirectory(prefix='star-page-preview-') as tmp:
                snapshot=Path(tmp)/('document'+source.suffix.lower());output=Path(tmp)/'preview.html'
                shutil.copyfile(source,snapshot)
                if store.fingerprint(snapshot)!=digest: raise ValueError('文件在读取期间发生变化，请重试预览。')
                binary=officecli_bridge.ensure_component('before_preview')
                try:
                    args=[str(binary),'view',str(snapshot),'html','--out',str(output)]
                    if total is not None:args+=['--start',str(page),'--end',str(page)]
                    result=subprocess.run(args,
                        cwd=tmp,capture_output=True,encoding='utf-8',errors='replace',timeout=120,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                        env={**os.environ,'OFFICECLI_NO_AUTO_RESIDENT':'1','OFFICECLI_SKIP_UPDATE':'1'})
                except subprocess.TimeoutExpired as e: raise ValueError('完整页面预览准备超时。文字对照仍可使用，请稍后重试。') from e
                if result.returncode or not output.is_file(): raise ValueError('文档组件未能生成完整页面，请导出诊断日志。')
                if output.stat().st_size>MAX_HTML: raise ValueError('当前单页含有超大图像，页面预览未完成。请导出诊断日志。')
                prepared=prepare(output.read_text(encoding='utf-8-sig'),source.suffix.lower(),page if total is not None else None,total)
            # Replacements and external edits produce a new fingerprint on the next view.
            cached.write_text(prepared,encoding='utf-8');stamp.write_text(cache_key)
            return prepared
    finally: SLOTS.release()


def response(comparison_id,side,shared=False):
    try:
        page=int(request.args.get('page','1')) if has_request_context() else 1
        content=preview(comparison_id,side,page)
    except Exception as error:
        logging.getLogger(__name__).exception('Could not prepare read-only page comparison')
        message=str(error) if isinstance(error,ValueError) else '页面预览未完成，请导出诊断日志。'
        if shared and ('检查位置' in message or not isinstance(error,ValueError)):
            message='页面预览未完成，请在共享电脑校验文档组件或导出诊断日志。'
        import json
        payload=json.dumps({'channel':'star-page-preview','type':'error','message':message},ensure_ascii=True).replace('<','\\u003c')
        content='<html><head><meta charset="utf-8"></head><body style="background:#071422;color:#abc2d5;font:16px sans-serif;padding:20px">'+escaping.escape(message)+'<script>parent.postMessage({...'+payload+',token:new URLSearchParams(location.search).get("preview_token")},"*")</script></body></html>'
    result=Response(content,mimetype='text/html')
    result.headers['Content-Security-Policy']=CSP+("; frame-ancestors 'self'" if shared else '')
    result.headers['Cache-Control']='no-store';result.headers['X-Content-Type-Options']='nosniff'
    return result
