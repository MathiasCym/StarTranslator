# 第三方组件

星译官源码使用仓库已有的 BSD 2-Clause 许可。以下组件保留各自的许可证与版权声明。

- Electron / Chromium / Node.js：运行环境随安装包提供原有许可证。
- Python 3.11.9：来自 python.org 官方便携运行库，安装包保留运行库原有许可。
- Python 依赖：版本固定于 requirements-runtime.txt，运行库包含其发行元数据与许可证。
- pypdf：BSD 3-Clause；用于本地读取 PDF 文字层，不提供 OCR。许可证随固定版本的运行库元数据一并分发。
- OfficeCLI v1.0.155：Apache License 2.0；完整许可位于 vendor/officecli/LICENSE.txt，与组件一同分发。来源与二进制摘要见 backend/skills/sources.json。
- Humanizer：MIT License，Copyright (c) 2025 Siqi Chen；完整许可位于 backend/skills/LICENSE.humanizer.txt。
- rcedit：electron/rcedit 项目的构建工具，仅在开发和打包阶段使用；锁定现有已验证的工具摘要，不参与使用者的文档处理。

参考文档中标明的其他项目用于设计和实现研究；其完整参考副本、使用者文档和研究诊断不上传到本仓库。
