"""Twenty fixed DBG plans over the unchanged, genuinely calculated C00 goal.

This module does not calculate financial forwards or admit a source/task. Native
error absence, complete D and controls remain obligations of the caller's actual
engineering validation. Every plan retains the previously validated SG4000 core.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl.utils import quote_sheetname
from . import audit, debug_class_variants as core, schema

ROOT = Path(__file__).resolve().parents[4]
KIND = 'frozen_operating_reports_debug_scaling_twenty'
PLAN_KIND = 'pure_operating_reports_debug_scaling_plan'
CASE_IDS = tuple(f'DBG-S{i:02d}' for i in range(1, 21))
SEEDS = tuple(202711300+i for i in range(1, 21))
EXTRA_FIELDS = ('net_margin_percent', 'qoq_sales_delta', 'yoy_sales_delta', 'annual_sales_delta')
BRIEF = ('Audit and repair the calculations in all management reports for these hypothetical businesses. '
         'Use the supplied assumptions, reporting periods, units and presentation policies. '
         'Preserve the source data, labels, non-applicable fields and workbook layout. '
         'The completed reports must reconcile and calculate consistently throughout.')
ENVELOPE = ROOT/'outputs/research/operating_reports_200_debug_class_variants_prospective_20261101T013412Z/prospective.json'
ENVELOPE_SHA = 'de584267929f5d9f3d7abd71efb566a97b69aa191f7814266f6fd7a6eee5b95b'
CORE_PLAN_SHA = '0e64c7c9f86c804f4a99f02d86118e548bddb1db0af8b85c08709e69cc57384c'
CORE_PROOF_SHA = '40dbcae1c1f28b775422ac8e37ad10ae9f56c04fa5df3605cc97a09713e72c1c'
EXPECTED_SHA = '11127b067f269170d71ba0d8462de55c6b1ae296b50f9da809aed8fd09dd1055'
CORE_MODULE_SHA = '8d4b23e252ed5b29bda6589a5ee66d09f94f99f313a9b3554927c4373a7d11c1'
SENTINELS = {'E057/2026Q1/yoy_percent': ('E057 Glenmere Facilities', 'M68'),
             'E097/2026Q3/qoq_percent': ('E097 Valecrest Analytics', 'H30')}
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
require, reference, read = core.require, core.reference, core.read


def recipes():
    return {str(Path(p).resolve()): reference(p) for p in
            (__file__, core.__file__, schema.__file__, audit.__file__)}


def _point(row):
    return row['sheet']+'!'+row['cell']


def _ref(row):
    return quote_sheetname(row['sheet'])+'!'+row['cell']


def _exact(result, key):
    row = result['raw_cell_exact_values'][key]
    require(row['kind'] == 'rational', 'A changed report requires a retained exact rational')
    return Fraction(row['value'])


def _extra(public, bindings, definition, A, B):
    """Derive erroneous display alternatives from retained values, not forwards."""
    entities = {e['id']: e for e in public['entities']}
    faults, witnesses = {}, {}
    for key, binding in bindings['financial'].items():
        identity, period, field = key.split('/')
        if identity not in entities or field not in EXTRA_FIELDS or binding['role'] != 'report':
            continue
        point = _point(binding)
        require(point in definition['formulas'] and point not in definition['literals'],
                'Extra faults must address existing financial formulas, never supplied facts or NA')
        healthy = _exact(A, key)
        r = lambda p, f: _ref(bindings['financial'][f'{identity}/{p}/{f}'])
        current = _exact(A, f'{identity}/{period}/revenue')
        require(current > 0, 'Revenue must remain positive; no denominator or business input is changed')
        if field == 'net_margin_percent':
            cost = _exact(A, f'{identity}/{period}/direct_cost')
            income = _exact(A, f'{identity}/{period}/net_income')
            scale = core.RATE_SCALE[entities[identity]['rate_unit']]
            require(cost > 0 and healthy == income/current*scale,
                    'The margin must equal the retained income/revenue relationship in its labelled unit')
            opex = _exact(A, f'{identity}/{period}/operating_expense')
            require(cost+opex > 0, 'Operating cost coverage requires a strictly positive unchanged cost denominator')
            wrong = current/(cost+opex)*scale
            formula = '='+r(period, 'revenue')+'/('+r(period, 'direct_cost')+'+'+r(period, 'operating_expense')+')'
            if scale != 1:
                formula += '*'+str(scale)
            family = 'operating_cost_coverage_presented_as_net_sales_margin'
            dependencies = {'net_income': str(income), 'positive_sales': str(current),
                            'positive_direct_cost': str(cost), 'operating_expense':str(opex), 'rate_scale': scale}
        else:
            if period.startswith('FY'):
                base = 'FY'+str(int(period[2:])-1)
            else:
                offset = 1 if field == 'qoq_sales_delta' else 4
                base = schema.QUARTERS[schema.QUARTERS.index(period)-offset]
            comparative = _exact(A, f'{identity}/{base}/revenue')
            require(comparative > 0 and healthy == current-comparative,
                    'The monetary change must equal current less the labelled positive comparative')
            wrong = current+comparative
            formula = '='+r(period, 'revenue')+'+'+r(base, 'revenue')
            family = 'combined_turnover_presented_as_sales_change'
            dependencies = {'positive_current_revenue': str(current), 'positive_comparative_revenue': str(comparative),
                            'comparison_period': base}
        primary = A['typed_2dp_values'][key]
        require(primary == B['typed_2dp_values'][key] == {'type':'number', 'value': core._quant(healthy)}
                and _exact(B, key) == healthy and core._quant(wrong) != primary['value'],
                'Every member must change the scored primary value; zero-impact members cannot be filtered')
        require(formula != definition['formulas'][point], 'A fault must change its healthy definition')
        faults[key] = {'family':family, 'sheet':binding['sheet'], 'cell':binding['cell'],
                       'healthy_formula':definition['formulas'][point], 'faulty_formula':formula}
        witnesses[key] = {'healthy_exact':str(healthy), 'wrong_exact':str(wrong),
                          'healthy_primary':primary, 'wrong_primary':{'type':'number', 'value':core._quant(wrong)},
                          'dependency_values':dependencies}
    return faults, witnesses


def _prepare(public, bindings, definition, core_plan, A, B):
    schema.validate_spec(public)
    require(public['dimension_mode'] == 'toy' or schema.canonical_sha256(public) == core.SPECIFICATION_SHA256,
            'Use the fixed original production business contract')
    comparison = audit.compare(public, A, B)
    require(comparison['passed'], 'Full retained independent A/B coverage is required')
    require(bindings['specification_sha256'] == definition['specification_sha256'] == schema.canonical_sha256(public),
            'The healthy formula and semantic binding specification differ')
    require(set(bindings['financial']) == set(dict(schema.points(public))), 'All financial report bindings are required')
    protected = {_point(r) for name in ('provided_facts','provided_context') for r in bindings[name].values()}
    financial = [_point(r) for r in bindings['financial'].values()]
    require(len(financial) == len(set(financial)) and not protected.intersection(financial),
            'Financial cells must be unique and disjoint from supplied inputs/context')
    require(core_plan['variant_id'] == 'SG4000' and core_plan['kind'] == core.PLAN_KIND,
            'Retain the complete original SG4000 fault class')
    faults = core_plan['DBG_faults']
    for key, row in faults.items():
        require(key in bindings['financial'] and _point(row) == _point(bindings['financial'][key])
                and definition['formulas'].get(_point(row)) == row['healthy_formula'],
                'A core fault changed its original physical/healthy binding')
    if public['dimension_mode'] == 'production':
        require(len(faults) == 4000 and Counter(r['family'] for r in faults.values()) ==
                {'associate_presentation_sign':800, 'ratio_as_quarterly_change':3200}, 'All SG4000 core roots are mandatory')
        for key, point in SENTINELS.items():
            require(key in faults and (faults[key]['sheet'],faults[key]['cell']) == point,
                    'Both retained growth boundary roots must remain in every input')
    extras, witnesses = _extra(public, bindings, definition, A, B)
    require(not set(extras).intersection(faults), 'Extra report classes must not replace a core fault')
    require(not core._outside_dependents(definition, {**faults, **extras}),
            'Additional outputs must be parsed report leaves; unreviewed dependent changes are forbidden')
    if public['dimension_mode'] == 'production':
        require(len(extras) == 7200 and all(sum(k.startswith(e['id']+'/') for k in extras)==36 for e in public['entities']),
                'Each whole entity must retain all36 additional applicable display/history fields')
    return extras, witnesses, comparison


def _selected(public, index):
    count = min(len(public['entities']), 25+5*index)
    seed = SEEDS[index]
    ordered = sorted((e['id'] for e in public['entities']),
                     key=lambda identity: hashlib.sha256(f'{seed}:{identity}'.encode()).hexdigest())
    return sorted(ordered[:count])


def _build(public, core_plan, extras, witnesses, index):
    entities = _selected(public, index)
    selected = set(entities)
    added = {k:r for k,r in extras.items() if k.split('/')[0] in selected}
    faults = {**deepcopy(core_plan['DBG_faults']), **deepcopy(added)}
    layouts = {e['id']:e['layout'] for e in public['entities']}
    return {'kind':PLAN_KIND, 'version':1, 'case_id':CASE_IDS[index], 'variant_id':CASE_IDS[index], 'seed':SEEDS[index],
            'selection_rule':'SHA256(seed:entity_id) ascending; fixed count25+5*case_index; whole entities/all applicable extra fields',
            'selected_extra_entities':entities, 'core_variant':'SG4000', 'core_root_count':len(core_plan['DBG_faults']),
            'extra_root_count':len(added), 'root_count':len(faults), 'DBG_faults':faults,
            'extra_root_witnesses':{k:witnesses[k] for k in added},
            'roots_by_family':dict(Counter(r['family'] for r in faults.values())),
            'roots_by_layout':dict(Counter(layouts[k.split('/')[0]] for k in faults)),
            'predicted_complete_D_count':len(faults), 'actual_D_unknown':True,
            'all_added_roots_primary_nonzero':True, 'parsed_outside_dependents':[],
            'given_facts_NA_labels_policies_unchanged':True,
            'new_financial_forwards':0, 'native_calls':0, 'model_calls':0, 'qualified':False}


def plan_all(public, bindings, healthy_definition, sg4000_plan, retained_A, retained_B):
    """Return all20 deterministic plans together. This writes no workbook."""
    extras, witnesses, comparison = _prepare(public, bindings, healthy_definition, sg4000_plan, retained_A, retained_B)
    plans = [_build(public, sg4000_plan, extras, witnesses, i) for i in range(20)]
    if public['dimension_mode'] == 'production':
        signatures = {schema.canonical_sha256(p['DBG_faults']) for p in plans}
        require(len(signatures) == 20, 'Twenty physically different fault sets are required, not renamed copies')
    return plans, comparison


def _context():
    require(reference(core.__file__)['sha256'] == CORE_MODULE_SHA, 'The frozen SG4000 design implementation changed')
    envelope_ref = reference(ENVELOPE)
    require(envelope_ref['sha256'] == ENVELOPE_SHA, 'The original jointly frozen variant envelope changed')
    envelope = read(envelope_ref); lineage = envelope['lineage']
    plan_ref = envelope['variants']['SG4000']['view_plans']; proof_ref = envelope['variants']['SG4000']['proof']
    require(plan_ref['sha256'] == CORE_PLAN_SHA and proof_ref['sha256'] == CORE_PROOF_SHA, 'The verified SG4000 core/proof changed')
    for ref in lineage.values():
        require(reference(ref['path']) == ref, 'An original retained source/financial artifact changed')
    source = read(lineage['source_manifest'])
    preparation = read(lineage['source_preparation'])
    expected_ref = preparation['expected']
    require(reference(expected_ref['path']) == expected_ref and expected_ref['sha256'] == EXPECTED_SHA,
            'The complete original independent93510 expected map changed')
    require(source['source'] == lineage['genuine_healthy_goal'] and source['source']['sha256'] == core.GOAL_SHA256,
            'The exact healthy source3 goal bytes must remain unchanged')
    proof = read(proof_ref)
    require(proof['root_count']==4000 and proof['exact_arithmetic_predicted_D_count']==4000
            and proof['all_roots_exact_nonzero_primary_impact'] is True, 'Retain the original complete root proof')
    keys = ('specification','bindings','healthy_definition','retained_A','retained_B')
    values = [read(lineage[k]) for k in keys]
    return {'original_variant_envelope':envelope_ref, **lineage, 'expected':expected_ref, 'SG4000_plan':plan_ref, 'SG4000_proof':proof_ref}, values, read(plan_ref)


def _save(folder, name, value):
    path = folder/name
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return reference(path)


def freeze_all(output):
    """Freeze all20 plans BEFORE any fault emission. No financial/native call."""
    out = Path(output).absolute()
    require(out == out.resolve() and not out.exists(), 'Use a fresh all20 prospective directory')
    ancestry, values, core_plan = _context()
    public, bindings, definition, A, B = values
    plans, comparison = plan_all(public, bindings, definition, core_plan, A, B)
    extras, witnesses = _extra(public, bindings, definition, A, B)
    out.mkdir(parents=True)
    population = _save(out,'eligible_extra_population_proof.json', {
        'kind':'pure_operating_reports_debug_scaling_extra_population_proof','version':1,
        'specification':ancestry['specification'],'healthy_goal':ancestry['genuine_healthy_goal'],
        'retained_A':ancestry['retained_A'],'retained_B':ancestry['retained_B'],
        'SG4000_plan':ancestry['SG4000_plan'],'complete_original_A_B_comparison':comparison,
        'eligible_extra_roots':len(extras),'core_roots':4000,'parsed_source_formulas':len(definition['formulas']),
        'all_eligible_roots_primary_nonzero':True,'dropped_or_resampled_roots':0,
        'parsed_outside_formula_dependents':[],'witnesses':witnesses,
        'native_error_absence_or_actual_D_proved':False,'new_financial_forwards':0,'native_calls':0})
    rows = [{'case_id':p['case_id'], 'seed':p['seed'], 'root_count':p['root_count'],
             'view_plans':_save(out,p['case_id']+'_view_plans.json',p)} for p in plans]
    instruction = out/'instruction.md';instruction.write_text(BRIEF+'\n',encoding='utf-8')
    return _save(out,'prospective.json',{'kind':KIND,'version':1,'case_order':list(CASE_IDS),'cases':rows,
                 'lineage':ancestry,'instruction':reference(instruction),'eligible_extra_population_proof':population,'complete_original_A_B_comparison':comparison,
                 'recipe':recipes(),'all_twenty_frozen_before_emission':True,'goal_bytes_unchanged':True,
                 'new_financial_forwards':0,'native_calls':0,'model_calls':0,'qualified':False})


def validate_frozen(value, case_id=None):
    frozen = read(value)
    require(frozen['kind']==KIND and frozen['version']==1 and frozen['case_order']==list(CASE_IDS)
            and frozen['recipe']==recipes() and frozen['all_twenty_frozen_before_emission'] is True,
            'Only the complete current predeclared twenty-case envelope is admitted')
    require([r['case_id'] for r in frozen['cases']]==list(CASE_IDS), 'No case may be omitted, renamed or repeated')
    require(Path(frozen['instruction']['path']).read_bytes()==(BRIEF+'\n').encode()
            and reference(frozen['instruction']['path'])==frozen['instruction'],'The concise all-reports brief changed')
    read(frozen['eligible_extra_population_proof'])
    for row in frozen['cases']:
        require(reference(row['view_plans']['path'])==row['view_plans'], 'An unused or selected case plan changed')
    ancestry, values, core_plan = _context()
    require(frozen['lineage']==ancestry,'The original healthy goal/SG4000/financial provenance changed')
    plans, comparison = plan_all(values[0],values[1],values[2],core_plan,values[3],values[4])
    require(frozen['complete_original_A_B_comparison']==comparison, 'The complete retained crosscheck changed')
    for row, plan in zip(frozen['cases'],plans):
        require(row['seed']==plan['seed'] and row['root_count']==plan['root_count'] and read(row['view_plans'])==plan,
                'Every fixed case must exactly replay before any emission')
    require(case_id is None or case_id in CASE_IDS, 'Choose a fixed case ID')
    return frozen if case_id is None else (frozen,plans[CASE_IDS.index(case_id)],values[1])


def _sheet_parts(archive):
    workbook=ET.fromstring(archive.read('xl/workbook.xml'))
    rels=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    targets={r.attrib['Id']:r.attrib['Target'].lstrip('/') for r in rels}
    result={}
    for sheet in workbook.find(NS+'sheets'):
        target=targets[sheet.attrib[REL+'id']]
        result[sheet.attrib['name']]=target if target.startswith('xl/') else 'xl/'+target
    return result


def _emit_workbook(goal, destination, faults):
    """OOXML-only surgery; all formulas cold, every literal/part retained."""
    edits={}
    for row in faults.values():
        require(row['faulty_formula'].startswith('='), 'Every edit requires a complete native formula')
        require((row['sheet'],row['cell']) not in edits,'Duplicate physical roots are forbidden')
        edits[row['sheet'],row['cell']]=row
    changed=[]; formulas=caches=0; literal_digest=hashlib.sha256()
    with ZipFile(goal) as incoming, ZipFile(destination,'x',ZIP_DEFLATED) as outgoing:
        parts=_sheet_parts(incoming); by_part={part:sheet for sheet,part in parts.items()}
        pending=dict(edits)
        for item in incoming.infolist():
            data=incoming.read(item.filename)
            if item.filename in by_part:
                sheet=by_part[item.filename];tree=ET.fromstring(data)
                before={}
                for cell in tree.iter(NS+'c'):
                    point=(sheet,cell.attrib['r']);formula=cell.find(NS+'f')
                    if formula is None:
                        require(point not in pending,'A fault cannot replace a supplied literal/NA/blank')
                        before[point]=ET.tostring(cell)
                        literal_digest.update(repr(point).encode()+ET.tostring(cell))
                        continue
                    formulas+=1
                    if point in pending:
                        row=pending.pop(point)
                        require('='+str(formula.text)==row['healthy_formula'],'A healthy goal formula changed before surgery')
                        formula.text=row['faulty_formula'][1:];changed.append(point)
                    for child in list(cell):
                        if child.tag in (NS+'v',NS+'is'):
                            cell.remove(child)
                    cell.attrib.pop('t',None)
                    caches+=int(cell.find(NS+'v') is not None or cell.find(NS+'is') is not None)
                require(all(ET.tostring(cell)==before[(sheet,cell.attrib['r'])]
                            for cell in tree.iter(NS+'c') if cell.find(NS+'f') is None),
                        'A provided literal, label, style or NA changed')
                data=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
            outgoing.writestr(item,data)
        require(not pending and len(changed)==len(edits) and caches==0,'Every planned edit must be applied exactly once; all formula caches must be cleared')
    return {'changed_formula_count':len(changed),'formula_count':formulas,'formula_cache_count':caches,
            'provided_literal_identity_sha256':literal_digest.hexdigest(),
            'other_parts_byte_identical':True,'goal_bytes_unchanged':True}


def emit_frozen(prospective, case_id, output):
    """Emit one fresh, uncalculated DBG input; never overwrite or recalculate."""
    frozen, plan, _bindings = validate_frozen(prospective,case_id)
    out=Path(output).absolute()
    require(out==out.resolve() and not out.exists(),'Use a fresh case directory; no resampling or overwrite')
    out.mkdir(parents=True)
    goal=frozen['lineage']['genuine_healthy_goal'];require(reference(goal['path'])==goal,'The healthy goal changed')
    target=out/'debugging_input.xlsx'
    census=_emit_workbook(goal['path'],target,plan['DBG_faults'])
    require(census['formula_count']==88676,'The complete original formula inventory must remain')
    require(reference(goal['path'])==goal,'The healthy goal bytes changed during emission')
    return _save(out,'candidate.json',{'kind':'unverified_operating_reports_debug_scaling_candidate','version':1,
                 'case_id':case_id,'prospective':prospective if isinstance(prospective,dict) else reference(prospective),
                 'view_plans':frozen['cases'][CASE_IDS.index(case_id)]['view_plans'],
                 'input':reference(target),'goal':goal,'instruction':frozen['instruction'],
                 'specification':frozen['lineage']['specification'],'bindings':frozen['lineage']['bindings'],
                 'expected':frozen['lineage']['expected'],
                 'census':census,'predicted_complete_D_count':plan['root_count'],
                 'actual_D_unknown':True,'native_calls':0,'model_calls':0,'new_financial_forwards':0,'qualified':False})


def design_all(public, bindings, healthy_definition, original_plans):
    """Factory API: freeze the returned complete20 list before calling emit."""
    ancestry, values, core_plan = _context()
    require(public == values[0] and bindings == values[1] and healthy_definition == values[2]
            and original_plans == read(ancestry['original_view_plans']),
            'Factory inputs must be the exact original C00 business/bindings/healthy definitions/plans')
    return plan_all(public,bindings,healthy_definition,core_plan,values[3],values[4])[0]


def emit(goal, public, bindings, definition, original_plans, plan, new_outputdir):
    """Factory API: OOXML fault input + byte-identical goal + concise brief.

    The caller must durably freeze every returned design_all plan before the
    first call. This function does not calculate, grade or qualify the result.
    """
    import shutil
    require(plan.get('variant_id') in CASE_IDS, 'Use a fixed DBG scaling variant')
    ancestry, values, core_plan = _context()
    require(reference(goal) == ancestry['genuine_healthy_goal'], 'Only the original exact healthy goal bytes may be copied')
    require(public == values[0] and bindings == values[1] and definition == values[2]
            and original_plans == read(ancestry['original_view_plans']),
            'Factory inputs must preserve every original raw fact, definition and binding')
    extras,witnesses,comparison=_prepare(public,bindings,definition,core_plan,values[3],values[4])
    wanted=_build(public,core_plan,extras,witnesses,CASE_IDS.index(plan['variant_id']))
    require(plan == wanted, 'The fixed whole-entity fault set or exact root witness changed')
    out=Path(new_outputdir).absolute()
    require(out==out.resolve() and not out.exists(),'Use a fresh variant directory; never overwrite an earlier attempt')
    out.mkdir(parents=True)
    census=_emit_workbook(goal,out/'input.xlsx',plan['DBG_faults'])
    require(census['formula_count']==88676,'Preserve the complete original healthy formula census')
    shutil.copyfile(goal,out/'reference.xlsx')
    (out/'instruction.md').write_text(BRIEF+'\n',encoding='utf-8')
    require(reference(goal)==ancestry['genuine_healthy_goal'] and reference(out/'reference.xlsx')['sha256']==core.GOAL_SHA256,
            'Original and copied healthy goal bytes must remain exact')
    return {'kind':'pure_operating_reports_debug_scaling_emission','version':1,
            'variant_id':plan['variant_id'],'seed':plan['seed'],'input':reference(out/'input.xlsx'),
            'goal':reference(out/'reference.xlsx'),'instruction':reference(out/'instruction.md'),
            'original_healthy_goal':ancestry['genuine_healthy_goal'],'original_SG4000_plan':ancestry['SG4000_plan'],
            'original_SG4000_proof':ancestry['SG4000_proof'],'plan_sha256':schema.canonical_sha256(plan),
            'complete_original_A_B_comparison':comparison,'census':census,'recipe':recipes(),
            'predicted_complete_D_count':plan['root_count'],'actual_D_unknown':True,
            'native_calls':0,'model_calls':0,'new_financial_forwards':0,'qualified':False}
