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

"""Keyword Planner tools (KeywordPlanIdeaService): search volume and ideas.

Both tools are read-only: they return Keyword Planner data and change nothing
in the account. The developer token needs a permissible use that includes
keyword research (KeywordPlanIdeaService).
"""

from typing import Any, Dict, List

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from google.ads.googleads.errors import GoogleAdsException
from mcp.types import ToolAnnotations

import ads_mcp.utils as utils

planner_mcp = FastMCP("planner")

_READ = ToolAnnotations(readOnlyHint=True)

# Defaults: Brazil (geo target 2076) and Portuguese (language 1014).
DEFAULT_LOCATION_IDS = ["2076"]
DEFAULT_LANGUAGE_ID = "1014"

MAX_HISTORICAL_KEYWORDS = 10000
MAX_SEED_KEYWORDS = 20
MAX_IDEAS = 1000


def _micros_to_currency(value: Any) -> float | None:
    if value is None or value == 0:
        return None
    return round(int(value) / 1_000_000, 2)


def _clean_keywords(keywords: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for kw in keywords or []:
        text = " ".join(str(kw).split()).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def _metrics_to_dict(metrics: Any, include_monthly: bool) -> Dict[str, Any]:
    """Converts KeywordPlanHistoricalMetrics into a flat dict."""
    data: Dict[str, Any] = {
        "avg_monthly_searches": int(metrics.avg_monthly_searches or 0),
        "competition": utils.format_output_value(metrics.competition),
        "competition_index": int(metrics.competition_index or 0),
        "low_top_of_page_bid": _micros_to_currency(
            metrics.low_top_of_page_bid_micros
        ),
        "high_top_of_page_bid": _micros_to_currency(
            metrics.high_top_of_page_bid_micros
        ),
    }
    if include_monthly:
        data["monthly_searches"] = [
            {
                "year": int(m.year),
                "month": utils.format_output_value(m.month),
                "searches": int(m.monthly_searches or 0),
            }
            for m in metrics.monthly_search_volumes
        ]
    return data


def _common_request_fields(
    client: Any,
    request: Any,
    customer_id: str,
    location_ids: List[str] | None,
    language_id: str | None,
    include_search_partners: bool,
) -> None:
    geo_service = client.get_service("GeoTargetConstantService")
    language_service = client.get_service("GoogleAdsService")

    request.customer_id = customer_id
    for loc in location_ids or DEFAULT_LOCATION_IDS:
        loc_id = utils.clean_customer_id(loc)
        if not loc_id:
            raise ToolError(f"Error: invalid location id '{loc}'.")
        request.geo_target_constants.append(
            geo_service.geo_target_constant_path(loc_id)
        )
    lang_id = utils.clean_customer_id(language_id or DEFAULT_LANGUAGE_ID)
    if not lang_id:
        raise ToolError(f"Error: invalid language id '{language_id}'.")
    request.language = language_service.language_constant_path(lang_id)

    network_enum = client.enums.KeywordPlanNetworkEnum
    request.keyword_plan_network = (
        network_enum.GOOGLE_SEARCH_AND_PARTNERS
        if include_search_partners
        else network_enum.GOOGLE_SEARCH
    )


def keyword_volumes(
    customer_id: str | int,
    keywords: List[str],
    location_ids: List[str] | None = None,
    language_id: str | None = None,
    include_monthly: bool = False,
    include_search_partners: bool = False,
    login_customer_id: str | int | None = None,
) -> List[Dict[str, Any]]:
    """Keyword Planner: historical search volume for a list of keywords.

    Same data as Keyword Planner > "Get search volume and forecasts": average
    monthly searches (last 12 months), competition (LOW/MEDIUM/HIGH and 0-100
    index) and the top-of-page bid range, in the account currency. Read-only.

    Args:
        customer_id: Account ID used for the request (no hyphens).
        keywords: Keywords to look up (up to 10,000). Close variants are grouped
            by Google; the result's `close_variants` lists which ones.
        location_ids: Geo target constant IDs. Default ["2076"] (Brazil). Find
            others with `search` on geo_target_constant (e.g. state of Paraná).
        language_id: Language constant ID. Default "1014" (Portuguese);
            "1003" Spanish, "1000" English.
        include_monthly: Also return the searches of each of the last 12 months.
        include_search_partners: Include Google search partners (default: Google
            Search only, which matches campaigns with partners turned off).
        login_customer_id: Optional manager account ID (login-customer-id header).

    Returns one row per keyword: keyword, close_variants, avg_monthly_searches,
    competition, competition_index, low_top_of_page_bid, high_top_of_page_bid
    (and monthly_searches if requested). Keywords Google has no data for come
    back with avg_monthly_searches 0.
    """
    customer_id = utils.clean_customer_id(customer_id)
    if not customer_id:
        raise ToolError("Error: 'customer_id' must contain digits.")
    kws = _clean_keywords(keywords)
    if not kws:
        raise ToolError("Error: 'keywords' is empty.")
    if len(kws) > MAX_HISTORICAL_KEYWORDS:
        raise ToolError(
            f"Error: at most {MAX_HISTORICAL_KEYWORDS} keywords per request."
        )

    client = utils.get_googleads_client(login_customer_id=login_customer_id)
    service = utils.get_googleads_service_from_client(
        client, "KeywordPlanIdeaService"
    )
    request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    _common_request_fields(
        client,
        request,
        customer_id,
        location_ids,
        language_id,
        include_search_partners,
    )
    request.keywords.extend(kws)

    try:
        response = service.generate_keyword_historical_metrics(request=request)
    except GoogleAdsException as ex:
        raise ToolError(utils.format_google_ads_error(ex)) from ex

    rows: List[Dict[str, Any]] = []
    returned: set[str] = set()
    for result in response.results:
        row = {
            "keyword": result.text,
            "close_variants": list(result.close_variants),
        }
        row.update(_metrics_to_dict(result.keyword_metrics, include_monthly))
        rows.append(row)
        returned.add(result.text.lower())
        returned.update(v.lower() for v in result.close_variants)

    # Keywords grouped under another one or without data are listed too, so
    # every requested keyword appears in the answer.
    for kw in kws:
        if kw.lower() not in returned:
            rows.append(
                {
                    "keyword": kw,
                    "close_variants": [],
                    "avg_monthly_searches": 0,
                    "competition": None,
                    "competition_index": 0,
                    "low_top_of_page_bid": None,
                    "high_top_of_page_bid": None,
                    "note": "no data returned by Keyword Planner",
                }
            )

    rows.sort(key=lambda r: r["avg_monthly_searches"], reverse=True)
    return rows


def keyword_ideas(
    customer_id: str | int,
    seed_keywords: List[str] | None = None,
    url: str | None = None,
    location_ids: List[str] | None = None,
    language_id: str | None = None,
    max_results: int = 100,
    min_monthly_searches: int = 0,
    include_monthly: bool = False,
    include_search_partners: bool = False,
    login_customer_id: str | int | None = None,
) -> List[Dict[str, Any]]:
    """Keyword Planner: new keyword ideas from seed keywords and/or a URL.

    Same data as Keyword Planner > "Discover new keywords". Give seed keywords
    (up to 20), a page URL, or both. Each idea comes with average monthly
    searches, competition and the top-of-page bid range. Read-only.

    Args:
        customer_id: Account ID used for the request (no hyphens).
        seed_keywords: Up to 20 seed keywords.
        url: A page (e.g. a product page) to extract ideas from.
        location_ids: Geo target constant IDs. Default ["2076"] (Brazil).
        language_id: Language constant ID. Default "1014" (Portuguese).
        max_results: Maximum number of ideas returned (1-1000, default 100),
            sorted by average monthly searches.
        min_monthly_searches: Drop ideas with fewer average monthly searches.
        include_monthly: Also return the searches of each of the last 12 months.
        include_search_partners: Include Google search partners.
        login_customer_id: Optional manager account ID (login-customer-id header).

    Returns rows with keyword, avg_monthly_searches, competition,
    competition_index, low_top_of_page_bid, high_top_of_page_bid,
    close_variants (and monthly_searches if requested).
    """
    customer_id = utils.clean_customer_id(customer_id)
    if not customer_id:
        raise ToolError("Error: 'customer_id' must contain digits.")
    seeds = _clean_keywords(seed_keywords or [])
    url = (url or "").strip() or None
    if not seeds and not url:
        raise ToolError("Error: give 'seed_keywords', 'url', or both.")
    if len(seeds) > MAX_SEED_KEYWORDS:
        raise ToolError(f"Error: at most {MAX_SEED_KEYWORDS} seed keywords.")
    if not 1 <= int(max_results) <= MAX_IDEAS:
        raise ToolError(
            f"Error: 'max_results' must be between 1 and {MAX_IDEAS}."
        )

    client = utils.get_googleads_client(login_customer_id=login_customer_id)
    service = utils.get_googleads_service_from_client(
        client, "KeywordPlanIdeaService"
    )
    request = client.get_type("GenerateKeywordIdeasRequest")
    _common_request_fields(
        client,
        request,
        customer_id,
        location_ids,
        language_id,
        include_search_partners,
    )
    request.include_adult_keywords = False
    request.page_size = MAX_IDEAS

    if seeds and url:
        request.keyword_and_url_seed.url = url
        request.keyword_and_url_seed.keywords.extend(seeds)
    elif seeds:
        request.keyword_seed.keywords.extend(seeds)
    else:
        request.url_seed.url = url

    try:
        pager = service.generate_keyword_ideas(request=request)
        rows: List[Dict[str, Any]] = []
        for idea in pager:
            row = {
                "keyword": idea.text,
                "close_variants": list(idea.close_variants),
            }
            row.update(
                _metrics_to_dict(idea.keyword_idea_metrics, include_monthly)
            )
            if row["avg_monthly_searches"] >= int(min_monthly_searches):
                rows.append(row)
            if len(rows) >= MAX_IDEAS:
                break
    except GoogleAdsException as ex:
        raise ToolError(utils.format_google_ads_error(ex)) from ex

    rows.sort(key=lambda r: r["avg_monthly_searches"], reverse=True)
    return rows[: int(max_results)]


planner_mcp.tool(annotations=_READ)(keyword_volumes)
planner_mcp.tool(annotations=_READ)(keyword_ideas)
