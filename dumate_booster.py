#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DuMate（百度搭子）充能计划 · 做任务 / 抽奖 / 领奖。

签到走 ``dumate_daily.py``，本脚本只处理「搭子充能计划」（growth plan），接口来自
官网前端 bundle（``api/dumate/activity/growth-plan/*``）：

==============================  ===============================================
GET  /api/dumate/activity/status                  活动总状态（enabled / 起止时间）
GET  /api/dumate/activity/growth-plan/page/status 充能计划页面状态
POST /api/dumate/activity/growth-plan/tasks       任务列表（body: device/version/riskContext）
POST /api/dumate/activity/growth-plan/task/complete  完成任务（body: {"task_id": "..."}）
GET  /api/dumate/activity/growth-plan/draw/status 抽奖次数与奖品
POST /api/dumate/activity/growth-plan/draw        抽奖（header: X-Bce-Request-Id）
POST /api/dumate/activity/growth-plan/prize/claim 实物奖领奖（body: draw_record_id + contact）
==============================  ===============================================

用法::

    export DUMATE_COOKIES='bce-sessionid=...; bce-user-info=...'
    python3 dumate_booster.py                  # 查任务 → 能完成的完成 → 抽奖
    python3 dumate_booster.py --dry-run        # 只看状态与任务，不做任何写操作
    python3 dumate_booster.py --no-draw        # 只做任务，不抽奖
    python3 dumate_booster.py --max-draw 3     # 最多抽 3 次
    python3 dumate_booster.py --contact 手机号  # 抽中实物奖时自动领奖

写操作（完成 / 抽奖 / 领奖 / 兑换）在官网前端走百度 acs+banti 风控签名；本脚本默认不带签名，
若服务端返回风控错误会以 ``RISK_BLOCKED`` 明确报出，不会静默成功。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any, Mapping, Optional, Sequence

import dumate_daily
from dumate_daily import (
    APIError,
    ConfigError,
    _headers,
    _number,
    _redact,
    _request_json,
    emit,
    load_accounts,
    make_session,
    resolve_base_url,
)

PROVIDER = "dumate-booster"

ACTIVITY_STATUS_PATH = "/api/dumate/activity/status"
PAGE_STATUS_PATH = "/api/dumate/activity/growth-plan/page/status"
TASKS_PATH = "/api/dumate/activity/growth-plan/tasks"
COMPLETE_TASK_PATH = "/api/dumate/activity/growth-plan/task/complete"
DRAW_STATUS_PATH = "/api/dumate/activity/growth-plan/draw/status"
DRAW_PATH = "/api/dumate/activity/growth-plan/draw"
CLAIM_PRIZE_PATH = "/api/dumate/activity/growth-plan/prize/claim"
MODULES_PATH = "/api/dumate/activity/growth-plan/modules"

# 前端声明的任务类型（taskType），用于报告里标注任务来源
TASK_TYPES = (
    "CODE_MODE",
    "QUERY_INPUT",
    "CREATE_SCHEDULED_TASK",
    "DUAL_LOGIN",
    "USE_SKILL",
    "MOBILE_PUSH",
    "PC_PUSH",
    "MEDIA_SUITE_CREATION",
    "INVITATION",
    "INVITED",
    "DOWNLOAD_MOBILE_CHAT",
    "DOWNLOAD_PC_CHAT",
    "FIRST_CREATE_SCHEDULED_TASK",
    "FIRST_PRO_AUTO_RENEW",
    "PRO_AUTO_RENEW",
    "COFFEE2026",
    "SUITE",
)

# 前端对这些类型有前置行为校验（query / suiteName 命中才允许上报），
# 只提交 task_id 大概率不会被认可 —— 报告里单独标出来，仍然可以逐个试。
EVIDENCE_REQUIRED_TYPES = {
    "CODE_MODE",
    "QUERY_INPUT",
    "USE_SKILL",
    "CREATE_SCHEDULED_TASK",
    "FIRST_CREATE_SCHEDULED_TASK",
    "SUITE",
    "MEDIA_SUITE_CREATION",
    "INVITATION",
    "INVITED",
    "FIRST_PRO_AUTO_RENEW",
    "PRO_AUTO_RENEW",
}

DEFAULT_CLIENT_VERSION = "1.0.82"
DEFAULT_DEVICE = "pc"


# --------------------------------------------------------------------------- #
# 响应解析（服务端字段存在 task_id/taskId 两种风格，统一容错）
# --------------------------------------------------------------------------- #
def _pick(payload: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload and payload[name] is not None:
            return payload[name]
    return None


def _unwrap(payload: Any) -> Mapping[str, Any]:
    """百度接口常见包装：{success, code, message, result}。取出 result 层。"""
    if not isinstance(payload, Mapping):
        raise APIError("BAD_PAYLOAD", "response is not a JSON object")
    result = payload.get("result")
    if isinstance(result, Mapping):
        return result
    data = payload.get("data")
    if isinstance(data, Mapping):
        return data
    return payload


def _check_business(payload: Any, *, action: str) -> Mapping[str, Any]:
    """业务层失败判定：success=False 或 code!=0 都视为失败。"""
    if not isinstance(payload, Mapping):
        raise APIError("BAD_PAYLOAD", "%s: response is not an object" % action)
    success = payload.get("success")
    code = payload.get("code")
    if success is False:
        message = str(payload.get("message") or payload.get("msg") or "")
        if _is_risk(message):
            raise APIError(
                "RISK_BLOCKED",
                "%s 被风控拦截：%s" % (action, message or "无 message"),
            )
        raise APIError("BUSINESS_ERROR", "%s failed: %s" % (action, message or "success=false"))
    if code not in (None, 0, "0", 200, "200"):
        message = str(payload.get("message") or payload.get("msg") or "")
        if _is_risk(message):
            raise APIError(
                "RISK_BLOCKED",
                "%s 被风控拦截（code=%s）：%s" % (action, code, message or "无 message"),
            )
        raise APIError("BUSINESS_ERROR", "%s failed (code=%s): %s" % (action, code, message))
    return payload


def _is_risk(message: str) -> bool:
    text = (message or "").lower()
    return any(
        token in text
        for token in ("风控", "风险", "risk", "forbidden", "captcha", "验证", "频繁")
    )


def parse_page_status(payload: Any) -> dict[str, Any]:
    body = _unwrap(payload)
    config = body.get("config") if isinstance(body.get("config"), Mapping) else {}
    return {
        "activity_id": _pick(body, "activity_id", "activityId"),
        "enabled": _pick(body, "enabled") is not False,
        "growth_plan_enable": _pick(body, "growth_plan_enable", "growthPlanEnable") is not False,
        "start_time": _pick(body, "start_time", "startTime"),
        "end_time": _pick(body, "end_time", "endTime"),
        "title": _pick(config, "title", "entry_title") if isinstance(config, Mapping) else None,
    }


def parse_tasks(payload: Any) -> list[dict[str, Any]]:
    body = _unwrap(payload)
    raw = _pick(body, "tasks", "task_list", "list", "groups", "modules") or []
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    tasks: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, Sequence) else []:
        if not isinstance(item, Mapping):
            continue
        # 分组结构：{group_name, tasks:[...]}
        if isinstance(item.get("tasks"), Sequence):
            for sub in item["tasks"]:
                if isinstance(sub, Mapping):
                    tasks.append(_normalize_task(sub))
            continue
        tasks.append(_normalize_task(item))
    return [t for t in tasks if t["task_id"]]


def _normalize_task(item: Mapping[str, Any]) -> dict[str, Any]:
    completed = _number(_pick(item, "completed_count", "completedCount", "finished_count"))
    repeat = _number(_pick(item, "repeat_count", "repeatCount", "max_count"))
    finished_flag = _pick(item, "finished", "completed", "done")
    if completed is None:
        completed = 1.0 if finished_flag is True else 0.0
    if repeat is None or repeat <= 0:
        repeat = max(1.0, completed)
    task_type = _pick(item, "task_type", "taskType")
    return {
        "task_id": str(_pick(item, "task_id", "taskId") or ""),
        "task_name": _pick(item, "task_name", "taskName", "name"),
        "task_type": task_type,
        "completed_count": int(completed),
        "repeat_count": int(repeat),
        "finished": completed >= repeat,
        "reward_points": _number(_pick(item, "reward_points", "rewardPoints", "points")),
        "jump_url": _pick(item, "jump_url", "jumpUrl"),
        # 前端 gate：任务可上报前会校验 query 是否被当前产物命中、SUITE 是否真用了对应套件
        "query": _pick(item, "query"),
        "suite_name": _pick(item, "suite_name", "suiteName"),
        "needs_evidence": bool(_pick(item, "query") or _pick(item, "suite_name", "suiteName")),
    }


def parse_draw_status(payload: Any) -> dict[str, Any]:
    body = _unwrap(payload)
    remaining = _number(_pick(body, "remaining_draws", "remainingDraws", "remaining"))
    return {
        "remaining_draws": int(remaining) if remaining is not None else 0,
        "prizes": _pick(body, "prizes") or [],
        "my_prizes": _pick(body, "my_prizes", "myPrizes") or [],
        "winning_records": _pick(body, "winning_records", "winningRecords") or [],
    }


def parse_draw_result(payload: Any) -> dict[str, Any]:
    body = _unwrap(payload)
    record_id = _pick(body, "draw_record_id", "drawRecordId", "record_id", "recordId")
    return {
        "draw_record_id": record_id,
        "prize_name": _pick(body, "prize_name", "prizeName", "name"),
        "prize_type": _pick(body, "prize_type", "prizeType", "type"),
        "need_contact": bool(_pick(body, "need_contact", "needContact")),
        "raw": body if record_id is None else None,
    }


# --------------------------------------------------------------------------- #
# 请求
# --------------------------------------------------------------------------- #
def _call(
    session,
    base_url: str,
    account: Mapping[str, Any],
    *,
    method: str,
    path: str,
    body: Optional[Mapping[str, Any]] = None,
    extra_headers: Optional[Mapping[str, str]] = None,
    secrets: Sequence[str],
) -> Any:
    headers = _headers(account, base_url=base_url, post=(method != "GET"))
    if extra_headers:
        headers.update({str(k): str(v) for k, v in extra_headers.items()})
    payload, _status = _request_json(
        session,
        method,
        base_url + path,
        headers=headers,
        secrets=secrets,
        json_body=body if method != "GET" else None,
    )
    return payload


def fetch_page_status(session, base_url, account, secrets) -> dict[str, Any]:
    return parse_page_status(
        _call(session, base_url, account, method="GET", path=PAGE_STATUS_PATH, secrets=secrets)
    )


def fetch_tasks(
    session,
    base_url,
    account,
    secrets,
    *,
    device: str = DEFAULT_DEVICE,
    version: str = DEFAULT_CLIENT_VERSION,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {}
    if device:
        body["device"] = device
    if version:
        body["version"] = version
    payload = _call(
        session, base_url, account, method="POST", path=TASKS_PATH, body=body, secrets=secrets
    )
    _check_business(payload, action="获取充能任务列表")
    return parse_tasks(payload)


def complete_task(session, base_url, account, secrets, task_id: str) -> dict[str, Any]:
    payload = _call(
        session,
        base_url,
        account,
        method="POST",
        path=COMPLETE_TASK_PATH,
        body={"task_id": str(task_id)},
        secrets=secrets,
    )
    _check_business(payload, action="完成任务 %s" % task_id)
    body = _unwrap(payload)
    reward = _number(_pick(body, "reward_count", "rewardCount", "reward"))
    return {
        "task_id": str(task_id),
        "reward_count": int(reward) if reward is not None else None,
        "message": payload.get("message") if isinstance(payload, Mapping) else None,
    }


def fetch_draw_status(session, base_url, account, secrets) -> dict[str, Any]:
    payload = _call(
        session, base_url, account, method="GET", path=DRAW_STATUS_PATH, secrets=secrets
    )
    _check_business(payload, action="获取抽奖状态")
    return parse_draw_status(payload)


def draw_once(session, base_url, account, secrets) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    payload = _call(
        session,
        base_url,
        account,
        method="POST",
        path=DRAW_PATH,
        body={},
        extra_headers={"X-Bce-Request-Id": request_id},
        secrets=secrets,
    )
    _check_business(payload, action="抽奖")
    result = parse_draw_result(payload)
    result["request_id"] = request_id
    return result


def claim_prize(session, base_url, account, secrets, *, draw_record_id: Any, contact: str) -> bool:
    payload = _call(
        session,
        base_url,
        account,
        method="POST",
        path=CLAIM_PRIZE_PATH,
        body={"draw_record_id": draw_record_id, "contact": contact},
        secrets=secrets,
    )
    _check_business(payload, action="领取实物奖品")
    return True


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run_account(
    account: Mapping[str, Any],
    *,
    base_url: str,
    dry_run: bool = False,
    do_draw: bool = True,
    max_draw: int = 0,
    contact: str = "",
    device: str = DEFAULT_DEVICE,
    version: str = DEFAULT_CLIENT_VERSION,
    only_tasks: Sequence[str] = (),
) -> dict[str, Any]:
    label = str(account.get("label") or "")
    secrets = list(account.get("secrets") or [])
    result: dict[str, Any] = {
        "account": label,
        "ok": False,
        "error": None,
        "page": None,
        "tasks_before": [],
        "completed": [],
        "tasks_failed": [],
        "draw": {"available": 0, "done": 0, "prizes": [], "claimed": []},
    }
    session = make_session()
    try:
        page = fetch_page_status(session, base_url, account, secrets)
        result["page"] = page
        if not page.get("enabled") or not page.get("growth_plan_enable"):
            result.update(ok=True, note="充能计划当前未开启，跳过")
            return result

        tasks = fetch_tasks(session, base_url, account, secrets, device=device, version=version)
        result["tasks_before"] = tasks
        wanted = {str(x).strip() for x in only_tasks if str(x).strip()}
        pending = [t for t in tasks if not t["finished"]]
        if wanted:
            pending = [
                t for t in pending
                if t["task_id"] in wanted or str(t.get("task_name") or "") in wanted
            ]
        if dry_run:
            result.update(ok=True, note="dry-run：只读，不完成任务也不抽奖")
            return result

        for task in pending:
            try:
                done = complete_task(session, base_url, account, secrets, task["task_id"])
                result["completed"].append(
                    {"task_id": done["task_id"], "name": task.get("task_name"),
                     "reward_count": done["reward_count"]}
                )
            except APIError as exc:
                result["tasks_failed"].append(
                    {"task_id": task["task_id"], "name": task.get("task_name"),
                     "code": exc.result, "message": str(exc)}
                )

        if do_draw:
            status = fetch_draw_status(session, base_url, account, secrets)
            remaining = int(status.get("remaining_draws") or 0)
            result["draw"]["available"] = remaining
            limit = remaining if max_draw <= 0 else min(remaining, int(max_draw))
            for _ in range(limit):
                try:
                    drawn = draw_once(session, base_url, account, secrets)
                except APIError as exc:
                    result["draw"]["prizes"].append({"error": exc.result, "message": str(exc)})
                    break
                result["draw"]["done"] += 1
                result["draw"]["prizes"].append(drawn)
                if drawn.get("need_contact") and contact and drawn.get("draw_record_id"):
                    try:
                        claim_prize(
                            session,
                            base_url,
                            account,
                            secrets,
                            draw_record_id=drawn["draw_record_id"],
                            contact=contact,
                        )
                        result["draw"]["claimed"].append(drawn["draw_record_id"])
                    except APIError as exc:
                        result["draw"]["prizes"].append(
                            {"claim_error": exc.result, "message": str(exc)}
                        )
            result["draw"]["after"] = fetch_draw_status(session, base_url, account, secrets)

        result["ok"] = True
    except APIError as exc:
        result["error"] = {"code": exc.result, "message": str(exc), "http_status": exc.http_status}
    except ConfigError as exc:
        result["error"] = {"code": "CONFIG_ERROR", "message": str(exc)}
    finally:
        try:
            session.close()
        except Exception:
            pass
    return result


def build_summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "accounts": len(results),
        "success": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
        "tasks_completed": sum(len(r.get("completed") or []) for r in results),
        "tasks_failed": sum(len(r.get("tasks_failed") or []) for r in results),
        "draws_done": sum(int((r.get("draw") or {}).get("done") or 0) for r in results),
        "results": list(results),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dumate_booster",
        description="DuMate（百度搭子）充能计划：做任务、抽奖、领奖",
    )
    parser.add_argument("--base-url", default="", help="覆盖接口域名（默认 console.bce.baidu.com）")
    parser.add_argument("--dry-run", action="store_true", help="只读：查询状态与任务，不做写操作")
    parser.add_argument("--no-draw", action="store_true", help="只做任务，不抽奖")
    parser.add_argument("--max-draw", type=int, default=0, help="最多抽奖次数（默认用服务端剩余次数）")
    parser.add_argument("--contact", default="", help="联系方式，抽中实物奖时用于领奖")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="任务列表 device 参数")
    parser.add_argument("--version", default=DEFAULT_CLIENT_VERSION, help="任务列表 version 参数")
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        metavar="TASK_ID|名称",
        help="只尝试指定任务（可重复），用于逐个验证哪些任务真的能完成",
    )
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        accounts = load_accounts()
        base_url = resolve_base_url({"DUMATE_BASE_URL": args.base_url} if args.base_url else None)
    except ConfigError as exc:
        emit({"provider": PROVIDER, "error": {"code": "CONFIG_ERROR", "message": str(exc)}})
        return 2

    results = [
        run_account(
            account,
            base_url=base_url,
            dry_run=args.dry_run,
            do_draw=not args.no_draw,
            max_draw=args.max_draw,
            contact=args.contact,
            device=args.device,
            version=args.version,
            only_tasks=args.task,
        )
        for account in accounts
    ]
    summary = build_summary(results)
    if args.json:
        emit(summary)
    else:
        _print_human(summary)
    return 0 if summary["failed"] == 0 else 1


def _print_human(summary: Mapping[str, Any]) -> None:
    print("=" * 62)
    print("DuMate 充能计划 | 账号 %s | 成功 %s | 失败 %s"
          % (summary["accounts"], summary["success"], summary["failed"]))
    print("=" * 62)
    for res in summary["results"]:
        print("\n▌%s" % res["account"])
        if res.get("error"):
            err = res["error"]
            print("  ❌ %s: %s" % (err.get("code"), err.get("message")))
            continue
        page = res.get("page") or {}
        if page:
            print("  活动: enabled=%s growth_plan=%s %s ~ %s"
                  % (page.get("enabled"), page.get("growth_plan_enable"),
                     page.get("start_time"), page.get("end_time")))
        pending = [t for t in (res.get("tasks_before") or []) if not t["finished"]]
        print("  任务: 共 %d 个，未完成 %d 个"
              % (len(res.get("tasks_before") or []), len(pending)))
        for t in pending:
            flag = ""
            if t.get("needs_evidence") or t.get("task_type") in EVIDENCE_REQUIRED_TYPES:
                flag = "  ← 需真实前置行为(可能不通过)"
            print("    - [%s] %s  (%s/%s)%s"
                  % (t.get("task_type"), t.get("task_name"), t["completed_count"],
                     t["repeat_count"], flag))
        for c in res.get("completed") or []:
            print("  ✅ 完成 %s → 奖励次数 +%s" % (c.get("name") or c.get("task_id"), c.get("reward_count")))
        for f in res.get("tasks_failed") or []:
            print("  ⚠️ 未完成 %s: [%s] %s" % (f.get("name") or f.get("task_id"), f.get("code"), f.get("message")))
        draw = res.get("draw") or {}
        if draw:
            print("  抽奖: 可抽 %s 次，已抽 %s 次"
                  % (draw.get("available"), draw.get("done")))
            for p in draw.get("prizes") or []:
                if isinstance(p, Mapping) and p.get("prize_name"):
                    print("    🎁 %s" % p["prize_name"])
                elif isinstance(p, Mapping) and p.get("error"):
                    print("    ⚠️ %s: %s" % (p.get("error"), p.get("message")))
            if draw.get("claimed"):
                print("    已领奖记录: %s" % ", ".join(str(x) for x in draw["claimed"]))
        if res.get("note"):
            print("  ℹ️ %s" % res["note"])


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())