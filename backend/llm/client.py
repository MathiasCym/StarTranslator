"""内网、Qwen、DeepSeek 和兼容接口的统一模型连接层。

维护方通过运行环境配置连接，密钥不写入源码或安装包。
默认保留原内网连接；连接层本身不等于已部署的免登录云服务。
模型不可用或响应无效时抛 LLMUnavailable，不生成虚假的零错误报告。
"""
import json
import http.client
import logging
import os
import time
import threading
from ..task_queue import request_slot
import urllib.error
import urllib.request
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "http://llm.novastar.tech:31000/v1"
DEFAULT_MODEL = "local-plus"

# 内部明文 HTTP 的服务放行名单。公司内网部署的模型服务通常只有 http 地址，
# 强制 https 会让它们连不上。用带点的后缀（.novastar.tech）避免误放行
# evilnovastar.tech 这类伪装域名；额外主机经 NOVATERM_LLM_INSECURE_HOSTS 补充。
INSECURE_HTTP_HOSTS = {"localhost", "127.0.0.1", "::1"}
INSECURE_HTTP_SUFFIXES = ("novastar.tech",)


def _insecure_http_allowed(hostname: str) -> bool:
    host = (hostname or "").lower()
    if host in INSECURE_HTTP_HOSTS:
        return True
    if any(host == suffix or host.endswith("." + suffix) for suffix in INSECURE_HTTP_SUFFIXES):
        return True
    extra = os.getenv("NOVATERM_LLM_INSECURE_HOSTS", "")
    return host in {h.strip().lower() for h in extra.split(",") if h.strip()}


class LLMUnavailable(Exception):
    """网关不可达或返回错误。调用方须向上报错，不得降级。"""


class LLMResponseInvalid(LLMUnavailable):
    """The service answered, but its generated body needs regeneration."""


class LLMRequestFailed(LLMUnavailable):
    """The transport already used its retry budget; callers must not retry again."""
    retry_exhausted = True


def _urlopen(request, timeout):
    """Re-read current proxy settings, sharing the same routing for probes/chat.

    urllib's global opener otherwise retains the proxy present at its first use.
    Local and original intranet endpoints go directly; public APIs follow the
    current system/environment proxy, without inferring connectivity from VPN.
    """
    host = (urlsplit(request.full_url).hostname or '').lower()
    direct = host in INSECURE_HTTP_HOSTS or host == urlsplit(DEFAULT_BASE_URL).hostname
    handler = urllib.request.ProxyHandler({} if direct else None)
    return urllib.request.build_opener(handler).open(request, timeout=timeout)


class LLMTruncated(LLMUnavailable):
    """响应被 max_tokens 截断。text 保留未截断前的原始内容，供调用方抢救已完整的条目。

    区别于普通 LLMUnavailable：调用方若能把 text 里的完整 JSON 解析出来，
    可以保留这部分结果，而不是把「截断」当成「没有发现问题」。
    """

    def __init__(self, message: str, text: str = ""):
        super().__init__(message)
        self.text = text


def _load_api_key() -> str:
    env_path = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "NovaClaudeTools", "providers", "local-plus.env",
    )
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("UPSTREAM_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


class LLMClient:
    supports_document_batches = True
    def __init__(self, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout: int = 120, retries: int = 2,
                 *, provider: str | None = None, api_format: str | None = None,
                 auth_type: str | None = None):
        settings = {}
        settings_dir = os.getenv('NOVATERM_DATA_DIR')
        if settings_dir:
            try:
                with open(os.path.join(settings_dir,'model-settings.json'),encoding='utf-8') as file:
                    settings = json.load(file)
            except FileNotFoundError:
                pass
        configured_url = base_url if base_url is not None else settings.get('base_url', os.getenv("NOVATERM_LLM_BASE_URL", ""))
        default_provider = "compatible" if configured_url and configured_url != DEFAULT_BASE_URL else "intranet"
        self.provider = (provider or settings.get('provider') or os.getenv("NOVATERM_LLM_PROVIDER") or default_provider).strip().lower()
        self.api_format = (api_format if api_format is not None else settings.get('api_format', os.getenv('NOVATERM_LLM_API_FORMAT', 'openai'))).strip().lower()
        self.auth_type = (auth_type if auth_type is not None else settings.get('auth_type', 'auto')).strip().lower()
        defaults = {
            "intranet": (DEFAULT_BASE_URL, DEFAULT_MODEL),
            "deepseek": ("https://api.deepseek.com", "deepseek-flash"),
            # 百炼地址依地域和业务空间而定，由维护方提供。
            "qwen": ("", "qwen-plus"),
            "compatible": ("", ""),
        }
        default_url, default_model = defaults.get(self.provider, ("", ""))
        self.base_url = (configured_url or default_url).strip().rstrip("/")
        self.model = (model if model is not None else settings.get('model',os.getenv("NOVATERM_LLM_MODEL", default_model))).strip()
        if api_key is not None:
            self.api_key = api_key
        elif os.getenv("NOVATERM_LLM_API_KEY"):
            self.api_key = os.environ["NOVATERM_LLM_API_KEY"]
        elif (profile_key := self._profile_key(self.provider, self.base_url)):
            # 「模型设置」里保存并激活的连接配置，其密钥经系统级加密落盘。
            # 仅当配置的提供方与地址都与当前连接一致时才采用，避免把某个
            # 服务的密钥误发到另一个服务。
            self.api_key = profile_key
        elif self.provider != "intranet" and settings.get('api_key'):
            # 用户在「模型设置」里自带的密钥。内网连接仍用公司凭据文件，
            # 不被配置文件覆盖；兼容接口则用用户自己的密钥，绝不回退到公司凭据。
            self.api_key = settings['api_key']
        elif self.provider == "intranet":
            # 界面里填的密钥优先（用户改了要生效），没填才用公司凭据文件。
            # provider==intranet 已强制 base_url 必须为公司网关（见 _validate_configuration），
            # 所以用户密钥最多发往该网关，不会被配置劫持到其它服务。
            self.api_key = settings.get('api_key', '') or _load_api_key()
        else:
            key_env = {"qwen": "DASHSCOPE_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}.get(self.provider)
            self.api_key = os.getenv(key_env, "") if key_env else ""
        self.timeout = timeout
        self.retries = retries
        self.last_error = ""
        self._transport_lock = threading.Lock()
        self._transport_pause_until = 0

    @staticmethod
    def _profile_key(provider: str, base_url: str) -> str:
        """从已保存的激活配置取密钥，仅在提供方与地址均匹配时返回，否则空串。"""
        try:
            from .. import model_profiles
            active = model_profiles.active_profile()
        except Exception:
            return ""
        if not active:
            return ""
        same_provider = active.get("provider", "") == provider
        same_url = (active.get("base_url", "").rstrip("/") == base_url.rstrip("/"))
        return model_profiles.active_key() if (same_provider and same_url) else ""

    def _validate_configuration(self) -> None:
        if self.provider not in {"intranet", "qwen", "deepseek", "compatible"}:
            raise LLMUnavailable("模型服务配置不正确，请联系软件维护方。")
        if self.api_format not in {'openai', 'anthropic'} or self.auth_type not in {'auto', 'bearer', 'x-api-key'}:
            raise LLMUnavailable('请选择有效的接口格式和密钥发送方式。')
        if self.provider == 'intranet' and (self.api_format != 'openai' or self.auth_type == 'x-api-key'):
            raise LLMUnavailable('公司内网模型使用 OpenAI 接口格式和 Bearer 密钥。')
        try:
            url = urlsplit(self.base_url)
            valid = (url.scheme in {"http", "https"} and bool(url.hostname)
                     and not url.username and not url.password and not url.query and not url.fragment)
        except ValueError:
            valid = False
        if not valid or not self.model:
            raise LLMUnavailable("模型服务地址或模型名称尚未配置，请联系软件维护方。")
        if self.provider == "intranet" and self.base_url != DEFAULT_BASE_URL:
            raise LLMUnavailable("内网凭据只能用于原公司网关；其它服务请使用独立连接配置。")
        if self.provider != "intranet" and url.scheme != "https" and not _insecure_http_allowed(url.hostname):
            raise LLMUnavailable("外部模型服务需要使用 HTTPS 地址。")
        if self.provider in {"qwen", "deepseek"} and not self.api_key:
            raise LLMUnavailable("模型服务尚未配置调用凭据，请联系软件维护方；使用者无需登录。")

    @staticmethod
    def _http_error(status: int) -> str:
        if status in (401, 403):
            return "模型服务授权失败，请联系软件维护方检查服务配置。"
        if status == 402:
            return "模型服务余额不足，请联系软件维护方。"
        if status == 429:
            return "模型服务请求过多或额度受限，请稍后重试。"
        if status in (400, 404, 422):
            return "模型服务配置与接口不匹配，请联系软件维护方。"
        return f"模型服务暂时不可用（HTTP {status}），请稍后重试。"

    def _post(self, path: str, payload: dict) -> dict:
        self._validate_configuration()
        data = json.dumps(payload).encode("utf-8")
        headers = self._headers()
        headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(
            self._endpoint(path), data=data,
            headers=headers,
        )
        error_message = "无法连接模型服务，请检查网络或稍后重试。"
        for attempt in range(self.retries + 1):
            cancel = getattr(self, 'cancel', None)
            if cancel and cancel.is_set():
                raise LLMRequestFailed('任务已取消。')
            started = time.monotonic()
            try:
                with request_slot(cancel):
                    with self._transport_lock:
                        paused = time.monotonic() < self._transport_pause_until
                    if paused: raise LLMRequestFailed('模型连接暂时不可用，已暂停后续请求并保留本机断点，请稍后继续任务。')
                    with _urlopen(req, timeout=self.timeout) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                if not isinstance(result, dict) or result.get("error"):
                    raise LLMUnavailable("模型服务返回了无效响应，请稍后重试。")
                with self._transport_lock: self._transport_pause_until = 0
                logging.getLogger(__name__).info('Model request complete: attempt=%s elapsed=%.2fs', attempt+1, time.monotonic()-started)
                return result
            except urllib.error.HTTPError as e:
                error_message = self._http_error(e.code)
                retryable = e.code in (429, 500, 502, 503, 504)
                e.close()
                if not retryable:
                    raise LLMRequestFailed(error_message) from None
            except http.client.HTTPException:
                # Chunked gateways may close without a terminating chunk. Never
                # accept partial JSON, and never let IncompleteRead kill a file.
                error_message = '模型响应传输中断，自动重试后仍未完成；已完成内容会保留，请稍后重试未完成部分。'
            except (urllib.error.URLError, TimeoutError, OSError):
                error_message = "无法连接模型服务，请检查网络或稍后重试。"
                if self.provider == "intranet":
                    error_message = "无法连接公司内网模型，请确认内网可达，并检查 VPN 是否影响连接。"
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise LLMUnavailable("模型服务返回的内容无法解析，请稍后重试。") from None
            logging.getLogger(__name__).warning('Model request incomplete: attempt=%s elapsed=%.2fs retry=%s',
                attempt+1, time.monotonic()-started, attempt < self.retries)
            if attempt < self.retries:
                delay = 1.5 * (attempt + 1)
                if cancel:
                    if cancel.wait(delay): raise LLMRequestFailed('任务已取消。')
                else:
                    time.sleep(delay)
        with self._transport_lock: self._transport_pause_until = time.monotonic()+15
        raise LLMRequestFailed(error_message) from None

    def _headers(self) -> dict:
        headers = {}
        if self.api_format == 'anthropic': headers['anthropic-version'] = '2023-06-01'
        auth = self.auth_type if self.auth_type != 'auto' else 'x-api-key' if self.api_format == 'anthropic' else 'bearer'
        if self.api_key:
            if auth == 'x-api-key': headers['x-api-key'] = self.api_key
            else: headers['Authorization'] = f'Bearer {self.api_key}'
        return headers

    def _endpoint(self, resource: str) -> str:
        # Accept a service base, /v1 prefix or complete endpoint without doubling paths.
        base = self.base_url
        complete = False
        for suffix in ('/chat/completions', '/messages'):
            if base.endswith(suffix): base = base[:-len(suffix)]; complete = True; break
        if self.api_format == 'anthropic' and not complete and not urlsplit(base).path.rstrip('/').endswith('/v1'):
            base += '/v1'
        return base + resource

    @property
    def supports_thinking_mode(self):
        return self.api_format=='openai' and (self.provider in ('intranet','qwen','deepseek') or
            urlsplit(self.base_url).hostname=='api.deepseek.com')

    def chat(self, prompt: str, system: str | None = None, max_tokens: int = 2000,
             thinking: bool = False, images=None) -> str:
        """单轮对话。thinking 默认关闭——翻译类任务无需思维链，可省一个数量级的 token。"""
        content=prompt
        if images:
            import base64
            from pathlib import Path
            if not 1<=len(images)<=2: raise ValueError('页面检查一次只能读取一组页面。')
            content=[{'type':'text','text':prompt}]
            for image in images:
                raw=Path(image).read_bytes()
                if len(raw)>12*1024*1024 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise ValueError('页面图像格式或大小不正确。')
                encoded=base64.b64encode(raw).decode('ascii')
                if self.api_format=='anthropic':
                    content.append({'type':'image','source':{'type':'base64','media_type':'image/png','data':encoded}})
                else:
                    content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+encoded}})
        if self.api_format == 'anthropic':
            body = {'model': self.model, 'messages': [{'role': 'user', 'content': content}],
                    'max_tokens': max_tokens, 'stream': False}
            if system: body['system'] = system
            result = self._post('/messages', body)
            blocks = result.get('content')
            if not isinstance(blocks, list):
                raise LLMResponseInvalid('模型未返回有效内容，请重新生成。')
            text = ''.join(block['text'] for block in blocks if isinstance(block, dict) and
                           block.get('type') == 'text' and isinstance(block.get('text'), str))
            reason = result.get('stop_reason')
            if reason in {'max_tokens', 'model_context_window_exceeded'}:
                raise LLMTruncated('模型审校结果被截断，本次检验未完成。', text)
            if reason not in {'end_turn', 'stop_sequence'}:
                raise LLMResponseInvalid('模型未完成文本生成，请重新生成。')
            if not text.strip(): raise LLMResponseInvalid('模型返回了空内容，本次处理未完成。')
            return text
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if self.provider == "intranet":
            body["chat_template_kwargs"] = {"enable_thinking": thinking}
        elif self.provider == "qwen":
            body["enable_thinking"] = thinking
        elif self.provider == "deepseek" or (self.provider == 'compatible' and urlsplit(self.base_url).hostname == 'api.deepseek.com'):
            body["thinking"] = {"type": "enabled" if thinking else "disabled"}
        result = self._post("/chat/completions", body)
        try:
            choice = result["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMResponseInvalid("模型未返回有效内容，请重新生成。") from None
        if choice.get("finish_reason") == "length":
            raise LLMTruncated("模型审校结果被截断，本次检验未完成。",
                               text if isinstance(text, str) else "")
        if not isinstance(text, str) or not text.strip():
            raise LLMResponseInvalid("模型返回了空内容，本次处理未完成。")
        return text

    def chat_json(self, prompt: str, system: str | None = None,
                  max_tokens: int = 2000, *, thinking: bool = False) -> dict | list:
        """解析失败明确报错，不能被调用方当成没有发现问题。

        被截断时先尝试抢救：数组里已完整的条目照样返回，只是把截断事实
        附在返回值上（`__truncated__`），由调用方决定如何提示。
        """
        text = self.chat(prompt, system=system, max_tokens=max_tokens, thinking=thinking)
        result = _extract_json(text)
        if not isinstance(result, (dict, list)):
            raise LLMResponseInvalid("模型返回的结果格式无效，请重新生成。")
        return result

    def chat_images_json(self, prompt, images, system=None, max_tokens=1600):
        """Private page comparison; invalid or unsupported vision must fail explicitly."""
        result=_extract_json(self.chat(prompt,system=system,max_tokens=max_tokens,images=images))
        if not isinstance(result,dict):
            raise LLMResponseInvalid('页面检查响应无效。')
        return result

    def chat_json_recoverable(self, prompt: str, system: str | None = None,
                              max_tokens: int = 2000) -> tuple[dict | list, bool]:
        """与 chat_json 相同，但把「响应被截断」降级为返回值里的一项。

        返回 (result, truncated)。truncated=True 表示响应被 max_tokens 截断，
        但 result 里已解析出的条目仍然可用（可能不完整）。用聊天文本被当成
        审校结论才是危险；保留已确认的部分另有价值。
        """
        try:
            text = self.chat(prompt, system=system, max_tokens=max_tokens)
        except LLMTruncated as error:
            salvaged = _salvage_json(error.text)
            if not salvaged:
                # 抢救不出任何完整条目 → 不能当成「没有发现问题」，照常报错。
                raise
            return salvaged, True
        result = _extract_json(text)
        if not isinstance(result, (dict, list)):
            raise LLMUnavailable("模型返回的审校结果格式无效，本次检验未完成。")
        return result, False

    def connection_status(self, timeout: float | None = None) -> dict:
        """用于每秒状态检测：只读取模型列表，不执行生成、不重试。

        连接可访问与实际推理成功分开处理；检验前的 health() 仍验证生成。
        不支持模型列表的网关显示未确认，不把本地 Flask 启动当作模型在线。
        """
        def status(state, message, detail=""):
            return {"state": state, "message": message, "detail": detail, "model": self.model}

        try:
            self._validate_configuration()
            if timeout is None:
                host = (urlsplit(self.base_url).hostname or '').lower()
                timeout = 1.5 if host in INSECURE_HTTP_HOSTS or self.provider == 'intranet' else 8.0
            headers = {**self._headers(), 'Accept': 'application/json'}
            req = urllib.request.Request(self._endpoint('/models'), headers=headers, method="GET")
            with _urlopen(req, timeout=timeout) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                return status("unknown", "模型状态待确认", "模型列表响应过大，无法确认连接状态。")
            result = json.loads(raw.decode("utf-8"))
            models = result.get("data") if isinstance(result, dict) else None
            if not isinstance(models, list):
                return status("unknown", "模型状态待确认", "模型服务未返回可识别的模型列表。")
            selected = next((item for item in models if isinstance(item, dict) and item.get("id") == self.model), None)
            if selected is None:
                return status("unavailable", "所选模型不可用", "服务可连接，但未找到配置中的模型。")
            # llama.cpp 路由模式可能列出尚未加载的模型，不能直接标绿。
            model_state = selected.get("status")
            if isinstance(model_state, dict):
                model_state = model_state.get("value")
            if model_state and model_state != "loaded":
                labels = {"loading": "模型正在加载", "downloading": "模型正在下载",
                          "unloaded": "模型尚未加载", "sleeping": "模型休眠中"}
                return status("unknown", labels.get(model_state, "模型状态待确认"), "模型服务可连接，模型尚未确认就绪。")
            return status("connected", "模型已连接", "当前模型接口与所选模型可访问。")
        except LLMUnavailable as e:
            return status("unavailable", "模型未连接", str(e))
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            if code in (404, 405):
                return status("unknown", "模型状态待确认", "该服务不支持轻量连接检测；开始检验时会验证实际调用。")
            return status("unavailable", "模型未连接", self._http_error(code))
        except TimeoutError:
            return status("unavailable", "模型连接超时", "模型未及时响应，将自动重试。")
        except (urllib.error.URLError, OSError):
            return status("unavailable", "模型未连接", "无法访问配置中的模型服务，将自动重试。")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return status("unknown", "模型状态待确认", "模型服务返回的连接信息无法解析。")

    def health(self) -> bool:
        try:
            self.chat("Reply with OK only.", max_tokens=16)
            self.last_error = ""
            return True
        except LLMUnavailable as e:
            self.last_error = str(e)
            return False


def _extract_json(text: str):
    """从模型输出里抠出 JSON——模型常会包 ```json 代码块或加前后说明。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 从最外层第一个括号开始，保留数组，不能截成里面的某个对象。
    starts = [i for i in (cleaned.find("["), cleaned.find("{")) if i >= 0]
    if starts:
        try:
            value, _ = json.JSONDecoder().raw_decode(cleaned[min(starts):])
            return value
        except json.JSONDecodeError:
            pass
    return None


def _salvage_json(text: str):
    """抢救被截断的 JSON 数组：保留其中最前面的完整对象。

    截断通常发生在数组末尾的某个元素中途。把末尾残缺的片段丢掉，
    对剩余前缀补上 `]` 再解析，就能拿到前面已经完整的条目。只用于
    数组（审校结果就是对象数组）；对象被截断则无意义，返回 None。
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("[")
    if start < 0:
        return None
    body = cleaned[start:]
    decoder = json.JSONDecoder()
    out, index = [], 1
    while index < len(body):
        while index < len(body) and (body[index] in " \t\r\n,"):
            index += 1
        if index >= len(body):
            break
        try:
            value, end = decoder.raw_decode(body, index)
        except json.JSONDecodeError:
            break
        out.append(value)
        index = end
    return out
