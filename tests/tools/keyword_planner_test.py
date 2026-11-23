# Copyright 2026 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test cases for the Keyword Planner tools."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastmcp.exceptions import ToolError
from google.ads.googleads.client import GoogleAdsClient

from ads_mcp.tools import keyword_planner as kp


def _metrics(avg, competition="LOW", index=10, low=1_500_000, high=4_250_000):
    return SimpleNamespace(
        avg_monthly_searches=avg,
        competition=competition,
        competition_index=index,
        low_top_of_page_bid_micros=low,
        high_top_of_page_bid_micros=high,
        monthly_search_volumes=[
            SimpleNamespace(year=2026, month="OCTOBER", monthly_searches=avg)
        ],
    )


class _FakeClient:
    """Uses the real request types and enums; services are mocks."""

    def __init__(self, idea_service):
        self._real = GoogleAdsClient(
            credentials=MagicMock(), developer_token="x", use_proto_plus=True
        )
        self.enums = self._real.enums
        self.idea_service = idea_service

    def get_type(self, name):
        return self._real.get_type(name)

    def get_service(self, name, **kwargs):
        if name == "KeywordPlanIdeaService":
            return self.idea_service
        return self._real.get_service(name)


class TestKeywordVolumes(unittest.TestCase):
    def setUp(self):
        self.service = MagicMock()
        self.client = _FakeClient(self.service)
        p1 = patch(
            "ads_mcp.utils.get_googleads_client", return_value=self.client
        )
        p2 = patch(
            "ads_mcp.utils.get_googleads_service_from_client",
            side_effect=lambda c, n: c.get_service(n),
        )
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def test_builds_request_with_brazil_portuguese_defaults(self):
        self.service.generate_keyword_historical_metrics.return_value = (
            SimpleNamespace(
                results=[
                    SimpleNamespace(
                        text="sistema de votação",
                        close_variants=["sistema de votacao"],
                        keyword_metrics=_metrics(880, "MEDIUM", 40),
                    )
                ]
            )
        )

        rows = kp.keyword_volumes(
            customer_id="444-848-3866",
            keywords=["sistema de votação", "  sistema   de votacao ", ""],
        )

        request = (
            self.service.generate_keyword_historical_metrics.call_args.kwargs[
                "request"
            ]
        )
        self.assertEqual(request.customer_id, "4448483866")
        self.assertEqual(
            list(request.keywords), ["sistema de votação", "sistema de votacao"]
        )
        self.assertEqual(
            list(request.geo_target_constants), ["geoTargetConstants/2076"]
        )
        self.assertEqual(request.language, "languageConstants/1014")
        self.assertEqual(request.keyword_plan_network.name, "GOOGLE_SEARCH")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["avg_monthly_searches"], 880)
        self.assertEqual(rows[0]["low_top_of_page_bid"], 1.5)
        self.assertEqual(rows[0]["high_top_of_page_bid"], 4.25)
        self.assertNotIn("monthly_searches", rows[0])

    def test_lists_keywords_without_data(self):
        self.service.generate_keyword_historical_metrics.return_value = (
            SimpleNamespace(
                results=[
                    SimpleNamespace(
                        text="guia de áudio",
                        close_variants=[],
                        keyword_metrics=_metrics(210),
                    )
                ]
            )
        )
        rows = kp.keyword_volumes(
            customer_id="9238468237",
            keywords=["guia de áudio", "rádio visitação"],
            include_monthly=True,
        )
        self.assertEqual(
            [r["keyword"] for r in rows], ["guia de áudio", "rádio visitação"]
        )
        self.assertEqual(rows[0]["monthly_searches"][0]["searches"], 210)
        self.assertEqual(rows[1]["avg_monthly_searches"], 0)
        self.assertIn("note", rows[1])

    def test_custom_location_language_and_partners(self):
        self.service.generate_keyword_historical_metrics.return_value = (
            SimpleNamespace(results=[])
        )
        kp.keyword_volumes(
            customer_id="1",
            keywords=["transcripción de audio"],
            location_ids=["2484", "2032"],
            language_id="1003",
            include_search_partners=True,
        )
        request = (
            self.service.generate_keyword_historical_metrics.call_args.kwargs[
                "request"
            ]
        )
        self.assertEqual(
            list(request.geo_target_constants),
            ["geoTargetConstants/2484", "geoTargetConstants/2032"],
        )
        self.assertEqual(request.language, "languageConstants/1003")
        self.assertEqual(
            request.keyword_plan_network.name, "GOOGLE_SEARCH_AND_PARTNERS"
        )

    def test_validation(self):
        with self.assertRaises(ToolError):
            kp.keyword_volumes(customer_id="abc", keywords=["x"])
        with self.assertRaises(ToolError):
            kp.keyword_volumes(customer_id="1", keywords=["  "])


class TestKeywordIdeas(unittest.TestCase):
    def setUp(self):
        self.service = MagicMock()
        self.client = _FakeClient(self.service)
        p1 = patch(
            "ads_mcp.utils.get_googleads_client", return_value=self.client
        )
        p2 = patch(
            "ads_mcp.utils.get_googleads_service_from_client",
            side_effect=lambda c, n: c.get_service(n),
        )
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.service.generate_keyword_ideas.return_value = [
            SimpleNamespace(
                text="sistema guia turistico",
                close_variants=[],
                keyword_idea_metrics=_metrics(90),
            ),
            SimpleNamespace(
                text="sistema de guia turístico sem fio",
                close_variants=[],
                keyword_idea_metrics=_metrics(320),
            ),
            SimpleNamespace(
                text="guia turístico curitiba",
                close_variants=[],
                keyword_idea_metrics=_metrics(5),
            ),
        ]

    def test_keyword_and_url_seed_sorted_and_filtered(self):
        rows = kp.keyword_ideas(
            customer_id="9238468237",
            seed_keywords=["sistema de guia turístico"],
            url="https://riole.com.br/techtour",
            max_results=2,
            min_monthly_searches=10,
        )
        request = self.service.generate_keyword_ideas.call_args.kwargs[
            "request"
        ]
        self.assertEqual(
            request.keyword_and_url_seed.url, "https://riole.com.br/techtour"
        )
        self.assertEqual(
            list(request.keyword_and_url_seed.keywords),
            ["sistema de guia turístico"],
        )
        self.assertFalse(request.include_adult_keywords)
        self.assertEqual(
            [r["keyword"] for r in rows],
            ["sistema de guia turístico sem fio", "sistema guia turistico"],
        )

    def test_url_only_seed(self):
        kp.keyword_ideas(customer_id="1", url="https://riole.com.br")
        request = self.service.generate_keyword_ideas.call_args.kwargs[
            "request"
        ]
        self.assertEqual(request.url_seed.url, "https://riole.com.br")

    def test_keyword_only_seed(self):
        kp.keyword_ideas(customer_id="1", seed_keywords=["intercom sem fio"])
        request = self.service.generate_keyword_ideas.call_args.kwargs[
            "request"
        ]
        self.assertEqual(
            list(request.keyword_seed.keywords), ["intercom sem fio"]
        )

    def test_validation(self):
        with self.assertRaises(ToolError):
            kp.keyword_ideas(customer_id="1")
        with self.assertRaises(ToolError):
            kp.keyword_ideas(
                customer_id="1", seed_keywords=[f"k{i}" for i in range(21)]
            )
        with self.assertRaises(ToolError):
            kp.keyword_ideas(
                customer_id="1", url="https://x.com", max_results=0
            )


class TestRegistration(unittest.IsolatedAsyncioTestCase):
    async def test_tools_registered_read_only(self):
        tools = {t.name: t for t in await kp.planner_mcp.list_tools()}
        self.assertEqual(set(tools), {"keyword_volumes", "keyword_ideas"})
        for tool in tools.values():
            self.assertTrue(tool.annotations.read_only_hint)


if __name__ == "__main__":
    unittest.main()
