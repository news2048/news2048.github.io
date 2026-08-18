#!/usr/bin/env python3
"""把 modules/*/module.json 合併成單一靜態檔 data/dashboard.json。

設計原則：
  - modules/<id>/module.json 是你唯一要編輯的來源檔
  - 這支腳本只做「收集 + 驗證 + 排序」，不做任何資料抓取
  - 輸出是純靜態 JSON，前端只需一次 fetch

用法：
    python3 tools/build.py            # 建置
    python3 tools/build.py --check    # 只驗證不寫檔
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT / "modules"
OUTPUT = ROOT / "data" / "dashboard.json"

TPE = timezone(timedelta(hours=8))

VALID_TYPES = {"delta", "compare", "list", "note", "lottery"}
VALID_STATUS = {"published", "draft", "archived"}
REQUIRED = ["id", "title", "type", "updated"]
NEWS_SOURCE_REQUIRED = ["outlet", "date", "title", "url"]


class ModuleError(Exception):
    pass


def validate_news_source_manifest(mod: dict) -> None:
    """媒體比較的證據必須能逐則回查；舊模組只能顯式標記為待回補。"""
    if mod["type"] != "compare" or "媒體比較" not in mod.get("tags", []):
        return

    manifest_ref = mod.get("source_manifest")
    if not manifest_ref:
        if mod.get("source_manifest_legacy") is True:
            return
        raise ModuleError("媒體比較模組缺少 source_manifest；不可只保存聚合篇數")

    path_text = manifest_ref.get("path")
    expected_count = manifest_ref.get("count")
    if not path_text or not isinstance(expected_count, int) or expected_count < 1:
        raise ModuleError("source_manifest 必須包含 path 與大於 0 的 count")

    manifest_path = (ROOT / path_text).resolve()
    try:
        manifest_path.relative_to(ROOT.resolve())
    except ValueError:
        raise ModuleError("source_manifest.path 必須位於專案目錄內")
    if not manifest_path.is_file():
        raise ModuleError(f"找不到逐則來源檔：{path_text}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ModuleError(f"逐則來源檔 JSON 格式錯誤：{e}")

    articles = manifest.get("articles")
    if not isinstance(articles, list) or not articles:
        raise ModuleError("逐則來源檔的 articles 必須是非空陣列")
    if manifest.get("module_id") != mod["id"]:
        raise ModuleError("逐則來源檔 module_id 與模組 id 不一致")
    if manifest.get("count") != len(articles) or expected_count != len(articles):
        raise ModuleError("source_manifest、來源檔 count 與 articles 實際筆數不一致")

    for index, article in enumerate(articles, start=1):
        missing = [field for field in NEWS_SOURCE_REQUIRED if not article.get(field)]
        if missing:
            raise ModuleError(f"逐則來源第 {index} 筆缺少欄位：{', '.join(missing)}")
        if not str(article["url"]).startswith(("https://", "http://")):
            raise ModuleError(f"逐則來源第 {index} 筆 url 不是 http(s) 網址")


def validate(mod: dict, path: Path) -> dict:
    """檢查必填欄位並補上預設值。失敗就丟 ModuleError，讓建置直接中斷。"""
    for field in REQUIRED:
        if not mod.get(field):
            raise ModuleError(f"缺少必填欄位 '{field}'")

    if mod["type"] not in VALID_TYPES:
        raise ModuleError(f"未知的 type '{mod['type']}'，可用：{sorted(VALID_TYPES)}")

    status = mod.setdefault("status", "published")
    if status not in VALID_STATUS:
        raise ModuleError(f"未知的 status '{status}'，可用：{sorted(VALID_STATUS)}")

    try:
        datetime.strptime(mod["updated"], "%Y-%m-%d")
    except ValueError:
        raise ModuleError(f"updated 必須是 YYYY-MM-DD，收到 '{mod['updated']}'")

    # 資料夾名稱即 id，避免兩者不同步造成除錯困難
    if mod["id"] != path.parent.name:
        raise ModuleError(f"id '{mod['id']}' 與資料夾名稱 '{path.parent.name}' 不符")

    mod.setdefault("tags", [])
    mod.setdefault("size", "m")          # s | m | l，控制卡片在 grid 佔幾欄
    mod.setdefault("pinned", False)
    mod.setdefault("order", 100)
    mod.setdefault("data", {})
    if status == "published":
        validate_news_source_manifest(mod)
    return mod


def collect() -> tuple[list[dict], list[str]]:
    mods, errors = [], []
    for path in sorted(MODULES_DIR.glob("*/module.json")):
        try:
            mod = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{path.parent.name}: JSON 格式錯誤 — {e}")
            continue
        try:
            mods.append(validate(mod, path))
        except ModuleError as e:
            errors.append(f"{path.parent.name}: {e}")

    ids = [m["id"] for m in mods]
    for dup in {i for i in ids if ids.count(i) > 1}:
        errors.append(f"重複的模組 id：{dup}")

    return mods, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只驗證，不寫出檔案")
    args = parser.parse_args()

    mods, errors = collect()
    if errors:
        print("建置失敗：", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    published = [m for m in mods if m["status"] == "published"]
    # 排序：置頂優先 → order 小的優先 → 更新日期新的優先。
    # 利用 Python sort 的穩定性：先排次要鍵（日期新→舊），再排主要鍵。
    published.sort(key=lambda m: m["updated"], reverse=True)
    published.sort(key=lambda m: (not m["pinned"], m["order"]))

    payload = {
        "generated_at": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
        "count": len(published),
        "modules": published,
    }

    skipped = len(mods) - len(published)
    if args.check:
        print(f"✓ 驗證通過：{len(mods)} 個模組（{len(published)} 個 published，{skipped} 個略過）")
        return 0

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"✓ 已寫出 {OUTPUT.relative_to(ROOT)}：{len(published)} 個模組"
          + (f"（略過 {skipped} 個非 published）" if skipped else ""))
    for m in published:
        pin = "📌" if m["pinned"] else "  "
        print(f"  {pin} [{m['type']:<8}] {m['id']:<28} {m['updated']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
