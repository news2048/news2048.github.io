#!/usr/bin/env python3
"""從疾管署 NIDSS 抓取「上週病例數 vs 前三週平均」，寫成 news2048 模組。

抓取對象（都是伺服器端渲染的 HTML 表格，不需要瀏覽器）：
  - 新冠併發重症   https://nidss.cdc.gov.tw/nndss/Disease?id=19SC
  - 流感併發重症   https://nidss.cdc.gov.tw/nndss/disease?id=487a

兩個數字來自同一張「統計表-依發病日」：
  「2026年31週 (上週累計數)」        → current
  「上週與前三週平均數比較 (病例數)」 → △/▽ 差值，用來回推 previous

用法：
    python3 tools/fetch_nidss.py              # 抓取 + 寫模組 + 重新建置
    python3 tools/fetch_nidss.py --dry-run    # 只抓取並印出，不寫檔
    python3 tools/fetch_nidss.py --no-build   # 寫模組但不跑 build.py
"""

import argparse
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT / "modules"
TPE = timezone(timedelta(hours=8))

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) news2048-nidss/1.0"

# 圖表裡有多條數列（流感頁第一條是「已排除病例數」），一定要靠名稱認人，
# 不能取 series[0]，否則會抓到完全不同的數字。
SERIES_NAME = "確定病例數"

# 近期趨勢的 sparkline 取幾週。故意不含「本週累計數」——本週還沒過完，
# 畫進去會出現假的斷崖。
SPARK_WEEKS = 12

SOURCES = [
    {
        "module_id": "cdc-covid-weekly",
        "url": "https://nidss.cdc.gov.tw/nndss/Disease?id=19SC",
        "title": "新冠併發重症",
        "order": 30,
    },
    {
        "module_id": "cdc-flu-severe-weekly",
        "url": "https://nidss.cdc.gov.tw/nndss/disease?id=487a",
        "title": "流感併發重症",
        "order": 31,
    },
]


class ScrapeError(Exception):
    """抓取或解析失敗。寧可整支中斷，也不要寫出半殘的模組資料。"""


# ------------------------------------------------------------------ 取得頁面

def fetch(url: str, retries: int = 3) -> str:
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            # 某些 macOS Python 沒有連到系統 CA；系統 curl 仍會正常驗證 TLS。
            # 只在憑證鏈驗證失敗時 fallback，絕不關閉憑證驗證。
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                try:
                    completed = subprocess.run(
                        [
                            "/usr/bin/curl", "--fail", "--silent", "--show-error",
                            "--max-time", "30", "--user-agent", UA, url,
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    return completed.stdout
                except (OSError, subprocess.CalledProcessError) as curl_error:
                    last = curl_error
                if attempt < retries:
                    time.sleep(2 * attempt)
                continue
            last = e
            if attempt < retries:
                time.sleep(2 * attempt)
        except (TimeoutError, OSError) as e:
            last = e
            if attempt < retries:
                time.sleep(2 * attempt)
    raise ScrapeError(f"無法取得 {url}：{last}")


# -------------------------------------------------------------------- 解析

def strip_tags(s: str) -> str:
    """把 <font id="lastWeekAvg" size=2>△22.33</font> 這種包裝拆掉。"""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def parse_table(html: str) -> dict[str, str]:
    """把「統計表-依發病日」的 <th>/<td> 讀成 dict。

    頁面上有多張表，只取標題含「統計表-依發病日」的那張，避免抓到
    地區別或年齡別的表。
    """
    anchor = html.find("統計表-依發病日")
    if anchor < 0:
        raise ScrapeError("找不到『統計表-依發病日』區塊，版面可能已改版")

    end = html.find("</table>", anchor)
    if end < 0:
        raise ScrapeError("『統計表-依發病日』找不到表格結尾")

    rows = re.findall(
        r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>",
        html[anchor:end],
        re.S,
    )
    table = {strip_tags(k): strip_tags(v) for k, v in rows}
    if not table:
        raise ScrapeError("『統計表-依發病日』沒有解析到任何列")
    return table


def parse_charts(html: str) -> tuple[list[str], list[float]]:
    """取出 Highcharts 的 x 軸年週與『確定病例數』數列。

    頁面用 hcJson.push({...}) 內嵌設定，這裡做括號配對取出完整 JSON，
    比正規表達式硬切可靠得多（data 陣列裡有上百個逗號）。
    """
    m = re.search(r"hcJson\.push\(", html)
    if not m:
        raise ScrapeError("找不到 hcJson.push 圖表資料")

    start = html.index("{", m.end())
    depth, in_str, esc = 0, False, False
    obj_text = None
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                obj_text = html[start:i + 1]
                break
    if obj_text is None:
        raise ScrapeError("圖表 JSON 括號不成對")

    try:
        chart = json.loads(obj_text)
    except json.JSONDecodeError as e:
        raise ScrapeError(f"圖表 JSON 解析失敗：{e}")

    cats = [str(c) for c in chart.get("xAxis_categories", [])]
    for s in chart.get("series", []):
        if s.get("name") == SERIES_NAME:
            data = [float(v) for v in s.get("data", [])]
            if len(data) != len(cats):
                raise ScrapeError(
                    f"數列長度 {len(data)} 與年週數 {len(cats)} 不符"
                )
            return cats, data

    names = [s.get("name") for s in chart.get("series", [])]
    raise ScrapeError(f"圖表找不到『{SERIES_NAME}』數列，只有：{names}")


def parse_delta(text: str) -> float:
    """把『△22.33』『▽10』轉成帶正負號的浮點數。

    疾管署用三角形而非 +/-：△ 是比前三週平均多，▽ 是少。
    """
    num = re.search(r"\d+(?:\.\d+)?", text)
    if not num:
        raise ScrapeError(f"『上週與前三週平均數比較』看不出數字：{text!r}")
    value = float(num.group())
    if "▽" in text or "▼" in text:
        return -value
    if "△" in text or "▲" in text:
        return value
    if value == 0:
        return 0.0
    raise ScrapeError(f"『上週與前三週平均數比較』缺少 △/▽ 方向：{text!r}")


def find_row(table: dict[str, str], keyword: str) -> tuple[str, str]:
    for k, v in table.items():
        if keyword in k:
            return k, v
    raise ScrapeError(f"表格找不到含『{keyword}』的列")


def to_int(text: str, what: str) -> int:
    m = re.search(r"-?\d+", text.replace(",", ""))
    if not m:
        raise ScrapeError(f"{what} 不是數字：{text!r}")
    return int(m.group())


# ---------------------------------------------------------------- 組成資料

def scrape(src: dict) -> dict:
    html = fetch(src["url"])
    table = parse_table(html)
    cats, series = parse_charts(html)

    last_key, last_val = find_row(table, "上週累計數")
    current = to_int(last_val, "上週累計數")

    wk = re.search(r"(\d{4})年\s*(\d+)\s*週", last_key)
    if not wk:
        raise ScrapeError(f"看不出上週是第幾週：{last_key!r}")
    year, week = int(wk.group(1)), int(wk.group(2))

    _, delta_text = find_row(table, "上週與前三週平均數比較")
    delta = parse_delta(delta_text)
    previous = round(current - delta, 4)   # 前三週平均數

    # 交叉驗證：用圖表數列自己重算一次前三週平均。
    # 官方表格與圖表若對不上，代表版面或欄位語意變了，寧可中斷也不要寫錯。
    tag = f"{year}{week:02d}"
    if tag not in cats:
        raise ScrapeError(f"圖表年週找不到 {tag}，無法驗證")
    idx = cats.index(tag)
    if idx < 3:
        raise ScrapeError(f"圖表在 {tag} 之前不足三週，無法驗證")

    if series[idx] != current:
        raise ScrapeError(
            f"表格上週數 {current} 與圖表 {tag} 的 {series[idx]:g} 不一致"
        )
    check = sum(series[idx - 3:idx]) / 3
    if abs(check - previous) > 0.05:
        raise ScrapeError(
            f"前三週平均對不上：由 {delta_text} 回推 {previous:g}，"
            f"由圖表重算 {check:.2f}"
        )

    # sparkline 收在「上週」，不含尚未過完的本週
    lo = max(0, idx + 1 - SPARK_WEEKS)
    spark = [int(v) if float(v).is_integer() else v for v in series[lo:idx + 1]]

    return {
        "year": year,
        "week": week,
        "current": current,
        "previous": previous,
        "delta": delta,
        "delta_text": delta_text,
        "onset_latest": find_row(table, "最近一例發病日")[1],
        "this_week": to_int(find_row(table, "本週累計數")[1], "本週累計數"),
        "ytd": to_int(find_row(table, "今年累計數")[1], "今年累計數"),
        "deaths_ytd": to_int(find_row(table, "今年累計死亡數")[1], "今年累計死亡數"),
        "yoy_text": find_row(table, "過去三年同期平均數比較")[1],
        "series": spark,
        "weeks": cats[lo:idx + 1],
    }


def build_module(src: dict, d: dict) -> dict:
    """組出 modules/<id>/module.json 的內容。

    顯示重點放在 subtitle：一句話講完「上週幾案、跟前三週平均差多少」，
    下方 delta 卡再用箭頭與 sparkline 呈現同一件事。
    """
    headline = (
        f"上週病例共 {d['current']} 案，"
        f"相較於前三週平均數 {d['delta_text']}"
    )

    note = (
        f"上週為 {d['year']} 年第 {d['week']} 週；前三週平均 "
        f"{d['previous']:g} 案。今年累計 {d['ytd']} 案、累計死亡 "
        f"{d['deaths_ytd']} 例。本週（第 {d['week'] + 1} 週）目前 "
        f"{d['this_week']} 案，週未過完不宜比較。"
        "疾管署資料依發病日統計且會回溯校正，最近幾週數字通常偏低估。"
    )

    return {
        "id": src["module_id"],
        "title": src["title"],
        "subtitle": headline,
        "type": "delta",
        "status": "published",
        "updated": datetime.now(TPE).strftime("%Y-%m-%d"),
        "tags": ["每週", "疫情"],
        "size": "s",
        "pinned": True,
        "order": src["order"],
        "sample": False,
        "source": {
            "name": "衛福部疾管署 傳染病統計資料查詢系統（NIDSS）",
            "url": src["url"],
        },
        "review": {"reviewed": False, "by": "", "at": ""},
        "note": note,
        "data": {
            "unit": "案",
            "scheme": "semantic",
            "polarity": "higher-is-bad",
            "metrics": [
                {
                    "label": f"上週確診病例數（第 {d['week']} 週）",
                    "current": d["current"],
                    "previous": d["previous"],
                    "current_label": f"第 {d['week']} 週",
                    "previous_label": "前三週平均",
                    # 基準是移動平均而非前一點，app.js 因此會另外補一行逐期變化。
                    # series 是週資料，明確寫「前一週」，別用預設的「前一期」。
                    "period_label": "前一週",
                    "mode": "absolute",
                    "series": d["series"],
                }
            ],
        },
        "fetched_at": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
    }


# --------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只抓取並印出，不寫檔")
    ap.add_argument("--no-build", action="store_true", help="不執行 tools/build.py")
    args = ap.parse_args()

    lines, failed = [], []
    for src in SOURCES:
        try:
            d = scrape(src)
        except ScrapeError as e:
            print(f"✗ {src['title']}：{e}", file=sys.stderr)
            failed.append(src["title"])
            continue

        mod = build_module(src, d)
        lines.append(f"{src['title']}：{mod['subtitle']}")
        print(f"✓ {src['title']}　{mod['subtitle']}")
        print(f"    最近一例發病日 {d['onset_latest']}／"
              f"前三週平均 {d['previous']:g}／近 {len(d['series'])} 週 {d['series']}")

        if args.dry_run:
            continue

        out_dir = MODULES_DIR / src["module_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "module.json").write_text(
            json.dumps(mod, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    if failed:
        # 部分成功時仍然重新建置，讓抓到的那一個能上線。
        print(f"\n⚠ 有 {len(failed)} 個來源失敗：{'、'.join(failed)}", file=sys.stderr)

    if not args.dry_run and not args.no_build and len(failed) < len(SOURCES):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "build.py")])
        if r.returncode != 0:
            return r.returncode

    if lines:
        print("\n--- 可直接複製的一句話 ---")
        for line in lines:
            print(line)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
