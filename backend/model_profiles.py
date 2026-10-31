"""已保存的模型连接配置。

解决的问题：切换连接配置时，密钥往往只在创建时可见一次，切走再切回就得
重新申请/重输。这里把「提供方 + 地址 + 模型 + 密钥」整套存成本机配置，
切换时一键生效。

密钥经 `llm.secret` 用系统级加密落盘，界面从不回显明文。激活某个配置时，
同时把 provider/base_url/model 写入既有的 model-settings.json（不含密钥），
使 LLMClient 无需改动即可沿用原有读取链路。

与产品原则一致：这些配置属于**使用者本机**，不随软件或安装包分发。
"""
import json
import uuid
import copy
from pathlib import Path

from .glossary import store
from .llm import secret

VALID_PROVIDERS = ("compatible", "intranet")


def _path() -> Path:
    return store.data_dir() / "model-profiles.json"


def _load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = {}
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        profiles = []
    active = str(data.get("active", ""))
    # Older versions used the saved record directly. Freeze that version before any edit.
    applied = data.get('applied') if 'applied' in data else next((p for p in profiles if p.get('id') == active), None)
    return {"active": active, "profiles": profiles, "applied": copy.deepcopy(applied)}


def _save(data: dict) -> None:
    store.atomic_json(_path(), data)


def _public(profile: dict) -> dict:
    """对外暴露的字段，绝不包含密钥明文或密文，只报是否已配置。"""
    return {
        "id": profile.get("id", ""),
        "name": profile.get("name", ""),
        "provider": profile.get("provider", ""),
        "base_url": profile.get("base_url", ""),
        "model": profile.get("model", ""),
        "api_format": profile.get('api_format', 'openai'),
        "auth_type": profile.get('auth_type', 'auto'),
        "has_key": bool(profile.get("key")),
    }


def encryption_available() -> bool:
    return secret.available()


def list_profiles() -> dict:
    data = _load()
    return {
        "active": data["active"],
        "max": None,  # Kept for old clients; null means no application limit.
        "encryption": "dpapi" if secret.available() else "plain",
        "profiles": [{**_public(p), 'pending': p.get('id') == data['active'] and
                      any(p.get(k) != (data.get('applied') or {}).get(k)
                          for k in ('provider', 'base_url', 'model', 'key')) or (p.get('id') == data['active'] and
                      any(p.get(k, default) != (data.get('applied') or {}).get(k, default)
                          for k, default in (('api_format','openai'),('auth_type','auto'))))}
                     for p in data["profiles"]],
    }


def _find(data: dict, profile_id: str) -> dict | None:
    return next((p for p in data["profiles"] if p.get("id") == profile_id), None)


def _resolve_key(data: dict, existing: dict | None, provided: str | None) -> str:
    """决定最终存储的密钥。

    provided is None  → 保留原密钥（界面没填就沿用）
    provided == ''    → 显式清空
    否则              → 加密后存入
    """
    if provided is None:
        return existing.get("key", "") if existing else ""
    return secret.encrypt(provided) if provided else ""


def save_profile(payload: dict) -> dict:
    """新建或更新一个配置。返回不含密钥的公开视图与当前状态。"""
    data = _load()
    profile_id = str(payload.get("id", "")).strip()
    existing = _find(data, profile_id) if profile_id else None
    if profile_id and existing is None:
        raise ValueError("要更新的配置不存在，请刷新后重试。")

    provider = str(payload.get("provider", "")).strip().lower()
    if provider not in VALID_PROVIDERS:
        raise ValueError("请选择公司模型或兼容接口。")
    base_url = str(payload.get("base_url", "")).strip()
    model = str(payload.get("model", "")).strip()
    name = str(payload.get("name", "")).strip() or model or base_url or "未命名配置"
    key_arg = payload.get("api_key")
    provided = None if key_arg is None else str(key_arg)

    record = {
        "id": existing["id"] if existing else uuid.uuid4().hex,
        "name": name[:60],
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_format": str(payload.get('api_format', (existing or {}).get('api_format', 'openai'))).strip().lower(),
        "auth_type": str(payload.get('auth_type', (existing or {}).get('auth_type', 'auto'))).strip().lower(),
        "key": _resolve_key(data, existing, provided),
    }
    # 复用连接层的校验：地址合法性、内网地址锁定、外部必须 HTTPS 等。
    from .llm.client import LLMClient
    key_for_check = ""
    if record["key"]:
        try:
            key_for_check = secret.decrypt(record["key"])
        except ValueError:
            key_for_check = ""
    LLMClient(provider=provider, base_url=base_url, model=model,
              api_key=key_for_check, api_format=record['api_format'], auth_type=record['auth_type'])._validate_configuration()

    if existing:
        data["profiles"][data["profiles"].index(existing)] = record
    else:
        data["profiles"].append(record)
    # Saving never changes the active connection, including its encrypted key.
    _save(data)
    return {"profile": _public(record), **list_profiles()}


def delete_profile(profile_id: str) -> dict:
    data = _load()
    target = _find(data, profile_id)
    if target is None:
        raise ValueError("要删除的配置不存在，请刷新后重试。")
    if data["active"] == profile_id:
        raise ValueError('这个配置正在使用，请先使用另一个配置，再删除。')
    data["profiles"].remove(target)
    _save(data)
    return list_profiles()


def activate(profile_id: str) -> dict:
    data = _load()
    if _find(data, profile_id) is None:
        raise ValueError("配置不存在，请刷新后重试。")
    data["active"] = profile_id
    data['applied'] = copy.deepcopy(_find(data, profile_id))
    _apply_active(data)
    _save(data)
    return list_profiles()


def _apply_active(data: dict) -> None:
    """把当前激活配置（不含密钥）写入 model-settings.json，供 LLMClient 读取。"""
    active = data.get('applied')
    if not active:
        return
    store.atomic_json(store.data_dir() / "model-settings.json", {
        "provider": active.get("provider", ""),
        "base_url": active.get("base_url", ""),
        "model": active.get("model", ""),
        "api_format": active.get('api_format', 'openai'),
        "auth_type": active.get('auth_type', 'auto'),
        "api_key": "",  # 密钥统一由 model-profiles.json + DPAPI 管理
    })


def active_profile() -> dict | None:
    data = _load()
    return data.get('applied')


def active_key() -> str:
    """当前激活配置的密钥明文，供连接层使用；无则返回空串。"""
    active = active_profile()
    if not active or not active.get("key"):
        return ""
    try:
        return secret.decrypt(active["key"])
    except ValueError:
        # 本机解不开（换了账户/机器）→ 当作没有密钥，交由上层提示重新填写。
        return ""
