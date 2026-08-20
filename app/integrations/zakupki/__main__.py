"""Запуск: python -m app.integrations.zakupki --limit 3"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.integrations.zakupki.client import EisClient
from app.integrations.zakupki.runner import EisParser


def _print(message: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.write(message.encode(encoding, "replace").decode(encoding) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Тестовый парсер ЕИС zakupki.gov.ru: контракты и закупки "
            "Дирекции благоустройства (поиск «освещения»). В Опору не пишет."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("both", "contracts", "orders"),
        default="both",
        help="Что скачивать",
    )
    parser.add_argument("--pages", type=int, default=1, help="Сколько страниц выдачи")
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Максимум карточек каждого типа (0 = без ограничения на странице)",
    )
    parser.add_argument(
        "--per-page",
        default="_10",
        help="recordsPerPage ЕИС: _10, _20, _50",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.2,
        help="Пауза между запросами, секунды",
    )
    parser.add_argument(
        "--no-contracts-from-orders",
        action="store_true",
        help="Для закупок не открывать карточки контрактов",
    )
    parser.add_argument(
        "--out",
        default="data/zakupki/last_run.json",
        help="Куда сохранить JSON",
    )
    parser.add_argument(
        "--contract",
        action="append",
        default=[],
        help="Реестровый номер контракта (можно несколько раз)",
    )
    parser.add_argument(
        "--order",
        action="append",
        default=[],
        help="Номер извещения закупки (можно несколько раз)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    limit = None if args.limit == 0 else args.limit
    parser = EisParser(EisClient(delay=args.delay))
    result = parser.run(
        mode=args.mode,
        pages=args.pages,
        limit=limit,
        per_page=args.per_page,
        with_contracts=not args.no_contracts_from_orders,
        contract_numbers=args.contract or None,
        order_numbers=args.order or None,
    )
    payload = result.to_dict()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _print(f"Контрактов в выдаче ЕИС: {result.contract_total}")
    _print(f"Скачано карточек контрактов: {len(result.contracts)}")
    for contract in result.contracts:
        names = "; ".join(item.name for item in contract.suppliers) or "—"
        _print(
            f"  {contract.reestr_number} | {contract.number} | "
            f"{contract.contract_date} | {contract.amount} | {names}"
        )
    _print(f"Закупок в выдаче ЕИС: {result.order_total}")
    _print(f"Скачано извещений: {len(result.orders)}")
    for order in result.orders:
        _print(
            f"  {order.reg_number} | {order.status} | НМЦК {order.nmck} | "
            f"контракты {', '.join(order.contract_reestr_numbers) or '—'}"
        )
    _print(f"Ошибок импорта: {len(result.issues)}")
    for issue in result.issues:
        _print(f"  [{issue.kind}] {issue.number or ''} {issue.message}")
    _print(f"JSON: {out_path.resolve()}")
    return 0 if not result.issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
