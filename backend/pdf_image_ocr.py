"""Local Windows OCR supplies positions; a vision model must verify its text."""
import io,json,math,os,subprocess,tempfile
from pathlib import Path
from PIL import Image


def view_image(raw):
    with Image.open(io.BytesIO(raw)) as image:
        image=image.convert('RGBA')
        # Outline logos are often white on transparent. Use a dark reading
        # surface without changing the original image or its transparency.
        background=Image.new('RGBA',image.size,'#183c55' if image.getextrema()[3][0]<255 else 'white')
        background.alpha_composite(image)
        scale=min(3 if image.height<160 else 1,2500/max(image.size))
        size=tuple(max(1,round(n*scale)) for n in image.size)
        output=io.BytesIO();background.convert('RGB').resize(size).save(output,format='PNG')
        return output.getvalue(),scale


def recognize(path, check_cancel=lambda:None):
    if os.name!='nt':raise ValueError('本机没有可用的 Windows 离线图片识别组件。')
    shell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    with tempfile.TemporaryDirectory(prefix='star-image-ocr-') as temp:
        output=Path(temp)/'ocr.json'
        command=[str(shell),'-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-File',
            str(Path(__file__).with_name('image_ocr.ps1')),'-InputFile',str(Path(path).resolve()),'-OutputFile',str(output)]
        import time
        with subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
                env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('API_KEY','TOKEN','SECRET'))}) as process:
            started=time.monotonic()
            try:
                while process.poll() is None:
                    check_cancel()
                    if time.monotonic()-started>35:raise ValueError('本机图片文字识别超时。')
                    time.sleep(.08)
            finally:
                if process.poll() is None:process.kill()
        if process.returncode or not output.is_file():raise ValueError('本机中文图片识别不可用，请检查 Windows 简体中文识别语言。')
        value=json.loads(output.read_text('utf-8'))
    if not isinstance(value,dict) or not isinstance(value.get('lines'),list) or len(value['lines'])>1500:
        raise ValueError('本机图片识别未返回有效定位。')
    width,height=value.get('width',0),value.get('height',0)
    if not all(isinstance(n,(int,float)) and math.isfinite(n) and 0<n<=2600 for n in (width,height)):
        raise ValueError('图片识别尺寸无效。')
    lines=[]
    for index,line in enumerate(value['lines']):
        words=line.get('words') if isinstance(line,dict) else None
        if not isinstance(words,list) or not words:continue
        bounds=[]
        for word in words:
            rect=[word.get(k) for k in ('x','y','width','height')]
            if not isinstance(word.get('text'),str) or not all(isinstance(n,(int,float)) and math.isfinite(n) for n in rect):
                raise ValueError('图片识别文字位置无效。')
            x,y,w,h=rect
            if min(x,y)<0 or min(w,h)<=0 or x+w>width+1 or y+h>height+1:raise ValueError('图片识别文字超出图像边界。')
            bounds.append((x,y,x+w,y+h))
        x=min(b[0] for b in bounds);y=min(b[1] for b in bounds)
        right=max(b[2] for b in bounds);bottom=max(b[3] for b in bounds)
        # Recover physical joins, rather than accepting OCR's inserted spaces
        # in names, Chinese words and model numbers such as VX 1000.
        text='';previous=None
        for word,b in zip(words,bounds):
            if previous is not None and b[0]-previous[2]>min(previous[3]-previous[1],b[3]-b[1])*.28:text+=' '
            text+=word['text'];previous=b
        lines.append({'id':index,'text':text,'box':[x,y,right,bottom]})
    return {'width':width,'height':height,'lines':lines,'angle':value.get('angle') or 0}
