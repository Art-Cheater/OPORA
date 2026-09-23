"""Импорт официального ГАР и подъездов OSM."""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal
from pathlib import Path

from app.core.address.directory import search_directory, search_settlements
from app.core.address.entrance_import import import_entrances
from app.core.address.gar_import import import_gar_archive
from app.core.geo.status import geo_status_lines, security_status_lines
from sqlalchemy import func, select

from app.extensions import db
from app.models.enums import Priority
from app.models.geo.directory import GeoEntrance, GeoHouse, GeoSettlement, GeoStreet
from app.models.requests.request import Request
from app.models.requests.request_status import RequestStatus
from app.modules.requests.repositories import RequestRepository


def _varint(value: int) -> bytes:
    out = bytearray()
    number = value
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 63)


def _field_bytes(field: int, payload: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def _field_varint(field: int, value: int) -> bytes:
    return _varint((field << 3) | 0) + _varint(value)


def _packed(field: int, values: list[int]) -> bytes:
    body = b"".join(_varint(item) for item in values)
    return _field_bytes(field, body)


def _tiny_pbf(path: Path) -> None:
    strings = b"".join(
        _field_bytes(1, item)
        for item in (
            b"",
            b"entrance",
            b"yes",
            b"ref",
            b"1",
            b"addr:street",
            "Ленина".encode("utf-8"),
            b"addr:housenumber",
            b"10",
        )
    )
    dense = (
        _packed(1, [_zigzag(100)])
        + _packed(8, [_zigzag(586_035_000)])
        + _packed(9, [_zigzag(496_680_000)])
        + _packed(10, [1, 2, 3, 4, 5, 6, 7, 8, 0])
    )
    group = _field_bytes(2, dense)
    block = _field_bytes(1, strings) + _field_bytes(2, group) + _field_varint(17, 100)
    blob = _field_bytes(1, block)
    header = _field_bytes(1, b"OSMData") + _field_varint(3, len(blob))
    path.write_bytes(len(header).to_bytes(4, "big") + header + blob)


def _gar_zip(path: Path) -> None:
    objects = """<?xml version="1.0" encoding="utf-8"?>
<OBJECTS>
  <OBJECT OBJECTID="1" OBJECTGUID="region-43" NAME="Кировская" TYPENAME="обл" LEVEL="1" ISACTIVE="1" ISACTUAL="1"/>
  <OBJECT OBJECTID="2" OBJECTGUID="city-kirov" NAME="Киров" TYPENAME="г" LEVEL="5" ISACTIVE="1" ISACTUAL="1"/>
  <OBJECT OBJECTID="3" OBJECTGUID="street-lenina" NAME="Ленина" TYPENAME="ул" LEVEL="8" ISACTIVE="1" ISACTUAL="1"/>
  <OBJECT OBJECTID="4" OBJECTGUID="village-bakhta" NAME="Бахта" TYPENAME="д" LEVEL="6" ISACTIVE="1" ISACTUAL="1"/>
  <OBJECT OBJECTID="5" OBJECTGUID="street-central" NAME="Центральная" TYPENAME="ул" LEVEL="8" ISACTIVE="1" ISACTUAL="1"/>
  <OBJECT OBJECTID="9" OBJECTGUID="old-street" NAME="Старая" TYPENAME="ул" LEVEL="8" ISACTIVE="0" ISACTUAL="0"/>
</OBJECTS>
"""
    houses = """<?xml version="1.0" encoding="utf-8"?>
<HOUSES>
  <HOUSE OBJECTID="6" OBJECTGUID="house-10" HOUSENUM="10" ADDNUM1="2" ADDTYPE1="1" ISACTIVE="1" ISACTUAL="1"/>
  <HOUSE OBJECTID="7" OBJECTGUID="house-bakhta" HOUSENUM="1" ADDNUM1="3" ADDTYPE1="2" ISACTIVE="1" ISACTUAL="1"/>
</HOUSES>
"""
    hierarchy = """<?xml version="1.0" encoding="utf-8"?>
<ITEMS>
  <ITEM OBJECTID="2" PARENTOBJID="1" ISACTIVE="1" ISACTUAL="1"/>
  <ITEM OBJECTID="3" PARENTOBJID="2" ISACTIVE="1" ISACTUAL="1"/>
  <ITEM OBJECTID="4" PARENTOBJID="1" ISACTIVE="1" ISACTUAL="1"/>
  <ITEM OBJECTID="5" PARENTOBJID="4" ISACTIVE="1" ISACTUAL="1"/>
  <ITEM OBJECTID="6" PARENTOBJID="3" ISACTIVE="1" ISACTUAL="1"/>
  <ITEM OBJECTID="7" PARENTOBJID="5" ISACTIVE="1" ISACTUAL="1"/>
</ITEMS>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("43/AS_ADDR_OBJ_20260101.XML", objects)
        archive.writestr("43/AS_HOUSES_20260101.XML", houses)
        archive.writestr("43/AS_ADM_HIERARCHY_20260101.XML", hierarchy)
    path.write_bytes(buffer.getvalue())


def test_gar_archive_imports_region_and_repeat_is_safe(app, tmp_path):
    archive = tmp_path / "gar.zip"
    _gar_zip(archive)
    with app.app_context():
        status = db.session.scalar(select(RequestStatus).where(RequestStatus.code == "new"))
        journal_id = RequestRepository.get_default_journal().id
        kept = Request(
            number="GAR-KEEP",
            title="Ручная точка",
            address="Киров, улица Ленина, дом 10",
            applicant_name="QA",
            priority=Priority.MEDIUM.value,
            status_id=status.id,
            journal_id=journal_id,
            latitude=Decimal("58.6000000"),
            longitude=Decimal("49.6600000"),
            geocode_quality="MANUAL",
        )
        db.session.add(kept)
        db.session.commit()
        first = import_gar_archive(archive, region="43")
        assert first["settlements"] == 2
        assert first["streets"] == 2
        assert first["houses"] == 2
        assert first["created"] == 6
        second = import_gar_archive(archive, region="43")
        assert second["created"] == 0
        assert second["updated"] == 6
        assert db.session.scalar(select(func.count()).select_from(GeoSettlement)) == 2
        assert db.session.scalar(select(func.count()).select_from(GeoStreet)) == 2
        assert db.session.scalar(select(func.count()).select_from(GeoHouse)) == 2
        house = db.session.scalar(select(GeoHouse).where(GeoHouse.external_id == "house-10"))
        assert house.number == "10"
        assert house.building == "2"
        assert house.fias_id == "house-10"
        assert house.latitude is None
        village = db.session.scalar(select(GeoHouse).where(GeoHouse.external_id == "house-bakhta"))
        assert village.structure == "3"
        saved = db.session.scalar(select(Request).where(Request.number == "GAR-KEEP"))
        assert saved.latitude == Decimal("58.6000000")
        assert saved.geocode_quality == "MANUAL"
        city = search_directory("Киров Ленина 10", limit=5)
        short = search_directory("ул Ленина д 10", limit=5)
        plain = search_directory("Ленина 10", limit=5)
        assert city and short and plain
        assert {item.normalized_address for item in (city[0], short[0], plain[0])} == {city[0].normalized_address}
        assert "корп. 2" in city[0].normalized_address
        assert city[0].address_level == "HOUSE"
        assert city[0].precision == "UNKNOWN"
        assert city[0].latitude is None
        assert city[0].fias_id == "house-10"
        village_hits = search_directory("Бахта, Центральная 1", limit=5)
        assert village_hits
        assert village_hits[0].settlement == "Бахта"
        assert "Центральная" in village_hits[0].normalized_address
        assert village_hits[0].address_level == "HOUSE"
        assert village_hits[0].precision == "UNKNOWN"
        places = search_settlements("Бахта", limit=5)
        assert places and places[0].precision == "SETTLEMENT"
        assert db.session.scalar(select(GeoStreet).where(GeoStreet.external_id == "old-street")) is None


def test_entrance_xml_and_pbf_are_idempotent(app, tmp_path):
    osm = tmp_path / "entrances.osm"
    osm.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<osm>
  <node id="10" lat="58.6035" lon="49.668">
    <tag k="entrance" v="yes"/>
    <tag k="addr:street" v="Ленина"/>
    <tag k="addr:housenumber" v="10"/>
  </node>
  <node id="11" lat="58.6036" lon="49.6681">
    <tag k="amenity" v="bench"/>
  </node>
</osm>
""",
        encoding="utf-8",
    )
    pbf = tmp_path / "entrances.pbf"
    _tiny_pbf(pbf)
    with app.app_context():
        xml_stats = import_entrances(osm)
        assert xml_stats["created"] == 1
        assert xml_stats["skipped"] == 1
        again = import_entrances(osm)
        assert again["created"] == 0
        assert again["updated"] == 1
        row = db.session.scalar(select(GeoEntrance).where(GeoEntrance.external_id == "10"))
        assert row.ref is None
        assert row.address_text == "Ленина, д. 10"
        assert row.entrance_type == "yes"
        pbf_stats = import_entrances(pbf)
        assert pbf_stats["created"] == 1
        imported = db.session.scalar(select(GeoEntrance).where(GeoEntrance.external_id == "100"))
        assert imported is not None
        assert imported.ref == "1"
        assert abs(float(imported.latitude) - 58.6035) < 0.0001
        assert abs(float(imported.longitude) - 49.668) < 0.0001
        assert db.session.scalar(select(func.count()).select_from(GeoEntrance)) == 2


def test_geo_status_hides_secrets_and_marks_routing_disabled(app):
    with app.app_context():
        app.config["CAPTCHA_ENABLED"] = False
        app.config["TURNSTILE_SITE_KEY"] = ""
        app.config["TURNSTILE_SECRET_KEY"] = "do-not-print"
        lines = geo_status_lines(app.config, reachable=False)
        text = "\n".join(lines)
        assert "ADDRESS DIRECTORY" in text
        assert "Settlements:" in text
        assert "ENTRANCES" in text
        assert "Provider: nominatim" in text
        assert "Reachable: no" in text
        assert "Disabled / not in current scope" in text
        assert "do-not-print" not in text
        security = "\n".join(security_status_lines(app.config))
        assert "Enabled: no" in security
        assert "Secret configured: yes" in security
        assert "do-not-print" not in security


def test_house_geocode_keeps_gar_address_and_uses_cache(app, tmp_path):
    archive = tmp_path / "gar.zip"
    _gar_zip(archive)

    class CountingProvider:
        def __init__(self):
            self.calls = 0

        def search(self, query, limit=8):
            self.calls += 1
            from app.core.address.providers import AddressSuggestion

            if "Бахта" in query:
                return [
                    AddressSuggestion(
                        original_address=query,
                        normalized_address="только улица, не дом",
                        street="Центральная",
                        latitude=58.2,
                        longitude=49.2,
                        address_source="nominatim",
                        address_external_id="osm/street",
                        precision="STREET",
                    )
                ]
            return [
                AddressSuggestion(
                    original_address=query,
                    normalized_address="чужой адрес геокодера",
                    house="10",
                    latitude=58.6035,
                    longitude=49.668,
                    address_source="nominatim",
                    address_external_id="osm/house",
                    precision="EXACT",
                )
            ]

        def reverse_geocode(self, latitude, longitude):
            return None

    with app.app_context():
        import_gar_archive(archive, region="43")
        from app.core.address.service import AddressSuggestionService
        from app.models.geo.directory import GeoGeocodeCache

        provider = CountingProvider()
        service = AddressSuggestionService(provider)
        street = service.suggest("Ленина")
        assert street and street[0].address_level == "STREET"
        assert street[0].precision != "EXACT"
        assert provider.calls == 0

        first = service.suggest("ул Ленина д 10")
        assert first[0].address_level == "HOUSE"
        assert first[0].precision == "EXACT"
        assert first[0].coordinate_quality == "EXACT"
        assert first[0].coordinate_source == "nominatim"
        assert first[0].latitude == 58.6035
        assert first[0].normalized_address != "чужой адрес геокодера"
        assert "улица Ленина" in first[0].official_address
        assert first[0].fias_id == "house-10"
        assert first[0].address_external_id == "house-10"
        house = db.session.scalar(select(GeoHouse).where(GeoHouse.external_id == "house-10"))
        assert house.number == "10"
        assert house.building == "2"
        assert house.fias_id == "house-10"
        assert float(house.latitude) == 58.6035
        assert provider.calls == 1
        assert db.session.scalar(select(GeoGeocodeCache).where(GeoGeocodeCache.cache_key == "house-point|house-10")) is not None

        house.latitude = None
        house.longitude = None
        db.session.commit()
        second = service.suggest("ул Ленина д 10")
        assert provider.calls == 1
        assert second[0].address_level == "HOUSE"
        assert second[0].fias_id == "house-10"
        assert second[0].normalized_address == first[0].normalized_address
        assert second[0].latitude == 58.6035

        village = service.suggest_settlement("Бахта, Центральная 1")
        assert village[0].address_level == "HOUSE"
        assert village[0].precision == "STREET"
        assert village[0].settlement == "Бахта"
        assert "Центральная" in village[0].official_address
        assert village[0].fias_id == "house-bakhta"
        untouched = db.session.scalar(select(GeoHouse).where(GeoHouse.external_id == "house-bakhta"))
        assert untouched.latitude is None
        assert untouched.structure == "3"
        again = service.suggest_settlement("Бахта, Центральная 1")
        assert again[0].precision == "STREET"
        assert provider.calls == 2


def test_geo_data_directory_status_and_compose_mount(app, tmp_path):
    filled = tmp_path / "filled"
    filled.mkdir()
    (filled / "gar.zip").write_bytes(b"PK")
    (filled / "kirov.osm.pbf").write_bytes(b"pbf")
    empty = tmp_path / "empty"
    empty.mkdir()
    with app.app_context():
        app.config["GEO_DATA_HOST_PATH"] = "/opt/opora/data/geo"
        app.config["GEO_DATA_CONTAINER_PATH"] = str(filled)
        text = "\n".join(geo_status_lines(app.config, reachable=False))
        assert "Host directory: /opt/opora/data/geo" in text
        assert f"Container directory: {filled}" in text
        assert "GAR archive: found" in text
        assert "OSM PBF: found" in text
        app.config["GEO_DATA_CONTAINER_PATH"] = str(empty)
        missing = "\n".join(geo_status_lines(app.config, reachable=False))
        assert "GAR archive: not found" in missing
        assert "OSM PBF: not found" in missing
        app.config["GEO_DATA_CONTAINER_PATH"] = str(tmp_path / "absent")
        absent = "\n".join(geo_status_lines(app.config, reachable=False))
        assert "GAR archive: not found" in absent
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "${GEO_DATA_HOST_PATH:-/opt/opora/data/geo}:/data/geo:ro" in compose
    assert "postgres_data:/var/lib/postgresql/data" in compose


def test_many_houses_and_entrances_stay_bounded(admin_client, app, tmp_path):
    objects = """<?xml version="1.0" encoding="utf-8"?>
<OBJECTS>
  <OBJECT OBJECTID="1" OBJECTGUID="region-43" NAME="Кировская" TYPENAME="обл" LEVEL="1" ISACTIVE="1" ISACTUAL="1"/>
  <OBJECT OBJECTID="2" OBJECTGUID="city-kirov" NAME="Киров" TYPENAME="г" LEVEL="5" ISACTIVE="1" ISACTUAL="1"/>
  <OBJECT OBJECTID="3" OBJECTGUID="street-lenina" NAME="Ленина" TYPENAME="ул" LEVEL="8" ISACTIVE="1" ISACTUAL="1"/>
</OBJECTS>
"""
    house_rows = [
        f'<HOUSE OBJECTID="{1000 + index}" OBJECTGUID="house-{index}" HOUSENUM="{index}" ISACTIVE="1" ISACTUAL="1"/>'
        for index in range(2000)
    ]
    hierarchy_rows = [
        '<ITEM OBJECTID="2" PARENTOBJID="1" ISACTIVE="1" ISACTUAL="1"/>',
        '<ITEM OBJECTID="3" PARENTOBJID="2" ISACTIVE="1" ISACTUAL="1"/>',
        *[
            f'<ITEM OBJECTID="{1000 + index}" PARENTOBJID="3" ISACTIVE="1" ISACTUAL="1"/>'
            for index in range(2000)
        ],
    ]
    archive = tmp_path / "many.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as packed:
        packed.writestr("43/AS_ADDR_OBJ_20260101.XML", objects)
        packed.writestr("43/AS_HOUSES_20260101.XML", "<HOUSES>" + "".join(house_rows) + "</HOUSES>")
        packed.writestr("43/AS_ADM_HIERARCHY_20260101.XML", "<ITEMS>" + "".join(hierarchy_rows) + "</ITEMS>")
    archive.write_bytes(buffer.getvalue())
    nodes = [
        f'<node id="{index}" lat="{58.60 + index / 1_000_000:.6f}" lon="49.660000"><tag k="entrance" v="yes"/></node>'
        for index in range(800)
    ]
    osm = tmp_path / "many.osm"
    osm.write_text("<osm>" + "".join(nodes) + "</osm>", encoding="utf-8")
    with app.app_context():
        stats = import_gar_archive(archive, region="43")
        assert stats["houses"] == 2000
        assert stats["created"] == 2002
        again = import_gar_archive(archive, region="43")
        assert again["created"] == 0
        assert db.session.scalar(select(func.count()).select_from(GeoHouse)) == 2000
        entrance_stats = import_entrances(osm)
        assert entrance_stats["created"] == 800
        assert import_entrances(osm)["created"] == 0
    hidden = admin_client.get("/api/geo/entrances?min_lat=58.59&max_lat=58.62&min_lon=49.65&max_lon=49.67&zoom=12")
    shown = admin_client.get("/api/geo/entrances?min_lat=58.59&max_lat=58.62&min_lon=49.65&max_lon=49.67&zoom=18")
    assert hidden.get_json()["hidden"] is True
    assert hidden.get_json()["geojson"]["features"] == []
    assert len(shown.get_json()["geojson"]["features"]) == 500
