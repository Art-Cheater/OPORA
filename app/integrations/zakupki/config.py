"""Параметры поиска по Дирекции благоустройства города Кирова."""

from __future__ import annotations

from urllib.parse import urlencode

EIS_BASE = "https://zakupki.gov.ru"
SEARCH_STRING = "освещения"
CUSTOMER_NAME = (
    'МУНИЦИПАЛЬНОЕ КАЗЕННОЕ УЧРЕЖДЕНИЕ "ДИРЕКЦИЯ БЛАГОУСТРОЙСТВА ГОРОДА КИРОВА"'
)
# Значение customerIdOrg как в выдаче ЕИС (код + подпись + служебные хвосты).
CUSTOMER_ID_ORG = (
    "03403001222:"
    f"{CUSTOMER_NAME}"
    "zZ03403001222zZ03403001222zZzZ4345288563zZ-1zZ434501001zZ1104345019184"
)

STATUS_SUPPLIER_DEFINED = "Определение поставщика завершено"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def contract_search_url(page: int = 1, per_page: str = "_50") -> str:
    query = {
        "searchString": SEARCH_STRING,
        "morphology": "on",
        "fz44": "on",
        "fz94": "on",
        "contractStageList_0": "on",
        "contractStageList_1": "on",
        "contractStageList_2": "on",
        "contractStageList_3": "on",
        "contractStageList": "0,1,2,3",
        "selectedContractDataChanges": "ANY",
        "currencyCode": "ANY",
        "budgetLevelsIdNameHidden": "{}",
        "customerIdOrg": CUSTOMER_ID_ORG,
        "countryRegIdNameHidden": "{}",
        "sortBy": "UPDATE_DATE",
        "pageNumber": str(page),
        "sortDirection": "false",
        "recordsPerPage": per_page,
        "showLotsInfoHidden": "false",
    }
    return f"{EIS_BASE}/epz/contract/search/results.html?{urlencode(query)}"


def order_search_url(page: int = 1, per_page: str = "_50") -> str:
    query = {
        "searchString": SEARCH_STRING,
        "morphology": "on",
        "search-filter": "Дате размещения",
        "pageNumber": str(page),
        "sortDirection": "false",
        "recordsPerPage": per_page,
        "showLotsInfoHidden": "false",
        "sortBy": "UPDATE_DATE",
        "fz44": "on",
        "fz223": "on",
        "af": "on",
        "ca": "on",
        "pc": "on",
        "pa": "on",
        "currencyIdGeneral": "-1",
        "customerIdOrg": CUSTOMER_ID_ORG,
        "gws": "Выберите тип закупки",
    }
    return f"{EIS_BASE}/epz/order/extendedsearch/results.html?{urlencode(query)}"


def absolute_url(path_or_url: str) -> str:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = "/" + path_or_url
    return EIS_BASE + path_or_url


def contract_card_url(reestr_number: str) -> str:
    return (
        f"{EIS_BASE}/epz/contract/contractCard/common-info.html"
        f"?reestrNumber={reestr_number}"
    )
