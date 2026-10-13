"""Build the reviewed terminology patch; source documents are read-only references."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
baseline = json.loads((ROOT/'dist/qa/audit-20260929/baseline.json').read_text(encoding='utf-8'))
sources = {
 'PPT': {'title':'人工校对：Nova-LED Cinema Solution_10082026_EN.pptx', 'location':'用户提供的 21 页英文演示文稿；逐条记录页码'},
 'ARMOR': {'title':'NovaStar Armor Comparison', 'url':'https://www.novastar.tech/product/detail.html?catid=2&id=33'},
 'A10EN': {'title':'A10s Pro Receiving Card Specifications V1.3.0', 'url':'https://oss.novastar.tech/uploads/2024/12/A10s-Pro-Receiving-Card-Specifications-V1.3.0.pdf'},
 'A10CN': {'title':'A10s Pro 接收卡规格书 V1.3.0（搜索索引可读；下载返回 403）', 'url':'https://oss.novastar-led.cn/down/datasheet/jieshouka/A10s%20Pro%20%E6%8E%A5%E6%94%B6%E5%8D%A1%20%E8%A7%84%E6%A0%BC%E4%B9%A6-V1.3.0.pdf'},
 'COEXCN': {'title':'COEX 控制系统 NCP 说明与应用手册 V1.0.1，第 22 页接收卡规格对比', 'url':'https://oss.novastar-led.cn/down/datasheet/tongbu/COEX%E6%8E%A7%E5%88%B6%E7%B3%BB%E7%BB%9F%E8%A7%A3%E5%86%B3%E6%96%B9%E6%A1%88-NCP%E6%96%87%E4%BB%B6%E8%AF%B4%E6%98%8E%E4%B8%8E%E5%BA%94%E7%94%A8%E6%89%8B%E5%86%8C-V1.0.1.pdf'},
 'MX': {'title':'MX6000 Pro / MX2000 Pro Comparison', 'url':'https://www.novastar.tech/product/detail.html?catid=2&id=1'},
 'MX5G': {'title':'COEX 5G Solution Product Comparison', 'url':'https://www.novastar.tech/product/detail.html?catid=2&id=48'},
 'VMP': {'title':'VMP 官方英文介绍', 'url':'https://www.novastar.tech/tpl/VMP.html'},
 'VMPCN': {'title':'VMP 视觉管理平台中文产品页', 'url':'https://www.novastar-led.cn/index/products/index/id/75.html'},
 'CINEMA': {'title':'COEX Wiki LED Cinema Solution', 'url':'https://coex.novastar.wiki/en/Collaboration%26Promotion/LED-Cinema-Solution'},
 'MXSOLUTION': {'title':'MX Series Solution', 'url':'https://www.novastar.tech/tpl/MX_SERIES_SOLUTION.html'},
 'MLED': {'title':'NovaStar Industry Development Trends', 'url':'https://www.novastar.tech/content/detail.html?catid=18&id=100'},
 'SMARTLCT': {'title':'SmartLCT User Manual V3.5.13，第 52 页', 'url':'https://oss.novastar.tech/uploads/2023/05/SmartLCT-Screen-Configuration-Software-User-Manual-V3.5.13.pdf'},
 'EDITORIAL': {'title':'语言与概念校订', 'location':'明确拼写错误、概念/单位混淆；不冒充官网逐字对应，不用于通用词自动替换'},
}
patches = []
def term(zh, en, refs, note='', aliases=(), wrong=(), old_zh=None, invalid=()):
    keys = [zh, *(old_zh or [])]
    old = [e for e in baseline if e['zh'] in keys]
    patches.append({'zh':zh,'en':en,'variants':list(aliases),'wrong_variants':list(wrong),
        'note':note,'refs':refs,'old':[[e['zh'],e['en']] for e in old],
        'invalid_forms':list(invalid)})

term('逐点校正','pixel-level calibration',['CINEMA','ARMOR','PPT:5,6'],
     '一般技术名称首选 pixel-level calibration；若中文明确包含亮色度，应使用独立词条“逐点亮色度校正”的完整译法。旧写法不一概判错。',
     ['pixel level calibration','per-pixel calibration','point-by-point calibration','point-by-point correction'],['point by point proofreading'])
term('逐点亮色度校正','Pixel Level Brightness and Chroma Calibration',['PPT:5,6','ARMOR','COEXCN','A10EN:3'],
     '产品功能名沿用人工校对 PPT；普通句子可小写并使用 pixel-level 连字符。不能简化为仅亮度校正。',
     ['pixel-level brightness and chroma calibration'])
term('画质引擎','Image Booster',['PPT:5','A10EN:3','A10CN:2'],
     '诺瓦产品功能名；与 Dynamic Booster（动态引擎）分开。',invalid=['image engine'])
term('动态引擎','Dynamic Booster',['ARMOR','A10CN:2'], '诺瓦产品功能名。')
term('精细灰度','Precise Grayscale',['PPT:5,6,9','ARMOR','A10CN:2'], '产品功能名优先使用 Precise Grayscale。')
term('精细灰度算法','Precise Grayscale',['PPT:5,9','A10CN:2'],
     '指诺瓦功能名时用 Precise Grayscale；泛指精细灰度算法可描述为 precise grayscale algorithm。', ['precise grayscale algorithm'], invalid=['Fine Grayscale Algorithm'])
term('全灰阶校正','Full-Grayscale Calibration',['A10EN:2','A10CN:2','ARMOR'],
     '全灰阶校正与多层全灰阶校正分开；连字符差异不判为错误。', ['full grayscale calibration'])
term('全灰度校正','Full-Grayscale Calibration',['A10EN:2','A10CN:2'],
     '“全灰度”在此为“全灰阶”的同义中文；校正系统技术名称采用 calibration。', ['full grayscale calibration'],invalid=['full grayscale correction'])
term('多Layer全灰阶校正','Multi-Layer Full Grayscale Calibration',['PPT:11','MX'],
     '沿用影院 PPT 技术名称；不与单层或普通全灰阶校正混为同一功能。', ['multi-layer full-grayscale calibration'])
term('多层全灰阶校正','Multi-Layer Full Grayscale Calibration',['PPT:11','MX'], '“多Layer全灰阶校正”的规范中文写法。')
term('自适应热力补偿','Adaptive Thermal Compensation',['PPT:12','A10CN:2','MX5G'])
term('热力补偿算法','Thermal Compensation',['PPT:6,12','MX'],
     '功能名称采用 Thermal Compensation；明确自适应时使用 Adaptive Thermal Compensation。', ['thermal compensation algorithm'])
term('动态热力补偿','Dynamic Thermal Compensation',['PPT:12'], '影院 PPT 中的具体表述，勿与自适应热力补偿直接互换。')
term('快门适配','Shutter Fit',['ARMOR','COEXCN'])
term('色彩管理','Color Management',['PPT:5,6','ARMOR','A10CN:2'],aliases=['colour management'])
term('VMP','Vision Management Platform',['VMP','VMPCN'],
     '产品正式展开为 Vision Management Platform；影院 PPT 第 5 页的 Visual / Managment 与正式名称不一致，产品名以官网为准。', ['VMP'], ['Vison Management Platform'])
term('带载','loading capacity',['PPT:5,13','ARMOR','COEXCN'],
     '用于参数标题或带载能力；作动词“带载某屏”仍可用 load / drive，不做通用词自动替换。', invalid=['load'])
term('带载能力','loading capacity',['ARMOR','COEXCN'], '参数名；数值单位通常为像素，不应与接口带宽混淆。')
term('最大带载能力','maximum loading capacity',['PPT:13','MX'],aliases=['max. loading capacity'])
term('单网口带载','per-port loading capacity',['PPT:13','EDITORIAL'],
     '由影院 PPT 的 per-cable loading 和带载参数语义规范化；网口能力与整机最大带载分开。')
term('无矩形框带载','No Rectangle Limitation',['MX','MX5G','VMP'],
     '官网 Comparison 功能标签；描述句可用 free from rectangular limitation。', ['no rectangular limitation','free from rectangular limitation'], invalid=['No rectangle loading capacity limit'])
term('接收卡','receiving card',['PPT:4,5,20','ARMOR'], aliases=['receiver card'],wrong=['receiving board card','reception card'])
term('发送卡','sending card',['PPT:20'],aliases=['sender card','transmitting card'],wrong=['sending board card','transmission board card'])
term('箱体','cabinet',['PPT:4,12','A10EN:4'],aliases=['LED cabinet'])
term('模组','module',['PPT:4','A10EN:4'],aliases=['LED module'])
term('驱动IC','driver IC',['PPT:4,5','A10EN:3'],aliases=['driver chip','LED driver IC'],wrong=['driving integrated circuit chip'])
term('LED影院解决方案','LED Cinema Solution',['PPT:1,4'])
term('影院控制器','cinema controller',['PPT:4,5'],aliases=['LED cinema controller'])
term('集成媒体模块','Integrated Media Block',['PPT:15'],aliases=['IMB'],note='影院语境下 IMB 的展开；不是普通 media server 的同义词。')
term('沉浸式音频解码器','immersive audio decoder',['PPT:4'])
term('功率放大器系统','power amplifier system',['PPT:4'])
term('扬声器系统','speaker system',['PPT:4'])
term('安全模块','security module',['PPT:6,14'])
term('安全芯片','security chip',['PPT:5,14'])
term('数字证书','digital certificate',['PPT:14'])
term('防拆检测','tamper detection',['PPT:14'],note='影院安全语境。Tamper clearance（清除防拆状态）应单独表述。')
term('箱门状态','cabinet-door status',['PPT:14'])
term('模组插拔','module insertion/removal',['PPT:14'])
term('显示屏监控','display monitoring',['PPT:14'])
term('PWM+PAM混合驱动技术','PWM+PAM Hybrid Driving Technology',['PPT:7','MLED'])
term('暗部细节','shadow detail',['PPT:7'],aliases=['details in dark areas'])
term('色域覆盖率','gamut coverage',['PPT:8'],aliases=['color gamut coverage'])
term('色彩准确性','color accuracy',['PPT:8,19'],aliases=['colour accuracy'])
term('色度','chromaticity',['PPT:6,10'],note='色度坐标/容差语境用 chromaticity；诺瓦“亮色度校正”固定功能名使用 chroma，不能全局互换。')
term('色度容差','chromaticity tolerance',['PPT:10'])
term('亮度容差','luminance tolerance',['PPT:10'])
term('灰阶过渡','grayscale transitions',['PPT:8'],aliases=['grayscale transition'])
term('传递函数','transfer function',['PPT:9'],note='SDR/HDR transfer function；不可与电路传输函数等其他上下文机械混用。')
term('分段线性化','piecewise linearization',['PPT:11'])
term('校正系数','calibration coefficients',['PPT:11,12','A10EN:4'],aliases=['calibration coefficient'])
term('实时监控','real-time monitoring',['PPT:5,14'])
term('亮度','luminance',['PPT:6,7,10','SMARTLCT','EDITORIAL'],
     '测光量用 luminance（cd/m² 或 nit）；产品亮度设置/描述也常用 brightness。nit 是单位，不是术语的译文；不要把文档中的数值单位自动改写。', ['brightness'],invalid=['nit','nits'])
term('照度','illuminance',['SMARTLCT','EDITORIAL'],
     '照度量的英文为 illuminance，单位为 lux（lx）。lux 不作为正确别名，也不自动替换数值单位。',invalid=['lux'])
term('饱和度','saturation',['MXSOLUTION'],
     '色彩属性用 saturation；原表附带音标且使用 Saturability，不能作为标准色彩术语。',invalid=['Saturability/sætʃərəˈbɪlɪti/','Saturability'])
term('色相','hue',['MXSOLUTION'])
term('散热','heat dissipation',['A10EN:2','MLED'],
     '屏体热管理语境；radiating 只是散热机制之一，不能作为通用标准译文。',invalid=['Radiating'])
term('主动式驱动','active matrix driving',['MLED'],aliases=['active-matrix driving','AM driving','active matrix'])
term('被动式驱动','passive matrix driving',['MLED'],aliases=['passive-matrix driving','PM driving','passive matrix'],wrong=['Passive Mactive'])
term('虚拟拍摄','virtual production',['MXSOLUTION'],
     '诺瓦解决方案与行业应用名称优先 virtual production；virtual shooting 可作历史描述性写法。', ['virtual shooting'],old_zh=['虚拟射拍摄'])
term('虚拟制片','virtual production',['MXSOLUTION','EDITORIAL'],
     '原表中文“虚拟纸片”为录入错误；VP 为简称。', ['VP'],old_zh=['虚拟纸片'])
term('XR虚拟拍摄','XR virtual production',['MXSOLUTION','EDITORIAL'],
     '行业应用名规范化；xR 是 extended reality，不代表所有 virtual production 都使用 xR。', ['xR virtual production','XR virtual shooting'])
term('亮度超驱动','Brightness Overdrive',['MX','A10CN:2'])
term('多模式','Multi-Mode',['MX5G','A10CN:2'])
term('帧频自适应','Adaptive Frame Rate',['MX','COEXCN'],
     'Comparison 标签用 Adaptive Frame Rate；A10s Pro 特定版本功能名为 Frame Rate Adaptive 3.0，不抹掉产品版本。', ['frame rate adaptive'])
term('RGB并行数据组','parallel RGB data groups',['ARMOR','COEXCN'],aliases=['RGB parallel data groups'])
term('串行数据组','serial data groups',['ARMOR','COEXCN'])
term('双卡备份','dual-card backup',['ARMOR','A10EN:5'],aliases=['dual card backup'])
term('环路备份','loop backup',['A10EN:5'])
term('固件程序回读','firmware program readback',['ARMOR'])
term('RGB独立Gamma调节','individual gamma adjustment for RGB',['ARMOR','A10CN:2'])
term('温度和电压监测','temperature and voltage monitoring',['A10EN:5','COEXCN'])
term('误码检测','bit error detection',['A10EN:5','COEXCN'])
term('色彩替换','Color Replacement',['MX','MXSOLUTION'])
term('色彩曲线','Color Curve',['MX','MXSOLUTION'])
term('14通道色彩校正','14-channel color correction',['MX'],aliases=['14CH Color Correction'])
term('输入位深','input bit depth',['MX'])
term('控制协议','control protocol',['MX'])
term('图层','layer',['MX'],aliases=['layers'])
term('成组管理','group management',['VMP'])
term('场景预设','scenario presets',['VMP'],aliases=['scene presets','scenario preset'])
term('拼缝校正','seam correction',['VMP','A10EN:3'])
term('曝光','exposure',['EDITORIAL'],
     '原表 Steper Exposure 含拼写错误且把泛称限缩为步进式曝光；若明确步进式曝光应写 stepper exposure。',invalid=['Steper Exposure'])
term('可靠性测试','reliability testing',['EDITORIAL'],
     'fusion 意为融合/熔合，与可靠性测试概念不符。保留为上下文核对线索，不自动替换普通单词 fusion。',invalid=['fusion'])
term('固晶机','die bonder',['EDITORIAL'],
     '与原部门表另一条 Die bonder 对照合并；Bounding machine 为拼写/术语错误。',wrong=['Bounding machine'])
term('芯片键合','die bonding',['EDITORIAL'], 'bonding 为键合；bounding 为拼写错误。',wrong=['Die bounding'])
term('分选','binning',['EDITORIAL'], 'LED 按参数分档分选；sorting 可作一般分选描述。', ['bin sorting','sorting'], ['Bining'])
term('编织','braiding',['EDITORIAL'], '仅纠正原表拼写；是否应收录在 LED 词库仍取决于线缆工艺语境。',wrong=['Briading'])

# Unresolved source concepts are retained as context, not advertised as verified terms.
pending = {
 '缓冲垫键合':'Bumper bonding 疑似应为 bump bonding，但中文本身存疑，须由封装工艺人员确认。',
 '后期前置化':'post-pre-installation 不符合影视语境，建议审阅“前置后期制作”等具体流程后定名。',
 '微焦':'Focus 通常指焦点/对焦；中文概念可能录入有误。',
 '余晖':'需区分 afterglow、persistence 与 ghosting；缺少原图/测试场景，不能简单互作别名。',
 '22bit+ 灰阶4倍提升算法':'官网 A10s Pro 文档描述 64 倍，原中文写 4 倍；可能是版本或功能差异，不能把数值直接统一。',
 '灯板':'light board / lamp board 与 LED module 的边界依产品结构而定，暂不统一。',
 '色块':'Color Block 与 display mura 有语境差异，需结合现象图片。',
 '麻点':'mura 是不均匀类现象泛称，不宜等同所有麻点；规格书也用 mottling。',
 '墨色':'ink color 易被理解为油墨颜色；PCB 阻焊膜颜色、屏幕黑态一致性需分别确认。',
 '气相外延生长':'MOCVD 是金属有机化学气相沉积，不能泛指所有气相外延。',
 '焊锡':'solder 与 solder paste（锡膏）需要区分原材料形态。',
 '裸眼3D':'anamorphic 与 autostereoscopic 是不同实现，原条目不应作为完全互换同义词。',
 '等保3级认证':'原英文不自然；需依据正式认证文件确定英文表述，当前材料不覆盖。',
 '面阵RGB相机亮色度精准测量':'原英文遗漏 chroma，设备功能的正式名称需要制造部门核定。',
}
audit={'id':'2026-09-29-cinema-v1','date':'2026-09-29','sources':sources,'patches':patches,'pending':pending,
       'pending_originals':[[e['zh'],e['en']] for e in baseline if e['zh'] in pending]}
(ROOT/'glossary/audit-20260929.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'{len(patches)} reviewed concepts; {len(pending)} unresolved concept groups')
