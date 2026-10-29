"""APIキー・ネットワーク不要のテスト。実モデルの品質や無料枠は検証しません。"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.genai import errors, types
from agent import (PROJECT, FREE_TIER_MODELS, GeminiProvider, LocalTools, MockProvider,
                   Settings, StopAgent, declarations, main, run_agent)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.tools = LocalTools(PROJECT / "samples/candidates.json", self.root / "outputs")
        self.settings = Settings("gemini-3.5-flash-lite")
        self.args = {"candidate_id": "weekly-report", "title": "練習", "body": "架空の下書き"}

    def test_mock_end_to_end(self):
        result = run_agent(MockProvider(), self.settings, self.tools)
        self.assertEqual((result["mode"], result["model_calls"], result["tool_calls"]), ("mock", 2, 2))
        self.assertTrue(result["human_review_required"])
        self.assertIn("架空データ", self.tools.saved.read_text(encoding="utf-8"))

    def test_unknown_tool_has_no_side_effect(self):
        with self.assertRaises(StopAgent):
            self.tools.invoke("run_shell", {"command": "anything"})
        self.assertEqual(list(self.tools.output_dir.iterdir()), [])

    def test_save_before_read_is_rejected(self):
        with self.assertRaises(StopAgent):
            self.tools.invoke("save_markdown", self.args)

    def test_duplicate_read_is_rejected(self):
        self.tools.invoke("list_candidates", {})
        with self.assertRaises(StopAgent):
            self.tools.invoke("list_candidates", {})

    def test_no_overwrite(self):
        target = self.tools.output_dir / "weekly-report.md"
        target.write_text("user edit", encoding="utf-8")
        with self.assertRaises(StopAgent):
            run_agent(MockProvider(), self.settings, self.tools)
        self.assertEqual(target.read_text(encoding="utf-8"), "user edit")

    def test_invalid_save_arguments(self):
        self.tools.invoke("list_candidates", {})
        for change in [{"candidate_id": "../escape"}, {"candidate_id": "unknown"},
                       {"title": "x\ny"}, {"title": ""}, {"body": "a" * 4001},
                       {"body": 1}, {"path": "/outside"}]:
            with self.subTest(change=change), self.assertRaises(StopAgent):
                self.tools.invoke("save_markdown", self.args | change)
        self.assertEqual(list(self.tools.output_dir.iterdir()), [])

    def test_read_rejects_extra_arguments(self):
        with self.assertRaises(StopAgent):
            self.tools.invoke("list_candidates", {"path": "secret"})

    def test_model_cap(self):
        provider = MockProvider()
        with self.assertRaises(StopAgent):
            run_agent(provider, Settings(self.settings.model, 1, 3), self.tools)
        self.assertEqual(provider.calls, 1)
        self.assertIsNone(self.tools.saved)

    def test_tool_cap(self):
        with self.assertRaises(StopAgent):
            run_agent(MockProvider(), Settings(self.settings.model, 3, 1), self.tools)
        self.assertIsNone(self.tools.saved)

    def test_parallel_calls_rejected_before_execution(self):
        response = MockProvider().generate([], self.settings)
        response.candidates[0].content.parts *= 2
        with self.assertRaises(StopAgent):
            run_agent(MagicMock(generate=MagicMock(return_value=response)), self.settings, self.tools)
        self.assertFalse(self.tools.listed)

    def test_missing_or_text_only_response(self):
        for response in [types.GenerateContentResponse(), types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="done")]))]
        )]:
            with self.subTest(response=response), self.assertRaises(StopAgent):
                run_agent(MagicMock(generate=MagicMock(return_value=response)), self.settings, self.tools)

    def test_response_content_and_signature_preserved(self):
        first = MockProvider().generate([], self.settings)
        first.candidates[0].content.parts[0].thought_signature = b"offline-test-signature"
        provider = MockProvider()
        provider.generate = MagicMock(side_effect=[first, provider.generate([], self.settings)])
        # 2回目用の応答だけを保存呼出に差し替えます。
        scripted = MockProvider()
        scripted.generate([], self.settings)
        second = scripted.generate([], self.settings)
        provider.generate.side_effect = [first, second]
        run_agent(provider, self.settings, self.tools)
        history = provider.generate.call_args_list[1].args[0]
        self.assertIs(history[1], first.candidates[0].content)
        self.assertEqual(history[1].parts[0].thought_signature, b"offline-test-signature")
        self.assertEqual(history[2].role, "user")
        self.assertEqual(history[2].parts[0].function_response.name, "list_candidates")

    def test_candidate_validation(self):
        for data in [[], [{"id": "../escape", "topic": "x", "reader": "y"}],
                     [{"id": "ok", "topic": "x", "reader": "y"}] * 2]:
            path = self.root / "bad.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(data=data), self.assertRaises(StopAgent):
                LocalTools(path, self.root / "other")

    def test_settings_reject_unchecked_model_and_unbounded_limits(self):
        path = self.root / "config.json"
        for patch_data in [{"model": "paid-unknown"}, {"max_model_calls": 4},
                           {"max_tool_calls": True}, {"max_tool_calls": 0}, {"extra": 1}]:
            path.write_text(json.dumps({"model": self.settings.model, "max_model_calls": 3,
                                        "max_tool_calls": 3} | patch_data), encoding="utf-8")
            with self.subTest(data=patch_data), self.assertRaises(StopAgent):
                Settings.read(path)

    def test_sdk_no_automatic_calls_or_retries(self):
        with patch("agent.genai.Client") as client:
            provider = GeminiProvider("offline-test-placeholder")
            options = client.call_args.kwargs["http_options"]
            self.assertEqual(options.base_url, "https://generativelanguage.googleapis.com")
            self.assertEqual(options.retry_options.attempts, 1)
            self.assertEqual(options.timeout, 30000)
            provider.generate([], self.settings)
            config = client.return_value.models.generate_content.call_args.kwargs["config"]
            self.assertTrue(config.automatic_function_calling.disable)
            self.assertEqual(config.candidate_count, 1)
            self.assertEqual(config.max_output_tokens, 2048)
            self.assertEqual(len(config.tools[0].function_declarations), 2)
            provider.close()
            client.return_value.close.assert_called_once()

    def test_no_argument_tool_omits_parameter_schema(self):
        declaration = declarations().function_declarations[0]
        self.assertIsNone(declaration.parameters)
        self.assertIsNone(declaration.parameters_json_schema)

    def test_api_errors_stop_once_and_do_not_echo_details(self):
        with patch("agent.genai.Client") as client:
            provider = GeminiProvider("offline-test-placeholder")
            for code in [400, 401, 403, 429, 404, 500]:
                method = client.return_value.models.generate_content
                method.reset_mock()
                method.side_effect = errors.APIError(code, {"message": "PRIVATE_SENTINEL"})
                with self.subTest(code=code), self.assertRaises(StopAgent) as caught:
                    provider.generate([], self.settings)
                self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))
                method.assert_called_once()

    def test_network_exception_is_redacted(self):
        with patch("agent.genai.Client") as client:
            client.return_value.models.generate_content.side_effect = RuntimeError("PRIVATE_SENTINEL")
            with self.assertRaises(StopAgent) as caught:
                GeminiProvider("offline-test-placeholder").generate([], self.settings)
            self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_live_requires_tier_confirmation_before_client_creation(self):
        with patch("sys.argv", ["agent.py", "--live"]), patch("agent.GeminiProvider") as provider:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
            provider.assert_not_called()

    def test_live_requires_explicit_env_path(self):
        with patch("sys.argv", ["agent.py", "--live", "--free-tier-confirmed"]), patch("agent.dotenv_values") as env:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
            env.assert_not_called()


if __name__ == "__main__":
    unittest.main()
