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


class ModuleError(Exception):
    pass


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
