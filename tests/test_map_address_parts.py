from app.core.address.map_points import split_map_address_parts


def test_range_and_compact_range_are_expanded_safely():
    parts, warning = split_map_address_parts("Киров, улица Рейдовая, дом 1 - 4")
    assert parts == [
        "Киров, улица Рейдовая, дом 1", "Киров, улица Рейдовая, дом 2",
        "Киров, улица Рейдовая, дом 3", "Киров, улица Рейдовая, дом 4",
    ] and warning is None
    assert len(split_map_address_parts("Рейдовая 1-4")[0]) == 4


def test_multiple_houses_but_not_normal_comma_address():
    parts, warning = split_map_address_parts("Даниловский проезд 7, 9, 9а, 11, 11а")
    assert len(parts) == 5 and parts[2].endswith("дом 9а") and warning is None
    assert split_map_address_parts("Киров, улица Ленина, дом 15")[0] == ["Киров, улица Ленина, дом 15"]


def test_large_and_ambiguous_ranges_remain_anchor():
    assert split_map_address_parts("Ленина 1-200")[1]
    assert split_map_address_parts("Ленина 12/1-12/3")[0] == ["Ленина 12/1-12/3"]
