#!/usr/bin/env python3
"""Prepare or explicitly run a complete N360 native source certification.

The isolated adapter retains three real LibreOffice calculations, full A/B
financial audits, exact geometry and two complete typed stability comparisons.
No engine, solver or model starts on import or during preparation.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM = _Path(__file__).with_name('build_linear_capital_source.py')
UPSTREAM_SHA256 = '8a4d9a84908242faa807fd969707326e028afaa17a3f8a9b0fc82d597f54c90e'
PRODUCER = _Path(__file__).with_name('build_linear_capital_producer_source.py')
PRODUCER_SHA256 = '79099dcc2e0ba8ad7f7ded6fc6416452ed22f3f8e686e22f36de19d5d0621a52'
REFERENCE_KIND = 'linear_capital_scaled_producer16_best_runner_dual_financial_reference'


def adapted_ast():
    raw, producer_raw = UPSTREAM.read_bytes(), PRODUCER.read_bytes()
    if (_hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256
            or _hashlib.sha256(producer_raw).hexdigest() != PRODUCER_SHA256):
        raise ValueError('The frozen complete source certification implementations changed')
    tree = _ast.parse(raw, filename=str(UPSTREAM)); counts = {}
    producer = _ast.parse(producer_raw)
    expected_results = [n for n in producer.body if isinstance(n,_ast.FunctionDef) and n.name == 'expected_results']
    if len(expected_results) != 1: raise ValueError('The complete two-plan financial join changed')
    def changed(key): counts[key] = counts.get(key,0)+1
    strings = {
        'prepared_linear_capital_native_source':'prepared_linear_capital_scaled_native_source',
        'independently_verified_linear_capital_native_source':'independently_verified_linear_capital_scaled_native_source',
        'linear_capital_independent_best_runner_reference':REFERENCE_KIND,
        'linear_capital_native_source_build_terminal':'linear_capital_scaled_native_source_build_terminal',
        'sheets_factory.workbook.linear_capital_portfolio.excel':'sheets_factory.workbook.linear_capital_scaled.excel',
    }
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            prefix = 'sheets_factory.workbook.linear_capital_portfolio'
            if node.level == 0 and node.module and (node.module == prefix or node.module.startswith(prefix+'.')):
                node.module = node.module.replace(prefix,'sheets_factory.workbook.linear_capital_scaled',1)
                changed('schema_import')
            return node
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in strings:
                before = node.value; node.value = strings[before]; changed(before)
            return node
        def visit_Compare(self,node):
            if _ast.unparse(node) == '80 <= count <= 160':
                changed('density')
                return _ast.parse('120 <= count <= 240',mode='eval').body
            return self.generic_visit(node)
        def visit_FunctionDef(self,node):
            if node.name == '_reference_provider':
                changed('reference_provider')
                node.body = _ast.parse("return _module(ROOT/'scripts/run_linear_capital_scaled_reference.py', '_linear_scaled_source_reference')").body
                return node
            if node.name == 'expected_results':
                changed('two_plan_join'); return expected_results[0]
            return self.generic_visit(node)
    tree = Adapt().visit(tree)
    tree.body = [node for node in tree.body if not (isinstance(node,_ast.If)
        and _ast.dump(node.test) == _ast.dump(_ast.parse("__name__ == '__main__'",mode='eval').body))]
    expected = {key:1 for key in strings}
    expected['linear_capital_native_source_build_terminal'] = 2
    expected.update(schema_import=3,density=1,reference_provider=1,two_plan_join=1)
    if counts != expected:
        raise ValueError('The exact N360 complete-source substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),__file__,'exec'),globals())
_base_recipes = recipes
_base_expected_values = expected_values


def recipes():
    from sheets_factory.workbook.linear_capital_scaled import excel, finance, spec
    provider = _reference_provider()
    paths = [UPSTREAM,PRODUCER,*[Path(path) for path in provider.recipes()],
        Path(excel.__file__),excel.UPSTREAM,Path(spec.__file__),spec.upstream_path(),
        *finance.source_files().values(),
        ROOT/'src/sheets_factory/workbook/linear_capital_scaled/formula_identity.py']
    return {**_base_recipes(),**{str(Path(path).resolve()):reference(path)['sha256'] for path in paths}}


def expected_values(public,result_a,result_b,bindings,plan):
    require(bindings.get('kind') == 'linear_capital_scaled_native_excel_bindings',
        'Use the versioned complete N360 native bindings')
    return _base_expected_values(public,result_a,result_b,bindings,plan)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path);parser.add_argument('--reference',type=Path)
    parser.add_argument('--output',type=Path);parser.add_argument('--profile',type=Path)
    parser.add_argument('--prepared',type=Path);parser.add_argument('--run',action='store_true')
    parser.add_argument('--port',type=int,default=0);args=parser.parse_args(argv)
    if not 0 <= args.port <= 65535: parser.error('Use a port between 0 and 65535')
    if args.prepared is not None:
        if any(v is not None for v in (args.spec,args.reference,args.output,args.profile)):
            parser.error('An existing preparation cannot receive replacement inputs or profile')
        if args.run: result=execute_prepared(args.prepared,port=args.port)
        else:
            validate_prepared(args.prepared);result=reference(args.prepared/'preparation.json')
    else:
        if any(v is None for v in (args.spec,args.reference,args.output)):
            parser.error('A new source requires --spec --reference --output together')
        result=prepare(args.spec,args.reference,args.output,
            profile=args.profile if args.profile is not None else DEFAULT_PROFILE)
        if args.run: result=execute_prepared(args.output,port=args.port)
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__ == '__main__': raise SystemExit(main())
