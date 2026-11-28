import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dumate_booster as booster


COOKIE = "bce-sessionid=session-secret; bce-user-info=csrf-secret"


def account():
    return {
        "label": "acct1",
        "cookie_header": COOKIE,
        "csrf": "csrf-secret",
        "secrets": ["session-secret", "csrf-secret"],
    }


class ParsePageStatusTests(unittest.TestCase):
    def test_flat_payload(self):
        page = booster.parse_page_status(
            {"activity_id": "act1", "enabled": True,
             "start_time": "2026-01-01 00:00:00", "end_time": "2026-02-01 00:00:00"}
        )
        self.assertEqual(page["activity_id"], "act1")
        self.assertTrue(page["enabled"])
        self.assertTrue(page["growth_plan_enable"])

    def test_growth_plan_disabled(self):
        page = booster.parse_page_status(
            {"result": {"enabled": True, "growth_plan_enable": False}}
        )
        self.assertFalse(page["growth_plan_enable"])

    def test_config_carries_flag(self):
        page = booster.parse_page_status(
            {"result": {"enabled": True, "config": {"growth_plan_enable": True, "title": "充能计划"}}}
        )
        self.assertTrue(page["growth_plan_enable"])
        self.assertEqual(page["title"], "充能计划")


class ParseTasksTests(unittest.TestCase):
    def test_snake_case_list(self):
        tasks = booster.parse_tasks(
            {"result": {"tasks": [
                {"task_id": "t1", "task_name": "每日登录", "task_type": "DUAL_LOGIN",
                 "completed_count": 1, "repeat_count": 1},
                {"task_id": "t2", "task_name": "创建定时任务",
                 "task_type": "CREATE_SCHEDULED_TASK", "completed_count": 0, "repeat_count": 2},
            ]}}
        )
        self.assertEqual(len(tasks), 2)
        self.assertTrue(tasks[0]["finished"])
        self.assertFalse(tasks[1]["finished"])

    def test_camel_case_and_grouping(self):
        tasks = booster.parse_tasks(
            {"result": {"groups": [
                {"group_name": "新任务", "tasks": [
                    {"taskId": "g1", "taskName": "查看技能", "taskType": "USE_SKILL",
                     "finished": True},
                ]},
                {"taskId": "g2", "taskName": "下载移动端", "taskType": "DOWNLOAD_MOBILE_CHAT"},
            ]}}
        )
        ids = {t["task_id"] for t in tasks}
        self.assertEqual(ids, {"g1", "g2"})
        done = {t["task_id"]: t["finished"] for t in tasks}
        self.assertTrue(done["g1"])
        self.assertFalse(done["g2"])

    def test_repeat_count_allows_multiple(self):
        tasks = booster.parse_tasks(
            {"result": {"tasks": [
                {"task_id": "r1", "completed_count": 1, "repeat_count": 3},
            ]}}
        )
        self.assertEqual(tasks[0]["repeat_count"], 3)
        self.assertFalse(tasks[0]["finished"])

    def test_missing_task_id_dropped(self):
        tasks = booster.parse_tasks({"result": {"tasks": [{"task_name": "无 id"}]}})
        self.assertEqual(tasks, [])


class ParseDrawTests(unittest.TestCase):
    def test_draw_status(self):
        status = booster.parse_draw_status(
            {"result": {"remaining_draws": 4, "prizes": [{"name": "积分"}],
                        "my_prizes": [], "winning_records": []}}
        )
        self.assertEqual(status["remaining_draws"], 4)

    def test_draw_result_record_id(self):
        drawn = booster.parse_draw_result(
            {"result": {"draw_record_id": "rec-1", "prize_name": "2000积分",
                        "prize_type": "points", "need_contact": False}}
        )
        self.assertEqual(drawn["draw_record_id"], "rec-1")
        self.assertEqual(drawn["prize_name"], "2000积分")
        self.assertFalse(drawn["need_contact"])


class RunAccountTests(unittest.TestCase):
    """用假的请求层跑完整流程。"""

    def _run(self, responses, **kwargs):
        calls = []

        def fake_request(session, method, url, *, headers, secrets, json_body=None):
            calls.append((method, url, json_body, headers))
            key = url.rsplit("/api/dumate/activity", 1)[-1]
            if key not in responses:
                raise AssertionError("unexpected url: %s" % url)
            return responses[key], 200

        with mock.patch.object(booster, "make_session", return_value=mock.MagicMock()), \
             mock.patch.object(booster, "_request_json", side_effect=fake_request):
            result = booster.run_account(account(), base_url="https://console.bce.baidu.com",
                                         **kwargs)
        return result, calls

    def test_full_flow_completes_tasks_and_draws(self):
        responses = {
            "/growth-plan/page/status": {"result": {"enabled": True, "growth_plan_enable": True}},
            "/growth-plan/tasks": {"success": True, "result": {"tasks": [
                {"task_id": "t1", "task_name": "已完成", "completed_count": 1, "repeat_count": 1},
                {"task_id": "t2", "task_name": "待完成", "completed_count": 0, "repeat_count": 1},
            ]}},
            "/growth-plan/task/complete": {"success": True, "result": {"reward_count": 1}},
            "/growth-plan/draw/status": {"success": True, "result": {"remaining_draws": 1}},
            "/growth-plan/draw": {"success": True, "result": {
                "draw_record_id": "rec-9", "prize_name": "100积分", "need_contact": False}},
        }
        result, calls = self._run(responses)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual([c["task_id"] for c in result["completed"]], ["t2"])
        self.assertEqual(result["draw"]["done"], 1)
        self.assertEqual(result["draw"]["prizes"][0]["prize_name"], "100积分")
        # 只能对未完成任务发 complete
        completes = [c for c in calls if c[1].endswith("/task/complete")]
        self.assertEqual(len(completes), 1)
        self.assertEqual(completes[0][2], {"task_id": "t2"})

    def test_dry_run_writes_nothing(self):
        responses = {
            "/growth-plan/page/status": {"result": {"enabled": True, "growth_plan_enable": True}},
            "/growth-plan/tasks": {"success": True, "result": {"tasks": [
                {"task_id": "t2", "task_name": "待完成", "completed_count": 0, "repeat_count": 1},
            ]}},
        }
        result, calls = self._run(responses, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["completed"], [])
        self.assertFalse(any(c[1].endswith(("/task/complete", "/draw")) for c in calls))

    def test_activity_disabled_skips(self):
        responses = {
            "/growth-plan/page/status": {"result": {"enabled": False}},
        }
        result, calls = self._run(responses)
        self.assertTrue(result["ok"])
        self.assertIn("未开启", result["note"])
        self.assertEqual(len(calls), 1)

    def test_risk_blocked_surfaces_as_error(self):
        responses = {
            "/growth-plan/page/status": {"result": {"enabled": True, "growth_plan_enable": True}},
            "/growth-plan/tasks": {"success": True, "result": {"tasks": [
                {"task_id": "t3", "task_name": "风控任务", "completed_count": 0, "repeat_count": 1},
            ]}},
            "/growth-plan/task/complete": {"success": False, "message": "请求过于频繁，触发风控"},
        }
        result, _ = self._run(responses, do_draw=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tasks_failed"][0]["code"], "RISK_BLOCKED")

    def test_no_prize_draw_error_kept(self):
        responses = {
            "/growth-plan/page/status": {"result": {"enabled": True, "growth_plan_enable": True}},
            "/growth-plan/tasks": {"success": True, "result": {"tasks": []}},
            "/growth-plan/draw/status": {"success": True, "result": {"remaining_draws": 2}},
            "/growth-plan/draw": {"success": False, "message": "没有可抽奖次数"},
        }
        result, _ = self._run(responses)
        self.assertTrue(result["ok"])
        self.assertEqual(result["draw"]["done"], 0)
        self.assertEqual(result["draw"]["prizes"][0]["error"], "BUSINESS_ERROR")


class SummaryTests(unittest.TestCase):
    def test_summary_counts(self):
        summary = booster.build_summary([
            {"ok": True, "completed": [{"task_id": "a"}], "tasks_failed": [],
             "draw": {"done": 2}},
            {"ok": False, "completed": [], "tasks_failed": [{"task_id": "b"}],
             "draw": {"done": 0}},
        ])
        self.assertEqual(summary["success"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["tasks_completed"], 1)
        self.assertEqual(summary["tasks_failed"], 1)
        self.assertEqual(summary["draws_done"], 2)


if __name__ == "__main__":
    unittest.main()