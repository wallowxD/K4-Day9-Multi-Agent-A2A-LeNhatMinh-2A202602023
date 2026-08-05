from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from typing import Any

from .config import LIMITS, POLICY_VERSION
from .repository import DataContractError, OlistRepository
from .utils import money, parse_decimal, parse_timestamp, stable_unique, variance_hours


class CustomerAgent:
    name = "customer_agent"

    def __init__(self, repository: OlistRepository):
        self.repository = repository

    def investigate(self, order: dict[str, str]) -> dict[str, Any]:
        customer = self.repository.customers.get(order["customer_id"])
        if customer is None:
            raise DataContractError(f"Missing customer row: {order['customer_id']}")
        unique_id = customer["customer_unique_id"]
        related = [
            order_id
            for order_id in self.repository.orders_by_unique_customer.get(unique_id, [])
            if order_id != order["order_id"]
        ]
        return {
            "customer_unique_id": unique_id,
            "related_order_ids": related[: LIMITS["related_order_ids"]],
            "has_other_orders": bool(related),
        }


class OrderProductAgent:
    name = "order_product_agent"

    def __init__(self, repository: OlistRepository):
        self.repository = repository

    def investigate(self, order: dict[str, str]) -> dict[str, Any]:
        order_id = order["order_id"]
        items = self.repository.items.get(order_id, [])
        seller_ids = stable_unique(row["seller_id"] for row in items)
        product_ids = stable_unique(row["product_id"] for row in items)
        products = [self.repository.products.get(product_id) for product_id in product_ids]
        missing_products = [pid for pid, row in zip(product_ids, products) if row is None]
        missing_sellers = [sid for sid in seller_ids if sid not in self.repository.sellers]
        if missing_products or missing_sellers:
            raise DataContractError(
                f"Broken item references; products={missing_products}, sellers={missing_sellers}"
            )
        category_names = stable_unique(
            row["product_category_name"]
            for row in products
            if row and row.get("product_category_name")
        )
        return {
            "order": order,
            "items": items,
            "seller_ids": seller_ids,
            "product_ids": product_ids,
            "category_names": category_names,
        }


class PaymentAgent:
    name = "payment_agent"

    def __init__(self, repository: OlistRepository):
        self.repository = repository

    def investigate(self, order_id: str, order_findings: dict[str, Any]) -> dict[str, Any]:
        items = order_findings["items"]
        payments = self.repository.payments.get(order_id, [])
        item_total = sum((parse_decimal(row["price"]) for row in items), Decimal("0"))
        freight_total = sum((parse_decimal(row["freight_value"]) for row in items), Decimal("0"))
        payment_total = sum((parse_decimal(row["payment_value"]) for row in payments), Decimal("0"))

        expected_total: Decimal | None = item_total + freight_total if items else None
        difference: Decimal | None = payment_total - expected_total if expected_total is not None else None
        reconciled = abs(difference) <= Decimal("0.10") if difference is not None else None
        return {
            "payments": payments,
            "currency": "BRL",
            "item_total_brl": money(item_total),
            "freight_total_brl": money(freight_total),
            "expected_total_brl": money(expected_total) if expected_total is not None else None,
            "payment_total_brl": money(payment_total),
            "difference_brl": money(difference) if difference is not None else None,
            "reconciled": reconciled,
            "payment_types": stable_unique(row["payment_type"] for row in payments),
        }


class DeliveryAgent:
    name = "delivery_agent"

    def investigate(self, order_findings: dict[str, Any]) -> dict[str, Any]:
        order = order_findings["order"]
        carrier_at = order.get("order_delivered_carrier_date") or None
        grouped: OrderedDict[str, list[str]] = OrderedDict()
        for item in order_findings["items"]:
            grouped.setdefault(item["seller_id"], []).append(item["shipping_limit_date"])

        seller_analysis: list[dict[str, Any]] = []
        for seller_id, limits in grouped.items():
            nonempty = [value for value in limits if value]
            shipping_limit = min(nonempty) if nonempty else None
            handoff_variance = variance_hours(carrier_at, shipping_limit)
            carrier_timestamp = parse_timestamp(carrier_at)
            limit_timestamp = parse_timestamp(shipping_limit)
            seller_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit,
                    "handoff_variance_hours": handoff_variance,
                    "late_handoff": (
                        carrier_timestamp is not None
                        and limit_timestamp is not None
                        and carrier_timestamp > limit_timestamp
                    ),
                }
            )

        delivered_at = order.get("order_delivered_customer_date") or None
        estimated_at = order.get("order_estimated_delivery_date") or None
        delivered_timestamp = parse_timestamp(delivered_at)
        estimated_timestamp = parse_timestamp(estimated_at)
        return {
            "delivered_at": delivered_at,
            "estimated_delivery_at": estimated_at,
            "carrier_handoff_at": carrier_at,
            "late_delivery": (
                delivered_timestamp is not None
                and estimated_timestamp is not None
                and delivered_timestamp > estimated_timestamp
            ),
            "delivery_variance_hours": variance_hours(
                order.get("order_delivered_customer_date"),
                order.get("order_estimated_delivery_date"),
            ),
            "seller_handoff_analysis": seller_analysis,
            "late_handoff_seller_ids": [
                row["seller_id"] for row in seller_analysis if row["late_handoff"]
            ],
        }


class PolicyAgent:
    name = "policy_agent"

    ROOT_CAUSES = {
        "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
        "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
        "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
        "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
    }

    PRIMARY_ACTIONS = {
        "late_delivery_seller": "refund_freight",
        "late_delivery_logistics": "refund_freight",
        "canceled_order_paid": "issue_full_refund",
        "unavailable_order_paid": "issue_full_refund",
        "valid_split_payment": "explain_valid_split_payment",
        "unsupported_late_claim": "reject_late_refund",
    }

    def decide(
        self,
        order_findings: dict[str, Any],
        customer_findings: dict[str, Any],
        payment_findings: dict[str, Any],
        delivery_findings: dict[str, Any],
    ) -> dict[str, Any]:
        order = order_findings["order"]
        status = order["order_status"]
        paid = payment_findings["payment_total_brl"] > 0
        late_delivery = delivery_findings["late_delivery"]
        has_late_handoff = bool(delivery_findings["late_handoff_seller_ids"])
        split_payment = len(payment_findings["payments"]) >= 2

        if status == "canceled" and paid:
            primary = "canceled_order_paid"
        elif status == "unavailable" and paid:
            primary = "unavailable_order_paid"
        elif late_delivery and has_late_handoff:
            primary = "late_delivery_seller"
        elif late_delivery:
            primary = "late_delivery_logistics"
        elif split_payment and payment_findings["reconciled"] is True:
            primary = "valid_split_payment"
        elif (
            delivery_findings["delivery_variance_hours"] is not None
            and not late_delivery
            and payment_findings["reconciled"] is True
        ):
            primary = "unsupported_late_claim"
        else:
            raise DataContractError(
                "Case does not match any EC_POLICY_V2 primary issue; refusing to invent a classification"
            )

        secondary: list[str] = []
        if len(order_findings["items"]) >= 2:
            secondary.append("multi_item_order")
        if len(order_findings["seller_ids"]) >= 2:
            secondary.append("multi_seller_order")
        if split_payment:
            secondary.append("split_payment")
        if customer_findings["has_other_orders"]:
            secondary.append("repeat_customer")
        if len(order_findings["category_names"]) >= 2:
            secondary.append("multiple_categories")

        cause = self.ROOT_CAUSES[primary]
        if primary == "late_delivery_seller":
            responsible = [
                {"party_type": "seller", "party_id": seller_id}
                for seller_id in delivery_findings["late_handoff_seller_ids"][: LIMITS["responsible_parties"]]
            ]
        elif primary in {"canceled_order_paid", "unavailable_order_paid"}:
            responsible = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        elif primary == "late_delivery_logistics":
            responsible = [
                {"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}
            ]
        else:
            responsible = []

        if primary in {"canceled_order_paid", "unavailable_order_paid"}:
            refund = payment_findings["payment_total_brl"]
        elif primary in {"late_delivery_seller", "late_delivery_logistics"}:
            refund = payment_findings["freight_total_brl"]
        else:
            refund = 0.0

        actions = [self.PRIMARY_ACTIONS[primary]]
        if primary == "late_delivery_seller":
            actions.append("review_seller_handoff")
        elif primary == "late_delivery_logistics":
            actions.append("review_carrier_delay")
        if refund > 0:
            actions.append("verify_refund_completion")
        if "multi_seller_order" in secondary:
            actions.append("coordinate_multi_seller_case")
        if "split_payment" in secondary and primary != "valid_split_payment":
            actions.append("verify_payment_allocation")

        return {
            "policy_version": POLICY_VERSION,
            "primary_issue": primary,
            "secondary_issues": secondary,
            "case_status": "action_required" if refund > 0 else "no_action",
            "confidence": 1.0,
            "root_cause_code": cause,
            "responsible_parties": responsible,
            "recommended_refund_brl": money(Decimal(str(refund))),
            "resolution_actions": actions[: LIMITS["resolution_actions"]],
        }
