# Copyright 2026 Bryan Poncio.
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

"""Campaign management tools: campaigns, ad groups, ads, keywords and negatives.

Every tool follows the propose & confirm workflow used across this server:
1. Call with ``validate_only=True`` (default). The request is validated by the
   Google Ads API without changing anything, and the tool returns the proposed
   ``change_items`` plus a ``checksum``.
2. Show the ``change_items`` to the user and wait for explicit approval.
3. Call again with ``validate_only=False``, the exact same parameters and the
   ``checksum`` to commit.

New campaigns are always created PAUSED, so nothing spends money until the user
explicitly enables the campaign with ``update_campaign``.
"""

from enum import Enum
from typing import Any, Callable

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from ads_mcp import propose_and_confirm as pac
import ads_mcp.utils as utils

management_mcp = FastMCP("management")

_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

_CONFIRM_DOC = """
    Propose & Confirm Workflow (`validate_only` and `checksum`):
    1. Call with `validate_only=True` (the default). The Google Ads API validates the request without committing, and the tool returns `change_items` and a `checksum`.
    2. Present the `change_items` to the user in plain language and wait for explicit approval.
    3. Only after approval, call again with `validate_only=False`, the exact same parameters, and the `checksum`.
"""


def _confirm_doc(fn):
    """Appends the propose & confirm instructions to a tool's description."""
    fn.__doc__ = (fn.__doc__ or "").rstrip() + "\n" + _CONFIRM_DOC
    return fn


# ---------------------------------------------------------------- enums/models


class Status(str, Enum):
    ENABLED = "ENABLED"
    PAUSED = "PAUSED"


class StatusOrRemove(str, Enum):
    ENABLED = "ENABLED"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


class MatchType(str, Enum):
    EXACT = "EXACT"
    PHRASE = "PHRASE"
    BROAD = "BROAD"


class BiddingStrategy(str, Enum):
    MAXIMIZE_CLICKS = "MAXIMIZE_CLICKS"
    MAXIMIZE_CONVERSIONS = "MAXIMIZE_CONVERSIONS"
    MAXIMIZE_CONVERSION_VALUE = "MAXIMIZE_CONVERSION_VALUE"
    MANUAL_CPC = "MANUAL_CPC"


class NegativeLevel(str, Enum):
    CAMPAIGN = "CAMPAIGN"
    AD_GROUP = "AD_GROUP"


class AssetFieldType(str, Enum):
    SITELINK = "SITELINK"
    CALLOUT = "CALLOUT"
    STRUCTURED_SNIPPET = "STRUCTURED_SNIPPET"
    CALL = "CALL"
    PROMOTION = "PROMOTION"
    PRICE = "PRICE"


class Keyword(BaseModel):
    text: str = Field(description="Keyword text, without match-type symbols.")
    match_type: MatchType = Field(default=MatchType.PHRASE)
    cpc_bid: float | None = Field(
        default=None,
        description="Optional max CPC in the account currency (only used with MANUAL_CPC).",
    )


class NegativeKeyword(BaseModel):
    text: str
    match_type: MatchType = Field(default=MatchType.PHRASE)


class KeywordUpdate(BaseModel):
    criterion_id: str = Field(description="ad_group_criterion.criterion_id of the keyword.")
    status: StatusOrRemove | None = Field(
        default=None, description="ENABLED, PAUSED or REMOVED (REMOVED deletes the keyword)."
    )
    cpc_bid: float | None = None


# --------------------------------------------------------------------- helpers


def _cid(customer_id: str | int) -> str:
    cleaned = utils.clean_customer_id(customer_id)
    if not cleaned:
        raise ToolError("Error: 'customer_id' must contain digits.")
    return cleaned


def _micros(amount: float | None) -> int | None:
    """Converts a currency amount to micros, rounded to the cent."""
    if amount is None:
        return None
    if amount < 0:
        raise ToolError("Error: amounts must be positive.")
    return int(round(amount * 100)) * 10_000


def _money(micros: int | None) -> str | None:
    return None if micros is None else f"{micros / 1_000_000:.2f}"


def _result_names(response: Any) -> list[str]:
    names = []
    for r in response.mutate_operation_responses:
        pb = type(r).pb(r)
        which = pb.WhichOneof("response")
        if which:
            names.append(getattr(pb, which).resource_name)
    return names


def _run(
    *,
    tool: str,
    customer_id: str,
    params: dict,
    build_ops: Callable[[Any], list],
    change_items: list,
    validate_only: bool,
    checksum: str | None,
    login_customer_id: str | int | None,
    success: str,
) -> str:
    """Builds the operations, validates against the API and commits on confirmation."""
    client = utils.get_googleads_client(login_customer_id=login_customer_id)
    service = utils.get_googleads_service_from_client(client, "GoogleAdsService")
    operations = build_ops(client)
    if not operations:
        raise ToolError("Error: nothing to change.")

    def _request(validate: bool):
        req = client.get_type("MutateGoogleAdsRequest")
        req.customer_id = customer_id
        req.mutate_operations.extend(operations)
        req.validate_only = validate
        return service.mutate(request=req)

    def _commit() -> str:
        response = _request(False)
        names = _result_names(response)
        lines = "\n".join(f"- {n}" for n in names)
        return f"{success}\n{lines}" if lines else success

    return pac.propose_and_confirm(
        customer_id=customer_id,
        validate_only=validate_only,
        checksum=checksum,
        operation_payload={"tool": tool, **params},
        change_items=change_items,
        validate_fn=lambda: _request(True),
        commit_fn=_commit,
        error_prefix=f"Failed to run {tool}",
    )


def _query_one(client: Any, customer_id: str, query: str) -> Any:
    service = utils.get_googleads_service_from_client(client, "GoogleAdsService")
    for row in service.search(customer_id=customer_id, query=query):
        return row
    return None


def _items(op: str, entity: str, key: str, fields: dict, original: dict | None = None) -> list:
    return pac.build_change_items(
        operation=op,
        entity_readable=entity,
        primary_key_readable=key,
        fields=fields,
        original_fields=original,
    )


def _keyword_op(client, ad_group_rn: str, kw: Keyword, status: str):
    op = client.get_type("MutateOperation")
    crit = op.ad_group_criterion_operation.create
    crit.ad_group = ad_group_rn
    crit.status = getattr(client.enums.AdGroupCriterionStatusEnum, status)
    crit.keyword.text = kw.text
    crit.keyword.match_type = getattr(client.enums.KeywordMatchTypeEnum, kw.match_type.value)
    if kw.cpc_bid is not None:
        crit.cpc_bid_micros = _micros(kw.cpc_bid)
    return op


def _rsa_op(
    client,
    ad_group_rn: str,
    headlines: list[str],
    descriptions: list[str],
    final_url: str,
    path1: str | None,
    path2: str | None,
    status: str,
):
    _check_rsa(headlines, descriptions, path1, path2)
    op = client.get_type("MutateOperation")
    aga = op.ad_group_ad_operation.create
    aga.ad_group = ad_group_rn
    aga.status = getattr(client.enums.AdGroupAdStatusEnum, status)
    aga.ad.final_urls.append(final_url)
    rsa = aga.ad.responsive_search_ad
    for h in headlines:
        asset = client.get_type("AdTextAsset")
        asset.text = h
        rsa.headlines.append(asset)
    for d in descriptions:
        asset = client.get_type("AdTextAsset")
        asset.text = d
        rsa.descriptions.append(asset)
    if path1:
        rsa.path1 = path1
    if path2:
        rsa.path2 = path2
    return op


def _check_rsa(headlines, descriptions, path1, path2) -> None:
    if not 3 <= len(headlines) <= 15:
        raise ToolError("Error: responsive search ads need 3 to 15 headlines.")
    if not 2 <= len(descriptions) <= 4:
        raise ToolError("Error: responsive search ads need 2 to 4 descriptions.")
    long_h = [h for h in headlines if len(h) > 30]
    long_d = [d for d in descriptions if len(d) > 90]
    if long_h:
        raise ToolError(f"Error: headlines over 30 characters: {long_h}")
    if long_d:
        raise ToolError(f"Error: descriptions over 90 characters: {long_d}")
    for p in (path1, path2):
        if p and len(p) > 15:
            raise ToolError(f"Error: display path '{p}' is over 15 characters.")


def _negative_op(client, level: NegativeLevel, parent_rn: str, kw: NegativeKeyword):
    op = client.get_type("MutateOperation")
    if level == NegativeLevel.CAMPAIGN:
        crit = op.campaign_criterion_operation.create
        crit.campaign = parent_rn
    else:
        crit = op.ad_group_criterion_operation.create
        crit.ad_group = parent_rn
    crit.negative = True
    crit.keyword.text = kw.text
    crit.keyword.match_type = getattr(client.enums.KeywordMatchTypeEnum, kw.match_type.value)
    return op


# ----------------------------------------------------------------------- tools


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def create_search_campaign(
    customer_id: str | int,
    campaign_name: str,
    daily_budget: float,
    bidding_strategy: BiddingStrategy = BiddingStrategy.MAXIMIZE_CLICKS,
    target_cpa: float | None = None,
    max_cpc_limit: float | None = None,
    location_ids: list[str] | None = None,
    language_ids: list[str] | None = None,
    include_search_partners: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
    ad_group_name: str | None = None,
    ad_group_cpc_bid: float | None = None,
    keywords: list[Keyword] | None = None,
    negative_keywords: list[NegativeKeyword] | None = None,
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
    final_url: str | None = None,
    path1: str | None = None,
    path2: str | None = None,
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Creates a complete Google Search campaign in one atomic request, always PAUSED.

    Creates: daily budget, Search campaign (Google Search only, no Display network),
    location and language targeting, optional campaign negative keywords and, when
    `ad_group_name` is given, one ad group with its keywords and one responsive search ad.

    Args:
        customer_id: Account that will own the campaign (not the manager account).
        campaign_name: Unique campaign name.
        daily_budget: Average daily budget in the account currency (e.g. 50.0 for R$ 50/day).
        bidding_strategy: MAXIMIZE_CLICKS (default, good to start without conversion data),
            MAXIMIZE_CONVERSIONS (needs conversion tracking), MAXIMIZE_CONVERSION_VALUE or MANUAL_CPC.
        target_cpa: Optional target cost per conversion (only with MAXIMIZE_CONVERSIONS).
        max_cpc_limit: Optional max CPC ceiling (with MAXIMIZE_CLICKS).
        location_ids: Geo target constant IDs. Default ['2076'] (Brazil). Look up others with
            `search` on resource geo_target_constant.
        language_ids: Language constant IDs. Default ['1014'] (Portuguese).
        include_search_partners: Also show on Google search partner sites. Default False.
        start_date / end_date: Optional 'YYYY-MM-DD'.
        ad_group_name: If set, also creates an ad group (requires keywords, headlines, descriptions, final_url).
        ad_group_cpc_bid: Default max CPC for the ad group (MANUAL_CPC only).
        keywords: Keywords for the ad group: [{text, match_type: EXACT|PHRASE|BROAD, cpc_bid?}].
        negative_keywords: Campaign-level negatives: [{text, match_type}].
        headlines: 3-15 headlines, max 30 characters each.
        descriptions: 2-4 descriptions, max 90 characters each.
        final_url: Landing page URL of the ad.
        path1 / path2: Optional display URL paths, max 15 characters each.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    locations = location_ids or ["2076"]
    languages = language_ids or ["1014"]
    keywords = keywords or []
    negative_keywords = negative_keywords or []
    if ad_group_name:
        missing = [
            n
            for n, v in (
                ("keywords", keywords),
                ("headlines", headlines),
                ("descriptions", descriptions),
                ("final_url", final_url),
            )
            if not v
        ]
        if missing:
            raise ToolError(f"Error: creating an ad group also requires: {', '.join(missing)}.")
        _check_rsa(headlines, descriptions, path1, path2)
    if target_cpa is not None and bidding_strategy != BiddingStrategy.MAXIMIZE_CONVERSIONS:
        raise ToolError("Error: target_cpa only applies to MAXIMIZE_CONVERSIONS.")

    budget_rn = f"customers/{cid}/campaignBudgets/-1"
    campaign_rn = f"customers/{cid}/campaigns/-2"
    ad_group_rn = f"customers/{cid}/adGroups/-3"

    def build(client) -> list:
        ops = []
        op = client.get_type("MutateOperation")
        budget = op.campaign_budget_operation.create
        budget.resource_name = budget_rn
        budget.name = f"{campaign_name} - orçamento"
        budget.amount_micros = _micros(daily_budget)
        budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
        budget.explicitly_shared = False
        ops.append(op)

        op = client.get_type("MutateOperation")
        camp = op.campaign_operation.create
        camp.resource_name = campaign_rn
        camp.name = campaign_name
        camp.status = client.enums.CampaignStatusEnum.PAUSED
        camp.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        camp.campaign_budget = budget_rn
        camp.contains_eu_political_advertising = (
            client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
        )
        camp.network_settings.target_google_search = True
        camp.network_settings.target_search_network = include_search_partners
        camp.network_settings.target_partner_search_network = False
        camp.network_settings.target_content_network = False
        if bidding_strategy == BiddingStrategy.MAXIMIZE_CLICKS:
            camp.target_spend.target_spend_micros = 0
            if max_cpc_limit is not None:
                camp.target_spend.cpc_bid_ceiling_micros = _micros(max_cpc_limit)
        elif bidding_strategy == BiddingStrategy.MAXIMIZE_CONVERSIONS:
            camp.maximize_conversions.target_cpa_micros = _micros(target_cpa) or 0
        elif bidding_strategy == BiddingStrategy.MAXIMIZE_CONVERSION_VALUE:
            camp.maximize_conversion_value.target_roas = 0
        else:
            camp.manual_cpc.enhanced_cpc_enabled = False
        if start_date:
            camp.start_date_time = f"{start_date} 00:00:00"
        if end_date:
            camp.end_date_time = f"{end_date} 23:59:59"
        ops.append(op)

        for loc in locations:
            op = client.get_type("MutateOperation")
            crit = op.campaign_criterion_operation.create
            crit.campaign = campaign_rn
            crit.location.geo_target_constant = f"geoTargetConstants/{utils.extract_id(str(loc))}"
            ops.append(op)
        for lang in languages:
            op = client.get_type("MutateOperation")
            crit = op.campaign_criterion_operation.create
            crit.campaign = campaign_rn
            crit.language.language_constant = f"languageConstants/{utils.extract_id(str(lang))}"
            ops.append(op)
        for neg in negative_keywords:
            ops.append(_negative_op(client, NegativeLevel.CAMPAIGN, campaign_rn, neg))

        if ad_group_name:
            op = client.get_type("MutateOperation")
            ag = op.ad_group_operation.create
            ag.resource_name = ad_group_rn
            ag.name = ad_group_name
            ag.campaign = campaign_rn
            ag.status = client.enums.AdGroupStatusEnum.ENABLED
            ag.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
            if ad_group_cpc_bid is not None:
                ag.cpc_bid_micros = _micros(ad_group_cpc_bid)
            ops.append(op)
            for kw in keywords:
                ops.append(_keyword_op(client, ad_group_rn, kw, "ENABLED"))
            ops.append(
                _rsa_op(client, ad_group_rn, headlines, descriptions, final_url, path1, path2, "ENABLED")
            )
        return ops

    change_items = _items(
        "CREATE",
        "Campaign (Search)",
        campaign_name,
        {
            "Status": "PAUSED (enable later with update_campaign)",
            "Daily budget": _money(_micros(daily_budget)),
            "Bidding": bidding_strategy.value,
            "Target CPA": _money(_micros(target_cpa)),
            "Max CPC limit": _money(_micros(max_cpc_limit)),
            "Locations": ", ".join(locations),
            "Languages": ", ".join(languages),
            "Search partners": include_search_partners,
            "Start date": start_date,
            "End date": end_date,
            "Negative keywords": [f"{n.text} [{n.match_type.value}]" for n in negative_keywords] or None,
        },
    )
    if ad_group_name:
        change_items += _items(
            "CREATE",
            "Ad group",
            ad_group_name,
            {
                "Default CPC": _money(_micros(ad_group_cpc_bid)),
                "Keywords": [f"{k.text} [{k.match_type.value}]" for k in keywords],
            },
        )
        change_items += _items(
            "CREATE",
            "Responsive search ad",
            ad_group_name,
            {
                "Headlines": headlines,
                "Descriptions": descriptions,
                "Final URL": final_url,
                "Path": "/".join(p for p in (path1, path2) if p) or None,
            },
        )

    params = {
        "campaign_name": campaign_name,
        "daily_budget": daily_budget,
        "bidding_strategy": bidding_strategy.value,
        "target_cpa": target_cpa,
        "max_cpc_limit": max_cpc_limit,
        "locations": locations,
        "languages": languages,
        "include_search_partners": include_search_partners,
        "start_date": start_date,
        "end_date": end_date,
        "ad_group_name": ad_group_name,
        "ad_group_cpc_bid": ad_group_cpc_bid,
        "keywords": [k.model_dump(mode="json") for k in keywords],
        "negative_keywords": [n.model_dump(mode="json") for n in negative_keywords],
        "headlines": headlines,
        "descriptions": descriptions,
        "final_url": final_url,
        "path1": path1,
        "path2": path2,
    }
    return _run(
        tool="create_search_campaign",
        customer_id=cid,
        params=params,
        build_ops=build,
        change_items=change_items,
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Campaign created (PAUSED). Resources:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def update_campaign(
    customer_id: str | int,
    campaign_id: str,
    status: StatusOrRemove | None = None,
    name: str | None = None,
    daily_budget: float | None = None,
    end_date: str | None = None,
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Updates a campaign: enable/pause/remove it, rename it, change its daily budget or end date.

    Enabling a campaign (status=ENABLED) starts spending money. REMOVED is permanent.
    Changing `daily_budget` edits the campaign's budget; if that budget is shared with
    other campaigns they change too (the proposal shows how many campaigns use it).

    Args:
        customer_id: Account ID.
        campaign_id: campaign.id.
        status: ENABLED, PAUSED or REMOVED.
        name: New campaign name.
        daily_budget: New average daily budget in the account currency.
        end_date: New end date 'YYYY-MM-DD'.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    camp_id = utils.extract_id(str(campaign_id))
    if status is None and name is None and daily_budget is None and end_date is None:
        raise ToolError("Error: give at least one of status, name, daily_budget, end_date.")

    client = utils.get_googleads_client(login_customer_id=login_customer_id)
    row = _query_one(
        client,
        cid,
        "SELECT campaign.name, campaign.status, campaign.end_date_time, "
        "campaign_budget.resource_name, campaign_budget.amount_micros, "
        "campaign_budget.reference_count "
        f"FROM campaign WHERE campaign.id = {int(camp_id)}",
    )
    if row is None:
        raise ToolError(f"Error: campaign {camp_id} not found in account {cid}.")
    budget_rn = row.campaign_budget.resource_name
    campaign_rn = f"customers/{cid}/campaigns/{camp_id}"

    def build(client) -> list:
        ops = []
        if status == StatusOrRemove.REMOVED:
            op = client.get_type("MutateOperation")
            op.campaign_operation.remove = campaign_rn
            return [op]
        paths = []
        op = client.get_type("MutateOperation")
        camp = op.campaign_operation.update
        camp.resource_name = campaign_rn
        if status is not None:
            camp.status = getattr(client.enums.CampaignStatusEnum, status.value)
            paths.append("status")
        if name is not None:
            camp.name = name
            paths.append("name")
        if end_date is not None:
            camp.end_date_time = f"{end_date} 23:59:59"
            paths.append("end_date_time")
        if paths:
            op.campaign_operation.update_mask.paths.extend(paths)
            ops.append(op)
        if daily_budget is not None:
            op = client.get_type("MutateOperation")
            budget = op.campaign_budget_operation.update
            budget.resource_name = budget_rn
            budget.amount_micros = _micros(daily_budget)
            op.campaign_budget_operation.update_mask.paths.append("amount_micros")
            ops.append(op)
        return ops

    change_items = _items(
        "REMOVE" if status == StatusOrRemove.REMOVED else "UPDATE",
        "Campaign",
        f"{row.campaign.name} ({camp_id})",
        {
            "Status": status.value if status else None,
            "Name": name,
            "Daily budget": _money(_micros(daily_budget)),
            "Campaigns sharing this budget": (
                row.campaign_budget.reference_count if daily_budget is not None else None
            ),
            "End date": end_date,
        },
        {
            "Status": row.campaign.status.name,
            "Name": row.campaign.name,
            "Daily budget": _money(row.campaign_budget.amount_micros),
            "End date": row.campaign.end_date_time or None,
        },
    )
    return _run(
        tool="update_campaign",
        customer_id=cid,
        params={
            "campaign_id": camp_id,
            "status": status.value if status else None,
            "name": name,
            "daily_budget": daily_budget,
            "end_date": end_date,
        },
        build_ops=build,
        change_items=change_items,
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Campaign updated:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def create_ad_group(
    customer_id: str | int,
    campaign_id: str,
    ad_group_name: str,
    cpc_bid: float | None = None,
    status: Status = Status.ENABLED,
    keywords: list[Keyword] | None = None,
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
    final_url: str | None = None,
    path1: str | None = None,
    path2: str | None = None,
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Creates a Search ad group in an existing campaign, optionally with keywords and a responsive search ad.

    Args:
        customer_id: Account ID.
        campaign_id: campaign.id of a Search campaign.
        ad_group_name: Unique name within the campaign.
        cpc_bid: Default max CPC (used by MANUAL_CPC campaigns).
        status: ENABLED (default) or PAUSED. In an enabled campaign, ENABLED starts serving.
        keywords: [{text, match_type, cpc_bid?}].
        headlines / descriptions / final_url / path1 / path2: Creates one responsive search ad
            when headlines, descriptions and final_url are all given.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    camp_id = utils.extract_id(str(campaign_id))
    keywords = keywords or []
    with_ad = bool(headlines or descriptions or final_url)
    if with_ad:
        if not (headlines and descriptions and final_url):
            raise ToolError("Error: an ad needs headlines, descriptions and final_url.")
        _check_rsa(headlines, descriptions, path1, path2)
    ad_group_rn = f"customers/{cid}/adGroups/-1"

    def build(client) -> list:
        op = client.get_type("MutateOperation")
        ag = op.ad_group_operation.create
        ag.resource_name = ad_group_rn
        ag.name = ad_group_name
        ag.campaign = f"customers/{cid}/campaigns/{camp_id}"
        ag.status = getattr(client.enums.AdGroupStatusEnum, status.value)
        ag.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
        if cpc_bid is not None:
            ag.cpc_bid_micros = _micros(cpc_bid)
        ops = [op]
        ops += [_keyword_op(client, ad_group_rn, kw, "ENABLED") for kw in keywords]
        if with_ad:
            ops.append(_rsa_op(client, ad_group_rn, headlines, descriptions, final_url, path1, path2, "ENABLED"))
        return ops

    change_items = _items(
        "CREATE",
        "Ad group",
        ad_group_name,
        {
            "Campaign ID": camp_id,
            "Status": status.value,
            "Default CPC": _money(_micros(cpc_bid)),
            "Keywords": [f"{k.text} [{k.match_type.value}]" for k in keywords] or None,
            "Ad headlines": headlines,
            "Ad descriptions": descriptions,
            "Final URL": final_url,
        },
    )
    return _run(
        tool="create_ad_group",
        customer_id=cid,
        params={
            "campaign_id": camp_id,
            "ad_group_name": ad_group_name,
            "cpc_bid": cpc_bid,
            "status": status.value,
            "keywords": [k.model_dump(mode="json") for k in keywords],
            "headlines": headlines,
            "descriptions": descriptions,
            "final_url": final_url,
            "path1": path1,
            "path2": path2,
        },
        build_ops=build,
        change_items=change_items,
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Ad group created:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def update_ad_group(
    customer_id: str | int,
    ad_group_id: str,
    status: StatusOrRemove | None = None,
    name: str | None = None,
    cpc_bid: float | None = None,
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Enables, pauses or removes an ad group, renames it, or changes its default max CPC.

    Args:
        customer_id: Account ID.
        ad_group_id: ad_group.id.
        status: ENABLED, PAUSED or REMOVED (permanent).
        name: New name.
        cpc_bid: New default max CPC in the account currency.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    ag_id = utils.extract_id(str(ad_group_id))
    if status is None and name is None and cpc_bid is None:
        raise ToolError("Error: give at least one of status, name, cpc_bid.")
    client = utils.get_googleads_client(login_customer_id=login_customer_id)
    row = _query_one(
        client,
        cid,
        "SELECT ad_group.name, ad_group.status, ad_group.cpc_bid_micros, campaign.name "
        f"FROM ad_group WHERE ad_group.id = {int(ag_id)}",
    )
    if row is None:
        raise ToolError(f"Error: ad group {ag_id} not found in account {cid}.")
    rn = f"customers/{cid}/adGroups/{ag_id}"

    def build(client) -> list:
        op = client.get_type("MutateOperation")
        if status == StatusOrRemove.REMOVED:
            op.ad_group_operation.remove = rn
            return [op]
        ag = op.ad_group_operation.update
        ag.resource_name = rn
        paths = []
        if status is not None:
            ag.status = getattr(client.enums.AdGroupStatusEnum, status.value)
            paths.append("status")
        if name is not None:
            ag.name = name
            paths.append("name")
        if cpc_bid is not None:
            ag.cpc_bid_micros = _micros(cpc_bid)
            paths.append("cpc_bid_micros")
        op.ad_group_operation.update_mask.paths.extend(paths)
        return [op]

    change_items = _items(
        "REMOVE" if status == StatusOrRemove.REMOVED else "UPDATE",
        "Ad group",
        f"{row.ad_group.name} ({ag_id}) — campaign {row.campaign.name}",
        {"Status": status.value if status else None, "Name": name, "Default CPC": _money(_micros(cpc_bid))},
        {
            "Status": row.ad_group.status.name,
            "Name": row.ad_group.name,
            "Default CPC": _money(row.ad_group.cpc_bid_micros),
        },
    )
    return _run(
        tool="update_ad_group",
        customer_id=cid,
        params={"ad_group_id": ag_id, "status": status.value if status else None, "name": name, "cpc_bid": cpc_bid},
        build_ops=build,
        change_items=change_items,
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Ad group updated:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def create_responsive_search_ad(
    customer_id: str | int,
    ad_group_id: str,
    headlines: list[str],
    descriptions: list[str],
    final_url: str,
    path1: str | None = None,
    path2: str | None = None,
    status: Status = Status.ENABLED,
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Creates a responsive search ad (RSA) in an existing ad group.

    Google combines the headlines and descriptions automatically. Ads go through
    Google's policy review before serving.

    Args:
        customer_id: Account ID.
        ad_group_id: ad_group.id.
        headlines: 3-15 headlines, max 30 characters each.
        descriptions: 2-4 descriptions, max 90 characters each.
        final_url: Landing page URL.
        path1 / path2: Optional display URL paths, max 15 characters each.
        status: ENABLED (default) or PAUSED.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    ag_id = utils.extract_id(str(ad_group_id))
    _check_rsa(headlines, descriptions, path1, path2)
    rn = f"customers/{cid}/adGroups/{ag_id}"
    change_items = _items(
        "CREATE",
        "Responsive search ad",
        f"ad group {ag_id}",
        {
            "Status": status.value,
            "Headlines": headlines,
            "Descriptions": descriptions,
            "Final URL": final_url,
            "Path": "/".join(p for p in (path1, path2) if p) or None,
        },
    )
    return _run(
        tool="create_responsive_search_ad",
        customer_id=cid,
        params={
            "ad_group_id": ag_id,
            "headlines": headlines,
            "descriptions": descriptions,
            "final_url": final_url,
            "path1": path1,
            "path2": path2,
            "status": status.value,
        },
        build_ops=lambda client: [
            _rsa_op(client, rn, headlines, descriptions, final_url, path1, path2, status.value)
        ],
        change_items=change_items,
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Ad created:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def update_ad_status(
    customer_id: str | int,
    ad_group_id: str,
    ad_id: str,
    status: StatusOrRemove,
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Enables, pauses or removes an ad. Ad text can't be edited in Google Ads: to change
    copy, create a new ad and pause or remove the old one.

    Args:
        customer_id: Account ID.
        ad_group_id: ad_group.id.
        ad_id: ad_group_ad.ad.id.
        status: ENABLED, PAUSED or REMOVED (permanent).
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    ag_id = utils.extract_id(str(ad_group_id))
    a_id = utils.extract_id(str(ad_id))
    rn = f"customers/{cid}/adGroupAds/{ag_id}~{a_id}"

    def build(client) -> list:
        op = client.get_type("MutateOperation")
        if status == StatusOrRemove.REMOVED:
            op.ad_group_ad_operation.remove = rn
        else:
            aga = op.ad_group_ad_operation.update
            aga.resource_name = rn
            aga.status = getattr(client.enums.AdGroupAdStatusEnum, status.value)
            op.ad_group_ad_operation.update_mask.paths.append("status")
        return [op]

    return _run(
        tool="update_ad_status",
        customer_id=cid,
        params={"ad_group_id": ag_id, "ad_id": a_id, "status": status.value},
        build_ops=build,
        change_items=_items(
            "REMOVE" if status == StatusOrRemove.REMOVED else "UPDATE",
            "Ad",
            f"ad {a_id} in ad group {ag_id}",
            {"Status": status.value},
        ),
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Ad updated:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def add_keywords(
    customer_id: str | int,
    ad_group_id: str,
    keywords: list[Keyword],
    status: Status = Status.ENABLED,
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Adds keywords to an ad group.

    Match types: EXACT ([keyword]) shows for searches with the same meaning;
    PHRASE ("keyword") for searches that include its meaning; BROAD for related searches.

    Args:
        customer_id: Account ID.
        ad_group_id: ad_group.id.
        keywords: [{text, match_type: EXACT|PHRASE|BROAD, cpc_bid?}].
        status: ENABLED (default) or PAUSED.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    ag_id = utils.extract_id(str(ad_group_id))
    if not keywords:
        raise ToolError("Error: give at least one keyword.")
    rn = f"customers/{cid}/adGroups/{ag_id}"
    return _run(
        tool="add_keywords",
        customer_id=cid,
        params={
            "ad_group_id": ag_id,
            "keywords": [k.model_dump(mode="json") for k in keywords],
            "status": status.value,
        },
        build_ops=lambda client: [_keyword_op(client, rn, kw, status.value) for kw in keywords],
        change_items=_items(
            "CREATE",
            "Keywords",
            f"ad group {ag_id}",
            {
                "Status": status.value,
                "Keywords": [
                    f"{k.text} [{k.match_type.value}]" + (f" CPC {k.cpc_bid:.2f}" if k.cpc_bid else "")
                    for k in keywords
                ],
            },
        ),
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Keywords added:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def update_keywords(
    customer_id: str | int,
    ad_group_id: str,
    updates: list[KeywordUpdate],
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Pauses, enables, removes (deletes) keywords or changes their max CPC.

    Find criterion IDs with `search` on resource keyword_view or ad_group_criterion
    (field ad_group_criterion.criterion_id). Keyword text and match type can't be
    edited: remove the keyword and add a new one.

    Args:
        customer_id: Account ID.
        ad_group_id: ad_group.id that owns the keywords.
        updates: [{criterion_id, status?: ENABLED|PAUSED|REMOVED, cpc_bid?}].
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    ag_id = utils.extract_id(str(ad_group_id))
    if not updates:
        raise ToolError("Error: give at least one update.")
    client = utils.get_googleads_client(login_customer_id=login_customer_id)
    service = utils.get_googleads_service_from_client(client, "GoogleAdsService")
    ids = ", ".join(str(int(u.criterion_id)) for u in updates)
    current = {
        str(r.ad_group_criterion.criterion_id): r
        for r in service.search(
            customer_id=cid,
            query=(
                "SELECT ad_group_criterion.criterion_id, ad_group_criterion.keyword.text, "
                "ad_group_criterion.keyword.match_type, ad_group_criterion.status, "
                "ad_group_criterion.cpc_bid_micros FROM ad_group_criterion "
                f"WHERE ad_group.id = {int(ag_id)} AND ad_group_criterion.criterion_id IN ({ids})"
            ),
        )
    }
    missing = [u.criterion_id for u in updates if str(int(u.criterion_id)) not in current]
    if missing:
        raise ToolError(f"Error: keywords not found in ad group {ag_id}: {missing}")

    def build(client) -> list:
        ops = []
        for u in updates:
            rn = f"customers/{cid}/adGroupCriteria/{ag_id}~{int(u.criterion_id)}"
            op = client.get_type("MutateOperation")
            if u.status == StatusOrRemove.REMOVED:
                op.ad_group_criterion_operation.remove = rn
            else:
                crit = op.ad_group_criterion_operation.update
                crit.resource_name = rn
                paths = []
                if u.status is not None:
                    crit.status = getattr(client.enums.AdGroupCriterionStatusEnum, u.status.value)
                    paths.append("status")
                if u.cpc_bid is not None:
                    crit.cpc_bid_micros = _micros(u.cpc_bid)
                    paths.append("cpc_bid_micros")
                if not paths:
                    raise ToolError(f"Error: nothing to change for keyword {u.criterion_id}.")
                op.ad_group_criterion_operation.update_mask.paths.extend(paths)
            ops.append(op)
        return ops

    change_items = []
    for u in updates:
        r = current[str(int(u.criterion_id))].ad_group_criterion
        change_items += _items(
            "REMOVE" if u.status == StatusOrRemove.REMOVED else "UPDATE",
            "Keyword",
            f"{r.keyword.text} [{r.keyword.match_type.name}] ({u.criterion_id})",
            {"Status": u.status.value if u.status else None, "Max CPC": _money(_micros(u.cpc_bid))},
            {"Status": r.status.name, "Max CPC": _money(r.cpc_bid_micros) if r.cpc_bid_micros else None},
        )
    return _run(
        tool="update_keywords",
        customer_id=cid,
        params={"ad_group_id": ag_id, "updates": [u.model_dump(mode="json") for u in updates]},
        build_ops=build,
        change_items=change_items,
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Keywords updated:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def add_negative_keywords(
    customer_id: str | int,
    level: NegativeLevel,
    parent_id: str,
    keywords: list[NegativeKeyword],
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Adds negative keywords to a campaign or an ad group, so ads don't show for those searches.

    Args:
        customer_id: Account ID.
        level: CAMPAIGN or AD_GROUP.
        parent_id: campaign.id (level CAMPAIGN) or ad_group.id (level AD_GROUP).
        keywords: [{text, match_type: EXACT|PHRASE|BROAD}].
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    pid = utils.extract_id(str(parent_id))
    if not keywords:
        raise ToolError("Error: give at least one negative keyword.")
    parent_rn = (
        f"customers/{cid}/campaigns/{pid}"
        if level == NegativeLevel.CAMPAIGN
        else f"customers/{cid}/adGroups/{pid}"
    )
    return _run(
        tool="add_negative_keywords",
        customer_id=cid,
        params={
            "level": level.value,
            "parent_id": pid,
            "keywords": [k.model_dump(mode="json") for k in keywords],
        },
        build_ops=lambda client: [_negative_op(client, level, parent_rn, k) for k in keywords],
        change_items=_items(
            "CREATE",
            f"Negative keywords ({level.value.lower()})",
            f"{level.value.lower()} {pid}",
            {"Negatives": [f"{k.text} [{k.match_type.value}]" for k in keywords]},
        ),
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Negative keywords added:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def remove_negative_keywords(
    customer_id: str | int,
    level: NegativeLevel,
    parent_id: str,
    criterion_ids: list[str],
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Removes negative keywords from a campaign or an ad group.

    Find criterion IDs with `search` on campaign_criterion (campaign.id, campaign_criterion.criterion_id,
    campaign_criterion.keyword.text, campaign_criterion.negative) or ad_group_criterion.

    Args:
        customer_id: Account ID.
        level: CAMPAIGN or AD_GROUP.
        parent_id: campaign.id or ad_group.id.
        criterion_ids: Criterion IDs of the negatives to remove.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    pid = utils.extract_id(str(parent_id))
    if not criterion_ids:
        raise ToolError("Error: give at least one criterion_id.")
    prefix = "campaignCriteria" if level == NegativeLevel.CAMPAIGN else "adGroupCriteria"

    def build(client) -> list:
        ops = []
        for crit_id in criterion_ids:
            op = client.get_type("MutateOperation")
            rn = f"customers/{cid}/{prefix}/{pid}~{int(utils.extract_id(str(crit_id)))}"
            if level == NegativeLevel.CAMPAIGN:
                op.campaign_criterion_operation.remove = rn
            else:
                op.ad_group_criterion_operation.remove = rn
            ops.append(op)
        return ops

    return _run(
        tool="remove_negative_keywords",
        customer_id=cid,
        params={"level": level.value, "parent_id": pid, "criterion_ids": [str(c) for c in criterion_ids]},
        build_ops=build,
        change_items=_items(
            "REMOVE",
            f"Negative keywords ({level.value.lower()})",
            f"{level.value.lower()} {pid}",
            {"Criterion IDs": [str(c) for c in criterion_ids]},
        ),
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Negative keywords removed:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def link_campaign_assets(
    customer_id: str | int,
    campaign_id: str,
    asset_ids: list[str],
    field_type: AssetFieldType,
    remove: bool = False,
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Links (or unlinks) existing assets to a campaign, e.g. sitelinks, callouts or structured snippets
    created with `create_asset`. Assets only show in ads after being linked.

    Args:
        customer_id: Account ID.
        campaign_id: campaign.id.
        asset_ids: asset.id values.
        field_type: SITELINK, CALLOUT, STRUCTURED_SNIPPET, CALL, PROMOTION or PRICE.
        remove: False (default) links; True unlinks.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    camp_id = utils.extract_id(str(campaign_id))
    ids = [utils.extract_id(str(a)) for a in asset_ids]
    if not ids:
        raise ToolError("Error: give at least one asset_id.")

    def build(client) -> list:
        ops = []
        for a in ids:
            op = client.get_type("MutateOperation")
            if remove:
                op.campaign_asset_operation.remove = (
                    f"customers/{cid}/campaignAssets/{camp_id}~{a}~{field_type.value}"
                )
            else:
                ca = op.campaign_asset_operation.create
                ca.campaign = f"customers/{cid}/campaigns/{camp_id}"
                ca.asset = f"customers/{cid}/assets/{a}"
                ca.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type.value)
            ops.append(op)
        return ops

    return _run(
        tool="link_campaign_assets",
        customer_id=cid,
        params={"campaign_id": camp_id, "asset_ids": ids, "field_type": field_type.value, "remove": remove},
        build_ops=build,
        change_items=_items(
            "REMOVE" if remove else "CREATE",
            f"Campaign asset link ({field_type.value})",
            f"campaign {camp_id}",
            {"Asset IDs": ids},
        ),
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Campaign assets updated:",
    )


class ExclusionPeriod(BaseModel):
    name: str = Field(description="Short name, e.g. 'Tag duplicada 12/out'.")
    start_date: str = Field(description="First excluded day, 'YYYY-MM-DD'.")
    end_date: str = Field(description="Last excluded day (inclusive), 'YYYY-MM-DD'.")
    campaign_ids: list[str] = Field(
        description="Campaigns affected (campaign.id). Only these campaigns ignore the period."
    )
    description: str | None = None


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def create_bidding_data_exclusions(
    customer_id: str | int,
    periods: list[ExclusionPeriod],
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Creates bidding data exclusions: Smart Bidding ignores conversion data from the given
    periods and campaigns (e.g. days when a conversion tag fired duplicates or broke).

    Reports are not changed; only automated bidding (Maximize conversions, target CPA,
    target ROAS, Maximize conversion value) stops learning from those days. Each period
    covers whole days, from 00:00:00 of start_date to 23:59:59 of end_date.

    Args:
        customer_id: Account ID.
        periods: [{name, start_date, end_date, campaign_ids, description?}].
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    if not periods:
        raise ToolError("Error: give at least one period.")
    for p in periods:
        if p.end_date < p.start_date:
            raise ToolError(f"Error: end_date before start_date in '{p.name}'.")
        if not p.campaign_ids:
            raise ToolError(f"Error: '{p.name}' needs at least one campaign_id.")

    def build(client) -> list:
        ops = []
        for p in periods:
            op = client.get_type("MutateOperation")
            ex = op.bidding_data_exclusion_operation.create
            ex.name = p.name
            if p.description:
                ex.description = p.description
            ex.scope = client.enums.SeasonalityEventScopeEnum.CAMPAIGN
            ex.start_date_time = f"{p.start_date} 00:00:00"
            ex.end_date_time = f"{p.end_date} 23:59:59"
            for c in p.campaign_ids:
                ex.campaigns.append(f"customers/{cid}/campaigns/{utils.extract_id(str(c))}")
            ops.append(op)
        return ops

    change_items = []
    for p in periods:
        change_items += _items(
            "CREATE",
            "Bidding data exclusion",
            p.name,
            {
                "Period": f"{p.start_date} 00:00 → {p.end_date} 23:59",
                "Campaign IDs": [utils.extract_id(str(c)) for c in p.campaign_ids],
                "Description": p.description,
            },
        )
    return _run(
        tool="create_bidding_data_exclusions",
        customer_id=cid,
        params={"periods": [p.model_dump(mode="json") for p in periods]},
        build_ops=build,
        change_items=change_items,
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Data exclusions created:",
    )


@management_mcp.tool(annotations=_WRITE)
@_confirm_doc
def remove_bidding_data_exclusions(
    customer_id: str | int,
    data_exclusion_ids: list[str],
    login_customer_id: str | int | None = None,
    validate_only: bool = True,
    checksum: str | None = None,
) -> str:
    """Removes bidding data exclusions. Find IDs with `search` on resource
    bidding_data_exclusion (field bidding_data_exclusion.data_exclusion_id).

    Args:
        customer_id: Account ID.
        data_exclusion_ids: bidding_data_exclusion.data_exclusion_id values.
        login_customer_id: Optional manager account ID.
    """
    cid = _cid(customer_id)
    ids = [utils.extract_id(str(i)) for i in data_exclusion_ids]
    if not ids:
        raise ToolError("Error: give at least one data_exclusion_id.")

    def build(client) -> list:
        ops = []
        for i in ids:
            op = client.get_type("MutateOperation")
            op.bidding_data_exclusion_operation.remove = f"customers/{cid}/biddingDataExclusions/{i}"
            ops.append(op)
        return ops

    return _run(
        tool="remove_bidding_data_exclusions",
        customer_id=cid,
        params={"data_exclusion_ids": ids},
        build_ops=build,
        change_items=_items("REMOVE", "Bidding data exclusions", ", ".join(ids), {"IDs": ids}),
        validate_only=validate_only,
        checksum=checksum,
        login_customer_id=login_customer_id,
        success="Data exclusions removed:",
    )
