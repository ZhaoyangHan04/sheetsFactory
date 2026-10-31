"""Bounded OOXML composition of unchanged, separately ringfenced mandates.

Only one worksheet row is retained while rewriting financial cells. Compact
style/string/name metadata is merged separately. No bindings JSON, financial
forward, optimizer, LibreOffice or task qualification runs in this module.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import posixpath
import re
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as X
from xml.sax.saxutils import quoteattr

from .. import heterogeneous_native_merge as syntax

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
C = 'http://schemas.openxmlformats.org/package/2006/content-types'
MERGER_SHA256 = '38bf2e1ad2f961af08e8f9138094c88c2b14dde0d216f4c5eaced3433b1fc701'
LIMITS = {'formulas': 5_200_000, 'nonempty': 7_500_000, 'targets': 6_400_000}
MAX_METADATA_BYTES = 16 * 1024**2
FIXED = [('M01', 'P01 - '), ('M02', 'P02 - '), ('M03', 'P07 - '), ('M04', 'P09 - ')]


def require(value, message):
    if not value:
        raise ValueError(message)


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'A real immutable package is required')
    before = path.stat(); digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024**2), b''):
            digest.update(chunk)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'A package changed while hashing')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': before.st_size}


def _checked(row):
    require(type(row) is dict and set(row) == {'path', 'sha256', 'bytes'} and reference(row['path']) == row,
            'A complete unchanged artifact reference is required')
    return Path(row['path'])


def _xml(archive, name):
    require(archive.getinfo(name).file_size <= MAX_METADATA_BYTES, 'Metadata part exceeds the bounded parser: ' + name)
    raw = archive.read(name)
    require(b'<!DOCTYPE' not in raw and b'<!ENTITY' not in raw, 'Document/entity declarations are unsupported')
    return X.fromstring(raw)


def _bytes(element):
    return X.tostring(element, encoding='UTF-8', xml_declaration=True)


def _tag(node):
    return node.tag.rsplit('}', 1)[-1]


def _resolve(source, target):
    require('\\' not in target and '?' not in target and '#' not in target, 'Unhandled internal relationship target')
    result = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(source), target))
    require(not result.startswith('../') and result != '..', 'Relationship escapes its package')
    return result


def sheet_map(prefix, names, used=None):
    require(re.fullmatch(r'[A-Za-z][A-Za-z0-9 ]{0,12} - ', prefix) is not None, 'Use a readable fixed fund prefix')
    used = set() if used is None else used
    result = {}
    for name in names:
        mapped = prefix + name
        require(len(mapped) <= 31 and not re.search(r'[\[\]:*?/\\]', mapped), 'A complete readable sheet name exceeds Excel bounds')
        require(name.casefold() not in {x.casefold() for x in result} and mapped.casefold() not in used,
                'Case-insensitive worksheet namespace collision')
        result[name] = mapped; used.add(mapped.casefold())
    return result


def rekey_binding(fund_id, binding, composition):
    """Map one retained binding on demand; do not build a combined JSON map."""
    donor = next((row for row in composition['donors'] if row['id'] == fund_id), None)
    require(donor is not None and binding['sheet'] in donor['sheet_map'], 'Unknown fund or local binding sheet')
    return {**deepcopy(binding), 'sheet': donor['sheet_map'][binding['sheet']], 'fund_id': fund_id}


def _load(donors):
    require(hashlib.sha256(Path(syntax.__file__).read_bytes()).hexdigest() == MERGER_SHA256, 'The frozen parsed formula rewriter changed')
    require(2 <= len(donors) <= 4 and len({d['id'] for d in donors}) == len(donors), 'Use two to four distinct mandates')
    loaded = []; used = set()
    for donor in donors:
        require(re.fullmatch(r'M[0-9]{2}', donor['id']) is not None, 'Invalid mandate identity')
        path = _checked(donor['workbook'])
        with ZipFile(path) as archive:
            infos = archive.infolist(); members = {part.filename for part in infos}
            require(len(infos) == len(members) and len(infos) <= 5000, 'Duplicate or excessive ZIP parts')
            require(all(not name.startswith('/') and '..' not in name.split('/') for name in members), 'Unsafe package path')
            types = _xml(archive, '[Content_Types].xml')
            require(all(n.get('PartName') is None or n.get('PartName').lstrip('/') in members for n in types),
                    'A content-type override references a missing part')
            allowed = {'[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels',
                       'xl/styles.xml', 'xl/sharedStrings.xml', 'xl/theme/theme1.xml', 'xl/calcChain.xml',
                       'docProps/core.xml', 'docProps/app.xml', 'docProps/custom.xml'}
            require(all(name in allowed or re.fullmatch(r'xl/worksheets/(?:sheet[0-9]+\.xml|_rels/sheet[0-9]+\.xml\.rels)', name)
                        for name in members), 'Unhandled workbook objects; no part may be silently dropped')
            wb = _xml(archive, 'xl/workbook.xml'); relations = _xml(archive, 'xl/_rels/workbook.xml.rels')
            rels = {r.get('Id'): r for r in relations}
            require(len(rels) == len(relations), 'Duplicate workbook relationship ID')
            require(all(r.get('Type', '').startswith(R+'/') and r.get('Type').rsplit('/', 1)[-1]
                in {'worksheet', 'styles', 'sharedStrings', 'theme', 'calcChain'} and r.get('TargetMode') is None for r in relations),
                'Unhandled or external workbook relationship')
            sheets = wb.find('{'+S+'}sheets'); names = [n.get('name') for n in sheets]
            mapped = sheet_map(donor['prefix'], names, used)
            parts = {}
            for n in sheets:
                relation = rels[n.get('{'+R+'}id')]
                require(relation.get('Type') == R+'/worksheet', 'Sheet relationship has wrong type')
                part = _resolve('xl/workbook.xml', relation.get('Target'))
                require(part in members, 'A required worksheet part is missing')
                parts[n.get('name')] = part
            require(set(parts.values()) == {n for n in members if re.fullmatch(r'xl/worksheets/sheet[0-9]+\.xml', n)},
                    'A worksheet is unbound or duplicated')
            sheet_relationship_ids = {}
            for name, part in parts.items():
                relation_part = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part)+'.rels')
                linked = _xml(archive, relation_part) if relation_part in members else []
                ids = {r.get('Id') for r in linked}
                require(None not in ids and len(ids) == len(linked), 'Duplicate or missing worksheet relationship ID')
                sheet_relationship_ids[name] = ids
            names_map = {}
            defined = wb.find('{'+S+'}definedNames')
            for n in defined if defined is not None else []:
                local = n.get('localSheetId'); scope = names[int(local)] if local is not None else None
                new = n.get('name') if n.get('name').startswith('_xlnm.') else donor['prefix'].replace(' - ', '__')+n.get('name')
                key = (scope.casefold() if scope else None, n.get('name').casefold())
                require(key not in names_map, 'Duplicate scoped defined name')
                names_map[key] = new
            root_relations = _xml(archive, '_rels/.rels')
            require(all(r.get('TargetMode') is None and _resolve('', r.get('Target', '')) in members
                and r.get('Type', '').rsplit('/', 1)[-1] in {'officeDocument', 'core-properties', 'extended-properties', 'custom-properties'}
                for r in root_relations), 'Unhandled package relationship')
            theme = archive.read('xl/theme/theme1.xml') if 'xl/theme/theme1.xml' in members else None
            epoch = wb.find('{'+S+'}workbookPr')
            calc = wb.find('{'+S+'}calcPr')
            settings = {'date1904': epoch.get('date1904', '0') in ('1', 'true') if epoch is not None else False,
                        'calc': dict(calc.attrib) if calc is not None else {}}
            require(settings['calc'].get('refMode', 'A1') == 'A1' and settings['calc'].get('fullPrecision', '1') not in ('false', '0'),
                    'Use full-precision A1 calculation')
            loaded.append({**donor, 'path': path, 'members': members, 'workbook_tree': wb, 'sheet_map': mapped,
                'sheet_relationship_ids': sheet_relationship_ids,
                'sheet_parts': parts, 'names': names_map, 'theme': theme, 'settings': settings})
    require(all(d['theme'] == loaded[0]['theme'] and d['settings'] == loaded[0]['settings'] for d in loaded),
            'Different themes, epochs or calculation policies need a separate semantic policy')
    return loaded


def _styles(loaded):
    root = X.Element('{'+S+'}styleSheet')
    families = ('numFmts', 'fonts', 'fills', 'borders', 'cellStyleXfs', 'cellXfs', 'cellStyles', 'dxfs')
    sections = {key: X.SubElement(root, '{'+S+'}'+key) for key in families}; offsets = []; next_format = 164
    colors = None
    for donor in loaded:
        with ZipFile(donor['path']) as archive:
            old = _xml(archive, 'xl/styles.xml')
        require(all(_tag(n) in {*families, 'colors', 'tableStyles'} for n in old), 'Unhandled style metadata')
        table = old.find('{'+S+'}tableStyles')
        require(table is None or len(table) == 0, 'Custom table styles are unsupported')
        palette = old.find('{'+S+'}colors')
        raw_colors = X.tostring(palette) if palette is not None else None
        if offsets:
            require(raw_colors == colors, 'Different indexed-color palettes require explicit normalization')
        else:
            colors = raw_colors
        off = {key: len(sections[key]) for key in families}; counts = {}
        formats = {}
        for family in families:
            node = old.find('{'+S+'}'+family); counts[family] = len(node) if node is not None else 0
            if family == 'numFmts':
                for n in node if node is not None else []:
                    formats[int(n.get('numFmtId'))] = next_format; next_format += 1
            for n in node if node is not None else []:
                n = deepcopy(n)
                for child in n.iter():
                    if child.get('numFmtId') is not None and int(child.get('numFmtId')) in formats:
                        child.set('numFmtId', str(formats[int(child.get('numFmtId'))]))
                    for attr, group in (('fontId', 'fonts'), ('fillId', 'fills'), ('borderId', 'borders'), ('xfId', 'cellStyleXfs')):
                        if child.get(attr) is not None:
                            index = int(child.get(attr)); require(0 <= index < counts.get(group, len(old.find('{'+S+'}'+group))), 'Style component index out of bounds')
                            child.set(attr, str(index+off[group]))
                if family == 'cellStyles':
                    n.set('name', donor['id']+'__'+n.get('name')); n.attrib.pop('builtinId', None)
                sections[family].append(n)
        off['counts'] = counts; offsets.append(off)
    for key, section in sections.items(): section.set('count', str(len(section)))
    if colors is not None: root.append(X.fromstring(colors))
    require(len(sections['cellXfs']) <= 65490, 'Excel unique style limit exceeded')
    return root, offsets


def _strings(loaded, offsets):
    root = X.Element('{'+S+'}sst')
    for donor, off in zip(loaded, offsets):
        off['sst'] = len(root); strings = []
        if 'xl/sharedStrings.xml' in donor['members']:
            with ZipFile(donor['path']) as archive: strings = list(_xml(archive, 'xl/sharedStrings.xml'))
        off['strings'] = strings
        for node in strings: root.append(deepcopy(node))
    return root


def _formula(text, donor, sheet=None, *, defined=False):
    result = syntax.rewrite_formula(text, donor['sheet_map'], donor['names'], local_sheet=sheet, defined_name=defined)
    require(len(result) <= 8192, 'A namespaced formula exceeds the Excel length limit')
    reverse = {v: k for k, v in donor['sheet_map'].items()}
    back_names = {(donor['sheet_map'][next(s for s in donor['sheet_map'] if s.casefold() == scope)].casefold() if scope else None, new.casefold()): old
        for (scope, old), new in donor['names'].items()}
    restored = syntax.rewrite_formula(result, reverse, back_names,
        local_sheet=donor['sheet_map'].get(sheet), defined_name=defined)
    require(syntax._formula_tokens(restored) == syntax._formula_tokens(text), 'Parsed reference round trip changed formula meaning')
    return result


def _misc(node, donor, off, sheet):
    for child in node.iter():
        local = _tag(child)
        for attr, value in child.attrib.items():
            if attr.startswith('{'+R+'}'):
                require(attr == '{'+R+'}id' and value in donor['sheet_relationship_ids'][sheet],
                        'Worksheet metadata references a missing or unsupported relationship')
        if local in ('formula', 'formula1', 'formula2') and child.text:
            child.text = _formula(child.text, donor, sheet)
        if local == 'hyperlink' and child.get('location'):
            child.set('location', _formula(child.get('location'), donor, sheet))
        for attr, group in (('style', 'cellXfs'), ('s', 'cellXfs'), ('dxfId', 'dxfs')):
            if child.get(attr) is not None:
                n = int(child.get(attr)); require(0 <= n < off['counts'][group], 'Metadata style index out of bounds')
                child.set(attr, str(n+off[group]))


def _sheet(archive, target, part, donor, off, sheet):
    counts = {'formulas': 0, 'nonempty': 0, 'cleared_formula_value_nodes': 0, 'maximum_row_cells': 0}
    given = hashlib.sha256(); formulas = hashlib.sha256()
    def row(element):
        cells = element.findall('{'+S+'}c'); counts['maximum_row_cells'] = max(counts['maximum_row_cells'], len(cells))
        for cell in cells:
            formula = cell.find('{'+S+'}f'); value = cell.find('{'+S+'}v')
            inline = cell.find('{'+S+'}is'); typ = cell.get('t', 'n')
            if formula is not None:
                require(set(formula.attrib) <= {'t', 'aca', 'ca'} and formula.get('t', 'normal') == 'normal', 'Shared/array/dataTable formulas require explicit support')
                original = formula.text or ''; require(bool(original), 'An empty physical formula is unsupported')
                formula.text = _formula(original, donor, sheet)
                formulas.update(json.dumps([sheet, cell.get('r'), original], ensure_ascii=False).encode()+b'\n')
                for tag in ('v', 'is'):
                    for cache in list(cell.findall('{'+S+'}'+tag)):
                        cell.remove(cache); counts['cleared_formula_value_nodes'] += 1
                cell.attrib.pop('t', None); counts['formulas'] += 1; counts['nonempty'] += 1
            else:
                text = value.text if value is not None else None
                semantic = text; nonempty = bool(text)
                if typ == 's':
                    n = int(text); require(0 <= n < len(off['strings']), 'Shared-string index out of bounds')
                    semantic = X.canonicalize(X.tostring(off['strings'][n], encoding='unicode')); value.text = str(n+off['sst'])
                    nonempty = bool(''.join(node.text or '' for node in off['strings'][n].iter('{'+S+'}t')))
                elif inline is not None:
                    semantic = X.canonicalize(X.tostring(inline, encoding='unicode'))
                    nonempty = bool(''.join(node.text or '' for node in inline.iter('{'+S+'}t')))
                if semantic is not None:
                    given.update(json.dumps([sheet, cell.get('r'), typ, semantic], ensure_ascii=False).encode()+b'\n')
                    counts['nonempty'] += int(nonempty)
            n = int(cell.get('s', '0')); require(0 <= n < off['counts']['cellXfs'], 'Cell style index out of bounds')
            cell.set('s', str(n+off['cellXfs']))
        if element.get('s') is not None:
            n = int(element.get('s')); require(0 <= n < off['counts']['cellXfs'], 'Row style index out of bounds')
            element.set('s', str(n+off['cellXfs']))
    with archive.open(part) as source, target as destination:
        destination.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        depth = 0; data_open = False; parents = []; namespaces = {}
        for event, element in X.iterparse(source, events=('start-ns', 'start', 'end')):
            if event == 'start-ns':
                if depth == 0: namespaces[element[0]] = element[1]
                continue
            if event == 'start':
                depth += 1; parents.append(element)
                if depth == 1:
                    require(element.tag == '{'+S+'}worksheet', 'A worksheet root is required')
                    namespaces[''] = S
                    attrs = {'xmlns'+(':'+prefix if prefix else ''): uri for prefix, uri in namespaces.items()}
                    for key, value in element.attrib.items():
                        if key.startswith('{'):
                            uri, local = key[1:].split('}')
                            prefix = next((p for p, u in namespaces.items() if p and u == uri), None)
                            require(prefix is not None, 'A namespaced root attribute lost its prefix')
                            key = prefix+':'+local
                        attrs[key] = value
                    destination.write(('<worksheet'+''.join(' '+key+'='+quoteattr(value) for key, value in attrs.items())+'>').encode())
                elif depth == 2 and _tag(element) == 'sheetData':
                    require(all(not key.startswith('{') for key in element.attrib), 'Unhandled sheetData attribute namespace')
                    destination.write(('<sheetData'+''.join(' '+key+'='+quoteattr(value) for key, value in element.attrib.items())+'>').encode()); data_open = True
                continue
            if depth == 3 and _tag(element) == 'row' and data_open:
                row(element); destination.write(X.tostring(element)); parents[-2].remove(element); element.clear()
            elif depth == 2:
                if _tag(element) == 'sheetData': destination.write(b'</sheetData>'); data_open = False
                else: _misc(element, donor, off, sheet); destination.write(X.tostring(element))
                parents[-2].remove(element); element.clear()
            elif depth == 1: destination.write(b'</worksheet>')
            depth -= 1; parents.pop()
    return {**counts, 'given_literal_semantic_sha256': given.hexdigest(), 'original_formula_coordinate_sha256': formulas.hexdigest()}


def _compose(donors, output, *, mode, target_count=None, toy=False, ancestry=None, expected_census=None):
    output = Path(output).absolute()
    require(output == output.resolve() and output.suffix == '.xlsx' and not output.exists(), 'Use a fresh real XLSX output path')
    loaded = _load(donors); styles, offsets = _styles(loaded); strings = _strings(loaded, offsets)
    content = X.Element('{'+C+'}Types'); seen_types = {}
    workbook = deepcopy(loaded[0]['workbook_tree']); sheets = workbook.find('{'+S+'}sheets'); sheets.clear()
    for child in list(workbook):
        if _tag(child) == 'definedNames': workbook.remove(child)
    names = X.Element('{'+S+'}definedNames')
    position = next((i for i, child in enumerate(workbook) if _tag(child) in ('calcPr', 'extLst')), len(workbook))
    workbook.insert(position, names)
    relationships = X.Element('{'+P+'}Relationships')
    calc = workbook.find('{'+S+'}calcPr')
    if calc is None: calc = X.SubElement(workbook, '{'+S+'}calcPr')
    calc.set('fullCalcOnLoad', '1'); calc.set('forceFullCalc', '1'); calc.set('calcMode', 'auto')
    geometry = {'formulas': 0, 'nonempty': 0}; reports = []; sheet_index = 0
    custom_properties = None
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.ringfenced-compose-', dir=output.parent) as temporary:
        pending = Path(temporary)/'pending.xlsx'
        with ZipFile(pending, 'w', ZIP_DEFLATED, compresslevel=6) as out:
            for index, (donor, off) in enumerate(zip(loaded, offsets)):
                report = {'id': donor['id'], 'workbook': donor['workbook'],
                          'sheet_map': donor['sheet_map'], 'worksheets': []}
                sheet_parts = donor['sheet_parts']; mapped_parts = {part: 'xl/funds/'+donor['id']+'/'+part.removeprefix('xl/') for part in sheet_parts.values()}
                for original, part in sheet_parts.items():
                    relation_id = 'rId'+str(sheet_index+1)
                    source_sheet = next(n for n in donor['workbook_tree'].find('{'+S+'}sheets') if n.get('name') == original)
                    attrs = {**source_sheet.attrib, 'name': donor['sheet_map'][original], 'sheetId': str(sheet_index+1), '{'+R+'}id': relation_id}
                    X.SubElement(sheets, '{'+S+'}sheet', attrib=attrs)
                    X.SubElement(relationships, '{'+P+'}Relationship', Id=relation_id, Type=R+'/worksheet', Target=mapped_parts[part].removeprefix('xl/'))
                    with ZipFile(donor['path']) as archive:
                        result = _sheet(archive, out.open(mapped_parts[part], 'w'), part, donor, off, original)
                    report['worksheets'].append({'original_sheet': original, 'mapped_sheet': donor['sheet_map'][original], **result})
                    for key in geometry: geometry[key] += result[key]
                    sheet_index += 1
                with ZipFile(donor['path']) as archive:
                    defined = donor['workbook_tree'].find('{'+S+'}definedNames')
                    for item in defined if defined is not None else []:
                        item = deepcopy(item); local = item.get('localSheetId'); old_names = list(donor['sheet_map'])
                        scope = old_names[int(local)] if local is not None else None
                        item.set('name', donor['names'][scope.casefold() if scope else None, item.get('name').casefold()])
                        item.text = _formula(item.text or '', donor, scope, defined=True)
                        if local is not None: item.set('localSheetId', str(int(local)+sheet_index-len(old_names)))
                        names.append(item)
                    for part in donor['members']:
                        if re.fullmatch(r'xl/worksheets/_rels/sheet[0-9]+\.xml\.rels', part):
                            relations = _xml(archive, part)
                            local_part = part.replace('/_rels/', '/').removesuffix('.rels')
                            local_sheet = next(name for name, value in sheet_parts.items() if value == local_part)
                            for relation in relations:
                                target = relation.get('Target', '')
                                require(relation.get('Type') == R+'/hyperlink' and relation.get('TargetMode') == 'External'
                                    and (target.startswith('#') or re.match(r'^https?://', target)),
                                    'Only parsed internal locations or noncalculation web hyperlinks are supported')
                                if target.startswith('#'):
                                    relation.set('Target', '#'+_formula(target[1:], donor, local_sheet))
                            out.writestr('xl/funds/'+donor['id']+'/'+part.removeprefix('xl/'), _bytes(relations))
                    types = _xml(archive, '[Content_Types].xml')
                    for item in types:
                        item = deepcopy(item)
                        if item.get('PartName'):
                            old = item.get('PartName').lstrip('/')
                            if old == 'xl/calcChain.xml': continue
                            if old in mapped_parts: item.set('PartName', '/'+mapped_parts[old])
                            elif index and old.startswith('docProps/'): continue
                        identity = (_tag(item), item.get('Extension') or item.get('PartName'))
                        if identity in seen_types: require(seen_types[identity] == item.get('ContentType'), 'Content-type collision')
                        else: seen_types[identity] = item.get('ContentType'); content.append(item)
                    if 'docProps/custom.xml' in donor['members']:
                        source_properties = _xml(archive, 'docProps/custom.xml')
                        if custom_properties is None:
                            custom_properties = X.Element(source_properties.tag)
                        for prop in source_properties:
                            prop = deepcopy(prop); prop.set('name', donor['id']+'__'+prop.get('name')); prop.set('pid', str(len(custom_properties)+2))
                            custom_properties.append(prop)
                    if index == 0:
                        for part in ('_rels/.rels', 'docProps/core.xml', 'docProps/app.xml', 'xl/theme/theme1.xml'):
                            if part in donor['members']: out.writestr(part, archive.read(part))
                reports.append(report)
            for key, name in (('styles', 'styles.xml'), ('sharedStrings', 'sharedStrings.xml'), ('theme', 'theme/theme1.xml')):
                if key != 'theme' or loaded[0]['theme'] is not None:
                    X.SubElement(relationships, '{'+P+'}Relationship', Id='global_'+key, Type=R+'/'+key, Target=name)
            for name, typ in (('/xl/sharedStrings.xml', 'sharedStrings'), ('/xl/styles.xml', 'styles')):
                if ('Override', name) not in seen_types:
                    X.SubElement(content, '{'+C+'}Override', PartName=name,
                        ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.'+typ+'+xml')
            if custom_properties is not None:
                require('docProps/custom.xml' in loaded[0]['members'], 'Custom-property relationship must exist in the common package')
                out.writestr('docProps/custom.xml', _bytes(custom_properties))
            for part, node in (('xl/workbook.xml', workbook), ('xl/_rels/workbook.xml.rels', relationships),
                               ('xl/styles.xml', styles), ('xl/sharedStrings.xml', strings), ('[Content_Types].xml', content)):
                out.writestr(part, _bytes(node))
        require(not toy or geometry['nonempty'] <= 20000, 'Toy composition cannot emit a production workbook')
        counts = {**geometry, 'targets': geometry['formulas'] if toy else target_count}
        if expected_census is not None:
            require({**geometry, 'sheets': sheet_index} == expected_census,
                    'Complete written geometry differs from the genuine donor census')
        require(all(type(counts[key]) is int and 0 <= counts[key] <= cap for key, cap in LIMITS.items()), 'Complete composition exceeds declared geometry; no truncation')
        require(all(reference(row['workbook']['path']) == row['workbook'] for row in donors), 'An original donor changed during composition')
        require(not output.exists(), 'Another composition already owns the output')
        pending.replace(output)
    return {'kind': 'uncalculated_ringfenced_group_stream_composition', 'version': 1, 'mode': mode,
        'output': reference(output), 'donors': reports, 'geometry': counts, 'geometry_limits': dict(LIMITS),
        'sheet_count': sheet_index, 'coordinates_relocated': False, 'all_derived_formula_caches_cleared': True,
        'retained_given_literals_NA_booleans_unchanged': True, 'binding_strategy': 'On-demand region/sheet rekey over retained local bindings; no combined financial JSON.',
        'prototype_toy_only': toy, 'ancestry': ancestry, 'new_group_source_admitted': False,
        'exact_expected_census': expected_census,
        'financial_quality_or_difficulty_inherited': False, 'full_actual_D_unknown': True,
        'future_runtime_policy_unchanged': {'cpus': 2, 'memory_bytes': 34359738368, 'pids_limit': 256,
            'MAX_CONCURRENCY': 2, 'source_workbook_seconds': 600, 'verifier_total_seconds': 2400,
            'strict_summed_tool_seconds_less_than': 1800},
        'actual_container_resources_verified': False, 'runtime_profile_created_or_changed': False,
        'presentation_metadata': 'Common first core/app properties; every custom property retained under its mandate namespace; common identical theme/epoch/calculation policy.',
        'LO_model_solver_Harbor_calls': 0, 'new_financial_forwards': 0}


def compose_toy(donors, output):
    """Small fixture route only; the post-census20k guard is not a production bypass."""
    loaded = _load(donors)
    require(all(len(d['sheet_map']) <= 4 for d in loaded), 'Toy fixtures have at most four sheets per mandate')
    return _compose(donors, output, mode='toy', toy=True)


def compose(certificate, output, *, mode='goal', views=None):
    """Future production entry: cold genuine certificates, then full census.

    Calling this function emits a workbook; current assignment authorizes toy
    fixtures only. The external caller must separately authorize production.
    """
    from . import composition
    proof = composition.validate_certificate(certificate)
    require(mode == 'goal' and views is None, 'Actual FM/DBG view linkage needs its separately frozen whole-view contract')
    donors = proof['donors']
    require([(d['id'], d['prefix']) for d in donors] == FIXED, 'Only the first fixed four mandates are supported')
    targets = 0; expected = {'formulas': 0, 'nonempty': 0, 'sheets': 0}
    for donor in donors:
        source = json.loads(_checked(donor['source_manifest']).read_text())
        geometry = json.loads(_checked(source['geometry']).read_text())
        targets += geometry['resource_limits']['counts']['full_target_cells']+1
        expected['formulas'] += geometry['physical_formula_count']
        expected['nonempty'] += geometry['nonempty_cells']
        # Each genuine fixedN360 source has360 project sheets and10 contract,
        # capacity and reporting sheets; no source binding JSON is expanded.
        expected['sheets'] += 370
    return _compose(donors, output, mode=mode, target_count=targets,
                    ancestry={'composition_certificate': certificate, 'native_source_or_quality_inherited': False},
                    expected_census=expected)
