"""UNO calculation orchestration tests without importing a host office runtime."""

import importlib.util
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setitem(sys.modules, "uno", types.ModuleType("uno"))
    for name in ("com", "com.sun", "com.sun.star", "com.sun.star.beans"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules["com.sun.star.beans"].PropertyValue = type("PropertyValue", (), {})
    path = Path(__file__).resolve().parents[1] / "src/sheets_factory/workbook/uno_recalculate.py"
    spec = importlib.util.spec_from_file_location("uno_convergence_test_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDocument:
    def __init__(self, states, iterative=True):
        self.states = states
        self.iterative = iterative
        self.calls = 0
        self.property_names = []
        self.snapshot_ranges = []

    def calculateAll(self):
        self.calls += 1

    def getPropertyValue(self, name):
        self.property_names.append(name)
        assert name == "IsIterationEnabled"
        return self.iterative

    def getSheets(self):
        assert self.iterative, "Ordinary workbooks must not incur iterative snapshots"
        document = self
        state = self.states[min(self.calls - 1, len(self.states) - 1)]

        class Sheets:
            def getElementNames(self):
                return tuple(state)

            def getByName(self, name):
                data = state[name]

                class Sheet:
                    def createCursor(self):
                        class Cursor:
                            def gotoEndOfUsedArea(self, expand):
                                assert expand is True

                            def getRangeAddress(self):
                                return types.SimpleNamespace(EndColumn=len(data[0]) - 1, EndRow=len(data) - 1)
                        return Cursor()

                    def getCellRangeByPosition(self, left, top, right, bottom):
                        document.snapshot_ranges.append((name, left, top, right, bottom))
                        assert (left, top, right, bottom) == (0, 0, len(data[0]) - 1, len(data) - 1)
                        return types.SimpleNamespace(getDataArray=lambda: data)
                return Sheet()
        return Sheets()


def state(principal, downstream=0):
    return {"Financing": (("Principal", principal),),
            "Statements": (("Tax", downstream), ("Other downstream cells", "preserved"))}


def test_noniterative_workbooks_keep_exactly_one_calculate_all_call(runner):
    document = FakeDocument([state(1)], iterative=False)
    result = runner.calculate_to_stability(document)
    assert result == {"passes": 1, "iterative": False}
    assert document.calls == 1
    assert document.property_names == ["IsIterationEnabled"]
    assert not document.snapshot_ranges


def test_already_stable_iterative_workbooks_require_two_unchanged_successions(runner):
    document = FakeDocument([state(11129000, 1027551.25)])
    result = runner.calculate_to_stability(document)
    assert result == {"passes": 3, "iterative": True, "full_used_area_stable": True}
    assert document.calls == 3


def test_real_financial_dependency_shape_waits_for_downstream_values_too(runner):
    document = FakeDocument([state(10955000, 1136597.25), state(11126000, 1029256.17),
                             state(11129000, 1027580.65), state(11129000, 1027551.25)])
    result = runner.calculate_to_stability(document)
    assert result["passes"] == document.calls == 6
    assert {item[0] for item in document.snapshot_ranges} == {"Financing", "Statements"}


def test_one_quiet_pass_does_not_hide_later_financial_propagation(runner):
    document = FakeDocument([state(10), state(10), state(11), state(11), state(11)])
    assert runner.calculate_to_stability(document)["passes"] == 5


def test_cell_types_and_unrounded_float_changes_are_part_of_stability(runner):
    document = FakeDocument([state(1, ""), state(1, 0.0), state(1, 0.0000000001)])
    assert runner.calculate_to_stability(document)["passes"] == 5


def test_every_used_cell_is_captured_in_the_snapshot(runner):
    document = FakeDocument([{"Small": (("label", 1),),
                              "Wide": ((0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11))}])
    document.calculateAll()
    snapshot = runner.calculation_snapshot(document)
    assert snapshot[1] == ("Wide", ((0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11)))
    assert document.snapshot_ranges[-1] == ("Wide", 0, 0, 3, 2)


def test_nonconvergence_is_rejected_at_the_outer_pass_limit(runner):
    document = FakeDocument([state(index % 2) for index in range(64)])
    with pytest.raises(RuntimeError, match="within 64 calculation passes"):
        runner.calculate_to_stability(document)
    assert document.calls == 64


def test_explicit_smaller_bound_still_cannot_claim_convergence(runner):
    document = FakeDocument([state(index) for index in range(7)])
    with pytest.raises(RuntimeError, match="within 7 calculation passes"):
        runner.calculate_to_stability(document, max_outer_passes=7)
    assert document.calls == 7
