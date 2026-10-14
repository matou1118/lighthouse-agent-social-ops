"""AI 注册试验：仅测试平台是否允许自动化注册路径，不提交真实数据。
用于验证「AI自动注册」的可行性，所有数据均为明显虚假/无效。
"""
from __future__ import annotations

# 修复 Windows GBK 编码：先设置 UTF-8 再导入任何模块
import sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ================= 配置 =================
根 = Path(__file__).resolve().parent
load_dotenv(根 / ".env")

# 要试验注册的平台（选一个安全的 Discuz 论坛）
目标平台 = {
    "名": "江油论坛 (sc518.com)",
    "注册页": "https://www.sc518.com/member.php?mod=register",
    "profile目录": 根 / "数据" / "账号" / "sc518_试验",
    "备注": "Discuz 论坛，注册通常只需用户名/密码/邮箱/验证码",
}

# ================= 核心 =================
async def 注册试验() -> int:
    """打开注册页，填入明显虚假的信息，但不点击提交（或提交后期待失败）。"""
    # 延迟导入 Playwright
    from playwright.async_api import async_playwright

    目标平台["profile目录"].mkdir(parents=True, exist_ok=True)

    print(f"[+] AI 注册试验：{目标平台['名']}")
    print(f"    注册页: {目标平台['注册页']}")
    print(f"    profile: {目标平台['profile目录']}")
    print(f"    ⚠️ 仅填表演示，不提交真实数据；所有信息明显虚假")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(目标平台["profile目录"]),
            headless=False,  # 你可见过程
            args=["--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(目标平台["注册页"], wait_until="domcontentloaded")

        # 等待页面加载
        await page.wait_for_timeout(2000)

        # 填入明显虚假的注册信息（所有字段都带测试标识）
        try:
            # 用户名
            用户名输入 = page.locator('input[name="username"]')
            if await 用户名输入.count():
                await 用户名输入.fill("ai_test_account_12345")
                print(f"[+] 填入用户名: ai_test_account_12345")

            # 密码
            密码输入 = page.locator('input[name="password"]')
            if await 密码输入.count():
                await 密码输入.fill("TestPass123!@#")
                print(f"[+] 填入密码: TestPass123!@#")

            # 确认密码
            确认密码输入 = page.locator('input[name="password2"]')
            if await 确认密码输入.count():
                await 确认密码输入.fill("TestPass123!@#")
                print(f"[+] 确认密码: TestPass123!@#")

            # 邮箱（明显无效格式）
            邮箱输入 = page.locator('input[name="email"]')
            if await 邮箱输入.count():
                await 邮箱输入.fill("test@invalid-domain-xyz")
                print(f"[+] 填入邮箱: test@invalid-domain-xyz (故意无效格式)")

            # 验证码（需人工输入，此处仅演示定位）
            验证码输入 = page.locator('input[name="seccodeverify"]')
            if await 验证码输入.count():
                await 验证码输入.fill("0000")  # 明显错误
                print(f"[+] 填入验证码: 0000 (人工需改为真实验证码)")

            # 同意协议
            同意复选框 = page.locator('input[name="agree"]')
            if await 同意复选框.count():
                await 同意复选框.check()
                print(f"[+] 勾选同意协议")

            print(f"[+] 表单填充完成（全部为测试/无效数据）")
            print(f"[+] 请人工检查：")
            print(f"    - 用户名: ai_test_account_12345")
            print(f"    - 邮箱: test@invalid-domain-xyz (无效)")
            print(f"    - 验证码: 需要人工输入真实验证码")
            print(f"[+] AI 不会自动点击提交按钮——由你决定是否提交")
            print(f"[+] 如需提交，请人工点击 \"提交\" 按钮")

            # 等待你操作
            print(f"[+] 浏览器保持开启，供你人工确认/操作...")
            print(f"[+] 关闭此终端 = 结束会话")

            await context.wait_for_event("close")

        except Exception as e:
            print(f"[⚠️] 注册过程出错: {e}")
            return 1
        finally:
            await context.close()

    print(f"[+] 注册试验结束")
    return 0


def main() -> int:
    return asyncio.run(注册试验())


if __name__ == "__main__":
    sys.exit(main())