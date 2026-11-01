"""Private FM-only reuse of the frozen report formulas and decimal decoder."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

from sheets_factory.workbook.operating_reports_200 import excel as original
from sheets_factory.workbook.operating_reports_200 import excel_revision2 as decoder
from . import schema

KIND='prepared_unverified_operating_reports_financial_cohort_fm_emission'
PLAN_KIND='unverified_operating_reports_financial_cohort_FM_view_plan'
SCHEMA_SHA='cf5732f4e2a8a17ec3d9e339791c3f372ed04a22665815951c79f6a31ed53be4'
BRIEF='Complete the FY2026 and FY2027 reports for all listed businesses, their management divisions and the master portfolio. Use the supplied FY2025 actuals, opening balances and business assumptions. The report labels and Read Me state the reporting conventions. Preserve supplied facts, historical reports and nonapplicable fields, and make the forecast reports consistent. The businesses are hypothetical.\n'


def reference(path):
    path=Path(path).resolve();raw=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def _providers():
    if SCHEMA_SHA=='PENDING_COHORT_SCHEMA_PIN' or reference(schema.__file__)['sha256']!=SCHEMA_SHA:
        raise ValueError('The final cohort schema must be pinned before rendering')
    for name,module in (('renderer',original),('renderer_revision2',decoder)):
        if reference(module.__file__)!=schema.contract()['frozen_ancestors'][name]:
            raise ValueError('The complete frozen renderer or finite-decimal decoder changed')


def recipes():
    _providers()
    return {**schema.recipes(),**{str(Path(p).resolve()):reference(p) for p in
        (__file__,original.__file__,decoder.__file__)}}


def _clone(module,**overrides):
    namespace={k:deepcopy(v) if isinstance(v,(dict,list,set)) or k in ('INPUT_FONT','OUTPUT_FILL') else v
        for k,v in vars(module).items()}
    namespace.update(overrides)
    for key,value in vars(module).items():
        if isinstance(value,FunctionType) and value.__globals__ is vars(module):
            cloned=FunctionType(value.__code__,namespace,value.__name__,value.__defaults__,value.__closure__)
            cloned.__kwdefaults__=deepcopy(value.__kwdefaults__);namespace[key]=cloned
    return namespace


def forecast_keys(public):
    return [key for key,kind in schema.points(public) if kind!='text'
        and key.split('/')[1].startswith(('2026','2027','FY2026','FY2027'))]


def _namespace(public):
    _providers();schema.validate_spec(public);facade=schema.for_seed(public['seed'])
    base=_clone(original,s=facade)
    def fm_views(source,out,public,bindings,ref,fact,source_formulas):
        mask=forecast_keys(public)
        base['_surgery'](source,out/'financial_modeling_input.xlsx',bindings,{key:None for key in mask})
        (out/'view_plans.json').write_text(json.dumps({'kind':PLAN_KIND,'version':1,
            'specification_sha256':facade.canonical_sha256(public),'FM_mask':mask,
            'mode_order':['financial_modeling'],'actual_D_unknown':True,'native_calls':0},indent=2)+'\n')
    base['_views']=fm_views
    revised=_clone(decoder,frozen=SimpleNamespace(**base),schema=facade)
    return base,revised


def rules(public):
    return _namespace(public)[1]['rules'](public)


def emit(public,freshdir):
    """Write one uncalculated source and FM view, without financial forwards."""
    base,revised=_namespace(public);output=Path(freshdir)
    inherited=revised['emit'](public,output)
    raw=output/'specification.json';raw.write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n')
    brief=output/'financial_modeling_instruction.md';brief.write_text(BRIEF)
    plans=json.loads((output/'view_plans.json').read_text())
    bindings=json.loads((output/'private_bindings.json').read_text())
    if (plans['FM_mask']!=forecast_keys(public) or len(set(plans['FM_mask']))!=len(plans['FM_mask'])
            or any(bindings['financial'][key]['role']!='report' for key in plans['FM_mask'])):
        raise ValueError('The complete FM formula inventory changed')
    if public['dimension_mode']=='production' and (inherited['report_positions'],inherited['formulas'],
            inherited['sheets'],len(plans['FM_mask']),inherited['matching_growth_formulas'])!=(93510,88676,211,62322,1600):
        raise ValueError('The complete production rendering geometry changed')
    (output/'receipt.json').rename(output/'frozen_rendering_receipt.json')
    value={'kind':KIND,'version':1,'candidate_id':schema.candidate(public['seed'])['candidate_id'],
        'specification':reference(raw),'specification_sha256':schema.canonical_sha256(public),
        'source':reference(output/'source_uncalculated.xlsx'),'bindings':reference(output/'private_bindings.json'),
        'view_plans':reference(output/'view_plans.json'),
        'views':{'financial_modeling':{'input':reference(output/'financial_modeling_input.xlsx'),'instruction':reference(brief)}},
        'rendering_proof':reference(output/'rendering_proof.json'),
        'base_emission_receipt':reference(output/'base_emission_receipt.json'),
        'frozen_rendering_receipt':reference(output/'frozen_rendering_receipt.json'),
        'independent_business_field_count':inherited['report_positions'],'formula_count':inherited['formulas'],
        'forecast_mask_count':len(plans['FM_mask']),'sheet_count':inherited['sheets'],
        'matching_growth_formulas':inherited['matching_growth_formulas'],'recipe':recipes(),
        'formula_helper_source':reference(original.__file__),'finite_decimal_decoder_source':reference(decoder.__file__),
        'formula_helper_bytecode_unchanged':base['_formula'].__code__ is original._formula.__code__,
        'finite_decimal_rules_bytecode_unchanged':revised['rules'].__code__ is decoder.rules.__code__,
        'private_function_namespaces':True,'source_caches_seeded':False,
        'old_C00_failure_or_qualification_inherited':False,'financial_forwards':0,
        'actual_LO_calls':0,'model_calls':0,'qualified':False}
    target=output/'receipt.json'
    with target.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,sort_keys=True);stream.write('\n')
    return reference(target)
