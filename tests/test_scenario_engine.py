"""Unit tests for the Camoufox Advanced Scenario Engine."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.scenario_models import ScenarioDefinition, Step
from core.scenario_storage import ScenarioStorage
from core.scenario_engine import ExecutionContext, ScenarioEngine


class TestScenarioEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = ScenarioStorage(storage_dir=Path(self.temp_dir.name))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_storage_crud(self):
        scenario = ScenarioDefinition(
            id="test-scenario",
            name="Test Scenario",
            description="A test scenario",
            variables={"user": "alice", "count": 5},
            steps=[{"name": "Step 1", "action": "delay", "delay_ms": 100}],
        )
        saved = self.storage.save(scenario)
        self.assertEqual(saved.id, "test-scenario")

        items = self.storage.list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "test-scenario")

        loaded = self.storage.get("test-scenario")
        self.assertEqual(loaded.name, "Test Scenario")
        self.assertEqual(loaded.variables["user"], "alice")

        deleted = self.storage.delete("test-scenario")
        self.assertTrue(deleted)
        self.assertEqual(len(self.storage.list()), 0)

    def test_variable_interpolation(self):
        scenario = ScenarioDefinition(
            id="var-test",
            name="Var Test",
            variables={"domain": "example.com", "port": 8080},
            steps=[],
        )
        ctx = ExecutionContext(scenario=scenario, instance=None, run_id="run-1", initial_vars={"user": "bob"})
        try:
            interpolated = ctx.interpolate("https://{{domain}}:{{port}}/login?user={{user}}")
            self.assertEqual(interpolated, "https://example.com:8080/login?user=bob")
        finally:
            ctx.cleanup()

    def test_expression_evaluation(self):
        scenario = ScenarioDefinition(id="expr-test", name="Expr Test", variables={"code": "123456"}, steps=[])
        ctx = ExecutionContext(scenario=scenario, instance=None, run_id="run-2")
        try:
            self.assertTrue(ctx.evaluate_expression("len(ctx.vars['code']) == 6"))
            self.assertFalse(ctx.evaluate_expression("len(ctx.vars['code']) == 4"))
            self.assertEqual(ctx.evaluate_expression("int(ctx.vars['code']) + 1"), 123457)
        finally:
            ctx.cleanup()

    def test_conditional_branching_execution(self):
        async def run_test():
            scenario = ScenarioDefinition(
                id="branch-test",
                name="Branch Test",
                variables={"flag": True, "result": "initial"},
                steps=[
                    {
                        "if": "ctx.vars['flag'] is True",
                        "then": [
                            {"action": "set_var", "save_to_var": "result", "value": "branch_true"}
                        ],
                        "else": [
                            {"action": "set_var", "save_to_var": "result", "value": "branch_false"}
                        ],
                    }
                ],
            )
            mock_inst = MagicMock()
            mock_inst.page = MagicMock()
            mock_inst.id = "mock-inst-1"

            engine = ScenarioEngine()
            snapshot = await engine.execute(scenario, instance_id="mock-inst-1")
            return snapshot

        # Monkeypatch REGISTRY.get for test
        from core.instance_registry import REGISTRY
        orig_get = REGISTRY.get
        try:
            mock_inst = MagicMock()
            mock_inst.page = MagicMock()
            mock_inst.id = "mock-inst-1"
            REGISTRY.get = MagicMock(return_value=mock_inst)

            snapshot = asyncio.run(run_test())
            self.assertEqual(snapshot.status, "completed")
            self.assertEqual(snapshot.vars.get("result"), "branch_true")
        finally:
            REGISTRY.get = orig_get

    def test_loop_execution(self):
        async def run_test():
            scenario = ScenarioDefinition(
                id="loop-test",
                name="Loop Test",
                variables={"items": ["a", "b", "c"], "collected": ""},
                steps=[
                    {
                        "loop": {
                            "over": "ctx.vars['items']",
                            "as": "current_item",
                            "steps": [
                                {
                                    "action": "set_var",
                                    "save_to_var": "collected",
                                    "value": "ctx.vars['collected'] + ctx.vars['current_item']",
                                }
                            ],
                        }
                    }
                ],
            )
            engine = ScenarioEngine()
            snapshot = await engine.execute(scenario, instance_id="mock-inst-2")
            return snapshot

        from core.instance_registry import REGISTRY
        orig_get = REGISTRY.get
        try:
            mock_inst = MagicMock()
            mock_inst.page = MagicMock()
            mock_inst.id = "mock-inst-2"
            REGISTRY.get = MagicMock(return_value=mock_inst)

            snapshot = asyncio.run(run_test())
            self.assertEqual(snapshot.status, "completed")
            self.assertEqual(snapshot.vars.get("collected"), "abc")
        finally:
            REGISTRY.get = orig_get

    def test_real_browser_complex_scenario(self):
        """End-to-end integration test with real Camoufox browser."""
        try:
            import camoufox  # noqa: F401
            from camoufox.async_api import AsyncCamoufox  # noqa: F401
        except ImportError:
            self.skipTest("camoufox is not installed in the environment")

        async def run_e2e():
            scenario = ScenarioDefinition(
                id="e2e-scenario",
                name="E2E Real Browser Scenario",
                variables={"header_val": "Example Domain"},
                settings={"mode": "autonomous", "default_timeout_ms": 15000},
                steps=[
                    {
                        "name": "Navigate to Data URL",
                        "action": "goto",
                        "url": "data:text/html,<html><body><h1>{{header_val}}</h1><div class='test-box'>ok</div></body></html>",
                    },
                    {
                        "name": "Extract Header",
                        "action": "extract_text",
                        "selector": "h1",
                        "save_to_var": "header_text",
                    },
                    {
                        "if": "'Example' in ctx.vars.get('header_text', '')",
                        "then": [
                            {"name": "Mark Success", "action": "set_var", "save_to_var": "flow_status", "value": "matched"}
                        ],
                        "else": [
                            {"name": "Mark Failure", "action": "set_var", "save_to_var": "flow_status", "value": "unmatched"}
                        ],
                    },
                ],
            )
            engine = ScenarioEngine()
            # Launches a real ephemeral guest Camoufox instance
            snapshot = await engine.execute(scenario, mode="guest", headless=True)
            return snapshot

        snapshot = asyncio.run(run_e2e())
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.vars.get("flow_status"), "matched")
        self.assertIn("Example Domain", snapshot.vars.get("header_text", ""))


if __name__ == "__main__":
    unittest.main()
