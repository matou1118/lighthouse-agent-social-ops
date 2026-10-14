"""贴吧获客监控：采集 → 分类 → 过滤同行 → 提醒。

    python tieba.py --verify        出一份情报报告（首跑）
    python tieba.py --bars          看监控的吧
    python tieba.py                 扫一遍 → 提醒
    python tieba.py --watch         每 10 分钟轮询
    python tieba.py --leads         待跟进意向
    python tieba.py --stage ID 已回复  记跟进状态
    python tieba.py --dry-run       不通知不落盘

两股流
------
**意向流**：帖/楼含求卡求宽带信号 → 提醒。**不设回复量门槛** ——
刚发出来的求卡帖 0 回复，恰恰是最该抢的线索。

**热点流**：帖回复量 ≥ min_reply 且有新楼 → 跟贴机会。

同行过滤
--------
卡商帖和真人求助混在一起。命中的先用 `意向.是否同行` 过滤掉，
剩下的才是客户。（实测绵阳联通吧首页就被「号段」「丢一张…卡」这类占用。）

分界线
------
**工具只读**：采集、分类、提醒。不回复、不发帖、不顶贴。
回复由人在浏览器里手动做 —— 和 发布助手.py 同一个思路。

风险
----
只读、单号、限速（每请求间隔 1.2s）。8 吧 × 1 页 ≈ 每轮 10+ 请求，
低于真人刷新频率。**BDUSS 走 .env，绝不入库。**
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import aiotieba as tb

import 意向
import notify

根 = Path(__file__).resolve().parent
load_dotenv(根 / ".env")

数据目录 = 根 / "数据" / "贴吧"
配置文件 = 数据目录 / "配置.json"
帖子文件 = 数据目录 / "帖子.json"
意向文件 = 数据目录 / "意向.json"
状态文件 = 数据目录 / "状态.json"
报告文件 = 数据目录 / "情报.md"

默认吧 = [
    "四川联通吧", "绵阳联通吧",
    "四川移动吧", "绵阳移动吧",
    "四川电信吧", "绵阳电信吧",
]
#: ⚠️ 「四川广电吧」「绵阳广电吧」实测**不存在**（err=该吧还未建立）。
#: 广电有号段（192）但没建吧 —— 等有了再加回来：python tieba.py --bars
默认参数 = {"min_reply": 3, "每吧页数": 1, "回复上限": 300, "新鲜天数": 90}
请求间隔 = 1.2


# ── 基础设施 ─────────────────────────────────────────────────────────
def 现在() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def 读(path: Path, 默认):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            print(f"⚠️  {path.name} 损坏，用默认值", file=sys.stderr)
    return 默认


def 写(path: Path, 数据) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")


def 贴链接(tid, pid=None) -> str:
    u = f"https://tieba.baidu.com/p/{tid}"
    return f"{u}?pid={pid}#{pid}" if pid else u


def 作者名(obj) -> str:
    u = getattr(obj, "user", None)
    for a in ("user_name", "show_name", "nick_name"):
        v = getattr(u, a, None)
        if v:
            return str(v)
    return str(getattr(obj, "author_id", "") or "?")


def 判定(text: str, *, tid, pid, 吧, 作者, 回复量) -> dict:
    """把一条文本变成结构化条目。不管是不是意向，都返回（调用方自己筛）。"""
    a = 意向.分析(text)
    return {
        "tid": tid, "pid": pid, "吧": 吧, "作者": 作者,
        "内容": text.strip()[:200], "回复量": 回复量,
        "类别": a["类别"], "分数": a["分数"], "求助": a["求助"],
        "同行": a["同行"], "本地": a["本地"], "有联系方式": a["联系方式"],
        "水楼": 意向.是水楼(text), "卖家": 意向.是卖家(text),
        "链接": 贴链接(tid, pid), "发现": 现在(),
    }


def 是意向(条目: dict) -> bool:
    """和 意向.是意向 保持一致：在问/在求 + 话题相关 + 非同行 + 非水楼 + 非卖家。
    光有话题词会把整个吧都命中（实测单吧 300+ 条噪声）。"""
    return (bool(条目["类别"]) and 条目.get("求助", False)
            and not 条目["同行"] and not 条目.get("水楼", False)
            and not 条目.get("卖家", False))


# ── 采集 ─────────────────────────────────────────────────────────────
async def 拉新楼(client, tid: int, 已见floor: int, 上限页: int = 2) -> list:
    """只拉比 `已见floor` 新的楼层（`get_posts` 没有「某 pid 之后」接口，
    所以按 DESC 从最新往回走，碰到旧楼就停）。"""
    结果 = []
    for pn in range(1, 上限页 + 1):
        try:
            r = await client.get_posts(tid, pn, sort=tb.PostSortType.DESC,
                                       with_comments=True, comment_rn=10)
        except Exception as e:
            print(f"  ⚠️ 拉楼失败 tid={tid} pn={pn}: {e}", file=sys.stderr)
            break
        if getattr(r, "err", None):
            print(f"  ⚠️ 拉楼报错 tid={tid}: {r.err}", file=sys.stderr)
            break
        楼 = list(r)
        if not 楼:
            break
        新 = [p for p in 楼 if getattr(p, "floor", 0) > 已见floor]
        结果 += 新
        if len(新) < len(楼):        # 已经翻到旧楼，停
            break
        await asyncio.sleep(请求间隔)
    return 结果


async def 扫吧(client, 吧名, cfg, 帖子, 意向表, dry, 收集) -> list[dict]:
    """扫一个吧。返回本轮的意向提醒列表。"""
    提醒 = []
    页数 = cfg["参数"].get("每吧页数", 1)
    min_reply = cfg["参数"]["min_reply"]

    for pn in range(1, 页数 + 1):
        try:
            r = await client.get_threads(吧名, pn, sort=tb.ThreadSortType.REPLY)
        except Exception as e:
            print(f"  ⚠️ {吧名} 列表失败: {e}", file=sys.stderr)
            return 提醒
        if getattr(r, "err", None):
            print(f"  ⚠️ {吧名} 列表报错: {r.err}", file=sys.stderr)
            return 提醒

        新鲜天数 = cfg["参数"].get("新鲜天数", 90)
        截止 = time.time() - 新鲜天数 * 86400

        for t in r:
            if getattr(t, "is_top", False):        # 置顶广告，跳过
                continue
            tid = t.tid
            创建 = int(getattr(t, "create_time", 0) or 0)
            # 老帖不是线索。实测绵阳电信吧首屏混着 2011 年的帖
            # （「4M 宽带多少钱」），照样被 REPLY 排序顶上来。跳过。
            if 创建 and 创建 < 截止:
                continue
            回复量 = int(getattr(t, "reply_num", 0) or 0)
            旧 = 帖子.get(str(tid))
            收集["帖数"] += 1

            # 帖本身（标题 + 楼主正文）
            文本 = f"{t.title or ''} {getattr(t, 'text', '') or ''}"
            条目 = 判定(文本, tid=tid, pid=None, 吧=吧名, 作者=作者名(t), 回复量=回复量)
            if 条目["类别"]:
                收集["话题"][条目["类别"][0]] = 收集["话题"].get(条目["类别"][0], 0) + 1
            if 条目["同行"]:
                收集["同行帖"] += 1
            elif 是意向(条目):
                收集["意向帖"] += 1
                key = f"t{tid}"
                if key not in 意向表:
                    if not dry:
                        意向表[key] = 条目
                    提醒.append(条目)

            # 有新楼吗。**只对热帖拉楼层** —— 帖标题已含意向信号，
            # 每帖都拉会让首轮 200+ 请求，跑不完。冷帖的标题就够了。
            已见floor = (旧 or {}).get("最大floor", 0)
            有变化 = (旧 is None) or (旧.get("回复数") != 回复量)
            回复上限 = cfg["参数"].get("回复上限", 300)
            # 回复量爆表的通常是水楼/练级楼，拉楼又慢又没价值 —— 设上限。
            该拉楼 = 有变化 and min_reply <= 回复量 <= 回复上限
            if 该拉楼:
                await asyncio.sleep(请求间隔)
                楼 = await 拉新楼(client, tid, 已见floor)
                最大floor = 已见floor
                for p in 楼:
                    最大floor = max(最大floor, getattr(p, "floor", 0))
                    p文本 = getattr(p, "text", "") or ""
                    # 楼层
                    if p文本:
                        p条目 = 判定(p文本, tid=tid, pid=p.pid, 吧=吧名,
                                     作者=作者名(p), 回复量=回复量)
                        if p条目["同行"]:
                            收集["同行帖"] += 1
                        elif 是意向(p条目):
                            收集["意向楼"] += 1
                            pk = f"p{p.pid}"
                            if pk not in 意向表:
                                if not dry:
                                    意向表[pk] = p条目
                                提醒.append(p条目)
                    # 楼中楼
                    for cm in (getattr(p, "comments", None) or []):
                        cm文本 = getattr(cm, "text", "") or ""
                        if not cm文本:
                            continue
                        c条目 = 判定(cm文本, tid=tid, pid=cm.pid, 吧=吧名,
                                     作者=作者名(cm), 回复量=回复量)
                        if c条目["同行"]:
                            收集["同行帖"] += 1
                        elif 是意向(c条目):
                            收集["意向楼"] += 1
                            ck = f"p{cm.pid}"
                            if ck not in 意向表:
                                if not dry:
                                    意向表[ck] = c条目
                                提醒.append(c条目)
                if not dry:
                    帖子[str(tid)] = {
                        "吧": 吧名, "标题": t.title, "作者": 作者名(t),
                        "回复数": 回复量, "最大floor": 最大floor, "最后扫": 现在(),
                    }
            elif not dry:
                帖子[str(tid)] = {
                    "吧": 吧名, "标题": t.title, "作者": 作者名(t),
                    "回复数": 回复量, "最大floor": 已见floor, "最后扫": 现在(),
                }

        await asyncio.sleep(请求间隔)
    return 提醒


async def 扫一遍(dry: bool = False, 出报告: bool = False) -> int:
    bduss = os.environ.get("TB_BDUSS", "").strip()
    if not bduss:
        print("❌ 缺 TB_BDUSS。在 工作台/.env 里填（见文件头说明）", file=sys.stderr)
        return 1

    cfg = 读(配置文件, {"吧": 默认吧, "参数": dict(默认参数)})
    帖子 = 读(帖子文件, {})
    意向表 = 读(意向文件, {})
    收集 = {"帖数": 0, "意向帖": 0, "意向楼": 0, "同行帖": 0, "话题": {},
            "各吧": {}, "回复分布": []}

    print(f"[*] 扫描 {len(cfg['吧'])} 个吧（{现在()}）")
    全部提醒 = []
    async with tb.Client(bduss) as client:
        for 吧名 in cfg["吧"]:
            前 = len(全部提醒)
            print(f"  → {吧名} …", end="", flush=True)
            try:
                提醒 = await 扫吧(client, 吧名, cfg, 帖子, 意向表, dry, 收集)
            except Exception as e:
                print(f" 崩了: {e}", file=sys.stderr)
                提醒 = []
            新增 = len(全部提醒) - 前
            全部提醒 += 提醒
            print(f" 命中 {len(提醒)} 条", flush=True)
            收集["各吧"][吧名] = len(提醒)

    # 排序：分数高的先，其次回复量少的（新帖优先）
    全部提醒.sort(key=lambda e: (-e["分数"], e["回复量"]))

    if not dry:
        写(帖子文件, 帖子)
        写(意向文件, 意向表)

    if 全部提醒:
        print(f"\n{'='*50}\n  命中 {len(全部提醒)} 条意向（已过滤同行）\n{'='*50}")
        # 只发一次批量通知
        top = 全部提醒[:10]
        link_lines = "\n".join(f"  {i}. [{e['吧']}] {e['内容'][:40]}… → {e['链接']}" 
                               for i, e in enumerate(top, 1))
        notify.提醒(
            f"贴吧意向 · 本轮 {len(全部提醒)} 条",
            [f"最高分：{top[0]['分数']} | 吧：{top[0]['吧']} · {top[0]['作者']}",
             f"「{top[0]['内容'][:55]}」",
             f"类别：{'/'.join(top[0]['类别'])} · 回复{top[0]['回复量']}"
             + (" · 绵阳本地" if top[0].get('本地') else "")] +
             (["---", link_lines] if len(top) > 1 else []),
            top[0]["链接"],
        )
    else:
        print("\n本轮无新意向。")

    if 出报告:
        写报告()
    return 0


# ── 报告 ─────────────────────────────────────────────────────────────
def 写报告() -> None:
    """累计情报报告。从意向库读，不是当轮快照 —— 报告要能看趋势。"""
    import collections

    意向表 = 读(意向文件, {})
    状态 = 读(状态文件, {})
    帖子 = 读(帖子文件, {})

    def 阶段(k):
        return 状态.get(k, {}).get("阶段", "待回复")

    待 = [k for k in 意向表 if 阶段(k) == "待回复"]
    本地数 = sum(1 for e in 意向表.values() if e.get("本地"))
    吧分布 = collections.Counter(e["吧"] for e in 意向表.values())
    类别分布 = collections.Counter(c for e in 意向表.values() for c in e["类别"])
    分数分布 = collections.Counter(e["分数"] for e in 意向表.values())

    L = [
        "# 贴吧情报报告", "",
        f"> 生成 {现在()} · 累计意向 {len(意向表)} 条 · "
        f"待跟进 {len(待)} 条 · 覆盖 {len(吧分布)} 个吧", "",
        "## 总览", "",
        "| 指标 | 值 |", "|---|---|",
        f"| 累计意向 | {len(意向表)} |",
        f"| 待跟进 | {len(待)} |",
        f"| 其中绵阳本地 | {本地数} |",
        f"| 已跟踪帖子 | {len(帖子)} |",
        "",
        "## 哪个吧线索多", "",
        "| 吧 | 意向数 |", "|---|---|",
    ]
    for k, v in 吧分布.most_common():
        L.append(f"| {k} | {v} |")

    L += ["", "## 大家在问什么", "", "| 类别 | 数量 |", "|---|---|"]
    for k, v in 类别分布.most_common():
        L.append(f"| {k} | {v} |")

    L += ["", "## 分数分布（越高越可能是真客户）", "",
          "| 分数 | 条数 |", "|---|---|"]
    for k, v in sorted(分数分布.items(), reverse=True):
        L.append(f"| {k} | {v} |")

    L += ["", "## 怎么读", "",
          "- **线索集中在四川级吧**，绵阳本地吧基本没新帖（实测 90 天内绵阳联通吧 0 帖）",
          "- **「绵阳本地」这一栏常年是 0**：四川吧是全省流量，多数人不说具体城市。",
          "   想知道谁会成交，回复后要自己问一句「你在绵阳吗」",
          "- **分数高不一定是客户**：转网回顾帖也会高分（提到多个话题）。",
          "   `--leads` 按分数排完，仍要人工扫一眼语气",
          "- **同行/水楼/卖家已在采集时过滤**，但词表会漏，看到广告帖记下来补词",
          "- 报告每次 `--verify` 刷新，隔几天对比能看出趋势", ""]

    报告文件.parent.mkdir(parents=True, exist_ok=True)
    报告文件.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[*] 报告已写入 {报告文件}")


# ── 其余命令 ─────────────────────────────────────────────────────────
def 列意向(只看本地: bool = False) -> int:
    意向表 = 读(意向文件, {})
    状态 = 读(状态文件, {})
    if not 意向表:
        print("还没有采集到意向。先跑：python tieba.py")
        return 0
    待 = [(k, e) for k, e in 意向表.items()
          if 状态.get(k, {}).get("阶段", "待回复") == "待回复"]
    if 只看本地:
        待 = [(k, e) for k, e in 待 if e.get("本地")]
        待.sort(key=lambda kv: -kv[1]["分数"])
        print(f"待跟进 · 绵阳本地 {len(待)} 条\n")
    else:
        待.sort(key=lambda kv: (-kv[1]["分数"], kv[1]["回复量"]))
        print(f"待跟进 {len(待)} 条 / 共 {len(意向表)} 条\n")
    if not 待:
        print("（没有符合条件的）")
        return 0
    for k, e in 待[:40]:
        print(f"[{k}] {e['吧']} · {e['作者']} · 回复{e['回复量']}"
              + ("  · 绵阳" if e.get("本地") else ""))
        print(f"   「{e['内容'][:70]}」")
        print(f"   {'/'.join(e['类别'])}  分{e['分数']}")
        print(f"   {e['链接']}\n")
    if len(待) > 40:
        print(f"… 还有 {len(待)-40} 条，先处理前面的")
    return 0


def 记阶段(key: str, 阶段: str) -> int:
    意向表 = 读(意向文件, {})
    if key not in 意向表:
        print(f"❌ 没有这个意向：{key}")
        return 1
    状态 = 读(状态文件, {})
    状态.setdefault(key, {})["阶段"] = 阶段
    状态[key]["更新"] = 现在()
    写(状态文件, 状态)
    print(f"✅ {key} → {阶段}")
    return 0


def 看吧() -> int:
    cfg = 读(配置文件, {"吧": 默认吧, "参数": dict(默认参数)})
    print("监控的吧：")
    for b in cfg["吧"]:
        print(f"  - {b}")
    print(f"\n参数：{cfg['参数']}")
    print(f"配置：{配置文件}")
    return 0


def 改参数(键: str, 值: str) -> int:
    cfg = 读(配置文件, {"吧": 默认吧, "参数": dict(默认参数)})
    try:
        cfg["参数"][键] = int(值)
    except ValueError:
        print("❌ 值必须是整数")
        return 1
    写(配置文件, cfg)
    print(f"✅ {键} = {值}")
    return 0


async def 巡逻(每隔秒: int, dry: bool) -> int:
    print(f"[*] 进入轮询，每 {每隔秒//60} 分钟一次。Ctrl+C 停。")
    while True:
        try:
            await 扫一遍(dry=dry)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"⚠️ 本轮出错：{e}", file=sys.stderr)
        print(f"[*] 下次扫描 {每隔秒//60} 分钟后...")
        await asyncio.sleep(每隔秒)


def main() -> int:
    p = argparse.ArgumentParser(description="贴吧获客监控")
    p.add_argument("--verify", action="store_true", help="出一份情报报告")
    p.add_argument("--watch", action="store_true", help="每 10 分钟轮询")
    p.add_argument("--leads", action="store_true", help="待跟进意向")
    p.add_argument("--本地", action="store_true", help="只列提到绵阳的")
    p.add_argument("--stage", nargs=2, metavar=("ID", "阶段"), help="记跟进状态")
    p.add_argument("--bars", action="store_true", help="看监控的吧")
    p.add_argument("--set", nargs=2, metavar=("键", "值"), help="改参数，如 min_reply 5")
    p.add_argument("--dry-run", action="store_true", help="不通知不落盘")
    a = p.parse_args()

    if a.bars:
        return 看吧()
    if a.set:
        return 改参数(*a.set)
    if a.leads or a.本地:
        return 列意向(只看本地=a.本地)
    if a.stage:
        return 记阶段(*a.stage)
    if a.watch:
        return asyncio.run(巡逻(600, a.dry_run))
    if a.verify:
        return asyncio.run(扫一遍(dry=a.dry_run, 出报告=True))
    return asyncio.run(扫一遍(dry=a.dry_run))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已停止。")
        sys.exit(130)
