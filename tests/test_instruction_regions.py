"""Exact public edit scopes must stay readable without hiding extra cells."""
import random
import re

from openpyxl.utils.cell import get_column_letter, range_boundaries

from sheets_factory.nodes.construction import compact_target_regions


def expand(text):
    cells = set()
    for item in text.split('; '):
        match = re.fullmatch(r"'((?:[^']|'')+)'!([A-Z0-9:]+)", item)
        assert match
        sheet, region = match.groups()
        left, top, right, bottom = range_boundaries(region)
        for row in range(top, bottom + 1):
            for column in range(left, right + 1):
                key = (sheet.replace("''", "'"), get_column_letter(column) + str(row))
                assert key not in cells
                cells.add(key)
    return cells


def test_large_period_block_is_one_exact_readable_region():
    edits = [{'sheet': 'Cash Flow', 'cell': get_column_letter(c) + str(r)}
             for r in range(2, 24) for c in range(3, 39)]
    assert compact_target_regions(edits) == "'Cash Flow'!C2:AL23"


def test_holes_nonadjacent_periods_and_quoted_sheet_names_never_expand_scope():
    edits = [{'sheet': "Owner's Cash", 'cell': c} for c in ['A1', 'C1', 'A2', 'C2', 'A4', 'B4']]
    edits += [{'sheet': 'Tax', 'cell': 'XFD1048576'}]
    assert expand(compact_target_regions(edits)) == {(e['sheet'], e['cell']) for e in edits}


def test_sparse_unordered_scopes_round_trip_without_extra_or_missing_coordinates():
    rng = random.Random(73)
    edits = [{'sheet': 'Forecast', 'cell': get_column_letter(c) + str(r)}
             for r in range(1, 31) for c in range(1, 45) if rng.random() < .55]
    rng.shuffle(edits)
    assert expand(compact_target_regions(edits)) == {(e['sheet'], e['cell']) for e in edits}
