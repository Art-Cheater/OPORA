"""Публичный API адресных подсказок."""

from app.core.address.providers import (
    AddressSuggestion,
    GeocodingError,
    GeocodingProvider,
    HeuristicGeocodingProvider,
    NominatimGeocodingProvider,
)
from app.core.address.service import (
    AddressSuggestionService,
    get_address_suggestion_service,
    load_address_selection_token,
    make_address_selection_token,
    register_geocoding_provider,
)

__all__ = [
    "AddressSuggestion",
    "AddressSuggestionService",
    "GeocodingError",
    "GeocodingProvider",
    "HeuristicGeocodingProvider",
    "NominatimGeocodingProvider",
    "get_address_suggestion_service",
    "load_address_selection_token",
    "make_address_selection_token",
    "register_geocoding_provider",
]
