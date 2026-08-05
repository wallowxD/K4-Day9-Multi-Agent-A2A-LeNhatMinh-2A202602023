from __future__ import annotations

import unittest

from olist_agents.agents import PolicyAgent
from olist_agents.repository import DataContractError


class PolicyAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = PolicyAgent()
        self.order = {
            "order": {"order_status": "delivered"},
            "items": [{"x": 1}],
            "seller_ids": ["seller-a"],
            "category_names": ["cat-a"],
        }
        self.customer = {"has_other_orders": False}
        self.payment = {
            "payments": [{"payment_sequential": "1"}],
            "payment_total_brl": 110.0,
            "freight_total_brl": 10.0,
            "reconciled": True,
        }
        self.delivery = {
            "late_delivery": False,
            "delivery_variance_hours": -1.0,
            "late_handoff_seller_ids": [],
        }

    def decide(self):
        return self.agent.decide(self.order, self.customer, self.payment, self.delivery)

    def test_unsupported_late_claim(self) -> None:
        result = self.decide()
        self.assertEqual(result["primary_issue"], "unsupported_late_claim")
        self.assertEqual(result["recommended_refund_brl"], 0.0)
        self.assertEqual(result["resolution_actions"], ["reject_late_refund"])

    def test_valid_split_payment_precedes_supported_rejection(self) -> None:
        self.payment["payments"].append({"payment_sequential": "2"})
        result = self.decide()
        self.assertEqual(result["primary_issue"], "valid_split_payment")
        self.assertIn("split_payment", result["secondary_issues"])
        self.assertNotIn("verify_payment_allocation", result["resolution_actions"])

    def test_late_delivery_seller(self) -> None:
        self.delivery.update(
            late_delivery=True,
            delivery_variance_hours=24.0,
            late_handoff_seller_ids=["seller-a"],
        )
        result = self.decide()
        self.assertEqual(result["primary_issue"], "late_delivery_seller")
        self.assertEqual(result["responsible_parties"][0]["party_id"], "seller-a")
        self.assertEqual(result["recommended_refund_brl"], 10.0)

    def test_late_delivery_logistics(self) -> None:
        self.delivery.update(late_delivery=True, delivery_variance_hours=24.0)
        result = self.decide()
        self.assertEqual(result["primary_issue"], "late_delivery_logistics")
        self.assertEqual(result["responsible_parties"][0]["party_id"], "LOGISTICS_PROVIDER")

    def test_canceled_paid_has_highest_priority(self) -> None:
        self.order["order"]["order_status"] = "canceled"
        self.delivery.update(
            late_delivery=True,
            delivery_variance_hours=24.0,
            late_handoff_seller_ids=["seller-a"],
        )
        result = self.decide()
        self.assertEqual(result["primary_issue"], "canceled_order_paid")
        self.assertEqual(result["recommended_refund_brl"], 110.0)

    def test_unavailable_paid(self) -> None:
        self.order["order"]["order_status"] = "unavailable"
        result = self.decide()
        self.assertEqual(result["primary_issue"], "unavailable_order_paid")

    def test_null_delivery_does_not_become_unsupported_claim(self) -> None:
        self.delivery["delivery_variance_hours"] = None
        with self.assertRaises(DataContractError):
            self.decide()

    def test_secondary_issue_order_and_action_order(self) -> None:
        self.order.update(
            items=[{"x": 1}, {"x": 2}],
            seller_ids=["seller-a", "seller-b"],
            category_names=["cat-a", "cat-b"],
        )
        self.customer["has_other_orders"] = True
        self.payment["payments"].append({"payment_sequential": "2"})
        self.delivery.update(
            late_delivery=True,
            delivery_variance_hours=24.0,
            late_handoff_seller_ids=["seller-a"],
        )
        result = self.decide()
        self.assertEqual(
            result["secondary_issues"],
            [
                "multi_item_order",
                "multi_seller_order",
                "split_payment",
                "repeat_customer",
                "multiple_categories",
            ],
        )
        self.assertEqual(
            result["resolution_actions"],
            [
                "refund_freight",
                "review_seller_handoff",
                "verify_refund_completion",
                "coordinate_multi_seller_case",
                "verify_payment_allocation",
            ],
        )


if __name__ == "__main__":
    unittest.main()

