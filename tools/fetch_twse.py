#!/usr/bin/env python3
"""抓取臺灣證券交易所最近交易日資料，更新加權指數模組。

資料來源為 TWSE OpenAPI 的「集中市場每日市場成交資訊」。API 目前回傳
最近數個交易日，可同時取得 TAIEX 與成交金額，足以計算前一交易日變化。

用法：
    python3 tools/fetch_twse.py
    python3 tools/fetch_twse.py --dry-run
    python3 tools/fetch_twse.py --no-build
"""

import argparse
import json
import ssl
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "modules" / "twse-index" / "module.json"
API_URL = "https://openapi.twse.com.tw/v1/exchangeReport/FMTQIK"
TPE = timezone(timedelta(hours=8))
SERIES_DAYS = 10


class TwseError(Exception):
    pass


def fetch_json() -> list:
    request = Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "news2048/1.0 (+static dashboard data fetcher)",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except URLError as exc:
        # 與其他抓取器相同：僅在 Python CA 鏈失敗時改用系統 curl，
        # curl 仍會驗證 TLS，絕不使用 -k/--insecure。
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            try:
                completed = subprocess.run(
                    [
                        "/usr/bin/curl", "--fail", "--silent", "--show-error",
                        "--max-time", "30", "--header", "Accept: application/json",
                        "--user-agent", "news2048/1.0 (+static dashboard data fetcher)",
                        API_URL,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                payload = json.loads(completed.stdout)
            except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as curl_exc:
                raise TwseError(f"TWSE OpenAPI 讀取失敗：{curl_exc}")
        else:
            raise TwseError(f"TWSE OpenAPI 讀取失敗：{exc}")
    except (HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise TwseError(f"TWSE OpenAPI 讀取失敗：{exc}")

    if not isinstance(payload, list):
        raise TwseError("TWSE OpenAPI 回傳格式不是陣列")
    return payload


def parse_roc_date(value: object) -> date:
    text = str(value or "").strip()
    if len(text) != 7 or not text.isdigit():
        raise TwseError(f"日期格式錯誤：{value!r}")
    year = int(text[:3]) + 1911
    try:
        return date(year, int(text[3:5]), int(text[5:7]))
    except ValueError as exc:
        raise TwseError(f"日期格式錯誤：{value!r}（{exc}）")


def parse_number(value: object, label: str) -> float:
    text = str(value or "").replace(",", "").strip()
    try:
        number = float(text)
    except ValueError:
        raise TwseError(f"{label} 不是數字：{value!r}")
    if number <= 0:
        raise TwseError(f"{label} 必須大於 0：{value!r}")
    return number


def parse_rows(payload: list, today: date) -> list:
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        trading_date = parse_roc_date(item.get("Date"))
        rows.append({
            "date": trading_date,
            "taiex": round(parse_number(item.get("TAIEX"), "TAIEX"), 2),
            "trade_value": int(parse_number(item.get("TradeValue"), "TradeValue")),
            "reported_change": float(str(item.get("Change", "")).replace(",", "")),
        })

    rows.sort(key=lambda row: row["date"])
    if len(rows) < 2:
        raise TwseError("TWSE OpenAPI 至少需要兩個交易日才能比較")
    if len({row["date"] for row in rows}) != len(rows):
        raise TwseError("TWSE OpenAPI 含重複交易日期")
    if rows[-1]["date"] > today:
        raise TwseError(f"最新交易日 {rows[-1]['date']} 晚於台北今日 {today}")

    calculated_change = round(rows[-1]["taiex"] - rows[-2]["taiex"], 2)
    if abs(calculated_change - rows[-1]["reported_change"]) > 0.02:
        raise TwseError(
            f"最新指數差 {calculated_change:+.2f} 與 API 漲跌點數 "
            f"{rows[-1]['reported_change']:+.2f} 不一致"
        )
    return rows


def build_module(rows: list, now: datetime) -> dict:
    latest, previous = rows[-1], rows[-2]
    recent = rows[-SERIES_DAYS:]
    latest_label = f"{latest['date'].month}/{latest['date'].day} 收盤"
    previous_label = f"{previous['date'].month}/{previous['date'].day} 收盤"

    return {
        "id": "twse-index",
        "title": "台股加權指數",
        "subtitle": f"{latest_label} vs {previous_label}",
        "type": "delta",
        "status": "published",
        # updated 表示資料期別；週末或休市日應保留最後交易日，而非假裝是今日資料。
        "updated": latest["date"].isoformat(),
        "tags": ["每日", "股市"],
        "size": "s",
        "pinned": True,
        "order": 20,
        "sample": False,
        "source": {
            "name": "臺灣證券交易所 OpenAPI－集中市場每日市場成交資訊",
            "url": API_URL,
        },
        "review": {"reviewed": False, "by": "", "at": ""},
        "note": (
            "採臺灣市場慣例配色：紅漲綠跌。資料為證交所最近交易日收盤值；"
            "週末、休市日或開盤前執行時，日期會保留在最近交易日。"
            "成交金額由 API 原始元數換算為億元。"
        ),
        "data": {
            "unit": "",
            "scheme": "market-tw",
            "polarity": "neutral",
            "metrics": [
                {
                    "label": "加權指數",
                    "current": latest["taiex"],
                    "previous": previous["taiex"],
                    "current_label": latest_label,
                    "previous_label": previous_label,
                    "period_label": "前一交易日",
                    "mode": "percent",
                    "series": [row["taiex"] for row in recent],
                },
                {
                    "label": "成交金額（億元）",
                    "current": round(latest["trade_value"] / 100_000_000, 2),
                    "previous": round(previous["trade_value"] / 100_000_000, 2),
                    "current_label": latest_label,
                    "previous_label": previous_label,
                    "period_label": "前一交易日",
                    "mode": "percent",
                    "series": [round(row["trade_value"] / 100_000_000, 2) for row in recent],
                },
            ],
        },
        "fetched_at": now.strftime("%Y-%m-%d %H:%M"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只抓取並印出，不寫檔")
    parser.add_argument("--no-build", action="store_true", help="寫模組但不執行 build.py")
    args = parser.parse_args()

    now = datetime.now(TPE)
    try:
        module = build_module(parse_rows(fetch_json(), now.date()), now)
    except (TwseError, ValueError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    text = json.dumps(module, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(text, end="")
        return 0

    MODULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODULE_PATH.write_text(text, encoding="utf-8")
    print(f"✓ 已更新 {MODULE_PATH.relative_to(ROOT)}（資料日 {module['updated']}）")

    if not args.no_build:
        completed = subprocess.run([sys.executable, str(ROOT / "tools" / "build.py")])
        return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
