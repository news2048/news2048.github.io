#!/usr/bin/env python3
"""抓取中央氣象署觀測與鄉鎮預報，更新台北氣溫模組。

用法：
    CWA_API_TOKEN=... python3 tools/fetch_weather.py
    CWA_API_TOKEN=... python3 tools/fetch_weather.py --dry-run
    CWA_API_TOKEN=... python3 tools/fetch_weather.py --no-build

授權碼優先從環境變數讀取；未設定時改讀 macOS Keychain 的
news2048-cwa-api-token 項目。不會寫入模組或輸出。
"""

import argparse
import json
import os
import ssl
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "modules" / "weather-taipei" / "module.json"
API_ROOT = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
HISTORY_ROOT = "https://opendata.cwa.gov.tw/historyapi/v1"
OBSERVATION_ID = "O-A0001-001"
FORECAST_ID = "F-D0047-061"
STATION_ID = "466920"
DISTRICT = "中正區"
TPE = timezone(timedelta(hours=8))
KEYCHAIN_SERVICE = "news2048-cwa-api-token"
KEYCHAIN_ACCOUNT = "news2048"


class WeatherError(Exception):
    pass


def load_token() -> str:
    token = os.environ.get("CWA_API_TOKEN", "").strip()
    if token:
        return token
    try:
        completed = subprocess.run(
            [
                "/usr/bin/security", "find-generic-password",
                "-a", KEYCHAIN_ACCOUNT,
                "-s", KEYCHAIN_SERVICE,
                "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise WeatherError(
            "找不到 CWA API token；請設定 CWA_API_TOKEN，或在 macOS Keychain "
            f"建立 {KEYCHAIN_SERVICE}"
        )
    token = completed.stdout.strip()
    if not token:
        raise WeatherError("macOS Keychain 的 CWA API token 是空值")
    return token


def request_bytes(url: str, params=None) -> bytes:
    """以 urllib 讀取，只有本機 Python 缺 CA 時才改用系統 curl。"""
    full_url = url + ("?" + urlencode(params) if params else "")
    request = Request(
        full_url,
        headers={
            "Accept": "application/json, application/xml;q=0.9",
            "User-Agent": "news2048/1.0 (+static dashboard data fetcher)",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            try:
                completed = subprocess.run(
                    [
                        "/usr/bin/curl", "--fail", "--silent", "--show-error",
                        "--location", "--max-time", "30",
                        "--user-agent", "news2048/1.0 (+static dashboard data fetcher)",
                        full_url,
                    ],
                    check=True,
                    capture_output=True,
                )
                return completed.stdout
            except (OSError, subprocess.CalledProcessError):
                raise WeatherError("中央氣象署 API 讀取失敗")
        raise WeatherError("中央氣象署 API 讀取失敗")
    except (HTTPError, TimeoutError):
        raise WeatherError("中央氣象署 API 讀取失敗")


def request_json(url: str, token: str, **params) -> dict:
    params = {"Authorization": token, "format": "JSON", **params}
    try:
        payload = json.loads(request_bytes(url, params))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise WeatherError("中央氣象署 API 回傳的 JSON 無法解析")
    success = payload.get("success")
    if success is None:
        success = payload.get("dataset", {}).get("success")
    if success not in (True, "true"):
        raise WeatherError("中央氣象署 API 回傳失敗")
    return payload


def parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value).astimezone(TPE)
    except (TypeError, ValueError):
        raise WeatherError(f"時間格式錯誤：{value!r}")


def parse_number(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise WeatherError(f"{label}不是有效數值")
    if number <= -90:
        raise WeatherError(f"{label}為缺值")
    return number


def fetch_current(token: str) -> dict:
    payload = request_json(
        f"{API_ROOT}/{OBSERVATION_ID}", token, StationId=STATION_ID
    )
    stations = payload.get("records", {}).get("Station", [])
    station = next((item for item in stations if item.get("StationId") == STATION_ID), None)
    if not station:
        raise WeatherError(f"觀測資料找不到臺北測站 {STATION_ID}")

    elements = station.get("WeatherElement", {})
    return {
        "station_name": station.get("StationName") or "臺北",
        "observed_at": parse_time(station.get("ObsTime", {}).get("DateTime")),
        "temperature": parse_number(elements.get("AirTemperature"), "目前氣溫"),
        "humidity": int(parse_number(elements.get("RelativeHumidity"), "相對濕度")),
        "weather": elements.get("Weather") or "",
    }


def existing_previous_temperature(observed_at: datetime):
    """優先使用前一天排程留下的本機快照，或沿用同整點比較值。

    history API 是滾動短期保存，昨日相同整點在執行時常已退出窗口。
    每日固定時間執行後，前一天模組本身就是最可靠的同時段快照。
    """
    if not MODULE_PATH.exists():
        return None
    try:
        module = json.loads(MODULE_PATH.read_text(encoding="utf-8"))
        metric = module["data"]["metrics"][0]
        saved_at_text = module["data"].get("observed_at")
        if saved_at_text:
            saved_at = parse_time(saved_at_text)
            if saved_at.date() == observed_at.date() - timedelta(days=1):
                clock_gap = abs(
                    (saved_at.hour * 60 + saved_at.minute)
                    - (observed_at.hour * 60 + observed_at.minute)
                )
                if clock_gap <= 90:
                    return (
                        parse_number(metric.get("current"), "昨日排程氣溫"),
                        saved_at,
                    )

        if module.get("updated") == observed_at.date().isoformat():
            subtitle = module.get("subtitle", "")
            if subtitle.endswith(observed_at.strftime("%-m/%-d %H:%M")):
                previous_at_text = module["data"].get("previous_observed_at")
                previous_at = (
                    parse_time(previous_at_text)
                    if previous_at_text
                    else observed_at - timedelta(days=1)
                )
                return (
                    parse_number(metric.get("previous"), "既有昨日氣溫"),
                    previous_at,
                )
        return None
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def history_snapshot_url(token: str, observed_at: datetime) -> tuple[str, datetime]:
    target = observed_at - timedelta(days=1)
    payload = request_json(
        f"{HISTORY_ROOT}/getMetadata/{OBSERVATION_ID}",
        token,
        timeFrom=(target - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
        timeTo=(target + timedelta(minutes=150)).strftime("%Y-%m-%dT%H:%M:%S"),
    )
    times = (
        payload.get("dataset", {}).get("resources", {}).get("resource", {})
        .get("data", {}).get("time", [])
    )
    if not times:
        raise WeatherError("短期歷史 API 找不到昨天同時段的觀測快照")

    def distance(item):
        return abs((parse_time(item.get("DateTime")) - target).total_seconds())

    closest = min(times, key=distance)
    # 短期歷史 API 採滾動保存，最早整點偶爾已退出窗口；首日允許使用
    # 兩小時內最近快照，並在卡片明寫實際比較時間。之後每日排程會優先
    # 使用前一天同一排程整點留下的模組快照。
    if distance(closest) > 7200:
        raise WeatherError("昨天最近的觀測快照與目前觀測時間相差超過兩小時")
    url = closest.get("ProductURL")
    if not isinstance(url, str) or not url.startswith("https://opendata.cwa.gov.tw/"):
        raise WeatherError("短期歷史 API 未提供有效下載網址")
    return url, parse_time(closest.get("DateTime"))


def fetch_previous_temperature(token: str, observed_at: datetime) -> tuple[float, datetime]:
    existing = existing_previous_temperature(observed_at)
    if existing is not None:
        return existing

    snapshot_url, snapshot_at = history_snapshot_url(token, observed_at)
    raw = request_bytes(snapshot_url)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise WeatherError("昨天的觀測 XML 無法解析")

    namespace = {"cwa": "urn:cwa:gov:tw:cwacommon:0.1"}
    for station in root.findall(".//cwa:Station", namespace):
        station_id = station.findtext("cwa:StationId", namespaces=namespace)
        if station_id != STATION_ID:
            continue
        value = station.findtext(
            "cwa:WeatherElement/cwa:AirTemperature", namespaces=namespace
        )
        return parse_number(value, "昨天氣溫"), snapshot_at
    raise WeatherError(f"昨天觀測快照找不到臺北測站 {STATION_ID}")


def element_map(location: dict) -> dict:
    return {
        item.get("ElementName"): item.get("Time", [])
        for item in location.get("WeatherElement", [])
    }


def fetch_rain_forecast(token: str, now: datetime) -> dict:
    payload = request_json(
        f"{API_ROOT}/{FORECAST_ID}", token, locationName=DISTRICT
    )
    groups = payload.get("records", {}).get("Locations", [])
    locations = groups[0].get("Location", []) if groups else []
    location = next((item for item in locations if item.get("LocationName") == DISTRICT), None)
    if not location:
        raise WeatherError(f"預報資料找不到臺北市{DISTRICT}")

    elements = element_map(location)
    pop_by_start = {}
    for item in elements.get("3小時降雨機率", []):
        values = item.get("ElementValue", [])
        if values:
            pop_by_start[item.get("StartTime")] = int(parse_number(
                values[0].get("ProbabilityOfPrecipitation"), "降雨機率"
            ))

    candidates = []
    for item in elements.get("天氣現象", []):
        values = item.get("ElementValue", [])
        if not values:
            continue
        start = parse_time(item.get("StartTime"))
        end = parse_time(item.get("EndTime"))
        weather = values[0].get("Weather") or ""
        if end <= now or start.date() != now.date() or "雨" not in weather:
            continue
        candidates.append({
            "start": start,
            "end": end,
            "probability": pop_by_start.get(item.get("StartTime")),
            "weather": weather,
        })

    if candidates:
        return min(candidates, key=lambda item: item["start"])

    future_pop = []
    for item in elements.get("3小時降雨機率", []):
        start = parse_time(item.get("StartTime"))
        end = parse_time(item.get("EndTime"))
        if end <= now or start.date() != now.date():
            continue
        value = item.get("ElementValue", [{}])[0].get("ProbabilityOfPrecipitation")
        future_pop.append(int(parse_number(value, "降雨機率")))
    return {
        "start": None,
        "end": None,
        "probability": max(future_pop) if future_pop else None,
        "weather": "",
    }


def compact_number(value: float):
    return int(value) if value.is_integer() else round(value, 1)


def rain_summary(forecast: dict) -> str:
    probability = forecast.get("probability")
    if forecast.get("start"):
        start = forecast["start"].strftime("%H")
        end = forecast["end"].strftime("%H")
        pop = f"，降雨機率 {probability}%" if probability is not None else ""
        return f"{start}–{end} 時{forecast['weather']}{pop}"
    if probability is None:
        return "今日暫無可用的降雨預報"
    return f"今日暫無含雨時段，未來時段最高降雨機率 {probability}%"


def build_module(
    current: dict,
    previous: float,
    previous_at: datetime,
    forecast: dict,
    now: datetime,
) -> dict:
    observed_label = current["observed_at"].strftime("%-m/%-d %H:%M")
    same_clock = current["observed_at"].strftime("%H:%M") == previous_at.strftime("%H:%M")
    previous_label = "昨天同時" if same_clock else f"昨天 {previous_at.strftime('%H:%M')}"
    return {
        "id": "weather-taipei",
        "title": "台北氣溫",
        "subtitle": f"臺北測站 {observed_label}",
        "type": "delta",
        "status": "published",
        "updated": current["observed_at"].date().isoformat(),
        "tags": ["每日", "天氣"],
        "size": "s",
        "pinned": True,
        "order": 10,
        "sample": False,
        "source": {
            "name": "中央氣象署開放資料平臺",
            "url": "https://opendata.cwa.gov.tw/",
        },
        "review": {"reviewed": False, "by": "", "at": ""},
        "note": (
            f"氣溫與濕度取自臺北測站（{STATION_ID}）逐時觀測；溫差比較同一測站"
            "昨天相同整點。降雨資訊取自臺北市中正區逐 3 小時預報；顯示的是"
            "預報時段與機率，不代表該時段必然下雨。"
        ),
        "data": {
            "unit": "°C",
            "scheme": "thermal",
            "polarity": "neutral",
            "observed_at": current["observed_at"].isoformat(),
            "previous_observed_at": previous_at.isoformat(),
            "metrics": [{
                "label": "目前氣溫",
                "current": compact_number(current["temperature"]),
                "previous": compact_number(previous),
                "current_label": "目前",
                "previous_label": previous_label,
                "mode": "absolute",
            }],
            "context": [
                f"目前濕度 {current['humidity']}%（{current['weather'] or '天氣現象未提供'}）",
                rain_summary(forecast),
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
        token = load_token()
        current = fetch_current(token)
        previous, previous_at = fetch_previous_temperature(token, current["observed_at"])
        forecast = fetch_rain_forecast(token, now)
        module = build_module(current, previous, previous_at, forecast, now)
    except WeatherError as exc:
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
