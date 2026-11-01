"""The new review keeps source scope and public/private checks explicit."""
import importlib.util
from pathlib import Path
import pytest
from sheets_factory.workbook.operating_reports_200 import raw
from sheets_factory.workbook.associate_bridge_v1 import spec as bridge
from sheets_factory.workbook.tax_vintage_bridge_v2 import spec

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('_tax_vintage_review_test',ROOT/'scripts/run_tax_vintage_shared_review.py')
driver=importlib.util.module_from_spec(loader);loader.loader.exec_module(driver)


def test_public_and_reference_review_keep_distinct_assigned_checks():
    assert not set(driver._N['PUBLIC']) & set(driver._N['PRIVATE'])
    assert set(driver._N['PUBLIC']+driver._N['PRIVATE']) == {f'Q{i:02d}' for i in range(1,13)}
    public=driver.prompt('financial_modeling','public')
    private=driver.prompt('debugging','reference')
    assert 'only input.xlsx and instruction.md' in public
    assert '291,000' in private and '93,510' not in private
    assert 'assessment-quarter payment lag' in public and 'assessment-quarter payment lag' in private
    assert 'Do not solve or submit' in public
    assert driver._N['ObservedReviewCLI']._build_command.__globals__ is driver._N


def test_correlated_inventory_omission_is_rejected_before_review_workspaces(tmp_path,monkeypatch):
    public=spec.build(bridge.build(raw.build_spec(),'B05'),'T01')
    expected=dict(spec.points(public)); assert len(expected)==291000
    expected.pop(next(iter(expected)))
    source={'specification':'public','bindings':'bindings'}
    objects={'batch':{'source':'source'},'source':source,'public':public,'bindings':{'financial':expected}}
    monkeypatch.setitem(driver._N,'read',lambda p:objects[p])
    output=tmp_path/'never-created'
    with pytest.raises(ValueError,match='binding inventory is incomplete'):
        driver.prepare('batch',output)
    assert not output.exists()


def test_frozen_review_base_tampering_blocks_all_calls(monkeypatch):
    monkeypatch.setattr(driver,'BASE_SHA','0'*64)
    with pytest.raises(ValueError,match='frozen review protocol'):
        driver.guard()
