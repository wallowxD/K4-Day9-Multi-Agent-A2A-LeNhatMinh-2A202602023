from __future__ import annotations

import json
from typing import Any

from .agents import PolicyAgent
from .config import LIMITS
from .repository import DataContractError, OlistRepository


class VerifierAgent:
    name = "verifier_agent"

    TOP_LEVEL_KEYS = {
        "case_id",
        "case_assessment",
        "affected_entities",
        "customer_context",
        "product_context",
        "delivery_analysis",
        "payment_reconciliation",
        "root_cause_analysis",
        "evidence_ids",
        "financial_resolution",
        "resolution_actions",
    }

    def __init__(self, repository: OlistRepository):
        self.repository = repository

    def verify(self, result: dict[str, Any], claimed_order_id: str) -> dict[str, Any]:
        errors: list[str] = []
        if set(result) != self.TOP_LEVEL_KEYS:
            errors.append("top-level schema keys do not match the contract")
        assessment = result["case_assessment"]
        if assessment["primary_issue"] not in PolicyAgent.ROOT_CAUSES:
            errors.append("invalid primary_issue")
        if assessment["case_status"] not in {"action_required", "no_action"}:
            errors.append("invalid case_status")
        if not 0 <= assessment["confidence"] <= 1:
            errors.append("confidence is outside [0, 1]")

        affected = result["affected_entities"]
        if affected["order_ids"] != [claimed_order_id]:
            errors.append("affected order must be exactly the claimed order")
        if claimed_order_id not in self.repository.orders:
            errors.append("affected order does not exist")
        self._check_limit(errors, affected, "order_ids")
        self._check_limit(errors, affected, "item_ids")
        self._check_limit(errors, affected, "seller_ids")
        self._check_limit(errors, affected, "payment_ids")
        self._check_limit(errors, result["customer_context"], "related_order_ids")
        self._check_limit(errors, result["product_context"], "product_ids")
        self._check_limit(errors, result["product_context"], "category_names")
        self._check_limit(errors, result["root_cause_analysis"], "ranked_causes")
        self._check_limit(errors, result["root_cause_analysis"], "responsible_parties")
        if len(result["evidence_ids"]) > LIMITS["evidence_ids"]:
            errors.append("evidence_ids exceeds limit")
        if len(result["resolution_actions"]) > LIMITS["resolution_actions"]:
            errors.append("resolution_actions exceeds limit")

        self._verify_entity_ids(errors, result, claimed_order_id)
        self._verify_evidence(errors, result, claimed_order_id)

        payment = result["payment_reconciliation"]
        if not self.repository.items.get(claimed_order_id):
            for field in ("expected_total_brl", "difference_brl", "reconciled"):
                if payment[field] is not None:
                    errors.append(f"{field} must be null when the order has no items")
            if affected["item_ids"] or affected["seller_ids"]:
                errors.append("item and seller arrays must be empty when there are no items")
            if result["product_context"]["product_ids"] or result["product_context"]["category_names"]:
                errors.append("product arrays must be empty when there are no items")
            if result["delivery_analysis"]["seller_handoff_analysis"]:
                errors.append("seller handoff analysis must be empty when there are no items")

        refund = result["financial_resolution"]["recommended_refund_brl"]
        expected_status = "action_required" if refund > 0 else "no_action"
        if assessment["case_status"] != expected_status:
            errors.append("case_status and refund amount disagree")

        if errors:
            raise DataContractError("Verifier hard gate failed: " + "; ".join(errors))
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        return result

    @staticmethod
    def _check_limit(errors: list[str], container: dict[str, Any], field: str) -> None:
        if len(container[field]) > LIMITS[field]:
            errors.append(f"{field} exceeds limit")

    def _verify_entity_ids(
        self, errors: list[str], result: dict[str, Any], order_id: str
    ) -> None:
        source_items = {
            f"{order_id}:{row['order_item_id']}" for row in self.repository.items.get(order_id, [])
        }
        source_payments = {
            f"{order_id}:{row['payment_sequential']}"
            for row in self.repository.payments.get(order_id, [])
        }
        source_sellers = {row["seller_id"] for row in self.repository.items.get(order_id, [])}
        affected = result["affected_entities"]
        if not set(affected["item_ids"]).issubset(source_items):
            errors.append("affected item ID is not backed by source data")
        if not set(affected["payment_ids"]).issubset(source_payments):
            errors.append("affected payment ID is not backed by source data")
        if not set(affected["seller_ids"]).issubset(source_sellers):
            errors.append("affected seller ID is not backed by source data")

    def _verify_evidence(
        self, errors: list[str], result: dict[str, Any], order_id: str
    ) -> None:
        valid = {f"order:{order_id}"}
        valid.update(
            f"item:{order_id}:{row['order_item_id']}"
            for row in self.repository.items.get(order_id, [])
        )
        valid.update(
            f"payment:{order_id}:{row['payment_sequential']}"
            for row in self.repository.payments.get(order_id, [])
        )
        valid.update(f"seller:{row['seller_id']}" for row in self.repository.items.get(order_id, []))
        valid.update(f"policy:{code}" for code in PolicyAgent.ROOT_CAUSES.values())
        unknown = [evidence_id for evidence_id in result["evidence_ids"] if evidence_id not in valid]
        if unknown:
            errors.append(f"unsupported evidence IDs: {unknown}")

