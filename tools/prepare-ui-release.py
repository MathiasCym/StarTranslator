from pathlib import Path
import json
root = Path(__file__).resolve().parents[1]
for file in ('package.json', 'package-lock.json'):
    target = root / file
    data = json.loads(target.read_text(encoding='utf-8'))
    data['version'] = '1.6.1'
    if file == 'package-lock.json':
        data['packages']['']['version'] = '1.6.1'
    else:
        data['description'] = '星译官 —— 中英技术文档翻译与审校工作台'
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
target = root / 'CHANGELOG.md'
text = target.read_text(encoding='utf-8')
if '## [1.6.1]' not in text:
    text = text.replace('# 更新记录\n', '# 更新记录\n\n## [1.6.1] - 2026-10-08\n\n- 焕新文档工作台与常用页面，让内容层次更清晰，操作更加集中。\n- 统一窗口、表单与结果展示的视觉语言，改善阅读与日常使用体验。\n- 完善不同窗口下的布局与操作反馈，使常用内容更容易查看与处理。\n- 加强键盘操作与细节衔接，让资料管理和任务处理更加顺畅。\n', 1)
    target.write_text(text, encoding='utf-8')
target = root / 'renderer/file-picker.html'
text = target.read_text(encoding='utf-8')
if 'workspace.css' not in text:
    text = text.replace('<link rel="stylesheet" href="file-picker.css">', '<link rel="stylesheet" href="file-picker.css"><link rel="stylesheet" href="workspace.css">')
text = text.replace('id="pickerSearch" type="search"', 'id="pickerSearch" type="search" aria-label="搜索当前文件夹"')
target.write_text(text, encoding='utf-8')
target = root / 'renderer/setup.html'
text = target.read_text(encoding='utf-8')
if 'setup-theme.css' not in text:
    text = text.replace('<link rel="stylesheet" href="setup.css">', '<link rel="stylesheet" href="setup.css"><link rel="stylesheet" href="setup-theme.css">')
target.write_text(text.replace('<span>↗</span>', ''), encoding='utf-8')
target = root / 'renderer/setup.js'
target.write_text(target.read_text(encoding='utf-8').replace('<span>↗</span>', '').replace('<span>✓</span>', ''), encoding='utf-8')
target = root / 'dist/qa/skill-integration/ui.cjs'
target.write_text(target.read_text(encoding='utf-8').replace('length===24', 'length===25'), encoding='utf-8')
target = root / 'dist/qa/skill-integration/verify-build.cjs'
text = target.read_text(encoding='utf-8').replace("assert.equal(version, '1.6.0')", "assert.equal(version, '1.6.1')")
text = text.replace("'renderer/term-search.js',", "'renderer/workspace.css', 'renderer/workspace.js', 'renderer/setup-theme.css', 'renderer/setup.html', 'renderer/setup.js', 'renderer/file-picker.html', 'renderer/term-search.js',", 1)
target.write_text(text, encoding='utf-8')
print('Prepared 1.6.1 UI release')
