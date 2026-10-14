"""本地提醒：控制台横幅 + 系统通知（带可点链接）。

为什么不用第三方库
------------------
`win10toast` / `plyer` 都没装，而 Windows 自带的能力够用：
- 控制台：Windows Terminal 支持 OSC 8 可点超链接
- 系统通知：PowerShell 调 WinRT toast（不装任何东西）

**系统通知的 AppID 必须先在 HKCU 注册一次**，否则 toast 静默失败。
注册是幂等的、只写 HKCU（不碰系统级），失败也不影响主流程 ——
控制台横幅永远会打出来，通知只是锦上添花。
"""
from __future__ import annotations

import os
import subprocess
import sys

APPID = "XhsOps.Workbench.Tieba"

#: OSC 8 超链接。老 conhost 不认，会把转义符原样打出来，所以先探测。
_OSC = "\033]8;;{}\033\\{}\033]8;;\033\\"

#: 系统通知：标题/正文/链接全走环境变量传，避免引号转义地狱。
_PS_TOAST = r"""
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]
$launch = ''
if ($env:TB_URL) { $launch = 'activationType="protocol" launch="' + $env:TB_URL + '"' }
$xml = '<toast ' + $launch + '><visual><binding template="ToastGeneric"><text>' +
       $env:TB_TITLE + '</text><text>' + $env:TB_BODY + '</text></binding></visual></toast>'
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$n = New-Object Windows.UI.Notifications.ToastNotification -ArgumentList $doc
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:TB_APPID).Show($n)
"""

#: 一次性注册 AppID，否则 toast 不显示。幂等。
_PS_REGISTER = r"""
$k = "HKCU:\Software\Classes\AppUserModelId\$env:TB_APPID"
New-Item -Path $k -Force | Out-Null
Set-ItemProperty -Path $k -Name DisplayName -Value "工作台"
"""


def _可点链接() -> bool:
    """Windows Terminal 认 OSC 8；老 conhost 不认，会打出乱码。"""
    return bool(os.environ.get("WT_SESSION")) or os.environ.get("TERM_PROGRAM") == "vscode"


def 链接(url: str, 文本: str | None = None) -> str:
    """带上就原样返回，不带就返回空串。终端支持时可点。"""
    if not url:
        return ""
    t = 文本 or url
    return _OSC.format(url, t) if _可点链接() else t


def 横幅(标题: str, 行: list[str], url: str = "") -> None:
    """控制台提醒块。**永远不会失败**，是通知的兜底。"""
    bar = "─" * 46
    print(f"\n{bar}\n  {标题}")
    for line in 行:
        print(f"  {line}")
    if url:
        print(f"  → {链接(url, url)}")
    print(bar)


def 弹窗(标题: str, 正文: str, url: str = "") -> bool:
    """系统通知。成功返回 True，失败返回 False（调用方不依赖它）。"""
    env = {**os.environ,
           "TB_APPID": APPID, "TB_TITLE": 标题[:120],
           "TB_BODY": 正文[:200], "TB_URL": url[:900]}
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", _PS_REGISTER],
                       env=env, capture_output=True, timeout=15)
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _PS_TOAST],
                           env=env, capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def 提示音() -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


def 提醒(标题: str, 行: list[str], url: str = "", 响铃: bool = True) -> None:
    """主入口：横幅 + 提示音 + 系统通知。

    横幅和响铃必成；系统通知尽力而为。**调用方不该因为通知失败就不干活。**
    """
    横幅(标题, 行, url)
    if 响铃:
        提示音()
    正文 = " · ".join(x.strip() for x in 行 if x.strip())[:200]
    弹窗(标题, 正文, url)


if __name__ == "__main__":
    print("可点链接:", _可点链接())
    print("测试横幅：")
    横幅("测试 · 绵阳联通吧", ["「求个LT大流量卡」", "回复量 0（新帖）"],
         "https://tieba.baidu.com/p/1234567890")
    print("\n测试系统通知（看看右下角有没有弹）：")
    弹窗("工作台 · 测试", "如果看到这条，系统通知可用", "https://tieba.baidu.com")
    print("弹窗函数已调用（返回 False 说明 toast 不可用，横幅仍有效）")
