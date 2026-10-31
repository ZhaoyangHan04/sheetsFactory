"""The public CLI must work without mutating a frozen source adapter."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'scripts/run_linear_capital_producer_source.py'


@pytest.fixture
def cli(monkeypatch):
    definition = importlib.util.spec_from_file_location('_tested_linear_source_cli', PATH)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    calls = []

    def record(name):
        def call(*args, **kwargs):
            calls.append((name, args, kwargs))
            return {'path': name, 'sha256': '0'*64, 'bytes': 1}
        return call

    provider = SimpleNamespace(DEFAULT_PROFILE=Path('frozen_default_profile.json'),
        **{name: record(name) for name in ('prepare', 'execute_prepared', 'validate_prepared', 'reference')})
    monkeypatch.setattr(module, '_provider', lambda: provider)
    return module, calls


def test_real_help_has_no_provider_or_pipeline_side_effects():
    result = subprocess.run([sys.executable, str(PATH), '--help'], capture_output=True, text=True)
    assert result.returncode == 0
    assert '--prepared' in result.stdout and '--run' in result.stdout


def test_real_cli_provider_has_the_original_callable_apis_and_fixed_profile():
    definition = importlib.util.spec_from_file_location('_real_linear_source_cli', PATH)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    provider = module._provider()
    assert all(callable(getattr(provider, name)) for name in
               ('prepare', 'execute_prepared', 'validate_prepared', 'reference'))
    assert provider.DEFAULT_PROFILE == ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'


@pytest.mark.parametrize('arguments', [
    [], ['--spec', 's'], ['--reference', 'r', '--output', 'o'],
    ['--prepared', 'p', '--spec', 's'], ['--prepared', 'p', '--reference', 'r'],
    ['--prepared', 'p', '--output', 'o'], ['--prepared', 'p', '--profile', 'q'],
    ['--prepared', 'p', '--port', '-1'], ['--prepared', 'p', '--port', '65536'],
])
def test_invalid_or_mixed_modes_cannot_load_or_start_provider(cli, monkeypatch, arguments):
    module, calls = cli
    monkeypatch.setattr(module, '_provider', lambda: pytest.fail('Invalid arguments reached the source provider'))
    with pytest.raises(SystemExit) as error:
        module.main(arguments)
    assert error.value.code == 2 and not calls


def test_existing_preparation_is_validated_without_restarting(cli, capsys):
    module, calls = cli
    assert module.main(['--prepared', 'p']) == 0
    assert calls == [('validate_prepared', (Path('p'),), {}),
                     ('reference', (Path('p/preparation.json'),), {})]
    assert json.loads(capsys.readouterr().out)['path'] == 'reference'


def test_explicit_run_uses_frozen_preparation_without_new_prepare(cli):
    module, calls = cli
    assert module.main(['--prepared', 'p', '--run', '--port', '32123']) == 0
    assert calls == [('execute_prepared', (Path('p'),), {'port': 32123})]


@pytest.mark.parametrize('profile', [None, 'chosen_profile.json'])
def test_new_prepare_and_optional_execution_have_one_dispatch(cli, profile):
    module, calls = cli
    arguments = ['--spec', 's', '--reference', 'r', '--output', 'o']
    if profile is not None:
        arguments += ['--profile', profile, '--run']
    assert module.main(arguments) == 0
    assert calls[0] == ('prepare', (Path('s'), Path('r'), Path('o')),
                       {'profile': Path(profile or 'frozen_default_profile.json')})
    assert calls[1:] == ([] if profile is None else [('execute_prepared', (Path('o'),), {'port': 0})])
