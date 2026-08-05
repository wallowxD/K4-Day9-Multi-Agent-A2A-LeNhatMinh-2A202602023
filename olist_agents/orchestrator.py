from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .agents import CustomerAgent, DeliveryAgent, OrderProductAgent, PaymentAgent, PolicyAgent
from .config import LIMITS, POLICY_VERSION
from .llm import LlamaRuntime
from .repository import DataContractError, OlistRepository
from .trace import TraceWriter
from .verifier import VerifierAgent


class CoordinatorAgent:
    name = "coordinator_agent"

    def __init__(
        self,
        repository: OlistRepository,
        llama: LlamaRuntime,
        trace: TraceWriter,
    ):
        self.repository = repository
        self.llama = llama
        self.trace = trace
        self.customer_agent = CustomerAgent(repository)
        self.order_agent = OrderProductAgent(repository)
        self.payment_agent = PaymentAgent(repository)
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent(repository)

    def process(self, case: dict[str, Any]) -> dict[str, Any]:
        case_id, order_id = self._validate_case(case)
        order = self.repository.get_order(order_id)
        self.trace.emit(
            case_id,
            self.name,
            "case_received",
            details={"claimed_order_id": order_id, "policy_version": POLICY_VERSION},
        )
        coordinator_review = self.llama.review(
            self.name,
            {"task": "route_case", "case_id": case_id, "order_status": order["order_status"]},
        )
        self.trace.emit(case_id, self.name, "model_review", details=coordinator_review)

        with ThreadPoolExecutor(max_workers=2) as pool:
            customer_future = pool.submit(self.customer_agent.investigate, order)
            order_future = pool.submit(self.order_agent.investigate, order)
            customer = customer_future.result()
            order_findings = order_future.result()
        self._handoff(case_id, self.customer_agent.name, "policy_agent", customer)
        self._handoff(case_id, self.order_agent.name, "payment_agent,delivery_agent", order_findings)

        with ThreadPoolExecutor(max_workers=2) as pool:
            payment_future = pool.submit(self.payment_agent.investigate, order_id, order_findings)
            delivery_future = pool.submit(self.delivery_agent.investigate, order_findings)
            payment = payment_future.result()
            delivery = delivery_future.result()
        self._handoff(case_id, self.payment_agent.name, "policy_agent", payment)
        self._handoff(case_id, self.delivery_agent.name, "policy_agent", delivery)

        policy = self.policy_agent.decide(order_findings, customer, payment, delivery)
        self._handoff(case_id, self.policy_agent.name, "coordinator_agent", policy)
        result = self._assemble(case, order_findings, customer, payment, delivery, policy)

        verifier_review = self.llama.review(
            self.verifier_agent.name,
            {
                "primary_issue": policy["primary_issue"],
                "refund": policy["recommended_refund_brl"],
                "evidence_count": len(result["evidence_ids"]),
            },
        )
        self.trace.emit(case_id, self.verifier_agent.name, "model_review", details=verifier_review)
        verified = self.verifier_agent.verify(result, order_id)
        self.trace.emit(
            case_id,
            self.verifier_agent.name,
            "hard_gate_passed",
            handoff_to=self.name,
            details={"evidence_count": len(verified["evidence_ids"])},
        )
        self.trace.emit(
            case_id,
            self.name,
            "case_completed",
            details={"primary_issue": policy["primary_issue"], "status": policy["case_status"]},
        )
        return verified

    def _handoff(
        self,
        case_id: str,
        agent_name: str,
        recipient: str,
        payload: dict[str, Any],
    ) -> None:
        review_payload = self._compact_review_payload(agent_name, payload)
        model_review = self.llama.review(agent_name, review_payload)
        self.trace.emit(case_id, agent_name, "model_review", details=model_review)
        self.trace.emit(
            case_id,
            agent_name,
            "handoff",
            handoff_to=recipient,
            details={"fields": list(payload), "source_backed": True},
        )

    @staticmethod
    def _compact_review_payload(agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if agent_name == "order_product_agent":
            return {
                "status": payload["order"]["order_status"],
                "item_count": len(payload["items"]),
                "seller_ids": payload["seller_ids"],
                "category_names": payload["category_names"],
            }
        if agent_name == "payment_agent":
            return {key: value for key, value in payload.items() if key != "payments"}
        return payload

    @staticmethod
    def _validate_case(case: dict[str, Any]) -> tuple[str, str]:
        try:
            case_id = case["case_id"]
            request = case["customer_request"]
            order_id = request["claimed_order_id"]
            policy_version = case["policy_version"]
        except (KeyError, TypeError) as exc:
            raise DataContractError(f"Malformed case input: missing {exc}") from exc
        if not isinstance(case_id, str) or not case_id.startswith("EC_"):
            raise DataContractError(f"Invalid case_id: {case_id!r}")
        if not isinstance(order_id, str) or not order_id:
            raise DataContractError("claimed_order_id must be a non-empty string")
        if policy_version != POLICY_VERSION:
            raise DataContractError(f"Unsupported policy_version: {policy_version!r}")
        return case_id, order_id

    @staticmethod
    def _assemble(
        case: dict[str, Any],
        order_findings: dict[str, Any],
        customer: dict[str, Any],
        payment: dict[str, Any],
        delivery: dict[str, Any],
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        order = order_findings["order"]
        order_id = order["order_id"]
        items = order_findings["items"]
        payments = payment["payments"]
        item_ids = [f"{order_id}:{row['order_item_id']}" for row in items]
        payment_ids = [f"{order_id}:{row['payment_sequential']}" for row in payments]
        responsible_sellers = [
            row["party_id"]
            for row in policy["responsible_parties"]
            if row["party_type"] == "seller"
        ]
        evidence = [f"order:{order_id}"]
        evidence.extend(f"item:{value}" for value in item_ids[: LIMITS["item_ids"]])
        evidence.extend(f"payment:{value}" for value in payment_ids[: LIMITS["payment_ids"]])
        evidence.extend(f"seller:{seller_id}" for seller_id in responsible_sellers)
        evidence.append(f"policy:{policy['root_cause_code']}")

        scope = case.get("investigation_scope", {})
        include_history = scope.get("include_customer_history", True)
        include_products = scope.get("include_product_context", True)
        return {
            "case_id": case["case_id"],
            "case_assessment": {
                "primary_issue": policy["primary_issue"],
                "secondary_issues": policy["secondary_issues"],
                "case_status": policy["case_status"],
                "confidence": policy["confidence"],
            },
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids[: LIMITS["item_ids"]],
                "seller_ids": order_findings["seller_ids"][: LIMITS["seller_ids"]],
                "payment_ids": payment_ids[: LIMITS["payment_ids"]],
            },
            "customer_context": {
                "customer_unique_id": customer["customer_unique_id"],
                "related_order_ids": customer["related_order_ids"] if include_history else [],
            },
            "product_context": {
                "product_ids": (
                    order_findings["product_ids"][: LIMITS["product_ids"]] if include_products else []
                ),
                "category_names": (
                    order_findings["category_names"][: LIMITS["category_names"]]
                    if include_products
                    else []
                ),
            },
            "delivery_analysis": {
                "delivered_at": delivery["delivered_at"],
                "estimated_delivery_at": delivery["estimated_delivery_at"],
                "carrier_handoff_at": delivery["carrier_handoff_at"],
                "delivery_variance_hours": delivery["delivery_variance_hours"],
                "seller_handoff_analysis": delivery["seller_handoff_analysis"][
                    : LIMITS["seller_ids"]
                ],
                "late_handoff_seller_ids": delivery["late_handoff_seller_ids"][
                    : LIMITS["seller_ids"]
                ],
            },
            "payment_reconciliation": {
                key: value for key, value in payment.items() if key != "payments"
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": policy["root_cause_code"], "rank": 1}],
                "responsible_parties": policy["responsible_parties"],
            },
            "evidence_ids": evidence[: LIMITS["evidence_ids"]],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": policy["recommended_refund_brl"],
            },
            "resolution_actions": policy["resolution_actions"],
        }

