"""Subscription estimates retain per-request context pricing, not aggregate context."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subscription_cli as sub


class Sol61UsageCostTests(unittest.TestCase):
    def test_cached_and_output_including_reasoning(self):
        result = sub.codex_request_usage([{"usage": {
            "input_tokens": 100_000, "cached_input_tokens": 80_000,
            "output_tokens": 10_000, "reasoning_output_tokens": 8_000,
        }}], "gpt-6.1-sol")
        self.assertAlmostEqual(result["cost_usd"], 0.148)
        self.assertEqual(result["reasoning"], 8_000)
        self.assertEqual(result["cost_source"], sub.COST_NOTIONAL)

    def test_many_short_requests_are_not_one_long_request(self):
        result = sub.codex_request_usage([
            {"usage": {"input_tokens": 150_000, "output_tokens": 1_000}},
            {"usage": {"input_tokens": 150_000, "output_tokens": 1_000}},
        ], "gpt-6.1-sol")
        self.assertAlmostEqual(result["cost_usd"], 0.62)
        self.assertEqual(result["calls"], 2)

    def test_long_request_multipliers_and_cache_writes(self):
        result = sub.codex_request_usage([{"usage": {
            "input_tokens": 300_000, "cached_input_tokens": 100_000,
            "cache_write_input_tokens": 20_000, "output_tokens": 10_000,
        }}], "gpt-6.1-sol")
        self.assertAlmostEqual(result["cost_usd"], 0.99)
        self.assertEqual(result["cache_write"], 20_000)

    def test_unknown_model_stays_unpriced(self):
        result = sub.codex_request_usage([{"usage": {"input_tokens": 500}}], "unpriced-model")
        self.assertIsNone(result["cost_usd"])
        self.assertEqual(result["cost_source"], sub.COST_UNKNOWN)
