#!/usr/bin/env python3
"""Fresh normal quality with checked Q04 receipts; --prepared --run starts services."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import FunctionType, SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
UPSTREAM = Path(__file__).with_name('run_linear_capital_scaled_reference_quality.py')
UPSTREAM_SHA256 = '4df6616a67a491fa6824bd16a87744a7e5ddec64f5a8e8fd3d491714e232c516'
REGISTRY = ROOT/'config/task_adapters/linear_capital_scaled_receipt_review_nodes.yaml'
DEFAULT_CONFIG = ROOT/'config/pipelines/linear_capital_scaled_receipt_quality_v1.yaml'
KIND = 'prepared_complete_native_linear_capital_scaled_receipt_quality_v1'

if hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() != UPSTREAM_SHA256:
    raise ValueError('The frozen reference-review lifecycle changed')
_definition = importlib.util.spec_from_file_location('_receipt_reference_quality_upstream', UPSTREAM)
_upstream = importlib.util.module_from_spec(_definition); _definition.loader.exec_module(_upstream)
from sheets_factory.task_adapters import reference_receipt_diagnosis as receipt_node

reference, require = _upstream.reference, _upstream.require
_original_pipeline, _original_adapter = _upstream.pipeline, _upstream.adapter
_REVISION = yaml.safe_load(DEFAULT_CONFIG.read_text())['reference_receipt_revision']


def validate_registry():
    original = yaml.safe_load(_original_adapter.REGISTRY.read_text())
    expected = deepcopy(original)
    expected['nodes']['diagnose'] = 'sheets_factory.task_adapters.reference_receipt_diagnosis:ReferenceReceiptDiagnosisNode'
    require(yaml.safe_load(REGISTRY.read_text()) == expected,
        'Only the explicitly checked reference-receipt diagnosis node may differ')
    receipt_node.verify_dependencies()


def validate_configuration(config):
    validate_registry()
    require(config['pipeline']['node_registry'] == str(REGISTRY)
        and config.get('reference_receipt_revision') == _REVISION,
        'The exact receipt protocol registry and retained prior history are required')
    for record in _REVISION['prior_evidence']:
        require(reference(record['path']) == record, 'Prior protocol failure evidence changed')
    # The original validator checks every family setting, all twelve checks,
    # budgets and resources. The only allowed routing difference is above.
    baseline = deepcopy(config)
    baseline['pipeline']['node_registry'] = str(_original_adapter.REGISTRY)
    return _original_pipeline.validate_configuration(baseline)


class ReferenceReceiptQualityFactory(_original_pipeline.LinearCapitalQualityFactory):
    pass


_factory_namespace = dict(_original_pipeline.LinearCapitalQualityFactory.__init__.__globals__)
_factory_namespace['validate_configuration'] = validate_configuration
_original_init = _original_pipeline.LinearCapitalQualityFactory.__init__
ReferenceReceiptQualityFactory.__init__ = FunctionType(_original_init.__code__, _factory_namespace,
    _original_init.__name__, _original_init.__defaults__, _original_init.__closure__)
ReferenceReceiptQualityFactory.__init__.__kwdefaults__ = _original_init.__kwdefaults__

# The original family setting remains truthful and unchanged. This separate
# registry override is explicit, exact and additionally frozen in the recipe.
pipeline = SimpleNamespace(**{**vars(_original_pipeline),
    'validate_configuration': validate_configuration, 'LinearCapitalQualityFactory': ReferenceReceiptQualityFactory})
adapter = SimpleNamespace(**{**vars(_original_adapter), 'REGISTRY': REGISTRY})
_namespace = dict(vars(_upstream))
_namespace.update(__file__=__file__, __name__=__name__, DEFAULT_CONFIG=DEFAULT_CONFIG,
    KIND=KIND, pipeline=pipeline, adapter=adapter, _PREPARED_SESSIONS={})
_cloned = {}
for _name, _value in tuple(vars(_upstream).items()):
    if isinstance(_value, FunctionType) and _value.__globals__ is vars(_upstream):
        if _value not in _cloned:
            _function = FunctionType(_value.__code__, _namespace, _value.__name__,
                _value.__defaults__, _value.__closure__)
            _function.__kwdefaults__ = deepcopy(_value.__kwdefaults__)
            if _function.__kwdefaults__ and 'config_path' in _function.__kwdefaults__:
                _function.__kwdefaults__['config_path'] = DEFAULT_CONFIG
            _cloned[_value] = _function
        _namespace[_name] = _cloned[_value]
_base_recipes = _namespace['recipes']
_base_validate = _namespace['validate_prepared']


def recipes(config, admissions):
    rows = _base_recipes(config, admissions)
    for path in [UPSTREAM, Path(__file__), REGISTRY, DEFAULT_CONFIG,
                 _original_adapter.REGISTRY, Path(receipt_node.__file__), *receipt_node.DEPENDENCIES]:
        record = reference(path); rows[record['path']] = record['sha256']
    for record in _REVISION['prior_evidence']:
        require(reference(record['path']) == record, 'Prior protocol history changed')
        rows[record['path']] = record['sha256']
    return rows


def validate_prepared(output):
    frozen, config, admissions = _base_validate(output)
    require(frozen['kind'] == KIND
        and frozen['prior_source_or_task_quality_transferred'] is False
        and frozen['existing_development_score_transferred'] is False,
        'This fresh protocol revision cannot inherit old normal or development qualifications')
    validate_configuration(config)
    return frozen, config, admissions


_namespace.update(recipes=recipes, validate_prepared=validate_prepared)
prepare_many, prepare = _namespace['prepare_many'], _namespace['prepare']
execute_prepared, main = _namespace['execute_prepared'], _namespace['main']
_PREPARED_SESSIONS = _namespace['_PREPARED_SESSIONS']
validate_registry()

if __name__ == '__main__':
    raise SystemExit(main())
