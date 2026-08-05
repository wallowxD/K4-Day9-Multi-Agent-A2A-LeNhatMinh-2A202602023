from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


class DataContractError(ValueError):
    """Raised when an input or source-data contract is violated."""


class OlistRepository:
    """Read-only, indexed access to the Olist CSV sources."""

    REQUIRED_FILES = (
        "olist_customers_dataset.csv",
        "olist_orders_dataset.csv",
        "olist_order_items_dataset.csv",
        "olist_order_payments_dataset.csv",
        "olist_products_dataset.csv",
        "olist_sellers_dataset.csv",
    )

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        missing = [name for name in self.REQUIRED_FILES if not (self.data_dir / name).is_file()]
        if missing:
            raise DataContractError(f"Missing source files: {', '.join(missing)}")

        self.customers = self._index_one("olist_customers_dataset.csv", "customer_id")
        self.orders, order_rows = self._index_one_with_rows("olist_orders_dataset.csv", "order_id")
        self.items = self._index_many("olist_order_items_dataset.csv", "order_id")
        self.payments = self._index_many("olist_order_payments_dataset.csv", "order_id")
        self.products = self._index_one("olist_products_dataset.csv", "product_id")
        self.sellers = self._index_one("olist_sellers_dataset.csv", "seller_id")

        self.orders_by_unique_customer: dict[str, list[str]] = defaultdict(list)
        for order in order_rows:
            customer = self.customers.get(order["customer_id"])
            if customer:
                self.orders_by_unique_customer[customer["customer_unique_id"]].append(order["order_id"])

    def _rows(self, filename: str) -> list[dict[str, str]]:
        with (self.data_dir / filename).open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _index_one(self, filename: str, key: str) -> dict[str, dict[str, str]]:
        rows = self._rows(filename)
        return {row[key]: row for row in rows}

    def _index_one_with_rows(
        self, filename: str, key: str
    ) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
        rows = self._rows(filename)
        return {row[key]: row for row in rows}, rows

    def _index_many(self, filename: str, key: str) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self._rows(filename):
            result[row[key]].append(row)
        return result

    def get_order(self, order_id: str) -> dict[str, str]:
        try:
            return self.orders[order_id]
        except KeyError as exc:
            raise DataContractError(f"Unknown claimed_order_id: {order_id}") from exc

