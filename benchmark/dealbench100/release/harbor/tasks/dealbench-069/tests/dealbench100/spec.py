"""Synthetic deal worlds and task contracts for DealBench-100.

The benchmark is independently authored. Public APEX and Archipelago materials
informed the release shape (worlds, tasks, assets, trajectories, snapshots and
criterion-level grading); no gated APEX task or world data is copied here.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

BENCHMARK_NAME = "DealBench-100"
BENCHMARK_VERSION = "1.1.0"
WORLD_ID = "atlas-deal-team-v1.1"
METRIC = "DealScore"
SPONSOR_RETURN_FLOOR = Decimal("0.20")


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _q(value: Decimal, places: str = "0.01") -> float:
    return float(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


WORLDS: tuple[dict[str, Any], ...] = (
    {
        "project_code": "PROJECT-LANTERN",
        "company": "LumaWorks Lighting",
        "industry": "Commercial lighting",
        "deal_type": "sell-side auction",
        "revenue": 438.0,
        "ebitda_margin": 0.184,
        "allowed_addbacks": 7.6,
        "disallowed_addbacks": 2.1,
        "debt": 126.0,
        "cash": 18.5,
        "shares": 42.0,
        "share_price": 7.80,
        "growth": 0.072,
        "tax_rate": 0.25,
        "capex_pct": 0.031,
        "nwc_pct": 0.018,
        "comp_multiple": 9.4,
        "precedent_multiple": 10.2,
        "wacc": 0.101,
        "terminal_growth": 0.025,
        "entry_multiple": 9.6,
        "exit_multiple": 9.2,
        "leverage": 4.8,
        "buyer_net_income": 121.0,
        "buyer_shares": 83.0,
        "buyer_share_price": 24.50,
        "offer_premium": 0.18,
        "cash_pct": 0.55,
        "synergies": 13.0,
        "critical_open": False,
        "approval_status": "approved",
    },
    {
        "project_code": "PROJECT-COPPER",
        "company": "Northstar Robotics",
        "industry": "Industrial automation",
        "deal_type": "buy-side acquisition",
        "revenue": 612.0,
        "ebitda_margin": 0.216,
        "allowed_addbacks": 9.2,
        "disallowed_addbacks": 3.8,
        "debt": 205.0,
        "cash": 31.0,
        "shares": 55.0,
        "share_price": 12.40,
        "growth": 0.094,
        "tax_rate": 0.24,
        "capex_pct": 0.041,
        "nwc_pct": 0.021,
        "comp_multiple": 11.1,
        "precedent_multiple": 12.0,
        "wacc": 0.108,
        "terminal_growth": 0.027,
        "entry_multiple": 10.8,
        "exit_multiple": 10.3,
        "leverage": 5.2,
        "buyer_net_income": 208.0,
        "buyer_shares": 118.0,
        "buyer_share_price": 31.20,
        "offer_premium": 0.22,
        "cash_pct": 0.45,
        "synergies": 22.0,
        "critical_open": True,
        "approval_status": "conditional",
    },
    {
        "project_code": "PROJECT-KEEL",
        "company": "Meridian Components",
        "industry": "Aerospace components",
        "deal_type": "carve-out",
        "revenue": 287.0,
        "ebitda_margin": 0.162,
        "allowed_addbacks": 5.8,
        "disallowed_addbacks": 1.4,
        "debt": 74.0,
        "cash": 11.0,
        "shares": 34.0,
        "share_price": 6.90,
        "growth": 0.058,
        "tax_rate": 0.26,
        "capex_pct": 0.036,
        "nwc_pct": 0.024,
        "comp_multiple": 8.7,
        "precedent_multiple": 9.5,
        "wacc": 0.113,
        "terminal_growth": 0.021,
        "entry_multiple": 8.9,
        "exit_multiple": 8.6,
        "leverage": 4.2,
        "buyer_net_income": 96.0,
        "buyer_shares": 71.0,
        "buyer_share_price": 19.80,
        "offer_premium": 0.16,
        "cash_pct": 0.65,
        "synergies": 8.0,
        "critical_open": False,
        "approval_status": "approved",
    },
    {
        "project_code": "PROJECT-ORBIT",
        "company": "BluePeak Software",
        "industry": "Vertical SaaS",
        "deal_type": "sell-side auction",
        "revenue": 354.0,
        "ebitda_margin": 0.238,
        "allowed_addbacks": 11.0,
        "disallowed_addbacks": 4.4,
        "debt": 88.0,
        "cash": 46.0,
        "shares": 61.0,
        "share_price": 15.60,
        "growth": 0.132,
        "tax_rate": 0.23,
        "capex_pct": 0.019,
        "nwc_pct": 0.012,
        "comp_multiple": 13.8,
        "precedent_multiple": 14.6,
        "wacc": 0.112,
        "terminal_growth": 0.031,
        "entry_multiple": 13.2,
        "exit_multiple": 12.5,
        "leverage": 4.6,
        "buyer_net_income": 174.0,
        "buyer_shares": 101.0,
        "buyer_share_price": 28.10,
        "offer_premium": 0.25,
        "cash_pct": 0.35,
        "synergies": 19.0,
        "critical_open": True,
        "approval_status": "pending",
    },
    {
        "project_code": "PROJECT-CANOPY",
        "company": "Verdant Packaging",
        "industry": "Sustainable packaging",
        "deal_type": "sponsor recapitalization",
        "revenue": 521.0,
        "ebitda_margin": 0.171,
        "allowed_addbacks": 6.9,
        "disallowed_addbacks": 2.6,
        "debt": 151.0,
        "cash": 20.0,
        "shares": 49.0,
        "share_price": 9.30,
        "growth": 0.064,
        "tax_rate": 0.25,
        "capex_pct": 0.044,
        "nwc_pct": 0.023,
        "comp_multiple": 8.9,
        "precedent_multiple": 9.7,
        "wacc": 0.105,
        "terminal_growth": 0.024,
        "entry_multiple": 9.1,
        "exit_multiple": 8.8,
        "leverage": 5.0,
        "buyer_net_income": 142.0,
        "buyer_shares": 92.0,
        "buyer_share_price": 22.40,
        "offer_premium": 0.19,
        "cash_pct": 0.60,
        "synergies": 14.0,
        "critical_open": False,
        "approval_status": "approved",
    },
    {
        "project_code": "PROJECT-TIDELINE",
        "company": "Atlas Freight Systems",
        "industry": "Logistics technology",
        "deal_type": "leveraged buyout",
        "revenue": 746.0,
        "ebitda_margin": 0.143,
        "allowed_addbacks": 13.4,
        "disallowed_addbacks": 5.2,
        "debt": 277.0,
        "cash": 37.0,
        "shares": 68.0,
        "share_price": 11.70,
        "growth": 0.051,
        "tax_rate": 0.27,
        "capex_pct": 0.047,
        "nwc_pct": 0.026,
        "comp_multiple": 8.2,
        "precedent_multiple": 8.8,
        "wacc": 0.109,
        "terminal_growth": 0.020,
        "entry_multiple": 8.4,
        "exit_multiple": 8.0,
        "leverage": 5.4,
        "buyer_net_income": 238.0,
        "buyer_shares": 144.0,
        "buyer_share_price": 26.80,
        "offer_premium": 0.17,
        "cash_pct": 0.70,
        "synergies": 17.0,
        "critical_open": True,
        "approval_status": "conditional",
    },
    {
        "project_code": "PROJECT-EMBER",
        "company": "Solstice Materials",
        "industry": "Specialty chemicals",
        "deal_type": "strategic combination",
        "revenue": 683.0,
        "ebitda_margin": 0.197,
        "allowed_addbacks": 8.7,
        "disallowed_addbacks": 3.1,
        "debt": 232.0,
        "cash": 29.0,
        "shares": 58.0,
        "share_price": 13.20,
        "growth": 0.067,
        "tax_rate": 0.25,
        "capex_pct": 0.052,
        "nwc_pct": 0.028,
        "comp_multiple": 9.7,
        "precedent_multiple": 10.4,
        "wacc": 0.104,
        "terminal_growth": 0.023,
        "entry_multiple": 9.8,
        "exit_multiple": 9.3,
        "leverage": 4.9,
        "buyer_net_income": 265.0,
        "buyer_shares": 151.0,
        "buyer_share_price": 29.60,
        "offer_premium": 0.21,
        "cash_pct": 0.50,
        "synergies": 26.0,
        "critical_open": False,
        "approval_status": "approved",
    },
    {
        "project_code": "PROJECT-SIGNAL",
        "company": "Harbor Health Devices",
        "industry": "Medical devices",
        "deal_type": "dual-track sale",
        "revenue": 405.0,
        "ebitda_margin": 0.205,
        "allowed_addbacks": 7.9,
        "disallowed_addbacks": 3.6,
        "debt": 119.0,
        "cash": 24.0,
        "shares": 46.0,
        "share_price": 10.90,
        "growth": 0.088,
        "tax_rate": 0.24,
        "capex_pct": 0.033,
        "nwc_pct": 0.019,
        "comp_multiple": 10.8,
        "precedent_multiple": 11.7,
        "wacc": 0.107,
        "terminal_growth": 0.026,
        "entry_multiple": 10.6,
        "exit_multiple": 10.1,
        "leverage": 4.7,
        "buyer_net_income": 186.0,
        "buyer_shares": 109.0,
        "buyer_share_price": 27.30,
        "offer_premium": 0.23,
        "cash_pct": 0.40,
        "synergies": 16.0,
        "critical_open": True,
        "approval_status": "pending",
    },
    {
        "project_code": "PROJECT-RIDGE",
        "company": "PeakGrid Energy Services",
        "industry": "Energy services",
        "deal_type": "minority investment",
        "revenue": 571.0,
        "ebitda_margin": 0.156,
        "allowed_addbacks": 10.2,
        "disallowed_addbacks": 4.8,
        "debt": 184.0,
        "cash": 27.0,
        "shares": 53.0,
        "share_price": 8.60,
        "growth": 0.077,
        "tax_rate": 0.26,
        "capex_pct": 0.056,
        "nwc_pct": 0.031,
        "comp_multiple": 8.6,
        "precedent_multiple": 9.3,
        "wacc": 0.116,
        "terminal_growth": 0.022,
        "entry_multiple": 8.8,
        "exit_multiple": 8.4,
        "leverage": 4.5,
        "buyer_net_income": 157.0,
        "buyer_shares": 98.0,
        "buyer_share_price": 21.70,
        "offer_premium": 0.20,
        "cash_pct": 0.55,
        "synergies": 12.0,
        "critical_open": False,
        "approval_status": "approved",
    },
    {
        "project_code": "PROJECT-FOUNDRY",
        "company": "Ironwood Industrial Systems",
        "industry": "Engineered equipment",
        "deal_type": "public merger",
        "revenue": 894.0,
        "ebitda_margin": 0.188,
        "allowed_addbacks": 14.1,
        "disallowed_addbacks": 6.0,
        "debt": 318.0,
        "cash": 43.0,
        "shares": 76.0,
        "share_price": 14.80,
        "growth": 0.061,
        "tax_rate": 0.25,
        "capex_pct": 0.049,
        "nwc_pct": 0.025,
        "comp_multiple": 9.2,
        "precedent_multiple": 10.0,
        "wacc": 0.103,
        "terminal_growth": 0.024,
        "entry_multiple": 9.4,
        "exit_multiple": 9.0,
        "leverage": 5.1,
        "buyer_net_income": 312.0,
        "buyer_shares": 176.0,
        "buyer_share_price": 32.10,
        "offer_premium": 0.24,
        "cash_pct": 0.50,
        "synergies": 31.0,
        "critical_open": True,
        "approval_status": "conditional",
    },
)


FAMILIES: tuple[dict[str, str], ...] = (
    {
        "key": "source_control",
        "label": "Source control and launch readiness",
        "title": "Confirm the operative deal case",
        "request": "The VP needs the operative case locked before the team changes another number. Establish which forecast, QoE bridge, and approval are current; explain what makes the other versions stale; then commit the supported working case and prepare the deal-team handoff for review.",
    },
    {
        "key": "quality_of_earnings",
        "label": "Quality of earnings",
        "title": "Normalize EBITDA from diligence evidence",
        "request": "The diligence lead says the headline EBITDA includes adjustments that may not survive buyer review. Work out the defensible normalized EBITDA and margin from the current evidence, show which add-backs were excluded, update the live model and issue log, and draft the client-team explanation for review.",
    },
    {
        "key": "trading_comps",
        "label": "Trading comparables",
        "title": "Refresh the trading-comps valuation",
        "request": "Markets moved after the last committee deck. Refresh the valuation from the approved peer set and current normalized EBITDA, identify the binding source revision, carry the supported enterprise and equity values into the model and deck, and leave a review-ready note for the VP.",
    },
    {
        "key": "precedent_transactions",
        "label": "Precedent transactions",
        "title": "Refresh precedent-transaction valuation",
        "request": "The client asked whether the transaction range still holds after the latest diligence bridge. Reconcile the approved precedent set with the current operating case, update the valuation outputs and presentation only where supported, and prepare the client answer for review.",
    },
    {
        "key": "discounted_cash_flow",
        "label": "Discounted cash flow",
        "title": "Rebuild the DCF case",
        "request": "The MD wants a defensible DCF before today's valuation review, not the number from last week's draft. Use the current forecast, WACC and terminal-growth authority, calculate the supported range, commit the model revision, reconcile the deck, and prepare the review note with the main sensitivity.",
    },
    {
        "key": "leveraged_buyout",
        "label": "Leveraged buyout",
        "title": "Test sponsor returns and price capacity",
        "request": "A sponsor asked how far it can stretch without falling below the approved return threshold. Reconcile leverage, entry and exit assumptions with the current case, calculate price capacity and returns, commit the best supported scenario, and draft the internal response for review.",
    },
    {
        "key": "merger_model",
        "label": "Merger model",
        "title": "Recalculate accretion and dilution",
        "request": "The merger case changed after financing and synergy comments. Recalculate buyer accretion or dilution and target value using the current cash-stock mix, premium, funding cost and approved synergies; update the model and summary slide, and leave the transaction-team update ready for review.",
    },
    {
        "key": "bid_comparison",
        "label": "Bid comparison and process control",
        "title": "Select the defensible bid path",
        "request": "The board call needs an honest bid comparison, not just the highest headline. Reconcile price, financing certainty, conditions and timing across the current bids, select the best supported path, commit only that recommendation, and prepare the launch-team update for review.",
    },
    {
        "key": "model_deck_consistency",
        "label": "Model-to-deck consistency",
        "title": "Reconcile model and committee deck",
        "request": "Numbers in the committee deck no longer tie to the live model. Find the operative model and source revisions, repair the valuation and return outputs in the controlled deliverable, preserve unrelated slides, and send the checker note for review.",
    },
    {
        "key": "launch_approval",
        "label": "Launch and approval control",
        "title": "Decide whether the process can launch",
        "request": "The deal team wants to launch today. Determine whether current approvals and critical diligence actually permit it, explain the gating item if not, compare launch-now against the approved alternatives, commit the supported plan, and prepare the client-facing update for review.",
    },
)


DECISION_OPTIONS: dict[str, tuple[dict[str, str], ...]] = {
    "source_control": (
        {"id": "lock_current_case", "label": "Lock the current-authority case"},
        {"id": "reopen_prior_case", "label": "Reopen the prior working case"},
        {"id": "pause_for_source_reconciliation", "label": "Pause for source reconciliation"},
    ),
    "quality_of_earnings": (
        {"id": "commit_normalized_current_case", "label": "Commit defensible normalized earnings"},
        {"id": "retain_reported_ebitda", "label": "Retain reported EBITDA"},
        {"id": "accept_all_management_addbacks", "label": "Accept all management add-backs"},
    ),
    "trading_comps": (
        {"id": "refresh_at_approved_peer_median", "label": "Refresh at the approved peer median"},
        {"id": "retain_prior_trading_range", "label": "Retain the prior trading range"},
        {"id": "use_highest_peer_multiple", "label": "Use the highest peer multiple"},
    ),
    "precedent_transactions": (
        {"id": "refresh_at_approved_precedent_median", "label": "Refresh at the approved precedent median"},
        {"id": "retain_prior_precedent_range", "label": "Retain the prior precedent range"},
        {"id": "use_highest_precedent_multiple", "label": "Use the highest precedent multiple"},
    ),
    "discounted_cash_flow": (
        {"id": "commit_current_dcf_case", "label": "Commit the current DCF case"},
        {"id": "retain_prior_dcf_case", "label": "Retain the prior DCF case"},
        {"id": "use_management_upside_case", "label": "Use the management upside case"},
    ),
    "leveraged_buyout": (
        {"id": "cap_price_at_return_floor", "label": "Cap price at the approved return floor"},
        {"id": "stretch_to_requested_price", "label": "Stretch to the sponsor's requested price"},
        {"id": "hold_sponsor_response", "label": "Hold the sponsor response"},
    ),
    "merger_model": (
        {"id": "commit_current_cash_stock_mix", "label": "Commit the current cash-stock mix"},
        {"id": "use_all_cash_case", "label": "Use the all-cash case"},
        {"id": "use_unapproved_synergy_case", "label": "Use the unapproved synergy case"},
    ),
    "bid_comparison": (
        {"id": "advance_bid_a", "label": "Advance Bid A"},
        {"id": "advance_bid_b", "label": "Advance Bid B"},
        {"id": "advance_bid_c", "label": "Advance Bid C"},
    ),
    "model_deck_consistency": (
        {"id": "reconcile_deck_to_live_model", "label": "Reconcile the deck to the live model"},
        {"id": "retain_current_deck_values", "label": "Retain the current deck values"},
        {"id": "replace_the_full_deck", "label": "Replace the full committee deck"},
    ),
    "launch_approval": (
        {"id": "launch_under_approved_plan", "label": "Launch under the approved plan"},
        {"id": "hold_and_clear_gate", "label": "Hold launch and clear the gating item"},
        {"id": "escalate_without_decision", "label": "Escalate without a launch decision"},
    ),
}


METRIC_DESCRIPTIONS: dict[str, tuple[str, str, str]] = {
    "source_control": (
        "Normalized EBITDA from the operative case, USD millions.",
        "Normalized EBITDA margin from the operative case, percent.",
        "Forecast growth rate from the operative case, percent.",
    ),
    "quality_of_earnings": (
        "Defensible normalized EBITDA after allowed and disallowed add-backs, USD millions.",
        "Defensible normalized EBITDA margin, percent.",
        "Unsupported add-backs excluded from normalized EBITDA, USD millions.",
    ),
    "trading_comps": (
        "Enterprise value at the median approved trading-comparable multiple, USD millions.",
        "Median approved EV / EBITDA trading multiple, turns.",
        "Normalized EBITDA used in the trading-comps calculation, USD millions.",
    ),
    "precedent_transactions": (
        "Enterprise value at the median approved precedent-transaction multiple, USD millions.",
        "Median approved precedent EV / EBITDA multiple, turns.",
        "Normalized EBITDA used in the precedent calculation, USD millions.",
    ),
    "discounted_cash_flow": (
        "Enterprise value from the current five-year DCF case, USD millions.",
        "WACC used in the current DCF case, percent (for example 10.10, not 0.101).",
        "Terminal growth used in the current DCF case, percent (for example 2.50, not 0.025).",
    ),
    "leveraged_buyout": (
        "Maximum entry enterprise value supported by the current LBO case, USD millions.",
        "Five-year sponsor money-on-invested-capital, turns.",
        "Five-year sponsor internal rate of return, percent.",
    ),
    "merger_model": (
        "Target equity value at the current offer premium, USD millions.",
        "Buyer EPS accretion or dilution, percent (negative means dilution).",
        "Approved run-rate synergies, USD millions.",
    ),
    "bid_comparison": (
        "Headline enterprise value of the recommended bid, USD millions.",
        "Risk-adjusted bid value: headline value times financing certainty less condition cost, USD millions.",
        "Financing certainty of the recommended bid, percent.",
    ),
    "model_deck_consistency": (
        "Midpoint of the current trading-comps and DCF enterprise values, USD millions.",
        "Absolute spread between the trading-comps and DCF enterprise values, USD millions.",
        "Remaining model-to-deck variance after reconciliation, USD millions.",
    ),
    "launch_approval": (
        "Current precedent-transaction enterprise value carried into the launch case, USD millions.",
        "Launch readiness, percent: 100 only when approval is current and no critical gate is open.",
        "Number of open critical launch gates.",
    ),
}


SCORING_CATEGORIES: tuple[dict[str, Any], ...] = (
    {"key": "discovery", "label": "Discovery", "weight": 15},
    {"key": "model_accuracy", "label": "Model accuracy", "weight": 25},
    {"key": "decision", "label": "Decision", "weight": 15},
    {"key": "committed_state", "label": "Committed state", "weight": 20},
    {"key": "deliverable", "label": "Deliverable", "weight": 10},
    {"key": "readback", "label": "Readback", "weight": 10},
    {"key": "containment", "label": "Containment", "weight": 5},
)


def _world_metrics(world: dict[str, Any]) -> dict[str, float]:
    revenue = _d(world["revenue"])
    reported_ebitda = revenue * _d(world["ebitda_margin"])
    adjusted_ebitda = reported_ebitda + _d(world["allowed_addbacks"]) - _d(world["disallowed_addbacks"])
    margin = adjusted_ebitda / revenue
    comp_ev = adjusted_ebitda * _d(world["comp_multiple"])
    precedent_ev = adjusted_ebitda * _d(world["precedent_multiple"])

    fcf = adjusted_ebitda * (Decimal("1") - _d(world["tax_rate"]))
    fcf -= revenue * (_d(world["capex_pct"]) + _d(world["nwc_pct"]))
    pv = Decimal("0")
    grown = fcf
    for year in range(1, 6):
        grown *= Decimal("1") + _d(world["growth"])
        pv += grown / ((Decimal("1") + _d(world["wacc"])) ** year)
    terminal = grown * (Decimal("1") + _d(world["terminal_growth"])) / (
        _d(world["wacc"]) - _d(world["terminal_growth"])
    )
    dcf_ev = pv + terminal / ((Decimal("1") + _d(world["wacc"])) ** 5)

    entry_debt = adjusted_ebitda * _d(world["leverage"])
    exit_ebitda = adjusted_ebitda * ((Decimal("1") + _d(world["growth"])) ** 5)
    exit_ev = exit_ebitda * _d(world["exit_multiple"])
    exit_debt = entry_debt * Decimal("0.45")
    exit_equity = exit_ev - exit_debt
    minimum_moic = (Decimal("1") + SPONSOR_RETURN_FLOOR) ** 5
    entry_equity = exit_equity / minimum_moic
    entry_ev = entry_equity + entry_debt
    moic = exit_equity / entry_equity
    irr = moic ** (Decimal("1") / Decimal("5")) - Decimal("1")

    target_equity = _d(world["shares"]) * _d(world["share_price"]) * (
        Decimal("1") + _d(world["offer_premium"])
    )
    cash_funding = target_equity * _d(world["cash_pct"])
    stock_value = target_equity - cash_funding
    new_shares = stock_value / _d(world["buyer_share_price"])
    target_ni = adjusted_ebitda * Decimal("0.58")
    proforma_ni = (
        _d(world["buyer_net_income"])
        + target_ni
        + _d(world["synergies"]) * (Decimal("1") - _d(world["tax_rate"]))
        - cash_funding * Decimal("0.055") * (Decimal("1") - _d(world["tax_rate"]))
    )
    buyer_eps = _d(world["buyer_net_income"]) / _d(world["buyer_shares"])
    proforma_eps = proforma_ni / (_d(world["buyer_shares"]) + new_shares)
    accretion = proforma_eps / buyer_eps - Decimal("1")

    return {
        "reported_ebitda": _q(reported_ebitda),
        "adjusted_ebitda": _q(adjusted_ebitda),
        "adjusted_margin_pct": _q(margin * 100),
        "comp_ev": _q(comp_ev),
        "precedent_ev": _q(precedent_ev),
        "dcf_ev": _q(dcf_ev),
        "lbo_entry_ev": _q(entry_ev),
        "lbo_moic": _q(moic),
        "lbo_irr_pct": _q(irr * 100),
        "merger_equity_value": _q(target_equity),
        "merger_accretion_pct": _q(accretion * 100),
    }


def _family_outcome(world: dict[str, Any], family: dict[str, str], world_index: int) -> dict[str, Any]:
    metrics = _world_metrics(world)
    category = family["key"]
    net_debt = _d(world["debt"]) - _d(world["cash"])
    source_revision = f"REV-{world_index + 1:02d}-CURRENT"
    model_revision = f"MODEL-{world_index + 1:02d}-{category[:4].upper()}-R3"
    deliverable_revision = f"DECK-{world_index + 1:02d}-{category[:4].upper()}-R2"
    headline = _d(metrics["adjusted_ebitda"])
    primary = _d(metrics["adjusted_margin_pct"])
    secondary = _d(world["growth"]) * 100
    option = "lock_current_case"
    status = "ready_for_review"

    if category == "quality_of_earnings":
        secondary = _d(world["disallowed_addbacks"])
        option = "commit_normalized_current_case"
    elif category == "trading_comps":
        headline = _d(metrics["comp_ev"])
        primary = _d(world["comp_multiple"])
        secondary = _d(metrics["adjusted_ebitda"])
        option = "refresh_at_approved_peer_median"
    elif category == "precedent_transactions":
        headline = _d(metrics["precedent_ev"])
        primary = _d(world["precedent_multiple"])
        secondary = _d(metrics["adjusted_ebitda"])
        option = "refresh_at_approved_precedent_median"
    elif category == "discounted_cash_flow":
        headline = _d(metrics["dcf_ev"])
        primary = _d(world["wacc"]) * 100
        secondary = _d(world["terminal_growth"]) * 100
        option = "commit_current_dcf_case"
    elif category == "leveraged_buyout":
        headline = _d(metrics["lbo_entry_ev"])
        primary = _d(metrics["lbo_moic"])
        secondary = _d(metrics["lbo_irr_pct"])
        option = "cap_price_at_return_floor"
    elif category == "merger_model":
        headline = _d(metrics["merger_equity_value"])
        primary = _d(metrics["merger_accretion_pct"])
        secondary = _d(world["synergies"])
        option = "commit_current_cash_stock_mix"
    elif category == "bid_comparison":
        base = _d(metrics["precedent_ev"])
        bids = (
            ("BID-A", _d(_q(base * Decimal("0.99"))), Decimal("0.98"), Decimal("8")),
            ("BID-B", _d(_q(base * Decimal("1.04"))), Decimal("0.86"), Decimal("22")),
            ("BID-C", _d(_q(base * Decimal("1.01"))), Decimal("0.94"), Decimal("11")),
        )
        ranked = sorted(bids, key=lambda row: row[1] * row[2] - row[3], reverse=True)
        winner = ranked[0]
        headline = winner[1]
        primary = winner[1] * winner[2] - winner[3]
        secondary = winner[2] * 100
        option = f"advance_{winner[0].lower().replace('-', '_')}"
    elif category == "model_deck_consistency":
        headline = (_d(metrics["comp_ev"]) + _d(metrics["dcf_ev"])) / 2
        primary = abs(_d(metrics["comp_ev"]) - _d(metrics["dcf_ev"]))
        secondary = Decimal("0")
        option = "reconcile_deck_to_live_model"
    elif category == "launch_approval":
        blocked = bool(world["critical_open"]) or world["approval_status"] != "approved"
        option = "hold_and_clear_gate" if blocked else "launch_under_approved_plan"
        status = "blocked_pending_gate" if blocked else "approved_to_launch"
        headline = _d(metrics["precedent_ev"])
        primary = Decimal("0") if blocked else Decimal("100")
        secondary = Decimal("1") if world["critical_open"] else Decimal("0")

    equity = headline - net_debt
    per_share = equity / _d(world["shares"])
    return {
        "project_code": world["project_code"],
        "recommended_option": option,
        "headline_value_usd_m": _q(headline),
        "equity_value_usd_m": _q(equity),
        "per_share_value_usd": _q(per_share),
        "primary_metric": _q(primary),
        "secondary_metric": _q(secondary),
        "model_revision": model_revision,
        "deliverable_revision": deliverable_revision,
        "decision_status": status,
        "source_revision": source_revision,
    }


CORE_OUTPUT_FIELDS: tuple[str, ...] = (
    "headline_value_usd_m",
    "equity_value_usd_m",
    "per_share_value_usd",
    "primary_metric",
    "secondary_metric",
)


def _answer_schema(
    family: dict[str, str], expected: dict[str, Any]
) -> dict[str, Any]:
    headline_description, primary_description, secondary_description = (
        METRIC_DESCRIPTIONS[family["key"]]
    )
    options = DECISION_OPTIONS[family["key"]]
    statuses = (
        ["blocked_pending_gate", "approved_to_launch"]
        if family["key"] == "launch_approval"
        else ["ready_for_review"]
    )
    properties: dict[str, Any] = {
        "project_code": {
            "type": "string",
            "const": expected["project_code"],
            "description": "Exact active deal project code.",
        },
        "recommended_option": {
            "type": "string",
            "enum": [option["id"] for option in options],
            "description": "One allowed decision option, selected from evidence rather than list order.",
        },
        "headline_value_usd_m": {
            "type": "number",
            "multipleOf": 0.01,
            "description": headline_description,
        },
        "equity_value_usd_m": {
            "type": "number",
            "multipleOf": 0.01,
            "description": "Headline enterprise value less current net debt, USD millions.",
        },
        "per_share_value_usd": {
            "type": "number",
            "multipleOf": 0.01,
            "description": "Equity value divided by current diluted shares, USD per share.",
        },
        "primary_metric": {
            "type": "number",
            "multipleOf": 0.01,
            "description": primary_description,
        },
        "secondary_metric": {
            "type": "number",
            "multipleOf": 0.01,
            "description": secondary_description,
        },
        "model_revision": {
            "type": "string",
            "description": "Use the next_revision returned by deals.get_model for the active model.",
        },
        "deliverable_revision": {
            "type": "string",
            "description": "Use the next_revision returned by deals.get_deliverable for the controlled deck.",
        },
        "decision_status": {
            "type": "string",
            "enum": statuses,
            "description": "Durable plan status allowed by this workflow.",
        },
        "source_revision": {
            "type": "string",
            "description": "Operative source revision established from current forecast and authority evidence.",
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(expected),
        "properties": properties,
    }


def _controlled_targets(
    task_id: str, world: dict[str, Any]
) -> dict[str, Any]:
    project = world["project_code"]
    return {
        "model": {
            "id": f"MODEL-{project}",
            "next_revision_source": "deals.get_model.next_revision",
            "required_output_keys": list(CORE_OUTPUT_FIELDS),
        },
        "workbook": {
            "id": f"WB-{project}",
            "input_ranges": ["Inputs!A1:H20"],
            "output_range": "Outputs!B2:G2",
            "column_order": ["model_revision", *CORE_OUTPUT_FIELDS],
        },
        "deliverable": {
            "id": f"DECK-{project}",
            "next_revision_source": "deals.get_deliverable.next_revision",
            "status": "draft_for_review",
            "required_value_keys": list(CORE_OUTPUT_FIELDS),
        },
        "plan": {
            "model_id": f"MODEL-{project}",
            "deliverable_id": f"DECK-{project}",
        },
        "communications": {
            "email_recipient": "deal-lead-review@atlas-sim.example",
            "channel": f"deal-{project.lower()}",
            "review_status": "draft_for_review",
            "task_id": task_id,
        },
    }


def _asset_paths(world: dict[str, Any], task_id: str) -> list[str]:
    root = f"assets/{world['project_code'].lower()}"
    names = (
        "01-request-email.eml",
        "02-current-forecast.xlsx",
        "03-prior-forecast.xlsx",
        "04-quality-of-earnings.pdf",
        "05-management-case.csv",
        "06-current-assumptions.json",
        "07-retired-assumptions.json",
        "08-trading-comps.csv",
        "09-precedent-transactions.csv",
        "10-debt-schedule.xlsx",
        "11-bid-letters.pdf",
        "12-diligence-log.xlsx",
        "13-approval-policy.md",
        "14-current-approval.eml",
        "15-retired-approval.eml",
        "16-deal-team-thread.json",
        "17-model-change-log.csv",
        "18-committee-deck-current.pptx",
        "19-committee-deck-prior.pptx",
        "20-client-update-draft.md",
        "21-source-map.yaml",
        "22-data-room-permissions.json",
        "23-audit.log",
        "24-deal-timeline.ics",
    )
    return [f"{root}/{name}" for name in names] + [
        f"assets/tasks/{task_id}/task-brief.md",
        f"assets/tasks/{task_id}/starting-snapshot.json",
    ]


def _investigations(task_id: str, world: dict[str, Any], family: dict[str, str]) -> list[dict[str, Any]]:
    project = world["project_code"]
    category = family["key"]
    channel = f"deal-{project.lower()}"

    def investigation(
        identifier: str,
        description: str,
        tool: str,
        arguments: dict[str, Any],
        *,
        oracle_arguments: dict[str, Any] | None = None,
        result_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requirement: dict[str, Any] = {
            "tool": tool,
            # Only these identity-bearing arguments are graded. Free-text query
            # wording is deliberately absent and therefore semantically free.
            "argument_subset": arguments,
            "oracle_arguments": oracle_arguments or arguments,
        }
        if result_evidence is not None:
            requirement["result_evidence"] = result_evidence
        return {
            "id": identifier,
            "description": description,
            "any_of": [requirement],
        }

    common = [
        investigation(
            "task_contract",
            "read the task-scoped outcome and control contract",
            "benchmark.get_task",
            {"task_id": task_id},
        ),
        investigation(
            "project_record",
            "read the active project master record",
            "deals.get_project",
            {"project_code": project},
        ),
        investigation(
            "data_room_search",
            "search the data room and surface the current forecast record",
            "dealroom.search_files",
            {"project_code": project},
            oracle_arguments={"project_code": project, "query": "management forecast"},
            result_evidence={
                "path": ["files"],
                "contains": {"file_id": f"{project}-FORECAST-CURRENT"},
            },
        ),
        investigation(
            "current_forecast",
            "read the current management forecast",
            "dealroom.get_file",
            {"file_id": f"{project}-FORECAST-CURRENT"},
        ),
        investigation(
            "prior_forecast",
            "read the superseded forecast used for version comparison",
            "dealroom.get_file",
            {"file_id": f"{project}-FORECAST-PRIOR"},
        ),
        investigation(
            "version_history",
            "inspect forecast version history and authority",
            "dealroom.get_version_history",
            {"logical_name": f"{project}-FORECAST"},
            result_evidence={
                "path": ["versions"],
                "contains": {"file_id": f"{project}-FORECAST-CURRENT", "is_current": 1},
            },
        ),
        investigation(
            "request_mail_search",
            "search mail and surface the task request",
            "mail.search_messages",
            {"project_code": project},
            oracle_arguments={"project_code": project, "query": family["label"]},
            result_evidence={
                "path": ["messages"],
                "contains": {"message_id": f"MSG-{task_id}-REQUEST"},
            },
        ),
        investigation(
            "request_mail",
            "read the task request message",
            "mail.get_message",
            {"message_id": f"MSG-{task_id}-REQUEST"},
        ),
        investigation(
            "team_chat_search",
            "search the deal-team channel and surface the task thread",
            "chat.search_messages",
            {"channel": channel},
            oracle_arguments={"channel": channel, "query": "current authority"},
            result_evidence={
                "path": ["messages"],
                "contains": {"thread_id": f"THREAD-{task_id}"},
            },
        ),
        investigation(
            "team_thread",
            "read the deal-team task thread",
            "chat.get_thread",
            {"thread_id": f"THREAD-{task_id}"},
            result_evidence={
                "path": ["messages"],
                "contains": {"thread_id": f"THREAD-{task_id}"},
            },
        ),
        investigation(
            "workbook_index",
            "list the active project's controlled workbook",
            "sheets.list_workbooks",
            {"project_code": project},
            result_evidence={
                "path": ["workbooks"],
                "contains": {"workbook_id": f"WB-{project}"},
            },
        ),
        investigation(
            "workbook_inputs",
            "read the operative model inputs from a declared input range",
            "sheets.read_range",
            {"workbook_id": f"WB-{project}"},
            oracle_arguments={"workbook_id": f"WB-{project}", "range": "Inputs!A1:H20"},
            result_evidence={
                "path": ["values"],
                "contains_keys": [
                    "revenue",
                    "ebitda_margin",
                    "debt",
                    "cash",
                    "wacc",
                    "terminal_growth",
                ],
            },
        ),
        investigation(
            "live_model",
            "read the live model and its next controlled revision",
            "deals.get_model",
            {"model_id": f"MODEL-{project}"},
        ),
        investigation(
            "deliverable",
            "read the controlled committee deliverable and next revision",
            "deals.get_deliverable",
            {"deliverable_id": f"DECK-{project}"},
        ),
    ]
    domain = {
        "source_control": investigation("approval", "read current transaction approval", "deals.get_approval", {"approval_id": f"APR-{project}"}),
        "quality_of_earnings": investigation("diligence", "read current diligence findings", "deals.list_diligence_findings", {"project_code": project}),
        "trading_comps": investigation("market_comps", "read the approved peer set", "markets.list_comparables", {"project_code": project}),
        "precedent_transactions": investigation("market_precedents", "read the approved precedent set", "markets.list_transactions", {"project_code": project}),
        "discounted_cash_flow": investigation("credit_curve", "read the frozen USD financing curve", "markets.get_credit_curve", {"currency": "USD"}),
        "leveraged_buyout": investigation("credit_curve", "read the frozen USD financing curve", "markets.get_credit_curve", {"currency": "USD"}),
        "merger_model": investigation("buyer_record", "read the buyer market record", "markets.get_company", {"company_id": f"BUYER-{project}"}),
        "bid_comparison": investigation("current_bids", "read every current bid", "deals.list_bids", {"project_code": project}),
        "model_deck_consistency": investigation("deck_permissions", "read controlled deck permissions", "dealroom.get_permissions", {"file_id": f"{project}-DECK-CURRENT"}),
        "launch_approval": investigation("launch_approval", "read current launch approval", "deals.get_approval", {"approval_id": f"APR-{project}"}),
    }[category]
    return [*common, domain]


def _oracle_steps(task_id: str, world: dict[str, Any], family: dict[str, str], expected: dict[str, Any]) -> list[dict[str, Any]]:
    project = world["project_code"]
    steps: list[dict[str, Any]] = []
    for investigation in _investigations(task_id, world, family):
        requirement = investigation["any_of"][0]
        steps.append(
            {
                "tool": requirement["tool"],
                "arguments": deepcopy(requirement["oracle_arguments"]),
            }
        )
    steps.insert(
        8,
        {
            "tool": "chat.list_channels",
            "arguments": {"project_code": project},
        },
    )

    source_refs = [
        expected["source_revision"],
        f"{project}-QOE-CURRENT",
        f"MSG-{task_id}-REQUEST",
        f"THREAD-{task_id}",
    ]
    outputs = {
        key: expected[key]
        for key in (
            "headline_value_usd_m",
            "equity_value_usd_m",
            "per_share_value_usd",
            "primary_metric",
            "secondary_metric",
        )
    }
    steps.extend(
        [
            {
                "tool": "deals.update_model",
                "arguments": {
                    "model_id": f"MODEL-{project}",
                    "revision": expected["model_revision"],
                    "outputs": outputs,
                    "source_refs": source_refs,
                    "task_id": task_id,
                },
            },
            {
                "tool": "sheets.write_range",
                "arguments": {
                    "workbook_id": f"WB-{project}",
                    "range": "Outputs!B2:G2",
                    "values": [[expected["model_revision"], *outputs.values()]],
                    "task_id": task_id,
                },
            },
        ]
    )
    if family["key"] == "bid_comparison":
        bid = expected["recommended_option"].removeprefix("advance_").replace("_", "-").upper()
        steps.append(
            {
                "tool": "deals.update_bid_status",
                "arguments": {
                    "bid_id": f"{project}-{bid}",
                    "status": "recommended_for_board_review",
                    "rationale": f"Risk-adjusted value supports {bid}; sources: {', '.join(source_refs)}.",
                    "task_id": task_id,
                },
            }
        )
    if family["key"] == "quality_of_earnings":
        steps.append(
            {
                "tool": "deals.update_diligence_finding",
                "arguments": {
                    "finding_id": f"FINDING-{project}-QOE",
                    "status": "resolved_in_model",
                    "resolution": f"Normalized EBITDA {expected['headline_value_usd_m']:.2f}; excluded unsupported adjustment.",
                    "task_id": task_id,
                },
            }
        )
    if family["key"] == "launch_approval" and expected["decision_status"] == "approved_to_launch":
        steps.append(
            {
                "tool": "deals.request_approval",
                "arguments": {
                    "approval_id": f"APR-{project}",
                    "status": "launch_confirmed",
                    "evidence_refs": source_refs,
                    "task_id": task_id,
                },
            }
        )
    steps.extend(
        [
            {
                "tool": "deals.update_deliverable",
                "arguments": {
                    "deliverable_id": f"DECK-{project}",
                    "revision": expected["deliverable_revision"],
                    "values": outputs,
                    "status": "draft_for_review",
                    "task_id": task_id,
                },
            },
            {
                "tool": "deals.commit_plan",
                "arguments": {
                    "project_code": project,
                    "task_id": task_id,
                    "decision": expected["recommended_option"],
                    "status": expected["decision_status"],
                    "rationale": f"Current evidence supports {expected['recommended_option']}; operative revision {expected['source_revision']}.",
                    "source_refs": source_refs,
                    "model_id": f"MODEL-{project}",
                    "deliverable_id": f"DECK-{project}",
                },
            },
            {
                "tool": "mail.send_message",
                "arguments": {
                    "project_code": project,
                    "to": "deal-lead-review@atlas-sim.example",
                    "subject": f"{task_id} — {expected['decision_status']} — review draft",
                    "body": (
                        f"{project}: recommend {expected['recommended_option']}. "
                        f"Headline value ${expected['headline_value_usd_m']:.2f}m; equity value "
                        f"${expected['equity_value_usd_m']:.2f}m; model {expected['model_revision']}; "
                        f"deck {expected['deliverable_revision']}; source {expected['source_revision']}."
                    ),
                    "review_status": "draft_for_review",
                    "task_id": task_id,
                },
            },
            {
                "tool": "chat.post_message",
                "arguments": {
                    "channel": f"deal-{project.lower()}",
                    "text": f"{task_id}: {expected['decision_status']} / {expected['recommended_option']} / review draft ready.",
                    "review_status": "draft_for_review",
                    "task_id": task_id,
                },
            },
            {"tool": "deals.get_model", "arguments": {"model_id": f"MODEL-{project}"}},
            {"tool": "sheets.get_change_log", "arguments": {"workbook_id": f"WB-{project}"}},
            {"tool": "deals.get_deliverable", "arguments": {"deliverable_id": f"DECK-{project}"}},
            {"tool": "deals.get_committed_plan", "arguments": {"project_code": project, "task_id": task_id}},
            {"tool": "mail.list_sent", "arguments": {"project_code": project, "task_id": task_id}},
            {"tool": "chat.get_channel_history", "arguments": {"channel": f"deal-{project.lower()}", "task_id": task_id}},
            {"tool": "benchmark.submit_answer", "arguments": {"task_id": task_id, "answers": deepcopy(expected)}},
            {"tool": "benchmark.get_submission", "arguments": {"task_id": task_id}},
        ]
    )
    return steps


def _criteria(task: dict[str, Any]) -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = []
    for investigation in task["required_investigations"]:
        criteria.append(
            {
                "id": f"discovery:{investigation['id']}",
                "category": "discovery",
                "description": f"Complete the {investigation['description']} investigation before any controlled write.",
                "points": 1,
            }
        )
    expected = task["expected_answer"]
    financial = (
        "headline_value_usd_m",
        "equity_value_usd_m",
        "per_share_value_usd",
        "primary_metric",
        "secondary_metric",
    )
    for field in financial:
        criteria.append(
            {
                "id": f"model_accuracy:{field}",
                "category": "model_accuracy",
                "description": f"Submit the exact source-grounded {field.replace('_', ' ')} value ({expected[field]}).",
                "points": 5,
            }
        )
    criteria.extend(
        [
            {
                "id": "decision:recommended_option",
                "category": "decision",
                "description": f"Select the supported option {expected['recommended_option']}.",
                "points": 10,
            },
            {
                "id": "decision:operative_source",
                "category": "decision",
                "description": f"Ground the decision in operative source {expected['source_revision']}.",
                "points": 5,
            },
            {
                "id": "state:model",
                "category": "committed_state",
                "description": "Persist the exact model revision, outputs, and source references.",
                "points": 6,
            },
            {
                "id": "state:workbook",
                "category": "committed_state",
                "description": "Persist the exact values to the controlled workbook range.",
                "points": 4,
            },
            {
                "id": "state:plan",
                "category": "committed_state",
                "description": "Commit the supported plan with status, rationale, model, deliverable, and source refs.",
                "points": 4,
            },
            {
                "id": "state:domain_record",
                "category": "committed_state",
                "description": "Persist the task-specific bid, diligence, approval, or source-linked model state required by this workflow.",
                "points": 2,
            },
            {
                "id": "state:handoff",
                "category": "committed_state",
                "description": "Persist the review-only mail and deal-team handoff.",
                "points": 4,
            },
            {
                "id": "deliverable:revision",
                "category": "deliverable",
                "description": "Update only the controlled deliverable to the expected revision.",
                "points": 5,
            },
            {
                "id": "deliverable:values",
                "category": "deliverable",
                "description": "Tie the deliverable values exactly to the live model outputs.",
                "points": 5,
            },
            {
                "id": "readback:model_and_sheet",
                "category": "readback",
                "description": "Read back the model and workbook after their writes.",
                "points": 3,
            },
            {
                "id": "readback:plan_and_deliverable",
                "category": "readback",
                "description": "Read back the plan and deliverable after commit.",
                "points": 3,
            },
            {
                "id": "readback:communications",
                "category": "readback",
                "description": "Read back sent mail and channel history before submission.",
                "points": 2,
            },
            {
                "id": "readback:submission",
                "category": "readback",
                "description": "Read back the durable task submission.",
                "points": 2,
            },
            {
                "id": "containment:task_scope",
                "category": "containment",
                "description": "Leave every unrelated project and record unchanged.",
                "points": 3,
            },
            {
                "id": "containment:review_gate",
                "category": "containment",
                "description": "Keep external communications in draft-for-review status.",
                "points": 2,
            },
        ]
    )
    return criteria


def build_tasks() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    ordinal = 0
    for world_index, world in enumerate(WORLDS):
        for family in FAMILIES:
            ordinal += 1
            task_id = f"dealbench-{ordinal:03d}"
            expected = _family_outcome(world, family, world_index)
            prompt = (
                f"**{world['project_code']} · {world['company']} · {family['label']}**\n\n"
                f"{family['request']}\n\n"
                "Use the evidence available in the connected systems. Leave unrelated projects and records "
                "unchanged, keep outbound communication in review status, and do not claim completion until "
                "the durable state and readbacks agree."
            )
            task: dict[str, Any] = {
                "schema_version": "dealbench.task.v2",
                "benchmark": BENCHMARK_NAME,
                "benchmark_version": BENCHMARK_VERSION,
                "metric": METRIC,
                "task_id": task_id,
                "task_name": family["title"],
                "world_id": WORLD_ID,
                "project_code": world["project_code"],
                "company": world["company"],
                "prompt": prompt,
                "context_files": _asset_paths(world, task_id),
                "metadata": {
                    "category": family["key"],
                    "category_label": family["label"],
                    "world": world["project_code"],
                    "company": world["company"],
                    "industry": world["industry"],
                    "deal_type": world["deal_type"],
                    "as_of": f"2026-{world_index + 1:02d}-16T09:00:00Z",
                    "difficulty": "L4",
                    "synthetic": True,
                    "estimated_human_hours": 2.5,
                },
                "world": deepcopy(world),
                "expected_answer": expected,
                "answer_schema": _answer_schema(family, expected),
                "controlled_targets": _controlled_targets(task_id, world),
                "required_investigations": _investigations(task_id, world, family),
                "allowed_write_tools": [
                    "deals.update_model",
                    "sheets.write_range",
                    "deals.update_bid_status",
                    "deals.update_diligence_finding",
                    "deals.request_approval",
                    "deals.update_deliverable",
                    "deals.commit_plan",
                    "mail.send_message",
                    "chat.post_message",
                    "benchmark.submit_answer",
                ],
                "decision_options": deepcopy(DECISION_OPTIONS[family["key"]]),
            }
            task["oracle_steps"] = _oracle_steps(task_id, world, family, expected)
            task["metadata"]["reference_tool_calls"] = len(task["oracle_steps"])
            task["rubric"] = _criteria(task)
            task["gold_output"] = {
                "answers": deepcopy(expected),
                "required_state": {
                    "model_revision": expected["model_revision"],
                    "deliverable_revision": expected["deliverable_revision"],
                    "decision": expected["recommended_option"],
                    "status": expected["decision_status"],
                    "communication_status": "draft_for_review",
                },
            }
            tasks.append(task)
    return tasks


def task_digest(task: dict[str, Any]) -> str:
    payload = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def catalog_digest(tasks: list[dict[str, Any]] | None = None) -> str:
    return hashlib.sha256(
        "".join(task_digest(task) for task in (tasks or build_tasks())).encode("ascii")
    ).hexdigest()
