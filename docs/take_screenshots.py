"""截取工作台各页面（演示数据模式），输出到 docs/screenshots/。

用法：python docs/take_screenshots.py
前置：工作台服务已在 127.0.0.1:7654 运行
      （在 Beacon 目录跑 python server.py --no-open）

演示模式通过 localStorage['beacon-demo']=1 开启 —— 页面只显示
服务端生成的假数据，不含真实账号/客户信息。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

根 = Path(__file__).resolve().parent.parent
输出 = 根 / "docs" / "screenshots"
输出.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:7654/"
页面 = [
    ("overview",  "01_总览"),
    ("accounts",  "02_账号矩阵"),
    ("assets",    "03_内容资产"),
    ("review",    "04_审核发布"),
    ("trends",    "05_热点选题"),
    ("flow",      "06_业务流"),
    ("platforms", "07_平台矩阵"),
    ("knowledge", "08_知识库"),
    ("system",    "09_系统"),
]

#: 演示模式：切主题为极光、开启演示数据，避免真实账号/客户信息入镜
初始化脚本 = """
localStorage.setItem('beacon-demo', '1');
localStorage.setItem('beacon-theme', 'aurora');
"""


async def main() -> int:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
        )
        await context.add_init_script(初始化脚本)
        page = await context.new_page()

        for pid, name in 页面:
            try:
                await page.goto(f"{BASE}#{pid}", wait_until="load")
                await page.wait_for_timeout(1800)
                path = 输出 / f"{name}.png"
                await page.screenshot(path=str(path), full_page=False)
                print(f"OK  {path.name}")
            except Exception as e:
                print(f"ERR {name}: {e}", file=sys.stderr)

        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
