"""Normal Factory phases for a separately admitted complete V3 mutation provider."""
from copy import deepcopy
from pathlib import Path

from ..core.node import TaskRejected
from .factory import FactoryPipeline
from .semantic_graph_admission import (SETTING,SOURCE_KIND,PROVIDER_ID,SOURCE_ADAPTER,
    validate_seed,validate_setting,validate_plan_binding)
from ..task_adapters.public_input_priority import canonical,require,sha


class SemanticGraphFactory(FactoryPipeline):
    def __init__(self,config,*args,**kwargs):
        validate_setting(config.get(SETTING))
        require(not config.get('scc_activity',{}).get('enabled')
                and not config.get('joint_repair_activity',{}).get('enabled'),
                'The independent V3 provider cannot reuse or impersonate V2 activity dispatch')
        super().__init__(config,*args,**kwargs)

    def load_seeds(self):
        seeds=super().load_seeds()
        for seed in seeds:
            require(seed.get('source_kind')==SOURCE_KIND,'The V3-only entry cannot silently admit other seed kinds')
            proof=validate_seed(seed,self.config[SETTING]);evidence=seed.get('finance_evidence',{})
            require(evidence.get('audited_source_binding')==proof
                    and evidence.get('mutation_provider')==seed['mutation_provider']
                    and evidence.get('full_graph_financial_admission')==seed['semantic_graph_binding']['financial_admission']
                    and evidence.get('source_presentation_adapter')==SOURCE_ADAPTER
                    and evidence.get('task_adapter')is None,
                    'V3 financial source admission and separate provider evidence changed')
            seed['survey']={**seed.get('survey',{}),'normalized_path':proof['workbook']['path'],
                'source_sha256':seed['sha256'],'status':'ok','error_count':0}
        return seeds

    def run_phase(self,context,phase):
        result=super().run_phase(context,phase)
        if context.data.get('baseline'):
            require(sha(context.data['baseline'])==context.data['source_id'],
                    'The V3 normalized source changed the immutable admitted financial goal')
        return result

    def _claim_targets(self,context):
        # Normal V3 planning removes this empty FM-only field. The narrow guard
        # also handles an otherwise valid normal repair plan without rerouting
        # debugging into the FM range compiler.
        plan=context.data['plan']
        require(context.mode=='debugging'and plan.get('family_adapter',{}).get('id')==PROVIDER_ID,
                'V3 target claiming requires the explicit separate debugging provider')
        binding=context.data['finance_evidence']['semantic_graph_binding']
        validate_plan_binding(binding,plan)
        if'mask_ranges'in plan:
            if type(plan['mask_ranges'])is not list or plan['mask_ranges']:
                raise TaskRejected('Q06: V3 debugging cannot declare financial-modeling mask ranges')
            normalized=deepcopy(plan);normalized.pop('mask_ranges')
            context.data['plan']=normalized
            context.save('semantic_factory_empty_mask_compatibility.json',{
                'provider':PROVIDER_ID,'source_presentation_adapter':SOURCE_ADAPTER,
                'removed_field':'mask_ranges','removed_value':[],
                'before_plan_sha256':canonical(plan),'after_plan_sha256':canonical(normalized),
                'edits_sha256':canonical(normalized['edits']),'physical_edit_count':len(normalized['edits']),
                'normal_overlap_claim_and_fingerprint_still_required':True,
                'quality_or_difficulty_certified':False})
        return super()._claim_targets(context)
