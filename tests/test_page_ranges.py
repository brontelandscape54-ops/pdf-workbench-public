import pytest

from pdf_workbench.core.page_ranges import parse_page_spec


def test_parse_page_spec_mixed_ranges() -> None:
    assert parse_page_spec("4,11-13,20", 30) == [3, 10, 11, 12, 19]


def test_parse_page_spec_deduplicates_and_allows_spaces() -> None:
    assert parse_page_spec("1, 3, 2-4, 4", 10) == [0, 1, 2, 3]


def test_parse_page_spec_periodic_range_uses_range_start_as_origin() -> None:
    assert parse_page_spec("4-30/7", 40) == [3, 10, 17, 24]


def test_parse_page_spec_periodic_range_can_express_page_multiples() -> None:
    assert parse_page_spec("4-20/4", 30) == [3, 7, 11, 15, 19]


def test_parse_page_spec_periodic_and_regular_parts_can_be_mixed() -> None:
    assert parse_page_spec("2,4-20/4,9-10", 30) == [1, 3, 7, 8, 9, 11, 15, 19]


@pytest.mark.parametrize(
    "spec",
    [
        "",
        "1,,3",
        "3-1",
        "0",
        "11",
        "a",
        "1-2-3",
        "4-10/0",
        "4-10/a",
        "4/2",
        "4-10/2/3",
    ],
)
def test_parse_page_spec_rejects_invalid_values(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_page_spec(spec, 10)
