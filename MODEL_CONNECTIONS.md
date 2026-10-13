# 模型接入进度

软件现名为「星译官」，发布者为 MathiasCym。

从 1.1.0 起，内网模型连接已扩展为可配置的连接层，支持 Qwen 官方接口、DeepSeek 官方接口和兼容接口。没有新配置时仍连接原公司网关。未配置真实外部服务，尚未交付免登录云版或内置本地模型版。

## 使用者安装即用的云端方案

桌面软件 → 维护方的 HTTPS 审校服务 → 官方模型 API。

使用者无需账号、验证码或 API Key。维护方开通官方模型服务并承担调用与托管费用。官方 API Key 保存在服务端；安装包只应携带公开服务地址。服务端应限制单次文档量、并发与总额度，并提供停用开关。文档中提取的待审校文本和相关术语会发送到所选云服务，界面需要如实说明。

该方案尚需确定费用承担方、模型平台和服务托管位置。统一后台尚未实现或部署；仅配置本机环境变量不能实现向所有人分发即用。

## 当前维护方配置

这些配置供维护方开发联调或部署使用，不是最终使用者的操作步骤。不要将真实密钥写入本文件、代码、打包配置或安装包。

| 环境变量 | 含义 |
| --- | --- |
| `NOVATERM_LLM_PROVIDER` | `intranet`、`qwen`、`deepseek` 或 `compatible` |
| `NOVATERM_LLM_BASE_URL` | API 基础地址，外部服务要求 HTTPS；本机服务可使用 HTTP |
| `NOVATERM_LLM_MODEL` | 模型名称，由维护方按平台可用模型指定 |
| `NOVATERM_LLM_API_KEY` | 当前连接的密钥，可替代下方平台专用变量 |
| `DASHSCOPE_API_KEY` | Qwen 官方连接的密钥 |
| `DEEPSEEK_API_KEY` | DeepSeek 官方连接的密钥 |

DeepSeek 默认地址为 `https://api.deepseek.com`，默认模型为 `deepseek-flash`。Qwen 默认模型为 `qwen-plus`，接入地址需从百炼控制台确认，按地域及业务空间填写，例如 `https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。兼容接口需显式指定模型与地址，可用于后续公共后台或本地模型服务，但目前没有随安装包提供本地模型。

外部连接不会自动读取公司的内网凭据，也不会在连接失败时自动将文档转发到另一个服务。错误提示区分授权、余额、限流、网络与响应格式问题；无效或被截断的响应不作为零错误报告。

## 检验

从 1.2.0 起，右上角连接状态由主进程每 1 秒检测一次，最小化窗口后仍工作。检测读取当前 API 基础地址下的 `/models`，核对配置的模型是否存在；每次上游请求超时 0.8 秒，本地检测总时限 1.5 秒，上一请求尚未结束时跳过该轮以避免堆积。恢复后自动更新。

绿色表示当前模型接口及所选模型可访问，红色表示连接失败、授权失败或所选模型缺失，黄色表示正在启动、加载中或服务不支持轻量探测。该探测不调用生成接口，不消耗生成 token，也不代表余额、推理质量或实际审校已通过；开始检验时仍验证真实生成调用。不支持 `/models` 的服务会如实显示待确认。

`python-runtime/python.exe -B tests/test_llm_client.py` 执行不联网的连接层回归测试。实际审校质量仍需在配置合法服务后运行 `tests/test_matcher.py`，并用真实工作样本对比。

官方依据（2026-09-24 查阅）：

- [DeepSeek 接入文档](https://api-docs.deepseek.com/)
- [DeepSeek 思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)
- [Qwen 首次调用](https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen)
- [Qwen 思考模式](https://help.aliyun.com/zh/model-studio/deep-thinking)
