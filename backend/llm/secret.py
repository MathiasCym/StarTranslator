"""接口密钥的静态加密。

用 Windows DPAPI（CryptProtectData）加密后再落盘：密文与**当前 Windows
用户账户**绑定，配置文件被拷到别的电脑、或被同机其他用户读取，都无法解开。
这是 Chrome / Edge 保存密码所用的同一套系统机制，无需第三方依赖。

诚实的边界：它能防「文件被拿走」和「别的账户读到」，但挡不住以当前账户
运行的恶意程序——任何要用这个密钥发起请求的进程都必须能解密它。

DPAPI 不可用时（非 Windows、或系统调用异常）退化为明文存储，并在返回值里
如实标注 scheme='plain'，由界面提示用户，绝不假装已经加密。
"""
import base64
import ctypes
from ctypes import wintypes

DPAPI_PREFIX = "dpapi:"
PLAIN_PREFIX = "plain:"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_for(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi_available() -> bool:
    try:
        return bool(ctypes.windll.crypt32 and ctypes.windll.kernel32)
    except (AttributeError, OSError):
        return False


def _dpapi_protect(data: bytes) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    out = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(_blob_for(data)), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    out = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(_blob_for(data)), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def available() -> bool:
    """当前环境是否支持系统级加密。"""
    return _dpapi_available()


def encrypt(plaintext: str) -> str:
    """把明文密钥加密成带方案前缀的字符串。DPAPI 不可用时回退明文前缀。"""
    if not plaintext:
        return ""
    if _dpapi_available():
        try:
            return DPAPI_PREFIX + base64.b64encode(
                _dpapi_protect(plaintext.encode("utf-8"))).decode("ascii")
        except OSError:
            pass
    return PLAIN_PREFIX + plaintext


def decrypt(stored: str) -> str:
    """还原密钥。带 dpapi: 前缀但当前无法解密时抛 ValueError（不静默返回空）。"""
    if not stored:
        return ""
    if stored.startswith(PLAIN_PREFIX):
        return stored[len(PLAIN_PREFIX):]
    if stored.startswith(DPAPI_PREFIX):
        raw = base64.b64decode(stored[len(DPAPI_PREFIX):])
        try:
            return _dpapi_unprotect(raw).decode("utf-8")
        except OSError as error:
            raise ValueError("已保存的密钥无法在本机解密（可能来自其他 Windows 账户或电脑）。") from error
    # 兼容：无前缀的旧值按明文处理。
    return stored


def is_encrypted(stored: str) -> bool:
    return bool(stored) and stored.startswith(DPAPI_PREFIX)
