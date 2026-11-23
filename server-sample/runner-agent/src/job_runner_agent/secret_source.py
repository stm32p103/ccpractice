"""秘密の読み取り(SecretSource ポート。research.md R15)。

値は SecretValue(repr に値を出さない)で返す。ログ・例外に値を含めない。
実装: 資格情報の保管機能(prod。Windows の資格情報マネージャ)、環境変数(dev のみ。警告)。
"""

from __future__ import annotations

import os
import sys
from typing import Protocol


class SecretNotFound(LookupError):
    """名前の秘密がない。メッセージに名前だけを含める(値を含めない)。"""

    def __init__(self, name: str) -> None:
        super().__init__(f"秘密が見つからない: {name}")
        self.name = name


class SecretValue:
    """秘密の値。repr・str に値を出さない。値は reveal() でだけ取り出す。"""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretValue(***)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretValue) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)


class SecretSource(Protocol):
    def get(self, name: str) -> SecretValue: ...


class EnvSecretSource:
    """環境変数から読む(dev のみ。設定の検証が prod での使用を拒否する)。"""

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else dict(os.environ)

    def get(self, name: str) -> SecretValue:
        value = self._environ.get(name)
        if not value:
            raise SecretNotFound(name)
        return SecretValue(value)


class CredentialStoreSecretSource:
    """Windows の資格情報マネージャ(CredReadW)から読む。呼び出したアカウントの領域だけが対象。"""

    def get(self, name: str) -> SecretValue:
        if sys.platform != "win32":  # pragma: no cover - Windows のみ
            raise SecretNotFound(name)
        import ctypes
        from ctypes import wintypes

        class CREDENTIAL(ctypes.Structure):
            _fields_ = (
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            )

        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        pointer = ctypes.POINTER(CREDENTIAL)
        cred_read = advapi.CredReadW
        cred_read.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer))
        cred_read.restype = wintypes.BOOL
        cred_free = advapi.CredFree
        cred_free.argtypes = (ctypes.c_void_p,)
        out = pointer()
        if not cred_read(name, 1, 0, ctypes.byref(out)):  # CRED_TYPE_GENERIC
            raise SecretNotFound(name)
        try:
            blob = ctypes.string_at(out.contents.CredentialBlob, out.contents.CredentialBlobSize)
        finally:
            cred_free(out)
        try:
            value = blob.decode("utf-16-le")
        except UnicodeDecodeError:
            value = blob.decode("utf-8", errors="replace")
        if not value:
            raise SecretNotFound(name)
        return SecretValue(value)
