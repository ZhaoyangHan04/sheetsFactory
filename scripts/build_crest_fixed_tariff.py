#!/usr/bin/env python3
"""Build an explicitly derived fixed-PPA scenario from an authentic CREST workbook."""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET

import openpyxl
from openpyxl.utils.cell import range_boundaries

from sheets_factory.workbook.engine import LibreOfficeEngine
from sheets_factory.workbook.profile import profile_workbook

PINNED_IMAGE = 'sha256:d2e00cbc9a93f0694093d404198d1c420906390887fc8be64593d602433085a6'
SOURCES = {
    'solar': {'sha256': '9169f5cf975e798f791b08d3d55b9a91642d7719414e7f8bbc6325e6372f5f73',
              'url': 'https://nrel.sitefinity.cloud/docs/libraries/analysis/nrel-crest-solar.xlsx?sfvrsn=3cdfaa3b_2',
              'table_start': 205, 'input': 'G72', 'target': 'D72'},
    'geothermal': {'sha256': 'a2e19807723ad1d9c2b2818e268d48036529fede3a6532d0a65550e9553d6677',
                   'url': 'https://nrel.sitefinity.cloud/docs/libraries/analysis/nrel-crest-geothermal.xlsx?sfvrsn=983e9cd9_2',
                   'table_start': 248, 'input': 'G75', 'target': 'D75'},
}
IRR = re.compile(r'\bIRR\(([^()]*)\)', re.I)
SOLVER = "import json,subprocess,sys,time\nfrom pathlib import Path\nimport uno\nfrom com.sun.star.beans import PropertyValue\n\ndef prop(n,v):\n p=PropertyValue();p.Name=n;p.Value=v;return p\n\ndef main():\n src,receipt,config=map(Path,sys.argv[1:4]);cfg=json.loads(config.read_text());start=time.monotonic()\n process=subprocess.Popen(['/usr/bin/libreoffice','--headless','--nologo','--nodefault','--norestore','--nofirststartwizard','-env:UserInstallation=file:///tmp/crest-grid-profile','--accept=pipe,name=crest_grid;urp;StarOffice.ComponentContext'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)\n local=uno.getComponentContext();resolver=local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local);doc=None;desktop=None\n log={'method':'execute published three-grid what-if semantics using temporary input substitution; no cached result is assigned to any cell; no workbook saved','grids':[]}\n try:\n  for _ in range(300):\n   try:remote=resolver.resolve('uno:pipe,name=crest_grid;urp;StarOffice.ComponentContext');break\n   except Exception:time.sleep(.1)\n  else:raise RuntimeError('UNO startup timeout')\n  desktop=remote.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',remote)\n  doc=desktop.loadComponentFromURL(src.resolve().as_uri(),'_blank',0,(prop('Hidden',True),prop('ReadOnly',False),prop('MacroExecutionMode',0),prop('UpdateDocMode',0)))\n  doc.enableAutomaticCalculation(False);s=doc.Sheets.getByName('Cash Flow');inp=s.getCellRangeByName(cfg['input_cell']);original=inp.getFormula();log['original_input_formula']=original\n  grid=cfg['coarse_grid'];lastlower=None;lastupper=None\n  for stage,step in [('coarse',10),('integer',1),('tenth',.1)]:\n   if stage!='coarse':\n    grid=[lastlower]\n    for i in range(10):grid.append(grid[-1]+step)\n   values=[]\n   for rate in grid:\n    inp.setValue(rate);doc.calculateAll();target=s.getCellRangeByName(cfg['target_cell'])\n    if target.getError():raise RuntimeError('Financial target error '+str(target.getError())+' at rate '+str(rate))\n    if inp.getError() or inp.getValue()!=rate:raise RuntimeError('What-if input was not restored after TABLE evaluation')\n    values.append({'rate_cents_per_kwh':rate,'npv_dollars':target.getValue()})\n   brackets=[(values[i],values[i+1]) for i in range(10) if values[i]['npv_dollars']<0 and values[i+1]['npv_dollars']>0]\n   if len(brackets)!=1:raise RuntimeError('Published strictly-negative/positive search requires one crossing: '+str(brackets))\n   lower,upper=brackets[0];lastlower=lower['rate_cents_per_kwh'];lastupper=upper['rate_cents_per_kwh']\n   log['grids'].append({'stage':stage,'step':step,'values':values,'lower':lower,'upper':upper});receipt.write_text(json.dumps(log,indent=2))\n  computed=(lastlower+lastupper)/2;inp.setValue(computed);doc.calculateAll();log['computed_tariff_cents_per_kwh']=computed\n  snapshot=[]\n  for item in cfg['formula_cells']:\n   sn,ad=item['sheet'],item['cell'];c=doc.Sheets.getByName(sn).getCellRangeByName(ad)\n   snapshot.append({**item,'observed_error':c.getError(),'observed_numeric':c.getValue(),'observed_string':c.getString(),'observed_formula':c.getFormula(),'observed_result_type':str(c.getPropertyValue('FormulaResultType'))})\n  log['final_formula_snapshot']=snapshot\n  log['base_target_npv_dollars']=s.getCellRangeByName(cfg['target_cell']).getValue()\n  inp.setFormula(original);log['original_formula_restored']=inp.getFormula()==original;log['elapsed_seconds']=time.monotonic()-start\n  receipt.write_text(json.dumps(log,indent=2));doc.close(True);doc=None\n finally:\n  if doc is not None:\n   try:doc.close(True)\n   except Exception:pass\n  if desktop is not None:\n   try:desktop.terminate()\n   except Exception:pass\n  if process.poll() is None:process.terminate()\n  try:process.wait(timeout=5)\n  except subprocess.TimeoutExpired:process.kill()\nif __name__=='__main__':main()\n"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def cent(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def formula_text(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {'kind': type(value).__name__, **getattr(value, '__dict__', {})}


def unique_irr(cashflows):
    """A single sign change gives at most one positive discount-factor root."""
    if not cashflows or any(isinstance(x, bool) or not isinstance(x, (int, float))
                           or not math.isfinite(x) for x in cashflows):
        raise ValueError('IRR cash flows must be finite numbers')
    signs = [1 if x > 0 else -1 for x in cashflows if x]
    if not signs or signs[0] != -1 or signs[-1] != 1 or sum(
            a != b for a, b in zip(signs, signs[1:])) != 1:
        raise ValueError('IRR requires exactly one negative-to-positive sign change')
    # Values in CREST are one initial outlay followed by nonnegative inflows.
    # This domain also gives a strictly decreasing NPV in r > -1.
    if cashflows[0] >= 0 or any(x < 0 for x in cashflows[1:]):
        raise ValueError('IRR proof requires initial negative then nonnegative flows')
    def npv(rate):
        return sum(x / (1 + rate) ** i for i, x in enumerate(cashflows))
    low, high = -.999999, 1.0
    while npv(high) > 0:
        high *= 2
        if high > 1e12:
            raise ValueError('IRR root not bracketed')
    if npv(low) <= 0:
        raise ValueError('IRR root outside proved bracket')
    for _ in range(110):
        middle = (low + high) / 2
        if npv(middle) > 0:
            low = middle
        else:
            high = middle
    root = (low + high) / 2
    return {'cashflows': cashflows, 'sign_changes': 1, 'unique_root': root,
            'npv_residual': npv(root), 'method': 'independent_bracketed_bisection'}


def table_cells(book, start):
    expected = {f'{col}{row}' for col in ('G', 'K', 'O') for row in range(start, start + 11)}
    actual = set()
    for sheet in book:
        for cell in sheet._cells.values():
            if cell.value.__class__.__name__ != 'DataTableFormula':
                continue
            if sheet.title != 'Cash Flow':
                raise ValueError('Unexpected TABLE sheet')
            lo_c, lo_r, hi_c, hi_r = range_boundaries(cell.value.ref)
            for row in range(lo_r, hi_r + 1):
                for col in range(lo_c, hi_c + 1):
                    actual.add(openpyxl.utils.get_column_letter(col) + str(row))
    if actual != expected:
        raise ValueError('TABLE output coverage differs from the exact 33-cell contract')
    return expected


def execute_scenarios(root, source, output, kind):
    """Use the source formulas under temporary what-if inputs; never use cached answers."""
    cfg = SOURCES[kind]
    formula_book = openpyxl.load_workbook(source, data_only=False, keep_links=False)
    cells = [{'sheet': s.title, 'cell': c.coordinate} for s in formula_book
             for c in s._cells.values() if c.data_type == 'f']
    settings = {'input_cell': cfg['input'], 'target_cell': cfg['target'],
                'coarse_grid': [formula_book['Cash Flow'][f'F{r}'].value
                                for r in range(cfg['table_start'], cfg['table_start'] + 11)],
                'formula_cells': cells}
    if settings['coarse_grid'] != list(range(0, 101, 10)):
        raise ValueError('Unexpected public coarse grid')
    formula_book.close()
    script = output / 'scenario_executor.py'; script.write_text(SOLVER)
    config = output / 'scenario_executor_config.json'; write(config, settings)
    name = 'sf-crest-fixed-' + uuid.uuid4().hex[:16]
    commands = []
    def run(args, timeout=30):
        started = time.monotonic()
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        commands.append({'command': args, 'seconds': time.monotonic() - started,
                         'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise RuntimeError('Scenario engine failed: ' + result.stderr[-2000:])
    try:
        run(['docker', 'create', '--name', name, '--user', '0', '--workdir', '/tmp', '--network', 'none',
             '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges',
             '--memory', '2g', '--cpus', '2', '--pids-limit', '256', '--entrypoint', '/usr/bin/python3',
             PINNED_IMAGE, '/tmp/probe.py', '/tmp/source.xlsx', '/tmp/result.json', '/tmp/config.json'])
        for src, dst in [(source, '/tmp/source.xlsx'), (script, '/tmp/probe.py'), (config, '/tmp/config.json')]:
            run(['docker', 'cp', str(src), name + ':' + dst])
        run(['docker', 'start', '--attach', name], timeout=180)
        run(['docker', 'cp', name + ':/tmp/result.json', str(output / 'scenario_execution.json')])
    finally:
        subprocess.run(['docker', 'rm', '--force', name], capture_output=True, timeout=20)
        write(output / 'scenario_engine_commands.json', commands)
    data = json.loads((output / 'scenario_execution.json').read_text())
    if not data.get('original_formula_restored') or len(data.get('grids', [])) != 3:
        raise ValueError('Incomplete external scenario execution')
    return data


def calibration_values(execution, start):
    expected_stages = ['coarse', 'integer', 'tenth']
    outputs = {}
    for col, stage_name, stage in zip(('G', 'K', 'O'), expected_stages, execution['grids'], strict=True):
        if stage['stage'] != stage_name or len(stage['values']) != 11:
            raise ValueError('Incomplete 33-point calibration')
        for offset, item in enumerate(stage['values']):
            value = item['npv_dollars']
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Invalid calibration NPV')
            outputs[f'{col}{start + offset}'] = value
    return outputs


def expected_calibration_formulas(execution, start):
    """Independent public grid/bracket arithmetic for the original search helper cells."""
    results = {}; header = start - 1
    for col in ('G', 'K', 'O'):
        results[f'{col}{header}'] = execution['base_target_npv_dollars']
    results[f'R{header}'] = execution['grids'][2]['lower']['rate_cents_per_kwh']
    results[f'S{header}'] = execution['grids'][2]['upper']['rate_cents_per_kwh']
    for position, column in [(0, 'J'), (1, 'N')]:
        lo = execution['grids'][position]['lower']['rate_cents_per_kwh']
        hi = execution['grids'][position]['upper']['rate_cents_per_kwh']
        step = 1 if position == 0 else .1
        rate = lo
        for offset in range(11):
            results[f'{column}{start + offset}'] = hi if offset == 10 else rate
            rate += step
    for stage, negative, positive in zip(execution['grids'], ('H', 'L', 'P'), ('I', 'M', 'Q'), strict=True):
        vals = [x['npv_dollars'] for x in stage['values']]
        for offset in range(1, 11):
            previous, value = vals[offset - 1], vals[offset]
            following = vals[offset + 1] if offset < 10 else 0
            results[f'{negative}{start + offset}'] = value if value < 0 < following else None
            results[f'{positive}{start + offset}'] = value if previous < 0 < value else None
    return results


def restore_input_precision(destination, original_cells, allowed, sheet_names):
    """Preserve original numeric assumption values across openpyxl's 16-digit serialization."""
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    patches=[]; temporary=destination.with_suffix('.precision.tmp')
    with zipfile.ZipFile(destination) as old, zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as new:
        for name in old.namelist():
            payload=old.read(name)
            match=re.fullmatch(r'xl/worksheets/sheet(\d+)\.xml',name)
            if match:
                sheet=sheet_names[int(match.group(1))-1]; tree=ET.fromstring(payload)
                for cell in tree.findall('.//m:sheetData/m:row/m:c',ns):
                    key=(sheet,cell.attrib['r']); value=original_cells.get(key)
                    if key in allowed or isinstance(value,bool) or not isinstance(value,(int,float)):
                        continue
                    node=cell.find('m:v',ns)
                    if node is None or cell.find('m:f',ns) is not None:raise ValueError('Numeric input serialization changed cell type')
                    if float(node.text)!=value:
                        patches.append({'sheet':sheet,'cell':key[1],'serialized_value':node.text,'restored_original_value':value})
                        node.text=repr(value)
                payload=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
            new.writestr(name,payload)
    temporary.replace(destination)
    return patches


def create_derived(source, destination, kind, execution):
    cfg = SOURCES[kind]; start = cfg['table_start']
    book = openpyxl.load_workbook(source, data_only=False, keep_links=True)
    tables = table_cells(book, start); values = calibration_values(execution, start)
    if set(values) != tables:
        raise ValueError('Calibration values do not exactly cover TABLE output cells')
    snapshot = {(x['sheet'], x['cell']): x for x in execution['final_formula_snapshot']}
    edits = []; irr_proofs = {}; cf = book['Cash Flow']
    originals = {(s.title, c.coordinate): formula_text(c.value) for s in book
                 for c in s._cells.values() if c.data_type == 'f'}
    comment_count = sum(c.comment is not None for s in book for c in s._cells.values())
    original_cells={(s.title,c.coordinate):formula_text(c.value) for s in book for c in s._cells.values() if c.value is not None}
    original_comments={(s.title,c.coordinate):c.comment.text for s in book for c in s._cells.values() if c.comment is not None}
    for address in sorted(tables):
        cell = cf[address]
        anchor = next(c for c in cf._cells.values() if c.value.__class__.__name__ == 'DataTableFormula'
                      and c.value.ref.split(':')[0].rstrip('0123456789') == address.rstrip('0123456789')) if cell.value.__class__.__name__ != 'DataTableFormula' else cell
        edits.append({'sheet': 'Cash Flow', 'cell': address, 'kind': 'provided_calibration_snapshot',
                      'original_type': cell.data_type, 'original_formula_or_value': formula_text(cell.value),
                      'original_group_ref': getattr(anchor.value, 'ref', None),
                      'new_value': values[address], 'method': 'fresh_external_public_three_grid_formula_execution'})
    # Prepare the complete edit list before removing any group anchor.
    for address, value in values.items():
        cf[address] = value
    tariff = execution['computed_tariff_cents_per_kwh']
    edits.append({'sheet': 'Cash Flow', 'cell': cfg['input'], 'kind': 'provided_fixed_ppa_assumption',
                  'original_formula': cf[cfg['input']].value, 'new_value': tariff,
                  'method': 'midpoint_of_freshly_executed_public_tenth_cent_sign_bracket'})
    cf[cfg['input']] = tariff
    for sheet in book:
        for cell in list(sheet._cells.values()):
            if cell.data_type != 'f' or not isinstance(cell.value, str) or not IRR.search(cell.value):
                continue
            current = snapshot[(sheet.title, cell.coordinate)]
            # Preserve successful default IRR results. Only a currently failed guarded/default result needs a fallback.
            if not current['observed_error'] and current['observed_string'] not in {'NA', 'N/A'}:
                continue
            old = cell.value; proofs = []
            def replace(match):
                address = match.group(1)
                if ',' in address or '!' in address:
                    raise ValueError('Unsupported IRR arguments')
                minc, minr, maxc, maxr = range_boundaries(address)
                flows = []
                for row in range(minr, maxr + 1):
                    for col in range(minc, maxc + 1):
                        source_cell = sheet.cell(row, col); key = (sheet.title, source_cell.coordinate)
                        if key in snapshot:
                            observed = snapshot[key]
                            if observed['observed_error'] or "'VALUE'" not in observed.get('observed_result_type',''):
                                raise ValueError('IRR input execution is not a finite numeric result')
                            flow = observed['observed_numeric']
                        elif source_cell.data_type != 'f':
                            flow = source_cell.value
                        else:
                            raise ValueError('IRR formula input lacks independent execution')
                        if flow is not None:
                            flows.append(flow)
                proof = unique_irr(flows); proof['range'] = address; proofs.append(proof)
                return f'IFERROR(IRR({address}),IRR({address},-0.9))'
            cell.value = IRR.sub(replace, old)
            if not proofs:
                raise ValueError('Missing IRR proof')
            irr_proofs[(sheet.title, cell.coordinate)] = proofs[0]
            edits.append({'sheet': sheet.title, 'cell': cell.coordinate, 'kind': 'unique_irr_numerical_fallback',
                          'original_formula': old, 'new_formula': cell.value, 'proofs': proofs})
    note = book.create_sheet('Fixed PPA Scenario', 0)
    note['A1'] = 'Derived fixed-price project-finance scenario'
    note['A3'] = ('Use the provided fixed PPA tariff for the active financial forecasts. The original automatic COE/F9 '
                  'instructions do not apply to this scenario. The 33 search-table NPV observations are supplied calibration '
                  'snapshots generated from the original financial schedules at their listed tariff grid points; they do not '
                  'update when business assumptions change. Debt, reserves, depreciation, taxes and cash-flow forecasts remain formulas.')
    note['A5'] = 'Provided PPA tariff (cents/kWh)'; note['B5'] = tariff
    note['A7'] = 'Original public model'; note['B7'] = cfg['url']
    note['A8'] = 'Original file SHA256'; note['B8'] = sha(source)
    note['A10'] = 'Derived scenario version'; note['B10'] = 'crest-fixed-ppa-v1'
    note.column_dimensions['A'].width = 65; note.column_dimensions['B'].width = 100
    note['A3'].alignment = openpyxl.styles.Alignment(wrap_text=True, vertical='top'); note.row_dimensions[3].height = 100
    book.active = 0
    if any(c.value.__class__.__name__ == 'DataTableFormula' or (isinstance(c.value, str) and re.search(r'\bTABLE\s*\(', c.value, re.I))
           for s in book for c in s._cells.values()):
        raise ValueError('TABLE calculation remains')
    after = {(s.title, c.coordinate): formula_text(c.value) for s in book for c in s._cells.values() if c.data_type == 'f'}
    changed = {k for k in originals.keys() | after.keys() if originals.get(k) != after.get(k)}
    allowed = {('Cash Flow', cfg['input'])} | {('Cash Flow', ad) for ad in tables} | set(irr_proofs)
    if changed - allowed:
        raise ValueError('Unapproved financial formula edit')
    if sum(c.comment is not None for s in book for c in s._cells.values()) != comment_count:
        raise ValueError('Original comments changed')
    saved_sheet_names=book.sheetnames[:]
    book.save(destination); book.close()
    precision_patches=restore_input_precision(destination,original_cells,allowed,saved_sheet_names)
    saved=openpyxl.load_workbook(destination,data_only=False,keep_links=True)
    for (sn,ad),value in original_cells.items():
        if (sn,ad) not in allowed and formula_text(saved[sn][ad].value)!=value:
            raise ValueError('Protected source cell changed during serialization: '+sn+'!'+ad)
    if {(s.title,c.coordinate):c.comment.text for s in saved for c in s._cells.values() if c.comment is not None}!=original_comments:
        raise ValueError('Original comments changed during serialization')
    saved.close()
    return {'edits': edits, 'original_formula_sha256': hashlib.sha256(json.dumps(sorted((s,a,v) for (s,a),v in originals.items()),default=str).encode()).hexdigest(),
            'derived_formula_sha256': hashlib.sha256(json.dumps(sorted((s,a,v) for (s,a),v in after.items()),default=str).encode()).hexdigest(),
            'formula_changed_cells': [s+'!'+a for s,a in sorted(changed)], 'exact_calibration_cell_count': 33, 'preserved_numeric_input_precision': precision_patches,
            'retained_source_formula_count': len(set(originals) - changed), 'original_comment_count': comment_count,
            'irr_proofs': {s+'!'+a:v for (s,a),v in irr_proofs.items()}, 'provided_tariff': tariff}


def validate_result(source, normalized, kind, execution, mutation):
    cfg = SOURCES[kind]; start = cfg['table_start']
    actual = openpyxl.load_workbook(normalized, data_only=True, keep_links=False)
    formulas = openpyxl.load_workbook(normalized, data_only=False, keep_links=False)
    calibration = expected_calibration_formulas(execution, start)
    original = openpyxl.load_workbook(source,data_only=False,keep_links=False)
    proofs = mutation['irr_proofs']; failures = []; checked = []; display_differences=[]
    for item in execution['final_formula_snapshot']:
        sheet, address = item['sheet'], item['cell']; key = sheet+'!'+address
        if sheet == 'Cash Flow' and address in calibration_values(execution, start):
            continue
        if 'observed_result_type' not in item:
            raise ValueError('Independent execution lacks UNO result types')
        expected = item['observed_numeric'] if "'VALUE'" in item['observed_result_type'] else (item['observed_string'] or None)
        if item['observed_error']:
            if sheet == 'Cash Flow' and address in calibration:
                expected = calibration[address]
            else:
                failures.append({'cell': key, 'reason': 'independent_reference_execution_error'}); continue
        elif key in proofs:
            expected = proofs[key]['unique_root']
        elif item['observed_string'] in {'NA', 'N/A'}:
            # Guarded nonnumeric values are checked as text unless a proved fallback supplies a unique root.
            expected = item['observed_string']
        elif expected is not None and not isinstance(expected, (int,float)):
            expected = item['observed_string']
        observed = actual[sheet][address]
        if isinstance(expected,(int,float)) and not isinstance(expected,bool):
            is_amount = any(x in observed.number_format for x in ('$', '#,##0', '#,##0.00')) and '%' not in observed.number_format
            match = observed.data_type != 'e' and isinstance(observed.value,(int,float)) and (cent(observed.value)==cent(expected) if is_amount else math.isclose(observed.value,expected,rel_tol=1e-11,abs_tol=1e-10))
        elif expected is None:
            match = observed.value in (None,'')
        else:
            match = observed.value == expected
        # A dependent display with one changed IRR precedent inherits its independently proved root.
        if not match and item['observed_string'] in {'NA','N/A'}:
            from sheets_factory.workbook.profile import formula_references
            text = formulas[sheet][address].value
            if isinstance(text,str):
                refs=formula_references(text,sheet)
                candidates={r['sheet']+'!'+r['cell'] for r in refs['references']} & set(proofs)
                if refs['fully_supported'] and len(candidates)==1 and isinstance(observed.value,(int,float)):
                    proof=proofs[next(iter(candidates))]
                    match=abs(observed.value-proof['unique_root'])<1e-10
        if not match and original[sheet][address].hyperlink is not None and expected in (None,'') and isinstance(observed.value,str):
            display_differences.append({'cell':key,'expected':expected,'actual':observed.value,'scope':'nonfinancial_hyperlink_display'});match=True
        if not match: failures.append({'cell': key, 'expected': expected, 'actual': observed.value})
        checked.append(key)
    for address,value in calibration_values(execution,start).items():
        c=actual['Cash Flow'][address]
        if c.data_type=='e' or not isinstance(c.value,(int,float)) or abs(c.value-value)>1e-6:
            failures.append({'cell':'Cash Flow!'+address,'reason':'calibration_snapshot_mismatch'})
    for key,proof in proofs.items():
        sn,ad=key.rsplit('!',1);value=actual[sn][ad].value
        if not isinstance(value,(int,float)) or abs(value-proof['unique_root'])>1e-10:
            failures.append({'cell':key,'reason':'IRR_unique_root_mismatch'})
    errors=[{'sheet':s.title,'cell':c.coordinate,'value':c.value} for s in actual for c in s._cells.values() if c.data_type=='e']
    if errors: failures.extend(errors)
    # Financial formulas are preserved textually before normalization; after normalization allow only native expression serialization.
    actual.close(); formulas.close(); original.close()
    return {'passed':not failures,'checked_original_formula_cells':len(checked),'calibration_points_checked':33,
            'cached_errors':errors,'nonfinancial_display_differences':display_differences,'failures':failures,'reference_method':'fresh_source_formula_execution_at_externally_computed_tariff_plus_independent_grid_helpers_and_IRR_bisection'}


def build(root, source, output, kind):
    root,source,output=Path(root).resolve(),Path(source).resolve(),Path(output).resolve()
    if output.exists():raise FileExistsError('Refuse to overwrite a source experiment')
    output.mkdir(parents=True);started=time.monotonic();cfg=SOURCES[kind]
    recipe_paths=[Path(__file__).resolve(),root/'src/sheets_factory/workbook/engine.py',root/'src/sheets_factory/workbook/uno_recalculate.py',root/'src/sheets_factory/workbook/compare.py',root/'src/sheets_factory/workbook/profile.py']
    recipe_before={str(p.relative_to(root)):sha(p) for p in recipe_paths}
    try:
        if sha(source)!=cfg['sha256']:raise ValueError('Original CREST source SHA differs')
        engine=LibreOfficeEngine(root);metadata=engine.metadata()
        if metadata['image_id']!=PINNED_IMAGE:raise ValueError('Pinned engine differs')
        execution=execute_scenarios(root,source,output,kind)
        mutation=create_derived(source,output/'derived_input.xlsx',kind,execution);write(output/'mutation_audit.json',mutation)
        engine.normalize(output/'derived_input.xlsx',output/'normalized.xlsx')
        stable=engine.check_stable(output/'normalized.xlsx',output/'stability');write(output/'stability.json',stable)
        audit=validate_result(source,output/'normalized.xlsx',kind,execution,mutation);write(output/'financial_comparison.json',audit)
        profile=profile_workbook(output/'normalized.xlsx',max_cells=10**9);write(output/'profile_full.json',profile)
        if not stable['stable'] or not audit['passed'] or profile['truncated'] or profile['errors'] or profile['external_references']:
            raise ValueError('Derived source failed actual financial/runtime checks')
        if sha(source)!=cfg['sha256']:raise ValueError('Original source changed')
        if recipe_before!={str(p.relative_to(root)):sha(p) for p in recipe_paths}:raise ValueError('Source adapter/runtime recipe changed during build')
        manifest={'status':'compatible_derived_fixed_ppa_pending_business_quality_and_task_qualification','source_kind':'derived_explicit_fixed_ppa_calibration_snapshot',
                  'source_url':cfg['url'],'original_path':str(source),'original_sha256':sha(source),'normalized_path':str(output/'normalized.xlsx'),'normalized_sha256':sha(output/'normalized.xlsx'),
                  'provided_tariff_cents_per_kwh':execution['computed_tariff_cents_per_kwh'],'engine':metadata,'elapsed_seconds':time.monotonic()-started,
                  'real_lo_container_sessions':4,'model_calls':0,'tokens':0,'source_workbooks_modified':False,'source_financial_formulas_retained_except_proved_irr':True,
                  'selected':[],'qualified':False,'task_count':0,'unique_ancestors':1,'derived_workbook_count':1,
                  'proofs':{p.name:{'path':str(p),'sha256':sha(p)} for p in output.rglob('*') if p.is_file()},
                  'recipe_sha256':{str(p.relative_to(root)):sha(p) for p in [Path(__file__).resolve(),root/'src/sheets_factory/workbook/engine.py',root/'src/sheets_factory/workbook/uno_recalculate.py',root/'src/sheets_factory/workbook/compare.py',root/'src/sheets_factory/workbook/profile.py']}}
        write(output/'manifest.json',manifest);return manifest
    except Exception as exc:
        write(output/'failure.json',{'status':'rejected','error':type(exc).__name__,'detail':str(exc),'elapsed_seconds':time.monotonic()-started,'qualified':False,'task_count':0});raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--kind',choices=SOURCES,required=True);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);a=parser.parse_args()
    result=build(a.root,a.source,a.output,a.kind);print(json.dumps({k:result[k] for k in ['status','normalized_path','normalized_sha256','elapsed_seconds']},indent=2))
if __name__=='__main__':main()
