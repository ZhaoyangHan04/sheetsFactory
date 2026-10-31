"""Small explicit OOXML preservation fixtures, not financial or LO receipts."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
import pytest

from sheets_factory.workbook import entity_group_presentation as adapter
from sheets_factory.workbook.entity_group import spec

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('_presentation_public_toy_fixture', ROOT / 'tests/test_entity_group_ledger.py')
fixture = importlib.util.module_from_spec(loader); loader.loader.exec_module(fixture)
N = '{'+adapter.NS+'}'


def rewrite(path, mutator):
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    mutator(members)
    ordinal = 0
    replacement = path.with_name(path.stem + '_rewritten_'+str(ordinal)+'.xlsx')
    while replacement.exists():
        ordinal += 1
        replacement = path.with_name(path.stem + '_rewritten_'+str(ordinal)+'.xlsx')
    with ZipFile(replacement, 'x') as archive:
        for name, data in members.items(): archive.writestr(name, data)
    return replacement


def signature_source(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_source(tmp_path, *, shared=False):
    public = spec.load_spec(fixture.specification()); book = openpyxl.Workbook(); book.remove(book.active)
    rules = book.create_sheet('Group Rules'); rules.append(['Entity close policies'])
    for text in spec.PHASES: rules.append(['Phase', text])
    for text in spec.RULES: rules.append(['Rule', text])
    contract = book.create_sheet('Group Contract'); contract['A1'] = 'Complete public primitive JSON'
    raw = json.dumps(public, sort_keys=True, separators=(',', ':'))
    # Deliberately use more than one JSON chunk, as the production source does.
    for row, start in enumerate(range(0, len(raw), 700), 2):
        contract.cell(row, 1, 'JSON part '+str(row-1)); contract.cell(row, 2, raw[start:start+700])
    inputs = book.create_sheet('Group Inputs'); inputs.append(['Public primitive path', 'Literal value (Boolean flags: 0=false, 1=true)'])
    locations = {}
    for row, (path, value) in enumerate(adapter._flatten(public), 2):
        key = '/'.join(map(str, path)); inputs.cell(row, 1, key); inputs.cell(row, 2, int(value) if type(value) is bool else value)
        locations[key] = 'B'+str(row)
    for sid in spec.SCENARIOS:
        sheet = book.create_sheet(sid+' Close')
        sheet['A1'] = 'Public accounting definition / period / legal owner'; sheet['B1'] = 'Functional minor units; explicit GBP where labelled'
        sheet['A2'] = sid+'/E01/'+public['months'][0]+'/cash_open'
        sheet['B2'] = "='Group Inputs'!$"+locations['entities/0/opening_cash_minor'][0]+'$'+locations['entities/0/opening_cash_minor'][1:]
        sheet['A3'] = sid+'/L01/'+public['months'][0]+'/opening_principal'; sheet['B3'] = '=0'
        sheet['A4'] = sid+'/'+public['months'][0]+'/shared_bank_usage_gbp_pence'; sheet['B4'] = '=MAX(B2,0)'
        sheet['A5'] = sid+'/FY2025/cash_close_gbp_numerator.whole'; sheet['B5'] = '=INT(B4)'
        sheet['C2'] = 12.5; sheet['C2'].number_format = '0.000'; sheet['C3'] = datetime(2024,4,1)
        sheet['C4'] = True; sheet['C5'] = '=B2+1'; sheet['C6'] = 'Unrelated business description'
        sheet['A2'].style = 'Headline 1'; sheet['B2'].number_format = '0.00'
    source = tmp_path / 'synthetic_preservation_fixture.xlsx'; book.save(source); book.close()
    # Explicit synthetic cache bytes test preservation only. No engine computed
    # these values; no test treats them as financial truth or actual LO proof.
    def caches(members):
        for i in (4,5,6):
            part = f'xl/worksheets/sheet{i}.xml'; tree = ET.fromstring(members[part])
            for cell in tree.iter(N+'c'):
                if cell.find(N+'f') is not None:
                    value = cell.find(N+'v')
                    if value is None: value = ET.SubElement(cell,N+'v')
                    value.text = '17.2500'
            members[part] = ET.tostring(tree)
    source = rewrite(source,caches)
    if shared: source = to_shared(source)
    return source, public, locations


def to_shared(path, *, orphan=None):
    def mutation(members):
        sst = ET.Element(N+'sst'); indices = {}
        for name in list(members):
            if not name.startswith('xl/worksheets/sheet'): continue
            tree = ET.fromstring(members[name])
            for cell in tree.iter(N+'c'):
                if cell.attrib.get('t') != 'inlineStr': continue
                text = ''.join(cell.find(N+'is').itertext())
                if text not in indices:
                    indices[text] = len(indices); node = ET.SubElement(sst,N+'si'); ET.SubElement(node,N+'t').text = text
                for child in list(cell): cell.remove(child)
                cell.attrib['t'] = 's'; ET.SubElement(cell,N+'v').text = str(indices[text])
            members[name] = ET.tostring(tree)
        if orphan is not None: ET.SubElement(ET.SubElement(sst,N+'si'),N+'t').text = orphan
        sst.attrib.update(count='9999',uniqueCount=str(len(sst)))
        members['xl/sharedStrings.xml'] = ET.tostring(sst)
        rels = ET.fromstring(members['xl/_rels/workbook.xml.rels'])
        ET.SubElement(rels,'{'+adapter.PKG_REL+'}Relationship',Id='rIdSST',Type=adapter.REL+'/sharedStrings',Target='sharedStrings.xml')
        members['xl/_rels/workbook.xml.rels'] = ET.tostring(rels)
        types = ET.fromstring(members['[Content_Types].xml'])
        ET.SubElement(types,'{http://schemas.openxmlformats.org/package/2006/content-types}Override',PartName='/xl/sharedStrings.xml',ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml')
        members['[Content_Types].xml'] = ET.tostring(types)
    return rewrite(path,mutation)


@pytest.mark.parametrize('shared',[False,True])
def test_native_business_rendering_is_lossless_static_only_and_never_mutates_source(tmp_path,shared):
    source,public,locations = make_source(tmp_path,shared=shared); before = signature_source(source)
    destination = tmp_path/'native_business.xlsx'; report = adapter.transform(source,destination)
    assert signature_source(source) == before and report['source']['sha256'] == before
    assert report['native_public_leaf_count'] == len(list(adapter._flatten(public)))
    assert report['explicit_boolean_as_integer_count'] == 2
    assert report['all_native_primitive_values_preserved'] and report['all_original_phases_and_rules_preserved']
    assert report['uneditable_cells_and_formulas_and_cached_values_and_styles_preserved']
    assert report['static_reference_proof']['changed_text_is_unreferenced'] is True
    assert report['static_reference_proof']['formula_definitions'] == 15
    assert report['shared_string_entries_scrubbed'] > 0 if shared else report['shared_string_entries_scrubbed'] == 0
    old,new = adapter._Package(source),adapter._Package(destination)
    assert tuple(old.sheets) == tuple(new.sheets) == adapter.EXPECTED_SHEETS
    for key in old.cells:
        if key[0] == 'Group Inputs' and key[1].startswith('B'):
            assert adapter._signature(old.cells[key]) == adapter._signature(new.cells[key])
        if key[0].endswith(' Close') and not key[1].startswith('A'):
            assert adapter._signature(old.cells[key]) == adapter._signature(new.cells[key])
    assert 'Entity E01 (GBP)' in new.value(('S01 Close','A2'))
    assert 'Month '+public['months'][0] in new.value(('S01 Close','A2'))
    assert 'Loan L01' in new.value(('S01 Close','A3'))
    assert 'GBP pence' in new.value(('S01 Close','A4'))
    assert 'exact whole component' in new.value(('S01 Close','A5'))
    assert all(not value.startswith('{') for value in new.strings)
    assert report['qualified'] is False and report['new_LO_calls'] == report['model_calls'] == 0
    assert all(report[key] is True for key in ('old_JSON_reader_compatibility_pending','new_private_source_only_recovery_pending','new_source_financial_admission_and_actual_LO_pending','normal_quality_Harbor_and_difficulty_pending'))
    assert report['agent_facing_reconstruction_reader_supplied'] is False
    with ZipFile(source) as original,ZipFile(destination) as materialized:
        for name in original.namelist():
            if name not in report['allowed_changed_members']: assert original.read(name) == materialized.read(name)
    for path in [source,destination]:
        book = openpyxl.load_workbook(path,data_only=False); assert book.sheetnames == list(adapter.EXPECTED_SHEETS); book.close()


def test_real_small_forward_emitter_labels_are_supported_without_ledger_or_cache_claim(tmp_path):
    # Only the public toy primitives enter the emitter. This does not run a
    # ledger, source financial audit, engine, or production-sized transform.
    from sheets_factory.workbook.entity_group.excel import emit_entity_group_workbook
    public = spec.load_spec(fixture.specification())
    book = openpyxl.Workbook(); book.remove(book.active)
    bindings = emit_entity_group_workbook(book,public)
    source = tmp_path/'real_toy_emitter_unrecalculated.xlsx'; book.save(source); book.close()
    before = signature_source(source)
    report = adapter.transform(source,tmp_path/'native_real_toy.xlsx')
    assert report['source']['sha256'] == before
    assert report['static_reference_proof']['formula_definitions'] == bindings['formula_count']
    assert report['qualified'] is False and report['new_source_financial_admission_and_actual_LO_pending'] is True
    native = adapter._Package(tmp_path/'native_real_toy.xlsx')
    close_labels = [native.value(key) for key in native.cells if key[0].endswith(' Close') and key[1].startswith('A')]
    assert any('Group currency translation' in text and 'Functional currency GBP' in text for text in close_labels)
    assert any('exact whole component' in text for text in close_labels)
    assert all(cell.find(N+'v') is None or not cell.find(N+'v').text for cell in native.cells.values() if cell.find(N+'f') is not None)


def change_cell(path,part,address,*,formula=None,text=None,value=None):
    def mutation(parts):
        tree = ET.fromstring(parts[part]); cell = next(c for c in tree.iter(N+'c') if c.attrib['r']==address)
        if formula is not None:
            for child in list(cell):cell.remove(child)
            cell.attrib.pop('t',None);ET.SubElement(cell,N+'f').text = formula;ET.SubElement(cell,N+'v').text='1'
        elif text is not None:
            for child in list(cell):cell.remove(child)
            cell.attrib['t']='inlineStr';ET.SubElement(ET.SubElement(cell,N+'is'),N+'t').text=text
        else:cell.find(N+'v').text=value
        parts[part]=ET.tostring(tree)
    return rewrite(path,mutation)


@pytest.mark.parametrize('formula',["'Group Inputs'!A2", "SUM('Group Inputs'!A2:B6)", "'S01 Close'!A2", "'Group Contract'!B2", "'Group Rules'!B2+0"])
def test_edited_text_dependencies_hold_instead_of_silently_changing_finance(tmp_path,formula):
    source,_,_=make_source(tmp_path);source=change_cell(source,'xl/worksheets/sheet4.xml','B3',formula=formula)
    if 'Group Rules' in formula:
        # Rules are deliberately not edited; a normal static reference is safe.
        assert adapter.transform(source,tmp_path/'safe.xlsx')['all_original_phases_and_rules_preserved']
    else:
        with pytest.raises(adapter.PresentationHold,match='depends on proposed changed text'):
            adapter.transform(source,tmp_path/'held.xlsx')
        assert not (tmp_path/'held.xlsx').exists()


@pytest.mark.parametrize('formula',['INDIRECT("B2")','OFFSET(B2,0,0)','INDEX(B2:B4,1)','UnknownNamedRange','[other.xlsx]Sheet1!A2'])
def test_dynamic_named_external_or_unsupported_references_hold(tmp_path,formula):
    source,_,_=make_source(tmp_path);source=change_cell(source,'xl/worksheets/sheet4.xml','B3',formula=formula)
    with pytest.raises(adapter.PresentationHold):adapter.transform(source,tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()


def test_namespace_valued_extension_metadata_holds_instead_of_losing_its_prefix_scope(tmp_path):
    source,_,_=make_source(tmp_path)
    def extension(parts):
        name='xl/worksheets/sheet4.xml'
        tree=ET.fromstring(parts[name])
        tree.attrib['{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable']='x14ac'
        tree.attrib['xmlns:x14ac']='http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac'
        parts[name]=ET.tostring(tree)
    source=rewrite(source,extension)
    with pytest.raises(adapter.PresentationHold,match='Namespace-valued'):
        adapter.transform(source,tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()


@pytest.mark.parametrize('shared',[False,True])
def test_payload_alias_outside_allowlist_cannot_be_redacted_or_left_behind(tmp_path,shared):
    source,_,_=make_source(tmp_path)
    source=change_cell(source,'xl/worksheets/sheet4.xml','C6',text='entities/0/id')
    if shared:source=to_shared(source)
    before=signature_source(source)
    with pytest.raises(adapter.PresentationHold,match='nonallowlisted|canonical label'):
        adapter.transform(source,tmp_path/'held.xlsx')
    assert signature_source(source)==before and not (tmp_path/'held.xlsx').exists()


def test_unreferenced_shared_JSON_and_canonical_label_entries_are_scrubbed(tmp_path):
    source,public,_=make_source(tmp_path)
    source=to_shared(source,orphan=json.dumps(public,indent=2))
    report=adapter.transform(source,tmp_path/'native.xlsx')
    assert report['shared_string_entries_scrubbed']>0
    new=adapter._Package(tmp_path/'native.xlsx')
    assert not any(adapter._same_contract_object(text,public) for text in new.strings)


@pytest.mark.parametrize('where',['comment','custom_property','custom_xml'])
def test_orphan_JSON_payload_cannot_survive_in_comments_or_metadata(tmp_path,where):
    source,public,_=make_source(tmp_path)
    def mutation(parts):
        text=json.dumps(public,indent=2)
        if where=='comment':parts['xl/comments/comment1.xml']=('<comments><!--'+text+'--></comments>').encode()
        elif where=='custom_property':parts['docProps/custom.xml']=('<Properties><text>'+text.replace('&','&amp;').replace('<','&lt;')+'</text></Properties>').encode()
        else:parts['customXml/item1.xml']=('<data>'+text+'</data>').encode()
    source=rewrite(source,mutation)
    with pytest.raises(adapter.PresentationHold,match='JSON payload|custom XML'):
        adapter.transform(source,tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()


def test_missing_or_changed_native_primitive_or_policy_holds(tmp_path):
    source,_,locations=make_source(tmp_path)
    bad=change_cell(source,'xl/worksheets/sheet3.xml',locations['entities/0/opening_cash_minor'],value='987654')
    with pytest.raises(adapter.PresentationHold,match='native primitive differs'):adapter.transform(bad,tmp_path/'held.xlsx')
    other=change_cell(source,'xl/worksheets/sheet1.xml','B2',text='Wrong ordering')
    with pytest.raises(adapter.PresentationHold,match='all original phase'):adapter.transform(other,tmp_path/'held2.xlsx')


def test_rich_label_styles_and_implicit_shared_formulas_require_separate_proof(tmp_path):
    source,_,_=make_source(tmp_path)
    def mutation(parts):
        part='xl/worksheets/sheet4.xml';tree=ET.fromstring(parts[part]);cell=next(c for c in tree.iter(N+'c') if c.attrib['r']=='A2')
        string=cell.find(N+'is');text=''.join(string.itertext());string.clear();ET.SubElement(ET.SubElement(string,N+'r'),N+'t').text=text
        parts[part]=ET.tostring(tree)
    rich=rewrite(source,mutation)
    with pytest.raises(adapter.PresentationHold,match='Rich-text'):adapter.transform(rich,tmp_path/'rich_hold.xlsx')
    def implicit(parts):
        part='xl/worksheets/sheet4.xml';tree=ET.fromstring(parts[part]);f=next(tree.iter(N+'f'));f.attrib.update(t='shared',si='0',ref='B2:B3');parts[part]=ET.tostring(tree)
    shared=rewrite(source,implicit)
    with pytest.raises(adapter.PresentationHold,match='Shared, array'):adapter.transform(shared,tmp_path/'shared_hold.xlsx')


def test_existing_destination_invalid_mode_and_source_symlinks_never_overwrite(tmp_path):
    source,_,_=make_source(tmp_path);destination=tmp_path/'existing.xlsx';destination.write_bytes(b'preserve me')
    for target,mode in [(source,adapter.MODE),(destination,adapter.MODE),(tmp_path/'other.xlsx','opaque_labels')]:
        with pytest.raises(adapter.PresentationHold):adapter.transform(source,target,mode)
    assert destination.read_bytes()==b'preserve me'
    linked=tmp_path/'source_symlink.xlsx';linked.symlink_to(source)
    with pytest.raises(adapter.PresentationHold,match='symlink'):adapter.transform(linked,tmp_path/'linked.xlsx')


def test_unrelated_binary_member_is_preserved_and_unexpected_ZIP_paths_hold(tmp_path):
    source,_,_=make_source(tmp_path)
    source=rewrite(source,lambda parts:parts.update({'xl/media/image1.png':b'EXPLICIT_BINARY_FIXTURE\x00\xff'}))
    destination=tmp_path/'native.xlsx';adapter.transform(source,destination)
    with ZipFile(destination) as book:assert book.read('xl/media/image1.png')==b'EXPLICIT_BINARY_FIXTURE\x00\xff'
    unsafe=rewrite(source,lambda parts:parts.update({'../bad.xml':b'<bad/>'}))
    with pytest.raises(adapter.PresentationHold,match='Unsafe ZIP'):adapter.transform(unsafe,tmp_path/'unsafe.xlsx')


@pytest.mark.parametrize('kind',['archive','member'])
def test_zip_comments_preserve_ordinary_metadata_and_reject_obsolete_payload(tmp_path,kind):
    source,public,_=make_source(tmp_path)
    def comment_copy(path,target,text):
        with ZipFile(path) as z:
            infos=z.infolist();parts={i.filename:z.read(i.filename) for i in infos}
        with ZipFile(target,'x') as z:
            if kind=='archive':z.comment=text
            else:infos[0].comment=text
            for info in infos:z.writestr(info,parts[info.filename])
        return target
    ordinary=comment_copy(source,tmp_path/'commented.xlsx',b'Ordinary preserved source note')
    destination=tmp_path/'native.xlsx';adapter.transform(ordinary,destination)
    with ZipFile(destination) as z:
        assert (z.comment if kind=='archive' else z.infolist()[0].comment)==b'Ordinary preserved source note'
    bad=comment_copy(source,tmp_path/'payload_comment.xlsx',json.dumps(public,indent=2).encode())
    with pytest.raises(adapter.PresentationHold,match='JSON payload'):
        adapter.transform(bad,tmp_path/'held_comment.xlsx')
    assert not (tmp_path/'held_comment.xlsx').exists()


def test_post_write_guard_does_not_accept_a_changed_label_style(tmp_path,monkeypatch):
    source,_,_=make_source(tmp_path);old=adapter._replace_text
    def damage_style(cell,text):
        old(cell,text);cell.attrib['s']='9876'
    monkeypatch.setattr(adapter,'_replace_text',damage_style)
    with pytest.raises(adapter.PresentationHold,match='style or cell attribute'):
        adapter.transform(source,tmp_path/'rejected_style_candidate.xlsx')
    # A failed candidate is retained; the immutable source is not edited.
    assert (tmp_path/'rejected_style_candidate.xlsx').exists()
