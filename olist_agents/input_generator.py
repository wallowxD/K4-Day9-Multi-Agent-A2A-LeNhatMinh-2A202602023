from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .agents import CustomerAgent, DeliveryAgent, OrderProductAgent, PaymentAgent, PolicyAgent
from .repository import DataContractError, OlistRepository


DEFAULT_QUOTAS: OrderedDict[str, int] = OrderedDict(
    (
        ("canceled_order_paid", 8),
        ("unavailable_order_paid", 8),
        ("late_delivery_seller", 9),
        ("late_delivery_logistics", 9),
        ("valid_split_payment", 8),
        ("unsupported_late_claim", 8),
    )
)


class InputGenerator:
    """Select deterministic, source-backed cases covering all policy branches."""

    def __init__(self, repository: OlistRepository):
        self.repository = repository
        self.customer_agent = CustomerAgent(repository)
        self.order_agent = OrderProductAgent(repository)
        self.payment_agent = PaymentAgent(repository)
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()

    def select(self, quotas: dict[str, int] | None = None) -> list[tuple[str, str]]:
        targets = OrderedDict(quotas or DEFAULT_QUOTAS)
        selected: dict[str, list[str]] = {issue: [] for issue in targets}
        for order in self.repository.orders.values():
            if all(len(selected[issue]) >= count for issue, count in targets.items()):
                break
            try:
                order_findings = self.order_agent.investigate(order)
                customer = self.customer_agent.investigate(order)
                payment = self.payment_agent.investigate(order["order_id"], order_findings)
                delivery = self.delivery_agent.investigate(order_findings)
                policy = self.policy_agent.decide(order_findings, customer, payment, delivery)
            except DataContractError:
                continue
            issue = policy["primary_issue"]
            if issue in targets and len(selected[issue]) < targets[issue]:
                selected[issue].append(order["order_id"])

        shortages = {
            issue: targets[issue] - len(order_ids)
            for issue, order_ids in selected.items()
            if len(order_ids) < targets[issue]
        }
        if shortages:
            raise DataContractError(f"Not enough source-backed orders for quotas: {shortages}")

        # Round-robin keeps adjacent case IDs varied while preserving source order within each issue.
        result: list[tuple[str, str]] = []
        max_quota = max(targets.values())
        for index in range(max_quota):
            for issue in targets:
                if index < len(selected[issue]):
                    result.append((selected[issue][index], issue))
        return result

    def write(self, input_dir: Path) -> list[dict[str, Any]]:
        input_dir = Path(input_dir)
        input_dir.mkdir(parents=True, exist_ok=True)
        selected = self.select()
        cases: list[dict[str, Any]] = []
        for number, (order_id, expected_issue) in enumerate(selected, start=1):
            case_id = f"EC_{number:03d}"
            case = {
                "case_id": case_id,
                "customer_request": {
                    "language": "vi",
                    "message": (
                        "Hãy điều tra khiếu nại, kiểm tra lịch sử khách hàng "
                        "và đối soát toàn bộ order."
                    ),
                    "claimed_order_id": order_id,
                },
                "investigation_scope": {
                    "include_customer_history": True,
                    "include_product_context": True,
                },
                "policy_version": "EC_POLICY_V2",
            }
            destination = input_dir / f"{case_id}.json"
            destination.write_text(
                json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            cases.append(
                {"case_id": case_id, "claimed_order_id": order_id, "expected_issue": expected_issue}
            )
        return cases

