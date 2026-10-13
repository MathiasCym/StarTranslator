# 星译官 StarTranslator

**译步到位。** 中英技术文档翻译与审校工作台，由 MathiasCym 维护。

![星译官](renderer/assets/app-icon.png)

支持 Word / PowerPoint 翻译、英文校对、参考材料对照、专业术语维护、完整页面中英对照和局域网协作。软件无需账号登录；模型接口由使用者或共享电脑配置，支持公司内网模型及 OpenAI / Anthropic 兼容接口。

## 安装与更新

到 [正式发布版本](https://github.com/MathiasCym/StarTranslator/releases) 下载 Windows x64 安装包。2.0.0 起可在“关于 → 软件更新”检查、下载并安装新版本。下载和安装前均核对发布文件，升级保留模型配置、词库和历史记录；任务运行或配置尚未保存时需先完成处理。

## 团队维护术语库

1. 打开“术语库 → 团队同步”，点击“获取团队最新词库”。公开词库无需登录或安装 Git 即可读取。
2. 先保存当前编辑，再预览同步差异。双方修改相同字段时，选择保留本机或团队内容后确认，软件不会强行覆盖。
3. 维护者需成为仓库协作者，并在软件内保存具备内容写入权限的 GitHub 访问授权。授权在本机使用 Windows 加密，不回显、不上传、不包含在安装包中。
4. 填写维护说明并提交。本次改动会形成普通 Git 提交，可在“最近维护记录”或仓库中追溯。

团队词库为 [glossary/team.json](glossary/team.json)。仅该文件会由软件的团队同步功能提交；模型配置、文档、报告、日志与个人记录保持本地。已有共享文件方式和 JSON / Excel 导入导出仍可使用。

仓库所有者可使用仅选择 StarTranslator、授予 Contents 读写权限的细粒度授权。其他个人仓库协作者需在 [GitHub 的经典授权页面](https://github.com/settings/tokens/new) 创建具有 `public_repo` 权限的授权，再粘贴到软件的维护授权输入框。GitHub 当前不支持协作者通过细粒度授权写入他人的个人仓库，参见 [GitHub 授权说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)。授权不提供额外的仓库权限，维护者必须先接受本仓库的协作邀请。

## 局域网协作与文档对照

一台电脑配置模型后开启“局域网协作”，同事可以通过浏览器或已安装的软件连接，共享电脑同时处理两项任务，其余排队。无需注册或登录。翻译后的校对建议先展示，由使用者确认后保存；原稿保留。

完整页面对照通过已有 OfficeCLI 生成只读预览，无需安装 Office。字体、特殊效果和复杂公式可能与原生 Office 有差异，最终版式以导出的文件为准。详细使用说明见 [局域网协作与中英对照](docs/局域网协作与中英对照.md)。

## 开发与发布

需要 Windows x64、Node.js 24 和 Python 3.11。依赖版本与核心组件均固定，首次准备运行库需联网。

```powershell
npm ci
python tools/bootstrap-runtime.py
npm start
```

运行回归检查：

```powershell
python-runtime\python.exe -B tools/run-regressions.py
node --test tests/test_release.js tests/test_install_integrity.js tests/test_installation_repair.js tests/test_setup_worker.js tests/test_github_updates.js
```

版本按 [发布规则](RELEASING.md) 管理。维护者提交新版本源码到 main 后，GitHub Actions 执行测试、构建、实际安装引导图片验证及完整性校验，通过后发布安装包。单纯提交团队词库不会触发重复构建。已发布版本不会被覆盖。

## 联系与许可

作者邮箱：chenym1@novastar.tech。项目沿用仓库已有的 [BSD 2-Clause License](LICENSE)，第三方组件见 [组件说明](THIRD_PARTY_NOTICES.md)。
