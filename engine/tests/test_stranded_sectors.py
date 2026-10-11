"""Stranded-asset sector matching works on whole words and excludes low-carbon labels."""

import pytest

from models.sustainability import is_stranded_sector


@pytest.mark.parametrize(
    "sector",
    ["Energy", "energy", "Oil & Gas E&P", "Coal", "Utilities", "Gas Utilities", "Petroleum Refining"],
)
def test_fossil_linked_sectors_are_stranded(sector):
    assert is_stranded_sector(sector)


@pytest.mark.parametrize(
    "sector",
    ["Renewable Energy", "Clean Energy", "Utilities - Renewable", "Solar", "Technology", "Financials", "", None],
)
def test_other_sectors_are_not_stranded(sector):
    assert not is_stranded_sector(sector)


@pytest.mark.parametrize("sector", ["Soilless Farming", "Vegas Resorts", "Cocoal"])
def test_matching_is_on_whole_words_not_substrings(sector):
    assert not is_stranded_sector(sector)
