"""Exact finite-decimal input decoding for matching forecast growth outputs.

Financial amounts, forecasts and gates retain the original full-precision
formulas. ROUND reconstructs an integer encoded by a supplied decimal fact;
it never rounds a calculated financial amount or supplies an epsilon.
"""
from __future__ import annotations

from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
from types import FunctionType

from . import excel as frozen, schema

FROZEN_SHA256 = "50ee9cdcc19d3cff39494d47c43ea6e41ac2c4a824a200b381b366e2fe71baa8"
LIMIT = 2**53
KIND = "pure_operating_reports_200_emission_rendering_v2"


def _checked_base():
    if hashlib.sha256(Path(frozen.__file__).read_bytes()).hexdigest()!=FROZEN_SHA256:
        raise ValueError("The original frozen renderer changed")


def rules(public):
    """Plan all matching-reference fields using supplied facts, not answers."""
    schema.validate_spec(public)
    result={}
    for e in public['entities']:
        multiplier={'fraction':1,'percent_units':100,'basis_points':10000}[e['rate_unit']]
        for index,period in enumerate(schema.QUARTERS[4:],4):
            raw=e['forecast_sales'][period]
            denominator=10**(len(raw.split('.')[1])if'.'in raw else 0)
            numerator=F(raw)*denominator
            if numerator.denominator!=1:raise ValueError("The supplied decimal has no exact integer encoding")
            numerator=numerator.numerator
            form=e['driver_form_by_year'][period[:4]]
            integers=[numerator,denominator,multiplier]
            if form=='level_multiple':integers.extend((numerator-denominator,(numerator-denominator)*multiplier))
            elif form=='base100_index':integers.extend((100*denominator,numerator-100*denominator,(numerator-100*denominator)*multiplier))
            elif form=='money_delta':integers.append(numerator*multiplier)
            elif form!='change_rate':raise ValueError("Unknown declared forecast measure")
            if any(abs(value)>=LIMIT for value in integers):raise ValueError("Input integer reconstruction exceeds exact binary64 integer range")
            # Two correctly rounded normal binary64 operations: parsing N/D and
            # multiplying by D. gamma_2 bounds their absolute integer error.
            error_bound=F(2*abs(numerator),2**53-2)
            if error_bound>=F(1,2):raise ValueError("Integer reconstruction is not separated from a half-integer")
            metric='yoy_percent'if e['forecast_reference']=='same_quarter_last_year'else'qoq_percent'
            comparison=schema.QUARTERS[index-(4 if metric=='yoy_percent'else 1)]
            result[f"{e['id']}/{period}/{metric}"]={
                'entity':e['id'],'period':period,'metric':metric,'driver_form':form,
                'given_decimal':raw,'N':numerator,'D':denominator,'K':multiplier,
                'comparison_revenue_key':f"{e['id']}/{comparison}/revenue",
                'integer_terms':integers,'absolute_decode_error_bound':str(error_bound),
                'distance_to_nearest_half_integer_lower_bound':str(F(1,2)-error_bound),
            }
    return result


def _replacement(plan):
    original=frozen._formula
    def formula(identity,period,field,e,members,ref,fact,entity_scales):
        rule=plan.get(f"{identity}/{period}/{field}")
        if rule is None:return original(identity,period,field,e,members,ref,fact,entity_scales)
        D,K=rule['D'],rule['K']
        given=fact(identity,'forecast_sales',period)
        N=f"ROUND({given}*{D},0)"
        form=rule['driver_form']
        if form=='change_rate':return f"{N}/{D}"
        if form=='level_multiple':return f"({N}-{D})*{K}/{D}"
        if form=='base100_index':return f"({N}-{100*D})*{K}/{100*D}"
        previous=rule['comparison_revenue_key'].split('/')[1]
        return f"({N}*{K})/({D}*{ref(identity,previous,'revenue')})"
    return formula


def _ref(path):
    path=Path(path).resolve();data=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def emit(public_specification,output_directory):
    """Emit fresh packages through one isolated replacement of frozen logic."""
    _checked_base();plan=rules(public_specification)
    namespace={**vars(frozen),'_formula':_replacement(plan)}
    function=FunctionType(frozen.emit.__code__,namespace,frozen.emit.__name__,frozen.emit.__defaults__,frozen.emit.__closure__)
    function.__kwdefaults__=frozen.emit.__kwdefaults__
    receipt=function(public_specification,output_directory)
    output=Path(output_directory)
    bindings=json.loads((output/'private_bindings.json').read_text())
    for key,rule in plan.items():
        rule['report_binding']=bindings['financial'][key]
        rule['provided_binding']=bindings['provided_facts'][rule['entity']+'/forecast_sales/'+rule['period']]
    proof={'kind':'exact_finite_decimal_matching_growth_rendering','version':2,
        'specification_sha256':schema.canonical_sha256(public_specification),
        'frozen_renderer':_ref(frozen.__file__),'renderer':_ref(__file__),
        'changed_formula_class':'All entity forecast growth reports matching their supplied reference; no coordinate exceptions.',
        'matching_growth_fields':len(plan),'rules':plan,
        'public_policy_and_facts_changed':False,'financial_intermediate_rounding':False,
        'hidden_epsilon':False,'native_calculations':0,'actual_D_unknown':True}
    with(output/'rendering_proof.json').open('x')as stream:json.dump(proof,stream,indent=2);stream.write('\n')
    (output/'receipt.json').rename(output/'base_emission_receipt.json')
    revised={**receipt,'kind':KIND,'version':2,'rendering_proof':_ref(output/'rendering_proof.json'),
        'base_emission_receipt':_ref(output/'base_emission_receipt.json'),'matching_growth_formulas':len(plan)}
    with(output/'receipt.json').open('x')as stream:json.dump(revised,stream,indent=2);stream.write('\n')
    return revised


def _quant(value):
    v=F(value);x=abs(v)*100+F(1,2);n=x.numerator//x.denominator
    return ('-'if v<0 and n else'')+f'{n//100}.{n%100:02d}'


def prove(public,left,right,original_directory,revised_directory):
    """Post-emission full algebra/identity proof, with no oracle forward call."""
    from . import audit
    _checked_base();comparison=audit.compare(public,left,right)
    if not comparison['passed']:raise ValueError("Original complete independent results disagree")
    original=Path(original_directory);revised=Path(revised_directory)
    before=json.loads((original/'private_bindings.json').read_text());after=json.loads((revised/'private_bindings.json').read_text())
    if before!=after:raise ValueError("Rendering revision changed a report/context/fact binding or value")
    census=audit.census(public,revised)
    plan=rules(public);proof=json.loads((revised/'rendering_proof.json').read_text())
    original_receipt=_ref(original/'receipt.json');base_receipt=_ref(revised/'base_emission_receipt.json')
    if (original_receipt['sha256'],original_receipt['bytes'])!=(base_receipt['sha256'],base_receipt['bytes']):raise ValueError("The original frozen emission census receipt differs from the new base census")
    old_receipt=json.loads((original/'receipt.json').read_text());new_receipt=json.loads((revised/'receipt.json').read_text())
    if new_receipt!={**old_receipt,'kind':KIND,'version':2,'rendering_proof':_ref(revised/'rendering_proof.json'),'base_emission_receipt':base_receipt,'matching_growth_formulas':len(plan)}:raise ValueError("The rendering revision receipt/proof ancestry differs")
    exact_rules={key:{**rule,'report_binding':after['financial'][key],
        'provided_binding':after['provided_facts'][rule['entity']+'/forecast_sales/'+rule['period']]}
        for key,rule in plan.items()}
    if proof['rules']!=exact_rules or proof['kind']!='exact_finite_decimal_matching_growth_rendering'or proof['version']!=2 or proof['specification_sha256']!=schema.canonical_sha256(public)or proof['renderer']!=_ref(__file__)or proof['frozen_renderer']!=_ref(frozen.__file__):raise ValueError("Rendering proof changed the complete formula class or integer decoding")
    maximum_integer=0;minimum_margin=F(1,2)
    for key,rule in plan.items():
        N,D,K=rule['N'],rule['D'],rule['K'];form=rule['driver_form']
        if F(rule['given_decimal'])!=F(N,D):raise ValueError("Input numerator/denominator changed the exact provided fact")
        if any(abs(n)>=LIMIT for n in rule['integer_terms']):raise ValueError("An intermediate integer is not exact in binary64")
        maximum_integer=max(maximum_integer,*map(abs,rule['integer_terms']))
        minimum_margin=min(minimum_margin,F(rule['distance_to_nearest_half_integer_lower_bound']))
        if form=='change_rate':value=F(N,D)
        elif form=='level_multiple':value=F((N-D)*K,D)
        elif form=='base100_index':value=F((N-100*D)*K,100*D)
        else:value=F(N*K,D)/F(left['raw_cell_exact_values'][rule['comparison_revenue_key']]['value'])
        expected=left['raw_cell_exact_values'][key]
        if expected!={'kind':'rational','value':str(value)}or right['raw_cell_exact_values'][key]!=expected or left['typed_2dp_values'][key]!={'type':'number','value':_quant(value)}:
            raise ValueError("Rearranged full-class exact/primary values disagree with original independent results")
    # Compare cells: only planned formula nodes may differ. Facts, styles,
    # caches and labels stay identical. Package metadata is checked below.
    before_cells=_cells(original/'source_uncalculated.xlsx');after_cells=_cells(revised/'source_uncalculated.xlsx')
    planned={(before['financial'][key]['sheet'],before['financial'][key]['cell'])for key in plan}
    changed={point for point in before_cells if before_cells[point]!=after_cells.get(point)}
    if set(before_cells)!=set(after_cells)or changed!=planned:raise ValueError("Revision changed cells outside the declared complete formula class")
    for point in planned:
        first,last=before_cells[point],after_cells[point]
        if first[:1]+first[2:]!=last[:1]+last[2:]:raise ValueError("A formula rewrite also changed a style, literal or cache")
    old_plans=json.loads((original/'view_plans.json').read_text());new_plans=json.loads((revised/'view_plans.json').read_text())
    if old_plans['FM_mask']!=new_plans['FM_mask']or set(old_plans['DBG_faults'])!=set(new_plans['DBG_faults']):raise ValueError("The original scope or roots changed")
    for key,entry in old_plans['DBG_faults'].items():
        new=new_plans['DBG_faults'][key]
        if {k:v for k,v in entry.items()if k!='healthy_formula'}!={k:v for k,v in new.items()if k!='healthy_formula'}:raise ValueError("A DBG business fault definition changed")
        point=new['sheet'],new['cell']
        if after_cells[point][1]!=new['healthy_formula'][1:]:raise ValueError("A DBG healthy definition is not the revised source definition")
    changed_members=_package_identity(original/'source_uncalculated.xlsx',revised/'source_uncalculated.xlsx')
    entities={e['id']:e for e in public['entities']};impacts=[]
    for key,entry in new_plans['DBG_faults'].items():
        identity,period,field=key.split('/');e=entities[identity]
        def value(p,f):return F(left['raw_cell_exact_values'][identity+'/'+p+'/'+f]['value'])
        K={'fraction':1,'percent_units':100,'basis_points':10000}[e['rate_unit']]
        family=entry['family']
        if family=='associate_sign':wrong=value(period,'core_net_income')-value(period,'associate_income')
        elif family=='ratio_as_change':wrong=value(period,'revenue')/value('2026Q4','revenue')*K
        elif family=='money_scale':wrong=value(period,'revenue')/1000
        else:
            previous='2025Q1'if e['forecast_reference']=='previous_calendar_quarter'else'2025Q4'
            base=value(previous,'revenue');given=F(e['forecast_sales'][period]);form=e['driver_form_by_year']['2026']
            wrong=base+given if form=='money_delta'else base*(1+given/K)if form=='change_rate'else base*given if form=='level_multiple'else base*given/100
        expected=left['typed_2dp_values'][key]['value']
        if _quant(wrong)==expected:raise ValueError("An original DBG root lost its primary numerical impact")
        impacts.append({'key':key,'family':family,'expected_primary':expected,'wrong_root_primary':_quant(wrong)})
    return {'kind':'complete_exact_finite_decimal_rendering_equivalence','version':2,'passed':True,
        'specification_sha256':schema.canonical_sha256(public),'matching_growth_exact_and_primary_checked':len(plan),
        'original_emission_receipt':original_receipt,'base_emission_receipt':base_receipt,
        'rendering_proof':_ref(revised/'rendering_proof.json'),
        'complete_original_A_B_points_unchanged':len(left['typed_2dp_values']),
        'maximum_intermediate_integer':maximum_integer,'integer_limit_strict':LIMIT,
        'minimum_decode_half_integer_margin':str(minimum_margin),
        'all_provided_facts_context_and_NA_unchanged':True,'all_other_formulas_unchanged':True,
        'original_DBG_fault_definitions_retained':len(old_plans['DBG_faults']),
        'original_DBG_roots_primary_impact_proved':len(impacts),'fault_root_primary_impacts':impacts,
        'source_package_changed_members':changed_members,
        'emission_census':census,'native_calls':0,'actual_D_unknown':True}


def _cells(path):
    from zipfile import ZipFile
    import xml.etree.ElementTree as ET
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}';result={}
    with ZipFile(path)as archive:
        workbook=ET.fromstring(archive.read('xl/workbook.xml'));relationships={r.attrib['Id']:r.attrib['Target'].lstrip('/')for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        for sheet in workbook.find(ns+'sheets'):
            part=relationships[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            if not part.startswith('xl/'):part='xl/'+part
            for cell in ET.fromstring(archive.read(part)).iter(ns+'c'):
                f=cell.find(ns+'f');v=cell.find(ns+'v');text=cell.find(ns+'is')
                result[sheet.attrib['name'],cell.attrib['r']]=(dict(cell.attrib),f.text if f is not None else None,v.text if v is not None else None,ET.tostring(text)if text is not None else None)
    return result


def _package_identity(original,revised):
    from zipfile import ZipFile
    import xml.etree.ElementTree as ET
    changed=[]
    with ZipFile(original)as first,ZipFile(revised)as last:
        if set(first.namelist())!=set(last.namelist()):raise ValueError("Source package members changed")
        for name in first.namelist():
            a,b=first.read(name),last.read(name)
            if a==b:continue
            changed.append(name)
            if name.startswith('xl/worksheets/sheet')and name.endswith('.xml'):continue
            if name=='docProps/core.xml':
                x,y=ET.fromstring(a),ET.fromstring(b)
                # Fresh package creation times are not financial data. Every
                # other property remains identical, and this exception is named.
                for root in(x,y):
                    for child in list(root):
                        if child.tag in('{http://purl.org/dc/terms/}created','{http://purl.org/dc/terms/}modified'):root.remove(child)
                if ET.tostring(x)==ET.tostring(y):continue
            raise ValueError("Rendering changed a nonformula package object: "+name)
    return changed
