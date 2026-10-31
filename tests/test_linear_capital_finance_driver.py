import importlib.util
from pathlib import Path

import pytest

from sheets_factory.workbook.linear_capital_portfolio import candidate_a, ledger


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    descriptor = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(descriptor)
    descriptor.loader.exec_module(module)
    return module


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    raw = load('prepare_linear_capital_portfolio')
    driver = load('run_linear_capital_finance')

    def forbidden(*args, **kwargs):
        raise AssertionError('Preparation must not run a financial forward')

    monkeypatch.setattr(candidate_a, 'simulate_universe', forbidden)
    monkeypatch.setattr(ledger, 'simulate_universe', forbidden)
    original = raw.prepare(tmp_path / 'raw')
    output = tmp_path / 'finance'
    record = driver.prepare(original['path'], output)
    return driver, output, record, original


def test_preparation_binds_every_recipe_and_all_declared_plans_without_execution(prepared):
    driver, output, record, raw = prepared
    result = driver.read(record)
    assert result['raw_preparation'] == raw
    assert len(result['recipe']) == 7
    assert len(result['diagnostic_plan_ids']) == 18
    assert result['optimizer_calls'] == result['LO_calls'] == result['model_calls'] == 0
    assert not (output / 'started.json').exists()
    driver.validate(output)


def test_mutated_raw_preparation_is_rejected_before_execution(prepared):
    driver, output, _, original = prepared
    path = Path(original['path'])
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='frozen input changed'):
        driver.validate(output)
    assert not (output / 'started.json').exists()


def test_existing_started_attempt_rejected_without_starting_dashboard_or_finance(prepared):
    driver, output, _, _ = prepared
    marker = output / 'started.json'
    marker.write_text('{"preserve":true}')
    with pytest.raises(ValueError, match='first actual finance attempt'):
        driver.execute(output)
    assert marker.read_text() == '{"preserve":true}'
    assert not (output / 'audit').exists()
    assert not (output / 'failure.json').exists()
    assert not (output / 'terminal.json').exists()
