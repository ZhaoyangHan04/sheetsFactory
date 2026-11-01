"""Opt-in v2 source reconciliation. E05/E06 scoring is deliberately unchanged.

This utility grants no source admission. The source wrapper must retain the
independent A/B, formula, supplied-fact, resource, stability and cleanup gates.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import posixpath
from xml.etree import ElementTree as X
from zipfile import ZipFile

from . import schema

POLICY={'kind':'source_only_precision_reconciliation','version':2,
    'currency_economic_GBP_absolute_bound':'1/10000','dimensionless_absolute_bound':'1/1000000000000',
    'CAGR':'distance to original independently certified interval in dimensionless units',
    'types_text_booleans_and_errors':'exact; no numeric coercion',
    'provided_facts_and_formulas':'unchanged exact construction guards required',
    'E05_E06_grading':'unchanged two-decimal typed full-D comparison against actual gold',
    'round_boundary_only_failure_is_difficulty_evidence':False}
MONEY_BOUND=F(1,10000);RATIO_BOUND=F(1,10**12)
MONEY_FIELDS=frozenset(schema.FLOWS+schema.STOCKS+schema.REPORTED+('yoy_sales_delta','qoq_sales_delta','annual_sales_delta'))
PERCENT_FIELDS=frozenset(('net_margin_percent','yoy_percent','qoq_percent','cagr_percent'))
S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'

def require(condition,message):
    if not condition:raise ValueError(message)

def reference(path):
    path=Path(path).resolve();h=hashlib.sha256()
    with path.open('rb') as handle:
        for data in iter(lambda:handle.read(4*1024**2),b''):h.update(data)
    return {'path':str(path),'sha256':h.hexdigest(),'bytes':path.stat().st_size}

def policy_sha256():return schema.canonical_sha256(POLICY)

def _exact(value):
    require(type(value)is str,'An exact retained rational string is required')
    result=F(value);require(str(result)==value,'A canonical retained rational is required');return result

def _native(value):
    require(type(value)is str,'Use the original raw numeric XML text')
    try:decimal=Decimal(value)
    except InvalidOperation as exc:raise ValueError('Invalid native numeric cache') from exc
    require(decimal.is_finite(),'Nonfinite native values cannot pass reconciliation')
    return F(decimal)

def _quant(value):
    scaled=abs(value)*100+F(1,2);n=scaled.numerator//scaled.denominator
    return ('-'if value<0 and n else '')+f'{n//100}.{n%100:02d}'

def _compile(public,bindings,result):
    schema.validate_spec(public);schema.validate_result(public,result)
    require(type(result['version'])is int and set(bindings)=={'kind','version','specification_sha256','financial','provided_facts','provided_context'}
        and bindings['kind']=='private_operating_reports_200_bindings' and type(bindings['version'])is int and bindings['version']==1,
        'The complete frozen binding/result schema is required')
    declared=dict(schema.points(public));financial=bindings['financial'];digest=schema.canonical_sha256(public)
    require(bindings['specification_sha256']==digest and set(financial)==set(declared),'Complete bound financial inventory required')
    if public['dimension_mode']=='production':require(len(declared)==93510,'All93510 production fields are mandatory')
    entities={e['id']:e for e in public['entities']};compiled={};cagr_keys=set()
    for key,kind in declared.items():
        identity,period,field=key.split('/');row=financial[key]
        require(set(row)=={'sheet','cell','role','money_unit','rate_unit'} and all(type(row[k])is str for k in row),
            'Unknown or incomplete physical binding fields')
        money=entities[identity]['money_unit']if identity in entities else'GBP'
        rate=entities[identity]['rate_unit']if identity in entities else'percent_units'
        require(row['money_unit']==money and row['rate_unit']==rate and row['role']==('given_NA'if kind=='text'else'report'),
            'A declared unit or field role changed')
        point=row['sheet']+'!'+row['cell'];require(point not in compiled,'Duplicate physical financial binding')
        raw=result['raw_cell_exact_values'][key];economic=result['economic_exact_values'][key];typed=result['typed_2dp_values'][key]
        value={'key':key,'kind':kind,'typed':typed}
        if kind in('boolean','text'):
            require(raw==economic=={'kind':kind,'value':typed['value']},'Exact typed expectations differ')
            value['expected']=typed['value'];value['class']=kind
        else:
            if field in MONEY_FIELDS:scale=F({'GBP':1,'GBP_thousands':1000,'GBP_millions':1000000}[money]);category='currency_GBP';bound=MONEY_BOUND
            elif field in PERCENT_FIELDS:scale={'fraction':F(1),'percent_units':F(1,100),'basis_points':F(1,10000)}[rate];category='dimensionless';bound=RATIO_BOUND
            elif field in('prior_year_multiple','prior_year_index'):scale=F(1,100)if field=='prior_year_index'else F(1);category='dimensionless';bound=RATIO_BOUND
            else:raise ValueError('Unknown numeric semantic field: '+field)
            if field=='cagr_percent':
                cagr_keys.add(key);proof=result['cagr_proofs'][key]
                require(set(proof)=={'endpoint_ratio','years','percent_units_per_raw_unit','lower_raw','upper_raw','rounded'},'Incomplete original CAGR interval')
                lo,hi=_exact(proof['lower_raw']),_exact(proof['upper_raw']);ratio=_exact(proof['endpoint_ratio']);unit=scale*100
                require(type(proof['years'])is int and proof['years']==int(period[2:])-2025 and lo<=hi and ratio>0
                    and _exact(proof['percent_units_per_raw_unit'])==unit
                    and 0<1+lo*unit/100 and (1+lo*unit/100)**proof['years']<=ratio<=(1+hi*unit/100)**proof['years'],
                    'The original CAGR interval does not certify its exact endpoint root')
                expected={'kind':'cagr','endpoint_ratio':str(ratio),'years':proof['years'],'percent_units_per_raw_unit':str(unit)}
                require(raw==expected and economic=={**expected,'percent_units_per_raw_unit':'1'}
                    and F(_quant(lo))==F(_quant(hi))==F(proof['rounded'])==F(typed['value']),
                    'Original CAGR exact/unit/two-decimal proof changed')
                category='CAGR_original_interval'
            else:
                require(set(raw)==set(economic)=={'kind','value'} and raw['kind']==economic['kind']=='rational','An exact rational expectation is required')
                lo=hi=_exact(raw['value'])
                economic_scale=scale if category=='currency_GBP'else scale*100 if field in PERCENT_FIELDS else F(1)
                require(_exact(economic['value'])==lo*economic_scale and F(_quant(lo))==F(typed['value']),
                    'Retained exact economic/raw/typed values disagree')
            value.update(scale=scale,bound=bound,lo=lo*scale,hi=hi*scale,**{'class':category})
        compiled[point]=value
    require(set(result['cagr_proofs'])==cagr_keys,'Extra or missing CAGR proof')
    context=bindings.get('provided_context',{});allowed=set(compiled)
    require(not allowed&set(context),'Financial and supplied context scopes overlap')
    allowed.update(context)
    return compiled,allowed

def _cells(path):
    """Raw XML values only: no openpyxl float cast or two-decimal pre-rounding."""
    with ZipFile(path) as archive:
        require(len(archive.namelist())==len(set(archive.namelist())),'Duplicate workbook package member')
        strings=[]
        if 'xl/sharedStrings.xml'in archive.namelist():strings=[''.join(t.text or '' for t in n.iter('{'+S+'}t'))for n in X.fromstring(archive.read('xl/sharedStrings.xml'))]
        rels={n.get('Id'):n.get('Target') for n in X.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets=X.fromstring(archive.read('xl/workbook.xml')).find('{'+S+'}sheets');seen=set()
        for sheet in sheets:
            name=sheet.get('name');require(name not in seen,'Duplicate sheet');seen.add(name)
            part=rels[sheet.get('{'+R+'}id')];part=part.lstrip('/')if part.startswith('/')else posixpath.normpath('xl/'+part)
            with archive.open(part) as handle:
                for event,node in X.iterparse(handle,events=('end',)):
                    if node.tag=='{'+S+'}c':
                        value=node.find('{'+S+'}v');inline=node.find('{'+S+'}is');formula=node.find('{'+S+'}f')
                        if value is None and inline is None and formula is None:continue
                        text=value.text if value is not None else None;t=node.get('t','n')
                        if t=='b':kind='boolean';value=(text=='1')if text in('0','1')else None
                        elif t in('s','inlineStr','str'):
                            kind='text';value=strings[int(text)]if t=='s'and text is not None else ''.join(n.text or ''for n in inline.iter('{'+S+'}t'))if inline is not None else text
                        elif t in('n',''):kind='number';value=text
                        elif t=='e':kind='error';value=text
                        else:kind='unknown';value=text
                        yield name+'!'+node.get('r'),kind,value
                    elif node.tag=='{'+S+'}row':node.clear()

def audit_workbook(workbook,public,bindings,result):
    """Complete source-only value audit; separate genuine lifecycle checks remain mandatory."""
    record=reference(workbook['path']if isinstance(workbook,dict)else workbook)
    if isinstance(workbook,dict):require(record==workbook,'The retained workbook bytes changed')
    compiled,allowed=_compile(public,bindings,result);seen=set();mismatches=[];boundaries=[];counts=Counter();maxima={}
    for point,kind,value in _cells(record['path']):
        require(point not in seen,'Duplicate physical cell');seen.add(point)
        if point not in allowed:mismatches.append({'point':point,'reason':'unbound populated cell'});continue
        if point not in compiled:continue  # Exact construction guards belong to the unchanged source lifecycle.
        row=compiled[point];category=row['class'];counts[category]+=1
        if kind!=row['kind']or value is None:
            mismatches.append({'point':point,'reason':'type/error/empty mismatch','expected_type':row['kind'],'actual_type':kind});continue
        if kind!='number':
            if type(value)is not type(row['expected'])or value!=row['expected']:mismatches.append({'point':point,'reason':'exact typed value changed'})
            continue
        actual=_native(value);distance=max(row['lo']-actual*row['scale'],actual*row['scale']-row['hi'],F(0))
        if distance>maxima.get(category,(F(-1),None))[0]:maxima[category]=(distance,{'point':point,'key':row['key'],'raw_XML':value})
        if distance>row['bound']:mismatches.append({'point':point,'key':row['key'],'reason':'source-only numeric bound exceeded','distance':str(distance),'bound':str(row['bound'])})
        if F(_quant(actual))!=F(row['typed']['value']):boundaries.append({'point':point,'key':row['key'],'raw_XML':value,
            'oracle_2dp':row['typed']['value'],'actual_2dp':_quant(actual),'within_source_bound':distance<=row['bound']})
    for point in set(compiled)-seen:mismatches.append({'point':point,'reason':'missing financial cell'})
    require(reference(record['path'])==record,'The workbook changed during raw audit')
    return {'kind':'full_source_only_numeric_reconciliation_v2','version':2,'passed':not mismatches,
        'workbook':record,'specification_sha256':schema.canonical_sha256(public),'policy':POLICY.copy(),'policy_sha256':policy_sha256(),
        'implementation':reference(__file__),'declared_financial_fields':len(compiled),'checked_financial_fields':sum(counts.values()),
        'class_counts':dict(counts),'maximum_errors':{k:{**v[1],'distance':str(v[0])}for k,v in maxima.items()},
        'mismatches':mismatches,'round_boundary_differences':boundaries,'E05_E06_grader_changed':False,
        'new_financial_forwards':0,'source_or_resource_or_quality_admission':False,'difficulty_certified':False}
