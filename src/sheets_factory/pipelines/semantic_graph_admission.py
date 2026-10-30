"""A V3 mutation provider over an unchanged V2 financial source certificate.

Source financial admission, engineering evidence and later task quality are
separate contracts. The provider never relabels its compiler as the V2 source.
"""
from __future__ import annotations
from copy import deepcopy
import importlib.util
from pathlib import Path

from ..core.node import BaseNode,TaskRejected
from ..nodes.scc_activity import SCCConstructNode
from ..task_adapters.composite_semantic_family_v3 import ADAPTER_ID as PROVIDER_ID
from ..task_adapters.composite_full_family_v2 import ADAPTER_ID as SOURCE_ADAPTER
from ..task_adapters.public_input_priority import append_rule,canonical,checked,read,ref,require,sha,write
from ..task_adapters.public_workbook_scope import append_scope,CLAUSES
from .scc_activity_admission import validate_financial_admission,validate_scope_inventory,upstream_binding,IMAGE_ID
from .presented_numeric_timing import validate_presented_numeric_timing
from .joint_repair_activity import METHOD as JOINT_METHOD,validate_physical_edits,describe_joint_delta
from ..task_adapters.lease_family import compare_exact_typed

SETTING='semantic_graph_mutation'
SOURCE_KIND='derived_financial_source_with_semantic_mutation_provider_v3'


def node_binding():
    from ..nodes import scc_activity
    return {'ordinary_construction':upstream_binding(),'inherited_joint_construct':ref(scc_activity.__file__),
            'semantic_integration':ref(__file__)}


def validate_setting(setting):
    require(isinstance(setting,dict)and setting.get('enabled')is True
            and type(setting.get('version'))is int and setting['version']==1
            and setting.get('contract')==JOINT_METHOD and setting.get('nodes')==node_binding(),
            'V3 requires an explicit separately bound joint-workbook mutation setting')
    manifest=read(setting['bindings'])
    require(manifest.get('kind')=='semantic_graph_v3_source_and_provider_bindings'
            and manifest.get('version')==1,'Unsupported V3 mutation-source binding manifest')
    return manifest


def load_provider(provider):
    require(provider.get('id')==PROVIDER_ID,'V3 mutation provider identity differs')
    implementation=checked(provider['implementation'])
    spec=importlib.util.spec_from_file_location('sheets_factory.task_adapters._bound_semantic_'+provider['implementation']['sha256'],implementation)
    require(spec is not None and spec.loader is not None,'The bound V3 mutation provider cannot be loaded')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    require(getattr(result,'ADAPTER_ID',None)==PROVIDER_ID and callable(getattr(result,'compile_semantic_mutation',None))
            and sha(implementation)==provider['implementation']['sha256'],'V3 provider API or source changed')
    return result


def validate_plan_binding(binding,plan):
    inventory=read(binding['scope_inventory']);edits=plan.get('edits',[])
    validate_scope_inventory(inventory,edits)
    require(plan.get('family_adapter',{}).get('id')==PROVIDER_ID
            and canonical(edits)==binding['edits_sha256']
            and type(binding.get('root_count'))is int and len(edits)==binding['root_count'],
            'V3 plan provider, complete root set or physical edit hash differs')
    ranges=plan.get('mask_ranges',[])
    require(not plan.get('scenario_inputs')and type(ranges)is list and not ranges,
            'V3 debugging cannot change financial inputs or declare FM targets')
    return inventory


def validate_source_and_provider(binding,*,plan=None):
    require(binding.get('kind')=='financial_source_with_separate_semantic_mutation_provider'
            and binding.get('source_presentation_adapter')==SOURCE_ADAPTER,
            'V3 must retain the V2 presented-source identity separately from mutation')
    validate_financial_admission(binding)
    validate_presented_numeric_timing(binding['public_input_priority_audit'],binding)
    inventory=read(binding['scope_inventory']);provider=binding['mutation_provider']
    require(inventory.get('adapter')==SOURCE_ADAPTER,'The source financial inventory identity was relabelled')
    compiler=load_provider(provider);policy=read(provider['policy'])
    compiler.validate_policy(policy)
    require(canonical(policy)==provider.get('policy_sha256'),'The V3 policy digest differs')
    report=read(provider['offline_compilation'])
    require(report.get('offline_compile_complete')is True and report.get('adapter')==PROVIDER_ID
            and report.get('source')==binding['source']and report.get('policy')==policy
            and report.get('scope_inventory_sha256')==canonical(inventory)
            and report.get('edits_sha256')==binding.get('edits_sha256')==canonical(report['edits'])
            and report.get('root_count')==binding.get('root_count')==report.get('compiled_root_count')
            and report.get('unsatisfied_roots')==[],
            'The complete offline provider report does not bind this actual source and policy')
    require(report.get('mutation_provider_recipe',{}).get('mutation_provider')==provider['implementation'],
            'The offline compilation was not produced by the bound frozen V3 implementation')
    for record in report['mutation_provider_recipe'].values():checked(record)
    validate_scope_inventory(inventory,report['edits'])
    if plan is not None:validate_plan_binding(binding,plan)
    return compiler,policy


def validate_engineering(binding,probe_ref):
    """Re-read two real passes and full-D; this certifies no later quality stage."""
    probe=read(probe_ref);plan=read(probe['plan'])
    recipe=read(binding['engineering_execution_recipe'])
    require(isinstance(recipe,dict)and recipe,'The actual V3 engineering execution recipe is missing')
    for record in recipe.values():checked(record)
    validate_plan_binding(binding,plan)
    require(probe.get('kind')=='semantic_graph_v3_joint_engineering_probe'
            and probe.get('status')=='joint_engineering_probe_complete_not_task_admitted'
            and probe.get('source_binding')=={k:binding[k]for k in
                ('source','source_manifest','scope_inventory','financial_admission','public_input_priority_audit')}
            and probe.get('source_identity_unchanged')==SOURCE_ADAPTER
            and probe.get('mutation_provider')==binding['mutation_provider']
            and probe.get('baseline')==binding['source']
            and probe.get('root_count')==binding['root_count']and probe.get('edits_sha256')==binding['edits_sha256'],
            'The actual V3 engineering evidence binds another source, provider or root set')
    require(probe.get('actual_LO_recalculations')==2 and probe.get('exact_typed_stable')is True
            and probe.get('individual_or_marginal_activity_tested')is False
            and probe.get('qualified')is False and probe.get('task_count')==0
            and probe.get('five_controls_recovery_quality_Harbor_pending')is True
            and all(probe.get(k)==0 for k in ('SCC_executions','LLM_calls','quality_calls','strong_calls')),
            'V3 engineering cannot certify controls, quality, isolated activity or difficulty')
    calls=read(probe['engine_calls'])
    require(isinstance(calls,list)and len(calls)==2
            and [x.get('phase')for x in calls]==['mutant_normalize','mutant_second_recalculation']
            and all(x.get('completed')is True and x.get('backend')=='libreoffice_uno_docker'
                    and x.get('image_id')==IMAGE_ID and x.get('network')=='none'for x in calls),
            'V3 requires both actual pinned network-isolated engineering passes')
    for call in calls:checked(call['input']);checked(call['output'])
    injection=read(probe['raw_injection'])
    require(injection.get('passed')is True and injection.get('exact_formula_edit_set')is True
            and injection.get('mutated_root_cached_values_removed')is True
            and injection.get('edits_sha256')==binding['edits_sha256']
            and injection.get('baseline')==binding['source']and injection.get('plan')==probe['plan']
            and injection.get('raw_mutant')==calls[0]['input']
            and calls[0]['output']==probe['input']and calls[1]['input']==probe['input']
            and calls[1]['output']==probe['second_pass'],
            'The raw V3 injection or actual execution artifact chain differs')
    goal=checked(binding['source']);actual=checked(probe['input']);stable=checked(probe['second_pass'])
    validate_physical_edits(goal,checked(calls[0]['input']),plan['edits'])
    require(read(probe['physical_validation'])==validate_physical_edits(goal,actual,plan['edits'])
            and read(probe['stable_definition_validation'])==validate_physical_edits(actual,stable,[]),
            'V3 physical roots or protected definitions changed')
    stability=compare_exact_typed(actual,stable)
    require(stability.get('passed')is True and read(probe['stability'])==stability,
            'The complete V3 input is not exact typed stable')
    summary=describe_joint_delta(goal,actual,plan['edits'],read(probe['full_delta']))
    errors=read(probe['native_errors'])
    goal_errors={x['cell']:x['value']for x in summary['native_goal_errors']}
    input_errors={x['cell']:x['value']for x in summary['native_input_errors']}
    introduced={k:v for k,v in input_errors.items()if goal_errors.get(k)!=v}
    require(errors=={'source':goal_errors,'mutant':input_errors,'second':input_errors,'introduced':introduced}
            and probe.get('introduced_error_count')==len(introduced),
            'The complete V3 native-error artifact differs from actual stable cached values')
    require(probe.get('expected_change_count')==summary['complete_required_D_count']
            and probe.get('changed_edited_root_count')==summary['physical_edits_in_actual_D_count']
            and probe.get('unchanged_edited_root_count')==summary['unobservable_physical_edit_count']
            and probe.get('mutant_error_count')==len(summary['native_input_errors'])
            and probe.get('source_error_count')==len(summary['native_goal_errors']),
            'V3 full-D, unchanged roots or native error evidence differs')
    return {'engineering_probe':deepcopy(probe_ref),'activity_contract':JOINT_METHOD,
        'physical_formula_mutation_count':len(plan['edits']),
        'complete_required_D_count':summary['complete_required_D_count'],
        'physical_edits_in_actual_D_count':summary['physical_edits_in_actual_D_count'],
        'unobservable_physical_edit_count':summary['unobservable_physical_edit_count'],
        'native_input_error_count':len(summary['native_input_errors']),
        'actual_engine_calls':deepcopy(probe['engine_calls']),
        'individual_or_marginal_activity_claimed':False,'five_controls_recovery_quality_Harbor_pending':True,
        'quality_recovery_difficulty_certified':False}


def validate_seed(entry,setting):
    manifest=validate_setting(setting);binding=entry['semantic_graph_binding']
    require(entry.get('source_kind')==SOURCE_KIND and entry.get('modes')==['debugging']
            and type(entry.get('variant',0))is int and entry.get('variant',0)==0
            and manifest.get('sources',{}).get(entry.get('sha256'))==binding,
            'V3 seed must be a separate explicit full-graph debugging provider')
    require(entry.get('mutation_provider')==binding['mutation_provider']
            and entry.get('source_manifest')==binding['source_manifest']
            and entry.get('sha256')==binding['source']['sha256']
            and Path(entry['local_path']).resolve()==checked(binding['source'])
            and entry.get('task_adapter')is None,
            'V3 may not masquerade as the V2 compiler or change its financial source')
    validate_source_and_provider(binding)
    engineering=validate_engineering(binding,entry['engineering_probe'])
    return {'workbook':deepcopy(binding['source']),'source_manifest':deepcopy(binding['source_manifest']),
        'financial_admission':deepcopy(binding['financial_admission']),
        'public_input_priority_audit':deepcopy(binding['public_input_priority_audit']),
        'scope_inventory':deepcopy(binding['scope_inventory']),'mutation_provider':deepcopy(binding['mutation_provider']),
        'engineering':engineering,'validation_method':'transitive_independent_financial_audits_through_full_exact_typed_equivalence',
        'quality_recovery_difficulty_certified':False}


def validate_context_binding(ctx,*,require_plan=True):
    setting=ctx.config.get(SETTING);provider=ctx.data.get('finance_evidence',{}).get('mutation_provider')
    if setting is None:
        require(provider is None,'An explicit V3 provider requires its separate admission setting')
        return None
    manifest=validate_setting(setting);identity=sha(ctx.source)
    binding=manifest.get('sources',{}).get(identity)
    if binding is None:
        require(provider is None,'The explicit V3 provider has no actual source binding')
        return None
    require(ctx.mode=='debugging'and sha(ctx.data['baseline'])==identity==binding['source']['sha256']
            and Path(ctx.source).resolve()==checked(binding['source'])and provider==binding['mutation_provider'],
            'V3 source, baseline, mode or mutation-provider context changed')
    require(ctx.data['finance_evidence'].get('full_graph_financial_admission')==binding['financial_admission']
            and ctx.data['finance_evidence'].get('source_presentation_adapter')==SOURCE_ADAPTER,
            'V3 context lost its separate financial source admission')
    validate_source_and_provider(binding,plan=ctx.data['plan']if require_plan else None)
    if require_plan:
        require(CLAUSES['debugging']in ctx.data['plan']['public_instruction'],
                'The V3 task lacks its explicit public preservation scope')
    return {'source_binding':binding,'activity_contract':JOINT_METHOD,'proof_limits':{},
        'allow_constant_index_ancestors':False,'provider':None,'setting':setting}


class SemanticGraphPlanNode(BaseNode):
    node_id='plan'
    def execute(self,ctx):
        binding=validate_context_binding(ctx,require_plan=False)
        require(binding is not None,'The V3 plan node requires explicit separate mutation admission')
        source=binding['source_binding'];compiler,policy=validate_source_and_provider(source)
        plan=compiler.compile_semantic_mutation(ctx.data['baseline'],read(source['scope_inventory']),policy)
        validate_plan_binding(source,plan)
        original=deepcopy(plan)
        require(plan.get('mask_ranges')==[],'The V3 compiler declared unsupported FM targets')
        plan.pop('mask_ranges')
        plan=append_scope(append_rule(plan),'debugging')
        plan['reference_evidence'].append({'kind':'hash_bound_presented_source_and_separate_mutation_provider',
            'financial_admission':source['financial_admission'],'scope_inventory':source['scope_inventory'],
            'numeric_timing_audit':source['public_input_priority_audit'],'mutation_provider':source['mutation_provider'],
            'new_independent_journal_execution_claimed':False})
        plan['family_adapter'].update(root_proof_route=JOINT_METHOD,individual_or_marginal_activity_claimed=False)
        validate_plan_binding(source,plan)
        ctx.save('semantic_graph_plan_binding.json',{'source':source['source'],'financial_admission':source['financial_admission'],
            'source_presentation_adapter':SOURCE_ADAPTER,'mutation_provider':source['mutation_provider'],
            'root_count':len(plan['edits']),'edits_sha256':canonical(plan['edits']),
            'before_plan_sha256':canonical(original),'after_plan_sha256':canonical(plan),
            'empty_FM_only_mask_field_removed':True,'controls_recovery_quality_difficulty_certified':False})
        return {'plan':plan,'source_assessment':{'financial_evidence':ctx.data['finance_evidence'],
            'authoring_backend':PROVIDER_ID,'activity_quality_difficulty_pending':True}}


class SemanticGraphConstructNode(SCCConstructNode):
    """Keep the ordinary SCCConstruct body and joint proof, change only admission."""
    def execute(self,ctx):
        try:binding=validate_context_binding(ctx)
        except ValueError as error:raise TaskRejected('Q06: V3 semantic admission rejected: '+str(error))from error
        if binding is None:return super().execute(ctx)
        return self._execute_scc(ctx,binding)
