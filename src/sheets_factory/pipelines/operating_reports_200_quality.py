"""Opaque FM admission for the one frozen hypothetical 200-business report."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType
import weakref

from . import heterogeneous_native_quality as base
from .linear_capital_quality import References, ROOT, reference, require

SETTING = 'operating_reports_200_reference_quality'
REGISTRY = ROOT/'config/task_adapters/operating_reports_200_quality_nodes.yaml'
PROFILE = base.PROFILE
BOUNDARY = ROOT/'scripts/validate_operating_reports_200_tasks_revision2.py'
BOUNDARY_SHA = '9b09e434e0cbe0dfbb7b97d825bb8b457167558fc8f72be50234a2a9010763ee'
NORMAL_SOURCE_KIND = 'fixed_operating_reports_200_actual_financial_modeling_view'
SPECIFICATION_SHA = '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
TERMINAL_SHA = 'fba1c365aeead7902953dd1b8c6877ece8687fd35e757ec3e5286a53e3cf67aa'
DEV_PROBE = ROOT/'outputs/difficulty/operating-reports-200-first-development-v6-revision2-20261031T224700Z/prepared/probe_manifest.json'
DEV_PROBE_SHA = 'f66c469070426d9c80058aade5836c7546e1b577d334b796bb4ccb2675f5b01d'
FIRST_MATERIAL = '264ebd2acda6f8c8c08e0a1ae23cf3b715b55e537cb83b8d654c136cce302c43'
IO_APPENDIX = b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
BASE_SHA = 'ac87f3544c1e14f42827b93e895e59015554d93fc6c59b054f54084beeff1b86'
_LIVE = weakref.WeakSet()


def setting():
    return {'version': 1, 'scope': 'fixed200_complete_declared_business_outputs',
        'pipeline': reference(__file__), 'nodes': reference(ROOT/'src/sheets_factory/task_adapters/operating_reports_200_quality.py'),
        'registry': reference(REGISTRY), 'runtime_profile': reference(PROFILE), 'actual_task_boundary': reference(BOUNDARY)}


def boundary():
    require(reference(BOUNDARY)['sha256'] == BOUNDARY_SHA, 'The exact fixed200 revision2 engineering validator changed')
    definition = importlib.util.spec_from_file_location('_fixed200_quality_engineering', BOUNDARY)
    helper = importlib.util.module_from_spec(definition); definition.loader.exec_module(helper)
    return helper


class OperatingReportsAdmission:
    def __init__(self, validation_terminal):
        self.references = References(); self.helper = boundary()
        actual_ref = reference(validation_terminal['path'] if isinstance(validation_terminal, dict) else validation_terminal)
        require(actual_ref['sha256'] == TERMINAL_SHA, 'Select the exact retained passed fixed200 task8 revision2')
        if isinstance(validation_terminal, dict): self.references.check(validation_terminal)
        actual = self.helper.validate_completed(actual_ref)
        require(actual['kind'] == 'complete_fixed_operating_reports_200_task_engineering_revision2'
            and actual['version'] == 1 and actual['passed'] is True
            and actual['actual_LO_calls_started'] == actual['actual_LO_calls_completed'] == 8
            and actual['normal_all12_QA_passed'] is actual['qualified'] is False,
            'Only genuine complete fixed200 engineering may enter normal review')
        prepared = self.helper.read(actual['preparation'])
        require(prepared['kind'] == 'prepared_fixed_operating_reports_200_task_engineering_revision2'
            and prepared['financial_target_count'] == 62322 and prepared['independent_business_field_count'] == 93510
            and self.helper.source.schema.canonical_sha256(self.helper.read(prepared['specification'])) == SPECIFICATION_SHA,
            'The fixed raw assumptions and complete business scope changed')
        material = actual['records']['modes']['financial_modeling']
        require(material['complete_D_count'] == 62322 and material['goal'] == prepared['genuine_goal']
            and material['controls'] == {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0},
            'The complete FM changed set or five-control proof changed')
        dev_ref = reference(DEV_PROBE); require(dev_ref['sha256'] == DEV_PROBE_SHA, 'The spent first-v6 material snapshot changed')
        development = self.helper.read(dev_ref)['modes']['financial_modeling']
        business = self.helper.checked(material['instruction']).read_bytes()
        rendered = self.helper.checked(development['rendered_instruction']).read_bytes()
        require(development['input'] == material['input'] and development['goal'] == material['goal']
            and development['material_task_version']['sha256'] == FIRST_MATERIAL
            and development['original_instruction']['sha256'] == material['instruction']['sha256']
            and len(business) == 403 and rendered == business+IO_APPENDIX and len(rendered) == 494,
            'Preserve the original first-v6 input, goal and exact brief with its existing IO appendix')
        self.recipe = {}
        for path, record in self.helper.recipes().items():
            self.references.check(record); self.recipe[path] = record['sha256']
        for path in (BOUNDARY, Path(__file__), Path(base.__file__)):
            record = reference(path); self.references.check(record); self.recipe[record['path']] = record['sha256']
        self.references.discover(actual_ref); self.references.discover(dev_ref)
        # These large JSON objects are interpreted by nodes, so guard the
        # complete original bytes explicitly; no persisted pass replaces cold validation.
        for key in ('definition', 'source_definition', 'expected', 'bindings', 'specification', 'candidate_preparation'):
            self.references.check(prepared[key])
        self.evidence = {'actual_ref': actual_ref, 'actual': actual, 'preparation': prepared,
            'material': material, 'development_snapshot': dev_ref, 'development_material': development}
        self.proof = {'kind': 'opaque_fixed200_financial_modeling_reference_admission', 'version': 1,
            'mode': 'financial_modeling', 'workbook': material['goal'], 'input': material['input'], 'goal': material['goal'],
            'instruction': development['rendered_instruction'], 'original_business_instruction': material['instruction'],
            'actual_validation': actual_ref, 'source_manifest': actual['source_manifest'],
            'specification': prepared['specification'], 'independent_expected': prepared['expected'],
            'independent_scope': prepared['expected'],
            'definition': prepared['definition'], 'full_D_controls': material['full_D_controls'],
            'independent_scope_count': 93510, 'forecast_mask_count': 62322, 'complete_D_count': 62322,
            'first_development_material_identity': FIRST_MATERIAL, 'runtime_profile': prepared['runtime_profile'],
            'original_dev_and_normal_scores_transferred': False, 'qualified': False}
        self.identity = deepcopy(self.proof)
        self.evidence_sha = hashlib.sha256(json.dumps(self.evidence, sort_keys=True).encode()).hexdigest()
        _LIVE.add(self); self.guard()

    def guard(self):
        require(type(self) is OperatingReportsAdmission and self in _LIVE and self.proof == self.identity,
            'A live exact fixed200 opaque admission is required')
        self.references.guard()
        require(hashlib.sha256(json.dumps(self.evidence, sort_keys=True).encode()).hexdigest() == self.evidence_sha,
            'The admitted fixed200 evidence changed in memory')
        current = {path: record['sha256'] for path, record in self.helper.recipes().items()}
        require(all(current.get(path, reference(path)['sha256']) == digest for path, digest in self.recipe.items()),
            'The complete fixed200 task/source recipe changed')
        return deepcopy(self.proof)


NativeScopeAdmission = OperatingReportsAdmission


def admission(value):
    require(type(value) is OperatingReportsAdmission and value in _LIVE,
        'Persisted JSON, fabricated objects and other task families cannot admit fixed200')
    return value.guard()


def validate_seed(seed, admissions):
    require(seed.get('source_kind') == NORMAL_SOURCE_KIND and seed.get('variant') == 0
        and seed.get('modes') == ['financial_modeling'], 'Only the fixed FM view is selected; DBG is not difficulty-qualified')
    source = reference(seed['local_path']); proof = admission(admissions.get((source['sha256'], 'financial_modeling')))
    require(seed['sha256'] == source['sha256'] and proof['workbook'] == source
        and seed['finance_evidence']['scoped_task_admissions']['financial_modeling'] == proof,
        'The seed differs from its exact genuine current fixed200 proof')


require(reference(base.__file__)['sha256'] == BASE_SHA, 'The frozen generic native quality lifecycle changed')
_namespace = {**vars(base), **globals()}
_configuration = FunctionType(base.validate_configuration.__code__, _namespace, 'validate_configuration')


def validate_configuration(config):
    profile = _configuration(config)
    require(config['agents']['model'] == 'gpt-6-sol' and config['agents']['reasoning_effort'] == 'high'
        and config['run']['targets'] == {'financial_modeling': 1, 'debugging': 0},
        'Keep one fixed FM normal review and the ordinary quality model')
    return profile


class NativeQualityFactory(base.NativeQualityFactory):
    """The unchanged generic factory implementation in this family namespace."""


_namespace.update(globals())
for _method in ('__init__', 'load_seeds', 'run_phase', '_claim_targets'):
    _old = getattr(base.NativeQualityFactory, _method)
    _new = FunctionType(_old.__code__, _namespace, _old.__name__, _old.__defaults__, _old.__closure__)
    _new.__kwdefaults__ = _old.__kwdefaults__
    setattr(NativeQualityFactory, _method, _new)
