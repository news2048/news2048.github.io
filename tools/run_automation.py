#!/usr/bin/env python3
"""news2048 每日中央自動化排程器。

每天只做一次決策：讀取 automation/policies.json，該更新的 job 才執行；
靜態、一次性與尚無抓取器的模組不會被碰觸。多個 job 完成後最多 build 一次。

用法：
    python3 tools/run_automation.py
    python3 tools/run_automation.py --plan
    python3 tools/run_automation.py --plan --date 2026-08-19
    python3 tools/run_automation.py --force-job lottery-results
"""

import argparse
import copy
import fcntl
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POLICIES_PATH = ROOT / "automation" / "policies.json"
STATUS_PATH = ROOT / "data" / "automation-status.json"
MODULES_DIR = ROOT / "modules"
LOG_PATH = Path.home() / "Library" / "Logs" / "news2048-automation.log"
LOCK_PATH = Path.home() / "Library" / "Logs" / "news2048-automation.lock"
TPE = timezone(timedelta(hours=8))
VOLATILE_MODULE_FIELDS = {"updated", "fetched_at", "review"}

# policies.json 只能引用這份白名單，不能放任意 shell 指令。
RUNNERS = {
    "fetch_weather": [sys.executable, "tools/fetch_weather.py", "--no-build"],
    "fetch_lottery": [sys.executable, "tools/fetch_lottery.py", "--no-build"],
    "fetch_nidss": [sys.executable, "tools/fetch_nidss.py", "--no-build"],
    "fetch_twse": [sys.executable, "tools/fetch_twse.py", "--no-build"],
}

MODE_LABELS = {
    "scheduled": "自動排程",
    "static": "靜態",
    "one_time": "一次性",
    "pending": "待接自動化",
}


class AutomationError(Exception):
    pass


def now_tpe() -> datetime:
    return datetime.now(TPE)


def stamp(value: datetime = None) -> str:
    return (value or now_tpe()).strftime("%Y-%m-%d %H:%M:%S")


def append_log(level: str, message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{level}] {stamp()} {message}\n")


def load_json(path: Path, default=None):
    if not path.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutomationError(f"無法讀取 {path.relative_to(ROOT)}：{exc}")


def load_policies() -> dict:
    policies = load_json(POLICIES_PATH)
    if not isinstance(policies, dict):
        raise AutomationError("automation/policies.json 必須是 JSON object")
    if policies.get("version") != 1:
        raise AutomationError("automation/policies.json version 必須是 1")

    seen_jobs = set()
    seen_modules = set()
    for job in policies.get("jobs", []):
        job_id = job.get("id")
        if not job_id or job_id in seen_jobs:
            raise AutomationError(f"job id 缺漏或重複：{job_id!r}")
        seen_jobs.add(job_id)
        if job.get("runner") not in RUNNERS:
            raise AutomationError(f"job {job_id} 使用未知 runner：{job.get('runner')!r}")
        for module_id in job.get("module_ids", []):
            if module_id in seen_modules:
                raise AutomationError(f"模組 {module_id} 同時屬於多個自動 job")
            seen_modules.add(module_id)
        schedule = job.get("schedule", {})
        if schedule.get("type") != "iso_weekdays":
            raise AutomationError(f"job {job_id} 目前只支援 iso_weekdays schedule")
        days = schedule.get("days")
        if not isinstance(days, list) or not days or any(day not in range(1, 8) for day in days):
            raise AutomationError(f"job {job_id} 的 days 必須介於 1～7")
    return policies


def semantic_module(raw: bytes):
    try:
        module = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw
    if not isinstance(module, dict):
        return module
    for field in VOLATILE_MODULE_FIELDS:
        module.pop(field, None)
    return module


def module_path(module_id: str) -> Path:
    return MODULES_DIR / module_id / "module.json"


def snapshot_modules(module_ids: list) -> dict:
    snapshots = {}
    for module_id in module_ids:
        path = module_path(module_id)
        snapshots[module_id] = path.read_bytes() if path.exists() else None
    return snapshots


def reconcile_modules(before: dict, module_ids: list) -> tuple:
    """還原只有 updated/fetched_at/review 改動的檔案，回傳真正有資料變化者。"""
    changed, unchanged = [], []
    for module_id in module_ids:
        path = module_path(module_id)
        old = before.get(module_id)
        new = path.read_bytes() if path.exists() else None
        if old is not None and new is not None and semantic_module(old) == semantic_module(new):
            if old != new:
                path.write_bytes(old)
            unchanged.append(module_id)
        elif old != new:
            changed.append(module_id)
        else:
            unchanged.append(module_id)
    return changed, unchanged


def output_tail(completed: subprocess.CompletedProcess, max_chars: int = 2400) -> str:
    text = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    return text[-max_chars:]


def job_is_due(job: dict, target_date: date) -> bool:
    return target_date.isoweekday() in job["schedule"]["days"]


def run_job(job: dict) -> dict:
    started = now_tpe()
    started_clock = time.monotonic()
    before = snapshot_modules(job["module_ids"])
    command = RUNNERS[job["runner"]]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        changed, unchanged = reconcile_modules(before, job["module_ids"])
        success = completed.returncode == 0
        message = (
            f"更新 {len(changed)} 個模組：{'、'.join(changed)}"
            if changed else "來源內容未變，模組檔保持不動"
        )
        if not success:
            message = f"exit {completed.returncode}；{message}"
        return {
            "status": "success" if success else "error",
            "started_at": stamp(started),
            "finished_at": stamp(),
            "duration_seconds": round(time.monotonic() - started_clock, 2),
            "changed_modules": changed,
            "unchanged_modules": unchanged,
            "message": message,
            "output_tail": output_tail(completed),
            "return_code": completed.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        changed, unchanged = reconcile_modules(before, job["module_ids"])
        return {
            "status": "error",
            "started_at": stamp(started),
            "finished_at": stamp(),
            "duration_seconds": round(time.monotonic() - started_clock, 2),
            "changed_modules": changed,
            "unchanged_modules": unchanged,
            "message": "執行超過 240 秒，已中止",
            "output_tail": str(exc),
            "return_code": None,
        }


def run_build() -> dict:
    started_clock = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "tools/build.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "status": "success" if completed.returncode == 0 else "error",
        "duration_seconds": round(time.monotonic() - started_clock, 2),
        "return_code": completed.returncode,
        "output_tail": output_tail(completed),
    }


def read_modules(policies: dict, job_results: list, history: dict, target_date: date) -> list:
    membership = {}
    result_by_id = {result["id"]: result for result in job_results}
    for job in policies.get("jobs", []):
        for module_id in job.get("module_ids", []):
            membership[module_id] = job

    modules = []
    for path in sorted(MODULES_DIR.glob("*/module.json")):
        try:
            module = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        module_id = module.get("id", path.parent.name)
        job = membership.get(module_id)
        if job:
            result = result_by_id.get(job["id"], {})
            mode = "scheduled"
            if result.get("status") == "success":
                if module_id in result.get("changed_modules", []):
                    decision = "已更新"
                else:
                    decision = "已檢查，來源未變"
            elif result.get("status") == "error":
                decision = "更新失敗"
            elif result.get("due_today"):
                decision = "今天應更新"
            else:
                decision = "今天不需更新"
            policy = {
                "mode": mode,
                "cadence": job["schedule"]["description"],
                "reason": f"由 {job['label']} job 管理",
            }
            job_id = job["id"]
        else:
            policy = policies.get("module_policies", {}).get(module_id, {
                "mode": "pending",
                "cadence": "未設定",
                "reason": "automation/policies.json 尚未設定此模組",
            })
            mode = policy.get("mode", "pending")
            job_id = None
            decision = {
                "static": "靜態，不更新",
                "one_time": "一次性，不更新",
                "pending": "尚無抓取器",
            }.get(mode, "不自動更新")

        job_history = history.get(job_id, {}) if job_id else {}
        modules.append({
            "id": module_id,
            "title": module.get("title", module_id),
            "type": module.get("type", ""),
            "sample": bool(module.get("sample")),
            "mode": mode,
            "mode_label": MODE_LABELS.get(mode, mode),
            "cadence": policy.get("cadence", ""),
            "reason": policy.get("reason", ""),
            "job_id": job_id,
            "decision": decision,
            "updated": module.get("updated"),
            "fetched_at": module.get("fetched_at"),
            "last_automation_success": job_history.get("last_success_at"),
        })
    return modules


def read_log_tail(lines: int = 14) -> list:
    if not LOG_PATH.exists():
        return []
    try:
        return LOG_PATH.read_text(encoding="utf-8").splitlines()[-lines:]
    except OSError:
        return []


def write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATUS_PATH)


def build_plan(policies: dict, target_date: date, force_job: str = None) -> list:
    plan = []
    for job in policies.get("jobs", []):
        scheduled = job_is_due(job, target_date)
        due = scheduled or job["id"] == force_job
        plan.append({
            "id": job["id"],
            "label": job["label"],
            "module_ids": job["module_ids"],
            "schedule": job["schedule"]["description"],
            "scheduled_today": scheduled,
            "due_today": due,
            "forced": job["id"] == force_job,
        })
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true", help="只顯示決策，不執行、不寫狀態")
    parser.add_argument("--date", help="搭配 --plan 模擬 YYYY-MM-DD 的決策")
    parser.add_argument("--force-job", help="忽略日期，強制執行指定 job")
    args = parser.parse_args()

    if args.date and not args.plan:
        parser.error("--date 只能搭配 --plan，避免誤用歷史日期執行抓取")

    try:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else now_tpe().date()
        policies = load_policies()
    except (ValueError, AutomationError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    job_ids = {job["id"] for job in policies.get("jobs", [])}
    if args.force_job and args.force_job not in job_ids:
        print(f"✗ 未知 job：{args.force_job}；可用：{sorted(job_ids)}", file=sys.stderr)
        return 2

    plan = build_plan(policies, target_date, args.force_job)
    if args.plan:
        print(json.dumps({
            "date": target_date.isoformat(),
            "daily_check_time": policies.get("daily_check_time"),
            "jobs": plan,
        }, ensure_ascii=False, indent=2))
        return 0

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_PATH.open("a+")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        append_log("ERROR", "每日自動化未啟動：已有另一個執行程序")
        print("✗ 已有另一個自動化程序正在執行", file=sys.stderr)
        return 3

    started = now_tpe()
    check_time = policies.get("daily_check_time", "08:10")
    append_log("START", f"每日 {check_time} 自動化檢查（日期 {target_date.isoformat()}）")
    previous = load_json(STATUS_PATH, default={}) or {}
    history = previous.get("job_history", {}) if isinstance(previous, dict) else {}
    job_results = []
    changed_modules = []

    for item in plan:
        result = dict(item)
        if not item["due_today"]:
            result.update({"status": "skipped", "message": "今天不在排程日"})
            job_results.append(result)
            continue

        job = next(job for job in policies["jobs"] if job["id"] == item["id"])
        execution = run_job(job)
        result.update(execution)
        job_results.append(result)
        changed_modules.extend(execution["changed_modules"])

        current_history = dict(history.get(job["id"], {}))
        current_history.update({
            "last_attempt_at": execution["finished_at"],
            "last_status": execution["status"],
            "last_message": execution["message"],
            "last_changed_modules": execution["changed_modules"],
        })
        if execution["status"] == "success":
            current_history["last_success_at"] = execution["finished_at"]
            append_log("SUCCESS", f"{job['label']}：{execution['message']}（{execution['duration_seconds']} 秒）")
        else:
            append_log("ERROR", f"{job['label']}：{execution['message']}（{execution['duration_seconds']} 秒）")
        history[job["id"]] = current_history

    changed_modules = sorted(set(changed_modules))
    build_result = None
    if changed_modules:
        build_result = run_build()
        if build_result["status"] == "success":
            append_log("SUCCESS", f"dashboard build 完成：{len(changed_modules)} 個模組有新資料")
        else:
            append_log("ERROR", f"dashboard build 失敗：{build_result['output_tail']}")

    failed_jobs = [result for result in job_results if result["status"] == "error"]
    build_failed = build_result and build_result["status"] == "error"
    overall = "error" if failed_jobs or build_failed else "success"
    due_count = sum(1 for item in plan if item["due_today"])
    if overall == "success":
        summary = (
            f"完成 {due_count} 個應執行 job；{len(changed_modules)} 個模組有新資料"
            if due_count else "今日沒有需要更新的 job"
        )
        append_log("SUCCESS", summary)
    else:
        summary = f"{len(failed_jobs)} 個 job 失敗；build {'失敗' if build_failed else '正常'}"
        append_log("ERROR", summary)

    finished = now_tpe()
    payload = {
        "generated_at": stamp(finished),
        "timezone": policies.get("timezone", "Asia/Taipei"),
        "daily_check_time": policies.get("daily_check_time", "08:10"),
        "last_run": {
            "date": target_date.isoformat(),
            "status": overall,
            "summary": summary,
            "started_at": stamp(started),
            "finished_at": stamp(finished),
            "duration_seconds": round((finished - started).total_seconds(), 2),
            "changed_modules": changed_modules,
            "build": build_result,
        },
        "jobs": job_results,
        "job_history": history,
    }
    payload["modules"] = read_modules(policies, job_results, history, target_date)
    payload["log_file"] = str(LOG_PATH)
    payload["log_tail"] = read_log_tail()
    write_status(payload)

    print(f"✓ {summary}" if overall == "success" else f"✗ {summary}")
    for result in job_results:
        marker = "✓" if result["status"] == "success" else ("✗" if result["status"] == "error" else "—")
        print(f"  {marker} {result['label']}：{result['message']}")
    return 0 if overall == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
