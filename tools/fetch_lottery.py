#!/usr/bin/env python3
"""抓取台灣彩券最新結果，更新樂透累積獎金模組。

用法：
    python3 tools/fetch_lottery.py
    python3 tools/fetch_lottery.py --dry-run
    python3 tools/fetch_lottery.py --no-build
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
MODULE_PATH = ROOT / "modules" / "lottery-jackpots" / "module.json"
API_URL = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery/LatestResult"
SOURCE_URL = "https://www.taiwanlottery.com/lotto/lotto_lastest_result"
TPE = timezone(timedelta(hours=8))

# Python weekday：週一 = 0。官方固定開獎日為威力彩一／四、大樂透二／五。
GAMES = (
    {
        "key": "superLotto638Result",
        "id": "super-lotto-638",
        "name": "威力彩",
        "weekdays": (0, 3),
        "amount_decimals": 1,
        "first_prize_key": "super638JackpotAssign",
    },
    {
        "key": "lotto649Result",
        "id": "lotto-649",
        "name": "樂透彩",
        "weekdays": (1, 4),
        "amount_decimals": 0,
        "first_prize_key": "jackpotAssign",
    },
)


class LotteryError(Exception):
    pass


def fetch_json() -> dict:
    request = Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "news2048/1.0 (+static dashboard data fetcher)",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except URLError as exc:
        # 部分 macOS Python 安裝沒有連到系統鑰匙圈的 CA；系統 curl 仍會正常驗證。
        # 僅針對憑證鏈失敗 fallback，絕不關閉 TLS 驗證。
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            try:
                completed = subprocess.run(
                    [
                        "/usr/bin/curl", "--fail", "--silent", "--show-error",
                        "--max-time", "20", "--header", "Accept: application/json",
                        "--user-agent", "news2048/1.0 (+static dashboard data fetcher)",
                        API_URL,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return json.loads(completed.stdout)
            except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as curl_exc:
                raise LotteryError(f"台彩 API 讀取失敗：{curl_exc}")
        raise LotteryError(f"台彩 API 讀取失敗：{exc}")
    except (HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise LotteryError(f"台彩 API 讀取失敗：{exc}")


def parse_date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise LotteryError(f"{label} 缺少 lotteryDate")
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        raise LotteryError(f"{label} lotteryDate 格式錯誤：{value!r}")


def next_draw_after(latest: date, weekdays: tuple) -> date:
    candidate = latest + timedelta(days=1)
    while candidate.weekday() not in weekdays:
        candidate += timedelta(days=1)
    return candidate


def parse_game(content: dict, config: dict) -> dict:
    result = content.get(config["key"])
    if not isinstance(result, dict):
        raise LotteryError(f"API 缺少 {config['key']}")

    amount = result.get("totalAmount")
    if not isinstance(amount, int) or amount <= 0:
        raise LotteryError(f"{config['name']} totalAmount 無效：{amount!r}")

    period = result.get("period")
    if not isinstance(period, int):
        raise LotteryError(f"{config['name']} period 無效：{period!r}")

    first_prize = result.get(config["first_prize_key"])
    if not isinstance(first_prize, dict):
        raise LotteryError(f"{config['name']} 缺少頭獎分配資料")
    winner_count = first_prize.get("winnerCount")
    if not isinstance(winner_count, int) or winner_count < 0:
        raise LotteryError(f"{config['name']} 頭獎注數無效：{winner_count!r}")

    latest = parse_date(result.get("lotteryDate"), config["name"])
    return {
        "id": config["id"],
        "name": config["name"],
        "amount": amount,
        "amount_decimals": config["amount_decimals"],
        "latest_period": period,
        "latest_draw_date": latest.isoformat(),
        "next_draw_date": next_draw_after(latest, config["weekdays"]).isoformat(),
        "first_prize_winner_count": winner_count,
    }


def build_module(payload: dict, now: datetime) -> dict:
    if payload.get("rtCode") != 0:
        raise LotteryError(
            f"台彩 API 回傳失敗：rtCode={payload.get('rtCode')!r}, "
            f"rtMsg={payload.get('rtMsg')!r}"
        )
    content = payload.get("content")
    if not isinstance(content, dict):
        raise LotteryError("台彩 API 缺少 content")

    games = [parse_game(content, config) for config in GAMES]
    super_lotto = games[0]
    note = (
        "金額取自台灣彩券 LatestResult API 的 totalAmount，畫面以億元約數顯示，"
        "JSON 保留原始金額。開獎日依官方固定時程推算；威力彩每週一、四，"
        "樂透彩每週二、五。"
    )
    if super_lotto["first_prize_winner_count"] == 0:
        note = "最新一期威力彩頭獎無人中獎。" + note

    return {
        "id": "lottery-jackpots",
        "title": "樂透獎金累計",
        "subtitle": "威力彩 × 樂透彩",
        "type": "lottery",
        "status": "published",
        "updated": now.date().isoformat(),
        "tags": ["每日", "彩券"],
        "size": "s",
        "pinned": True,
        "order": 40,
        "sample": False,
        "source": {
            "name": "台灣彩券 LatestResult API",
            "url": API_URL,
        },
        "review": {"reviewed": False, "by": "", "at": ""},
        "note": note,
        "data": {"games": games},
        "fetched_at": now.strftime("%Y-%m-%d %H:%M"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只抓取並印出，不寫檔")
    parser.add_argument("--no-build", action="store_true", help="寫模組但不執行 build.py")
    args = parser.parse_args()

    try:
        module = build_module(fetch_json(), datetime.now(TPE))
    except LotteryError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    text = json.dumps(module, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(text, end="")
        return 0

    MODULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODULE_PATH.write_text(text, encoding="utf-8")
    print(f"✓ 已更新 {MODULE_PATH.relative_to(ROOT)}")

    if not args.no_build:
        completed = subprocess.run([sys.executable, str(ROOT / "tools" / "build.py")])
        return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
