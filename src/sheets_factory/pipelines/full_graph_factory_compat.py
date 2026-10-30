"""Explicit complete-DBG compatibility with the ordinary Factory target claim."""
from copy import deepcopy
from pathlib import Path
import hashlib

from .scc_activity_admission import SCCActivityFactory, ADAPTER, canonical
from ..core.node import TaskRejected

SETTING = 'full_graph_factory_compatibility'
METHOD = 'omit_empty_financial_modeling_range_field_for_complete_debug_graph_v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def implementation_binding():
    return {'path': str(Path(__file__).resolve()), 'sha256': sha(__file__)}


def upstream_binding():
    from . import factory
    return {'path': str(Path(factory.__file__).resolve()), 'sha256': sha(factory.__file__)}


def setting():
    return {'version': 1, 'method': METHOD, 'implementation': implementation_binding(),
            'upstream_factory': upstream_binding()}


def validate_setting(config):
    record = config.get(SETTING)
    if not isinstance(record, dict) or type(record.get('version')) is not int or record != setting():
        raise ValueError('Complete-DBG Factory compatibility must be explicit and exactly source-bound')


class FullGraphFactoryCompat(SCCActivityFactory):
    """All ordinary phases remain inherited; only empty FM-only metadata differs."""

    def __init__(self, config, *args, **kwargs):
        validate_setting(config)
        super().__init__(config, *args, **kwargs)

    def _claim_targets(self, context):
        validate_setting(self.config)
        plan = context.data['plan']
        if context.mode == 'debugging' and 'mask_ranges' in plan:
            ranges = plan['mask_ranges']
            if type(ranges) is not list or ranges:
                raise TaskRejected('Q06: complete debugging cannot declare financial-modeling mask ranges')
            if plan.get('family_adapter', {}).get('id') != ADAPTER:
                raise TaskRejected('Q06: empty range compatibility requires the explicit complete financial graph adapter')
            normalized = deepcopy(plan)
            del normalized['mask_ranges']
            assert {k: v for k, v in plan.items() if k != 'mask_ranges'} == normalized
            context.data['plan'] = normalized
            context.save('factory_plan_schema_compatibility.json', {
                'version': 1, 'method': METHOD, 'removed_field': 'mask_ranges', 'removed_value': [],
                'adapter': ADAPTER, 'before_plan_sha256': canonical(plan),
                'after_plan_sha256': canonical(normalized), 'edits_sha256': canonical(normalized['edits']),
                'physical_edit_count': len(normalized['edits']),
                'public_instruction_rules_source_and_edits_unchanged': True,
                'normal_overlap_claim_and_fingerprint_still_required': True,
                'quality_or_difficulty_certified': False})
        return super()._claim_targets(context)
