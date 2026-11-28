import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dumate_daily as dd


COOKIE = "bce-sessionid=session-secret; bce-user-info=csrf-secret"
BASE = "https://console.bce.baidu.com"


def account():
    return {
        "note": "acct1",
        "cookie_header": COOKIE,
        "csrf": "csrf-secret",
        "secrets": ["session-secret", "csrf-secret"],
    }


def signin_payload(issued=True, points="10", times=1):
    return {"hasIssued": issued, "totalPoints": points, "totalTimes": times}


def quota_payload(total="10", used="0"):
    return {"totalPoints": total, "usedPoints": used}


class ParsePageStatusTests(unittest.TestCase):
    def test_flat_payload(self):
        page = dd.parse_page_status(
            {"activity_id": "act1", "enabled": True,
             "start_time": "2026-01-01 00:00:00", "end_time": "2026-02-01 00:00:00"}
        )
        self.assertEqual(page["activity_id"], "act1")
        self.assertTrue(page["enabled"])
        self.assertTrue(page["growth_plan_enable"])

    def test_growth_plan_disabled(self):
        page = dd.parse_page_status({"enabled": True, "growth_plan_enable": False})
        self.assertFalse(page["growth_plan_enable"])

    def test_config_carries_flag(self):
        page = dd.parse_page_status(
            {"enabled": True, "config": {"growth_plan_enable": True, "title": "充能计划"}}
        )
        self.assertTrue(page["growth_plan_enable"])
        self.assertEqual(page["title"], "充能计划")


class ParseTasksTests(unittest.TestCase):
    def test_snake_case_list(self):
        tasks = dd.parse_tasks(
            {"tasks": [
                {"task_id": "t1", "task_name": "每日登录", "task_type": "DUAL_LOGIN",
                 "completed_count": 1, "repeat_count": 1},
                {"task_id": "t2", "task_name": "创建定时任务",
                 "task_type": "CREATE_SCHEDULED_TASK", "completed_count": 0, "repeat_count": 2},
            ]}
        )
        self.assertEqual(len(tasks), 2)
        self.assertTrue(tasks[0]["finished"])
        self.assertFalse(tasks[1]["finished"])

    def test_camel_case_and_grouping(self):
        tasks = dd.parse_tasks(
            {"groups": [
                {"group_name": "新任务", "tasks": [
                    {"taskId": "g1", "taskName": "查看技能", "taskType": "USE_SKILL",
                     "finished": True},
                ]},
                {"taskId": "g2", "taskName": "下载移动端", "taskType": "DOWNLOAD_MOBILE_CHAT"},
            ]}
        )
        ids = {t["task_id"] for t in tasks}
        self.assertEqual(ids, {"g1", "g2"})
        done = {t["task_id"]: t["finished"] for t in tasks}
        self.assertTrue(done["g1"])
        self.assertFalse(done["g2"])

    def test_repeat_count_allows_multiple(self):
        tasks = dd.parse_tasks({"tasks": [{"task_id": "r1", "completed_count": 1, "repeat_count": 3}]})
        self.assertEqual(tasks[0]["repeat_count"], 3)
        self.assertFalse(tasks[0]["finished"])

    def test_missing_task_id_dropped(self):
        self.assertEqual(dd.parse_tasks({"tasks": [{"task_name": "无 id"}]}), [])

    def test_evidence_fields_are_captured(self):
        tasks = dd.parse_tasks({"tasks": [
            {"task_id": "q1", "task_type": "QUERY_INPUT", "query": "写一个排序",
             "completed_count": 0, "repeat_count": 1},
            {"task_id": "s1", "task_type": "USE_SKILL", "suiteName": "self-media-expert",
             "completed_count": 0, "repeat_count": 1},
        ]})
        self.assertTrue(tasks[0]["needs_evidence"])
        self.assertEqual(tasks[0]["query"], "写一个排序")
        self.assertTrue(tasks[1]["needs_evidence"])
        self.assertEqual(tasks[1]["suite_name"], "self-media-expert")


class ParseDrawTests(unittest.TestCase):
    def test_draw_status(self):
        status = dd.parse_draw_status(
            {"remaining_draws": 4, "prizes": [{"name": "积分"}],
             "my_prizes": [], "winning_records": []}
        )
        self.assertEqual(status["remaining_draws"], 4)

    def test_draw_result_record_id(self):
        drawn = dd.parse_draw_result(
            {"draw_record_id": "rec-1", "prize_name": "2000积分",
             "prize_type": "points", "need_contact": False}
        )
        self.assertEqual(drawn["draw_record_id"], "rec-1")
        self.assertEqual(drawn["prize_name"], "2000积分")
        self.assertFalse(drawn["need_contact"])


class RunBoosterTests(unittest.TestCase):
    """Drive run_booster with a fake request layer.

    ``_request_json`` returns the already-unwrapped ``result`` body, so every
    fixture below is the content of ``result`` (the envelope is upstream).
    """

    def _run(self, responses, **kwargs):
        calls = []

        def fake_request(session, method, url, *, headers, secrets, json_body=None):
            calls.append((method, url, json_body, headers))
            key = url.rsplit("/api/dumate/activity", 1)[-1]
            if key not in responses:
                raise AssertionError("unexpected url: %s" % url)
            value = responses[key]
            if isinstance(value, dd.APIError):
                raise value
            return value, 200

        with mock.patch.object(dd, "_request_json", side_effect=fake_request):
            result = dd.run_booster(
                mock.MagicMock(), BASE, account(), ["session-secret", "csrf-secret"], **kwargs
            )
        return result, calls

    def test_full_flow_completes_tasks_and_draws(self):
        responses = {
            "/growth-plan/page/status": {"enabled": True, "growth_plan_enable": True},
            "/growth-plan/tasks": {"tasks": [
                {"task_id": "t1", "task_name": "已完成", "completed_count": 1, "repeat_count": 1},
                {"task_id": "t2", "task_name": "待完成", "completed_count": 0, "repeat_count": 1},
            ]},
            "/growth-plan/task/complete": {"reward_count": 1},
            "/growth-plan/draw/status": {"remaining_draws": 1},
            "/growth-plan/draw": {"draw_record_id": "rec-9", "prize_name": "100积分",
                                  "need_contact": False},
        }
        result, calls = self._run(responses)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual([c["task_id"] for c in result["completed"]], ["t2"])
        self.assertEqual(result["draw"]["done"], 1)
        self.assertEqual(result["draw"]["prizes"][0]["prize_name"], "100积分")
        completes = [c for c in calls if c[1].endswith("/task/complete")]
        self.assertEqual(len(completes), 1)
        self.assertEqual(completes[0][2], {"task_id": "t2"})

    def test_dry_run_writes_nothing(self):
        responses = {
            "/growth-plan/page/status": {"enabled": True, "growth_plan_enable": True},
            "/growth-plan/tasks": {"tasks": [
                {"task_id": "t2", "task_name": "待完成", "completed_count": 0, "repeat_count": 1},
            ]},
        }
        result, calls = self._run(responses, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["completed"], [])
        self.assertFalse(any(c[1].endswith(("/task/complete", "/draw")) for c in calls))

    def test_activity_disabled_skips(self):
        responses = {"/growth-plan/page/status": {"enabled": False}}
        result, calls = self._run(responses)
        self.assertTrue(result["ok"])
        self.assertIn("not active", result["note"])
        self.assertEqual(len(calls), 1)

    def test_risk_blocked_surfaces_per_task(self):
        responses = {
            "/growth-plan/page/status": {"enabled": True, "growth_plan_enable": True},
            "/growth-plan/tasks": {"tasks": [
                {"task_id": "t3", "task_name": "风控任务", "completed_count": 0, "repeat_count": 1},
            ]},
            "/growth-plan/task/complete": dd.APIError(
                "BUSINESS_ERROR", "请求过于频繁，触发风控"
            ),
        }
        result, _ = self._run(responses, do_draw=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tasks_failed"][0]["code"], "RISK_BLOCKED")

    def test_draw_failure_is_kept_not_silent(self):
        responses = {
            "/growth-plan/page/status": {"enabled": True, "growth_plan_enable": True},
            "/growth-plan/tasks": {"tasks": []},
            "/growth-plan/draw/status": {"remaining_draws": 2},
            "/growth-plan/draw": dd.APIError("BUSINESS_ERROR", "没有可抽奖次数"),
        }
        result, _ = self._run(responses)
        self.assertTrue(result["ok"])
        self.assertEqual(result["draw"]["done"], 0)
        self.assertEqual(result["draw"]["prizes"][0]["error"], "BUSINESS_ERROR")

    def test_only_named_task_is_attempted(self):
        responses = {
            "/growth-plan/page/status": {"enabled": True, "growth_plan_enable": True},
            "/growth-plan/tasks": {"tasks": [
                {"task_id": "t1", "task_name": "任务一", "completed_count": 0, "repeat_count": 1},
                {"task_id": "t2", "task_name": "任务二", "completed_count": 0, "repeat_count": 1},
            ]},
            "/growth-plan/task/complete": {"reward_count": 1},
        }
        result, calls = self._run(responses, do_draw=False, only_tasks=["任务二"])
        self.assertEqual([c["task_id"] for c in result["completed"]], ["t2"])
        completes = [c for c in calls if c[1].endswith("/task/complete")]
        self.assertEqual(len(completes), 1)


class BoosterSummaryTests(unittest.TestCase):
    def test_summary_counts(self):
        summary = dd.booster_summary([
            {"booster": {"ok": True, "completed": [{"task_id": "a"}], "tasks_failed": [],
                         "draw": {"done": 2}}},
            {"booster": {"ok": False, "completed": [], "tasks_failed": [{"task_id": "b"}],
                         "draw": {"done": 0}}},
            {"result": "ALREADY_CLAIMED"},
        ])
        self.assertEqual(summary["accounts"], 2)
        self.assertEqual(summary["tasks_completed"], 1)
        self.assertEqual(summary["tasks_failed"], 1)
        self.assertEqual(summary["draws_done"], 2)


class MergedRunnerTests(unittest.TestCase):
    """签到与充能计划必须在同一个脚本、同一条结果里。"""

    def test_check_account_runs_booster_after_signin(self):
        queue = [
            (signin_payload(True), 200),
            (quota_payload(), 200),
            ({"enabled": True, "growth_plan_enable": True}, 200),
            ({"tasks": [{"task_id": "b1", "task_name": "充能任务",
                         "completed_count": 0, "repeat_count": 1}]}, 200),
            ({"reward_count": 1}, 200),
            ({"remaining_draws": 0}, 200),
        ]

        def fake_request(s, method, url, *, headers, secrets, json_body=None):
            return queue.pop(0)

        with mock.patch.object(dd, "_request_json", side_effect=fake_request):
            result = dd.check_account(
                {"note": "acct1", "cookie_header": COOKIE, "csrf": "csrf-secret"},
                base_url=BASE,
                booster=True,
                booster_options={},
            )
        self.assertEqual("ALREADY_CLAIMED", result["result"])
        self.assertTrue(result["booster"]["ok"], result["booster"].get("error"))
        self.assertEqual([c["task_id"] for c in result["booster"]["completed"]], ["b1"])

    def test_no_booster_flag_skips_everything(self):
        def fake_request(s, method, url, *, headers, secrets, json_body=None):
            if "loginBonusInfo" in url:
                return signin_payload(True), 200
            if "quota" in url:
                return quota_payload(), 200
            raise AssertionError("booster must not be called: %s" % url)

        with mock.patch.object(dd, "_request_json", side_effect=fake_request):
            result = dd.check_account(
                {"note": "acct1", "cookie_header": COOKIE, "csrf": "csrf-secret"},
                base_url=BASE,
                booster=False,
            )
        self.assertNotIn("booster", result)
        self.assertEqual("ALREADY_CLAIMED", result["result"])

    def test_booster_only_uses_query_mode(self):
        def fake_request(s, method, url, *, headers, secrets, json_body=None):
            if "loginBonusInfo" in url:
                return signin_payload(False, "0", 0), 200
            if "quota" in url:
                return quota_payload("0", "0"), 200
            if "growth-plan/page/status" in url:
                return {"enabled": False}, 200
            raise AssertionError(url)

        with mock.patch.object(dd, "_request_json", side_effect=fake_request):
            result = dd.check_account(
                {"note": "acct1", "cookie_header": COOKIE, "csrf": "csrf-secret"},
                mode="query", base_url=BASE, booster=True,
                booster_options={"booster_only": True},
            )
        self.assertEqual("AVAILABLE", result["result"])
        self.assertIn("booster", result)


if __name__ == "__main__":
    unittest.main()