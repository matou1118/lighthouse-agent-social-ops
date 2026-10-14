"""浏览器会话管理：每个平台独立 profile，你点进去人工操作，AI也能填表/截图/巡检。

用法：
    python 浏览器会话管理.py <平台名>
    python 浏览器会话管理.py --list
    python 浏览器会话管理.py --status <平台名>

平台名：58tongcheng / xishuw / sc518 / tieba / douban / xhs
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ================= 配置 =================
根 = Path(__file__).resolve().parent
load_dotenv(根 / ".env")

# 平台 → 登录地址 + profile目录
平台配置 = {
    "58tongcheng": {
        "name": "58同城绵阳/成都",
        "login_url": "https://m.58.com/w/npphywx202211107362/",
        "profile_dir": 根 / "数据" / "账号" / "58tongcheng",
        "env_key": "TB_58_COOKIE",  # 你可自行填 env
        "tag": "[MANUAL] 你注册/登录；AI仅巡检/生成文案",
    },
    "xishuw": {
        "name": "西蜀论坛·商家直通车",
        "login_url": "http://bbs.xishuw.com/member.php?mod=logging&action=login",
        "profile_dir": 根 / "数据" / "账号" / "xishuw",
        "env_key": "TB_XISHUW_COOKIE",
        "tag": "[MANUAL] 你注册/登录；AI尝试过自动注册（见记录）",
    },
    "sc518": {
        "name": "江油论坛",
        "login_url": "https://www.sc518.com/member.php?mod=logging&action=login",
        "profile_dir": 根 / "数据" / "账号" / "sc518",
        "env_key": "TB_SC518_COOKIE",
        "tag": "[AI-注册试验] 已尝试自动化注册 / [MANUAL-操作] 你登录确认",
    },
    "tieba": {
        "name": "百度贴吧（绵阳/成都/四川）",
        "login_url": "https://tieba.baidu.com/",
        "profile_dir": 根 / "数据" / "账号" / "tieba",
        "env_key": "TB_BDUSS",
        "tag": "[MANUAL-你操作] / [AI-只读] 你已登录，AI不动登录态",
    },
    "douban": {
        "name": "豆瓣小组（成都租房）",
        "login_url": "https://www.douban.com/accounts/login",
        "profile_dir": 根 / "数据" / "账号" / "douban",
        "env_key": "TB_DOUBAN_COOKIE",
        "tag": "[MANUAL] 你注册小号；AI仅生成文案",
    },
    "xhs": {
        "name": "小红书（主号 acct-new）",
        "login_url": "https://creator.xiaohongshu.com/",
        "profile_dir": Path(os.environ.get("XHS_USER_DATA_DIR",
                                            str(Path.home() / ".xhs-kit" / "profiles" / "acct-new"))),
        "env_key": "XHS_PROFILE",
        "tag": "[MANUAL-制动中] 禁止自动登录/发布；AI仅本地生成文案",
    },
}

# ================= 核心类 =================
class 浏览器管理器:
    def __init__(self, 平台名: str):
        if 平台名 not in 平台配置:
            raise ValueError(f"未知平台：{平台名}，可用：{list(平台配置.keys())}")
        self.cfg = 平台配置[平台名]
        self.平台名 = 平台名
        self.profile_dir = self.cfg["profile_dir"]
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    async def 打开浏览器(self, headless: bool = False) -> None:
        """启动浏览器，加载/保存 profile，供你人工操作。"""
        # 延迟导入 Playwright（仅运行时需要）
        from playwright.async_api import async_playwright

        print(f"[+] 启动浏览器 → {self.cfg['name']}")
        print(f"    profile: {self.profile_dir}")
        print(f"    标签: {self.cfg['tag']}")

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                locale="zh-CN",
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(self.cfg["login_url"], wait_until="domcontentloaded")
            print(f"[+] 已打开 {self.cfg['login_url']}")
            print(f"[+] 浏览器保持开启 —— 你可以直接操作（登录/发帖/回复/巡检）")
            print(f"[+] 关闭此终端窗口 = 结束会话（profile 自动保存 cookies）")

            # 保持运行直到你关浏览器
            try:
                await context.wait_for_event("close")
            except Exception:
                pass
            finally:
                print(f"[+] 会话结束，profile 已保存至 {self.profile_dir}")

    def 读登录态(self) -> dict | None:
        """读取 profile 里的 cookies（供 AI 巡检/填表用）"""
        cookies_file = self.profile_dir / "cookies.json"
        if cookies_file.exists():
            return json.loads(cookies_file.read_text(encoding="utf-8"))
        return None

    def 写登录态(self, cookies: list[dict]) -> None:
        cookies_file = self.profile_dir / "cookies.json"
        cookies_file.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")


# ================= 命令 =================
async def cmd_打开(平台名: str) -> int:
    mgr = 浏览器管理器(平台名)
    await mgr.打开浏览器(headless=False)
    return 0


def cmd_列表() -> int:
    print("可用平台：")
    for k, v in 平台配置.items():
        print(f"  {k:12} → {v['name']}")
        print(f"    {v['tag']}")
        print(f"    profile: {v['profile_dir']}")
        print(f"    login:   {v['login_url']}")
    return 0


def cmd_状态(平台名: str) -> int:
    if 平台名 not in 平台配置:
        print(f"❌ 未知平台：{平台名}")
        return 1
    cfg = 平台配置[平台名]
    profile = cfg["profile_dir"]
    print(f"平台: {cfg['name']}")
    print(f"标签: {cfg['tag']}")
    print(f"profile目录: {profile}")
    print(f"目录存在: {'是' if profile.exists() else '否'}")
    if profile.exists():
        cookies = profile / "cookies.json"
        print(f"cookies.json: {'存在' if cookies.exists() else '不存在'}")
        if cookies.exists():
            import time
            print(f"修改时间: {time.ctime(cookies.stat().st_mtime)}")
    # 读 .env 对应键
    val = os.environ.get(cfg["env_key"], "")
    print(f"环境变量 {cfg['env_key']}: {'已设置' if val else '未设置'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="浏览器会话管理（人工登录/操作，AI巡检/填表）")
    p.add_argument("平台", nargs="?", help="平台名（如 58tongcheng / xishuw / sc518 / tieba / douban / xhs）")
    p.add_argument("--list", action="store_true", help="列出所有平台")
    p.add_argument("--status", metavar="平台", help="查看某平台登录态状态")
    a = p.parse_args()

    if a.list:
        return cmd_列表()
    if a.status:
        return cmd_状态(a.status)
    if not a.平台:
        p.print_help()
        return 1
    return asyncio.run(cmd_打开(a.平台))


if __name__ == "__main__":
    sys.exit(main())