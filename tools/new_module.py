#!/usr/bin/env python3
"""建立新模組的骨架，避免每次都要回想 schema。

用法：
    python3 tools/new_module.py delta   weather-taichung  "台中氣溫"
    python3 tools/new_module.py compare fu-kunchi-absence "傅崐萁缺席院會三報比較"
    python3 tools/new_module.py list    yt-topics-0812    "各台 YouTube 選題"
    python3 tools/new_module.py note    editor-note-0812  "編輯台觀察"

產生的模組預設 status=draft，你人工檢視內容後改成 published 再 build。
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

TEMPLATES = {
    "delta": {
        "unit": "°C",
        "polarity": "neutral",
        "scheme": "thermal",
        "metrics": [
            {
                "label": "白天最高溫",
                "current": 0,
                "previous": 0,
                "current_label": "今天",
                "previous_label": "昨天",
                "mode": "absolute",
                "series": [],
            }
        ],
    },
    "compare": {
        "question": "這則新聞，各家媒體怎麼處理？",
        "axes": [
            {"key": "headline", "label": "標題"},
            {"key": "framing", "label": "框架"},
            {"key": "sources", "label": "引述對象"},
        ],
        "subjects": [
            {
                "name": "中央社",
                "tone": "neutral",
                "url": "",
                "fields": {"headline": "", "framing": "", "sources": ""},
            }
        ],
        "takeaway": "",
    },
    "list": {
        "question": "各媒體今日 YouTube 選題差異",
        "columns": [
            {
                "name": "民視新聞",
                "url": "",
                "items": [{"text": "", "meta": ""}],
            }
        ],
        "takeaway": "",
    },
    "note": {
        "body": [
            "第一段文字。",
            "第二段文字。",
        ],
        "image": "",
        "image_caption": "",
    },
}


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 1

    mtype, mid, title = sys.argv[1], sys.argv[2], sys.argv[3]
    if mtype not in TEMPLATES:
        print(f"未知型別 '{mtype}'，可用：{', '.join(TEMPLATES)}")
        return 1

    target = ROOT / "modules" / mid
    if target.exists():
        print(f"模組 '{mid}' 已存在：{target}")
        return 1

    module = {
        "id": mid,
        "title": title,
        "subtitle": "",
        "type": mtype,
        "status": "draft",
        "updated": TODAY,
        "tags": [],
        "size": "m",
        "pinned": False,
        "order": 100,
        "source": {"name": "", "url": ""},
        "review": {"reviewed": False, "by": "", "at": ""},
        "note": "",
        "data": TEMPLATES[mtype],
    }

    target.mkdir(parents=True)
    out = target / "module.json"
    out.write_text(json.dumps(module, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ 已建立 {out.relative_to(ROOT)}")
    print("  編輯完內容後，把 status 改成 \"published\"，再執行 python3 tools/build.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
