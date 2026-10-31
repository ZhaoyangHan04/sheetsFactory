"""Pure package-preservation tests; no calculation or external services."""
import base64
import importlib.util
import json
import posixpath
from pathlib import Path
from xml.dom import minidom
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.styles.colors import Color
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table
from openpyxl.formatting.rule import FormulaRule

from sheets_factory.workbook import heterogeneous_native_merge as m


def _patch(path, update):
    with ZipFile(path) as archive:
        parts = {n: archive.read(n) for n in archive.namelist()}
    update(parts)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)


def _fixture(tmp_path, identity, prefix, *, objects=True, epoch=False):
    from openpyxl.utils.datetime import CALENDAR_MAC_1904
    wb = Workbook();ws = wb.active;ws.title = "Data";other = wb.create_sheet("Other's")
    if epoch:
        wb.epoch = CALENDAR_MAC_1904
    ws.append(["Category", "Amount"]);ws.append(["A", 5]);ws.append(["B", 8])
    ws["B2"].font = Font(color=Color(theme=4), bold=True)
    ws["B3"].fill = PatternFill("solid", fgColor="FFFFFF00")
    ws["B2"].number_format = '#,##0.000" units"'
    other["A1"] = "=SUM(Data!B2:B3)"
    other["A2"] = "=Amount"
    other["A3"] = "=SUM(Sales[Amount])"
    other["A4"] = '=IF(A1>0,"ordinary text","")'
    ws.print_area = "A1:B3";ws.print_title_rows = "1:1"
    ws.freeze_panes = "B2";ws.column_dimensions["B"].width = 22
    ws.row_dimensions[2].height = 26;ws.merge_cells("D1:E1");ws["D1"] = "Inputs are yellow"
    wb.defined_names.add(DefinedName("Amount", attr_text="Data!$B$2:$B$3"))
    other.defined_names.add(DefinedName("Amount", attr_text="Data!$B$3"))
    if objects:
        table = Table(displayName="Sales", ref="A1:B3");ws.add_table(table)
        chart = BarChart();chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=3), titles_from_data=True);chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=3));ws.add_chart(chart, "G2")
        ws["B2"].comment = Comment("Original financial note", "Analyst")
        ws["C2"] = "citation";ws["C2"].hyperlink = "https://example.org/source"
        ws["C3"] = "internal";ws["C3"].hyperlink = "#'Other''s'!A1"
        # openpyxl serializes the previous hyperlink as an external target;
        # replace it below with the actual OOXML internal location contract.
        dv = DataValidation(type="list", formula1="'Other''s'!$A$1:$A$2");dv.add(ws["D2"]);ws.add_data_validation(dv)
        ws.conditional_formatting.add("B2:B3", FormulaRule(formula=["'Other''s'!A1>0"], fill=PatternFill("solid", fgColor="FFFF0000")))
    else:
        other["A3"] = "=SUM(Data!B2:B3)"
    path = tmp_path / (identity + ".xlsx");wb.save(path)
    def update(parts):
        doc = minidom.parseString(parts["xl/worksheets/sheet2.xml"])
        for n in doc.getElementsByTagName("c"):
            if n.getAttribute("r") == "A1":
                n.getElementsByTagName("v")[0].appendChild(doc.createTextNode("13"))
        parts["xl/worksheets/sheet2.xml"] = doc.toxml(encoding="UTF-8")
        if objects:
            doc = minidom.parseString(parts["xl/worksheets/sheet1.xml"])
            for h in doc.getElementsByTagName("hyperlink"):
                if h.getAttribute("ref") == "C3":
                    old = h.getAttribute("r:id");h.removeAttribute("r:id");h.setAttribute("location", "'Other''s'!A1")
                    rel = minidom.parseString(parts["xl/worksheets/_rels/sheet1.xml.rels"])
                    for r in list(rel.documentElement.childNodes):
                        if r.nodeType == r.ELEMENT_NODE and r.getAttribute("Id") == old:
                            rel.documentElement.removeChild(r)
                    parts["xl/worksheets/_rels/sheet1.xml.rels"] = rel.toxml(encoding="UTF-8")
            parts["xl/worksheets/sheet1.xml"] = doc.toxml(encoding="UTF-8")
            doc = minidom.parseString(parts["xl/tables/table1.xml"])
            columns = doc.getElementsByTagName("tableColumn");formula = doc.createElement("calculatedColumnFormula");formula.appendChild(doc.createTextNode("Sales[Amount]"));columns[1].appendChild(formula)
            parts["xl/tables/table1.xml"] = doc.toxml(encoding="UTF-8")
        # An actual rich shared string exercises global SST index translation.
        doc = minidom.parseString(parts["xl/worksheets/sheet1.xml"])
        for n in doc.getElementsByTagName("c"):
            if n.getAttribute("r") == "A2":
                for child in list(n.childNodes): n.removeChild(child)
                n.setAttribute("t", "s");v=doc.createElement("v");v.appendChild(doc.createTextNode("0"));n.appendChild(v)
        parts["xl/worksheets/sheet1.xml"] = doc.toxml(encoding="UTF-8")
        parts["xl/sharedStrings.xml"] = (f'<sst xmlns="{m.S}" count="1" uniqueCount="1"><si><r><rPr><b/><color theme="4"/></rPr><t>A</t></r></si></sst>').encode()
        doc = minidom.parseString(parts["xl/_rels/workbook.xml.rels"]);r=doc.createElement("Relationship")
        for k,v in {"Id":"strings", "Type":m.R+"/sharedStrings", "Target":"sharedStrings.xml"}.items():r.setAttribute(k,v)
        doc.documentElement.appendChild(r);parts["xl/_rels/workbook.xml.rels"] = doc.toxml(encoding="UTF-8")
        doc=minidom.parseString(parts["[Content_Types].xml"]);r=doc.createElement("Override")
        r.setAttribute("PartName","/xl/sharedStrings.xml");r.setAttribute("ContentType","application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml");doc.documentElement.appendChild(r);parts["[Content_Types].xml"]=doc.toxml(encoding="UTF-8")
    _patch(path, update)
    return {"id":identity,"prefix":prefix,"workbook":m.file_ref(path),"source_sha256":"f"*64}


def _fresh_ref(donor):
    donor["workbook"] = m.file_ref(donor["workbook"]["path"])


def test_two_complete_relationship_graphs_styles_names_tables_and_cached_types(tmp_path):
    donors=[_fixture(tmp_path,"first","Alpha"),_fixture(tmp_path,"second","Beta")]
    pre=m.inspect_donors(donors);assert pre["passed"],pre["holds"]
    out=tmp_path/"merged.xlsx";result=m.compose(donors,out)
    assert result["all_internal_relationships_resolved"] and result["all_other_typed_cached_values_preserved"]
    assert result["LO_model_solver_Harbor_calls"] == 0
    wb=load_workbook(out,data_only=False);cached=load_workbook(out,data_only=True)
    assert wb.sheetnames == ["Alpha - Data","Alpha - Other's","Beta - Data","Beta - Other's"]
    for prefix in ["Alpha","Beta"]:
        ws=wb[prefix+" - Data"];other=wb[prefix+" - Other's"]
        assert other["A1"].value == f"=SUM('{prefix} - Data'!B2:B3)"
        assert cached[other.title]["A1"].value == 13
        assert other["A2"].value == "="+prefix+"__Amount"
        assert other["A3"].value == "=SUM("+prefix+"__Sales[Amount])"
        assert ws["B2"].number_format == '#,##0.000" units"'
        assert ws["B2"].font.color.type == "rgb" and ws["B2"].font.bold
        original = m._load(next(d for d in donors if d["prefix"]==prefix),set())
        assert ws["B2"].font.color.rgb == "FF"+original.palette["accent1"]
        assert ws["B3"].fill.fgColor.rgb == "FFFFFF00"
        assert ws["B2"].comment.text == "Original financial note"
        assert len(ws._charts)==1 and len(ws.tables)==1 and len(ws.data_validations.dataValidation)==1
        assert len(ws.conditional_formatting)==1 and ws.freeze_panes=="B2"
        assert ws["C2"].hyperlink.target == "https://example.org/source"
        assert ws["C3"].hyperlink.location == "'"+prefix+" - Other''s'!A1"
        assert prefix+"__Sales" in ws.tables
        assert prefix+"__Amount" in wb.defined_names and prefix+"__Amount" in other.defined_names
        assert ws.print_title_rows == "$1:$1" and "$A$1" in str(ws.print_area)
    with ZipFile(out) as z:
        assert len([p for p in z.namelist() if p.endswith(".vml")])==2
        assert len([p for p in z.namelist() if "/comments/" in p and p.endswith(".xml")])==2
        chart=[z.read(p).decode() for p in z.namelist() if "/charts/chart" in p and p.endswith(".xml")]
        assert len(chart)==2 and all(" - Data" in x for x in chart)


def test_namespace_is_stable_quoted_and_case_insensitive():
    names=["Very long original financial statement", "Other's"]
    a=m.sheet_namespace("FS",names);assert a==m.sheet_namespace("FS",names)
    assert max(map(len,a.values()))<=31
    assert m.rewrite_formula("='Other''s'!$A$1+A2",a)=="='FS - Other''s'!$A$1+A2"
    with pytest.raises(m.UnsupportedWorkbook,match="collision"):
        m.sheet_namespace("FS",names,{x.casefold() for x in a.values()})


@pytest.mark.parametrize("formula",["INDIRECT(\"A1\")","ADDRESS(1,1)","SUM([1]Sheet1!A1)","SUM(Data:Other!A1)",'HYPERLINK("#Data!A1","go")',"{1,2}","UnknownName+1"])
def test_unhandled_reference_forms_fail_explicitly(formula):
    with pytest.raises(m.UnsupportedWorkbook):m.rewrite_formula(formula,{"Data":"A - Data","Other":"A - Other"})


def test_offset_keeps_local_coordinates_and_only_translates_qualified_tokens():
    assert m.rewrite_formula("OFFSET(Z$1,Data!$B$13,0,1,1)",{"Data":"Agent - Data"}) == "OFFSET(Z$1,'Agent - Data'!$B$13,0,1,1)"


def test_image_relationship_and_binary_payload_are_retained_without_a_renderer(tmp_path):
    donor=_fixture(tmp_path,"image","Image")
    png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    def update(parts):
        parts["xl/media/image1.png"]=png
        doc=minidom.parseString(parts["xl/drawings/drawing1.xml"])
        fragment=minidom.parseString('<oneCellAnchor xmlns="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="'+m.R+'"><from><col>2</col><colOff>0</colOff><row>10</row><rowOff>0</rowOff></from><ext cx="9525" cy="9525"/><pic><nvPicPr><cNvPr id="2" name="Original Image"/><cNvPicPr/></nvPicPr><blipFill><a:blip r:embed="image"/><a:stretch><a:fillRect/></a:stretch></blipFill><spPr><a:prstGeom prst="rect"/></spPr></pic><clientData/></oneCellAnchor>')
        doc.documentElement.appendChild(doc.importNode(fragment.documentElement,True));parts["xl/drawings/drawing1.xml"]=doc.toxml(encoding="UTF-8")
        doc=minidom.parseString(parts["xl/drawings/_rels/drawing1.xml.rels"]);rel=doc.createElement("Relationship")
        for k,v in {"Id":"image","Type":m.R+"/image","Target":"../media/image1.png"}.items():rel.setAttribute(k,v)
        doc.documentElement.appendChild(rel);parts["xl/drawings/_rels/drawing1.xml.rels"]=doc.toxml(encoding="UTF-8")
        doc=minidom.parseString(parts["[Content_Types].xml"]);n=doc.createElement("Default");n.setAttribute("Extension","png");n.setAttribute("ContentType","image/png");doc.documentElement.appendChild(n);parts["[Content_Types].xml"]=doc.toxml(encoding="UTF-8")
    _patch(donor["workbook"]["path"],update);_fresh_ref(donor)
    result=m.compose([donor],tmp_path/"image-merged.xlsx")
    mapping=result["copies"][0]["part_map"]
    with ZipFile(tmp_path/"image-merged.xlsx") as z:
        assert z.read(mapping["xl/media/image1.png"])==png
        drawing=z.read(mapping["xl/drawings/drawing1.xml"]).decode();assert 'r:embed="image"' in drawing and "Original Image" in drawing
        rels=minidom.parseString(z.read(mapping["xl/drawings/_rels/drawing1.xml.rels"]))
        rel=next(n for n in rels.getElementsByTagName("Relationship") if n.getAttribute("Id")=="image")
        actual=posixpath.normpath(posixpath.join(posixpath.dirname(mapping["xl/drawings/drawing1.xml"]),rel.getAttribute("Target")))
        assert actual==mapping["xl/media/image1.png"]


def test_style_component_and_sst_indexes_are_checked_before_emit(tmp_path):
    donor=_fixture(tmp_path,"badindex","BadIndex",objects=False)
    def update(parts):
        doc=minidom.parseString(parts["xl/worksheets/sheet1.xml"])
        for n in doc.getElementsByTagName("c"):
            if n.getAttribute("t")=="s":n.getElementsByTagName("v")[0].firstChild.data="999999"
        parts["xl/worksheets/sheet1.xml"]=doc.toxml(encoding="UTF-8")
    _patch(donor["workbook"]["path"],update);_fresh_ref(donor)
    pre=m.inspect_donors([donor]);assert not pre["passed"] and any("Shared-string index" in x["reason"] for x in pre["holds"])


def test_roundtrip_audit_detects_reference_changes(tmp_path):
    spec=_fixture(tmp_path,"proof","Proof",objects=False);donor=m._load(spec,set())
    part="xl/worksheets/sheet2.xml";translated=m._part_rewrite(donor,part,donor.parts[part])
    altered=translated.replace(b"B2:B3",b"B2:B4",1)
    with pytest.raises(m.UnsupportedWorkbook,match="round trip"):
        m.audit_formula_translation(donor,part,altered)


@pytest.mark.parametrize("case",["external","array","unknown_part","unknown_extension","missing_relationship"])
def test_package_unsupported_cases_hold_before_emission(tmp_path,case):
    d=_fixture(tmp_path,"held","Held",objects=False)
    def update(parts):
        if case=="unknown_part":parts["xl/pivotTables/pivotTable1.xml"]=b"<pivotTable/>"
        elif case=="external":
            doc=minidom.parseString(parts["xl/_rels/workbook.xml.rels"]);r=doc.createElement("Relationship")
            for k,v in {"Id":"outside","Type":m.R+"/externalLink","Target":"https://example.org/a.xlsx","TargetMode":"External"}.items():r.setAttribute(k,v)
            doc.documentElement.appendChild(r);parts["xl/_rels/workbook.xml.rels"]=doc.toxml(encoding="UTF-8")
        elif case=="missing_relationship":parts.pop("xl/worksheets/sheet2.xml")
        else:
            doc=minidom.parseString(parts["xl/worksheets/sheet2.xml"])
            if case=="array":doc.getElementsByTagName("f")[0].setAttribute("t","array")
            else:doc.documentElement.appendChild(doc.createElement("extLst"));doc.getElementsByTagName("extLst")[0].appendChild(doc.createElement("unknownObject"))
            parts["xl/worksheets/sheet2.xml"]=doc.toxml(encoding="UTF-8")
    _patch(d["workbook"]["path"],update);_fresh_ref(d)
    p=m.inspect_donors([d]);assert not p["passed"] and p["holds"]
    out=tmp_path/"never.xlsx"
    with pytest.raises(m.UnsupportedWorkbook,match="held"):m.compose([d],out)
    assert not out.exists()


def test_changed_frozen_donor_is_rejected(tmp_path):
    d=_fixture(tmp_path,"one","One",objects=False)
    with Path(d["workbook"]["path"]).open("ab") as stream:stream.write(b"changed")
    assert not m.inspect_donors([d])["passed"]


def test_date_epoch_adjustment_is_exact_and_text_is_not_shifted(tmp_path):
    a=_fixture(tmp_path,"normal","Normal",objects=False)
    b=_fixture(tmp_path,"mac","Mac",objects=False,epoch=True)
    def update(parts):
        doc=minidom.parseString(parts["xl/worksheets/sheet1.xml"])
        cells={n.getAttribute("r"):n for n in doc.getElementsByTagName("c")}
        # Add one date style rather than changing every financial cell's style.
        styles=minidom.parseString(parts["xl/styles.xml"]);xfs=styles.getElementsByTagName("cellXfs")[0];xf=xfs.firstChild.cloneNode(True);xf.setAttribute("numFmtId","14");xfs.appendChild(xf);index=len([x for x in xfs.childNodes if x.nodeType==x.ELEMENT_NODE])-1;xfs.setAttribute("count",str(index+1))
        row=doc.createElement("row");row.setAttribute("r","5");cell=doc.createElement("c");cell.setAttribute("r","B5");cell.setAttribute("s",str(index));value=doc.createElement("v");value.appendChild(doc.createTextNode("44592"));cell.appendChild(value);row.appendChild(cell);doc.getElementsByTagName("sheetData")[0].appendChild(row)
        row=doc.createElement("row");row.setAttribute("r","8");cell=doc.createElement("c");cell.setAttribute("r","D8");cell.setAttribute("s",str(index));cell.setAttribute("t","inlineStr");inline=doc.createElement("is");text=doc.createElement("t");text.appendChild(doc.createTextNode("Years 2-5"));inline.appendChild(text);cell.appendChild(inline);row.appendChild(cell);doc.getElementsByTagName("sheetData")[0].appendChild(row)
        parts["xl/styles.xml"]=styles.toxml(encoding="UTF-8");parts["xl/worksheets/sheet1.xml"]=doc.toxml(encoding="UTF-8")
        doc=minidom.parseString(parts["xl/worksheets/sheet2.xml"])
        for cell in doc.getElementsByTagName("c"):
            if cell.getAttribute("r")=="A2":cell.getElementsByTagName("f")[0].firstChild.data="SUM(Data!B2:B3)"
        for address in ["A6","A7"]:
            row=doc.createElement("row");row.setAttribute("r",address[1:]);cell=doc.createElement("c");cell.setAttribute("r",address);cell.setAttribute("s",str(index));formula=doc.createElement("f");formula.appendChild(doc.createTextNode("Data!B5"));value=doc.createElement("v");value.appendChild(doc.createTextNode("44592"));cell.appendChild(formula);cell.appendChild(value);row.appendChild(cell);doc.getElementsByTagName("sheetData")[0].appendChild(row)
        parts["xl/worksheets/sheet2.xml"]=doc.toxml(encoding="UTF-8")
    _patch(b["workbook"]["path"],update);_fresh_ref(b)
    assert not m.inspect_donors([a,b])["passed"]
    b["date_conversion"]={"source_date1904":True,"target_date1904":False,"serial_delta":1462,"cells":[{"sheet":s,"cell":a,"original_cached_text":"44592"} for s,a in [("Data","B5"),("Other's","A6"),("Other's","A7")]]}
    assert m.inspect_donors([a,b])["passed"]
    result=m.compose([a,b],tmp_path/"dates.xlsx")
    assert result["explicit_date_cache_conversions"][0]["converted_cached_text"]=="46054"
    assert len(result["explicit_date_cache_conversions"])==3
    from openpyxl.utils.datetime import from_excel,CALENDAR_MAC_1904,CALENDAR_WINDOWS_1900
    assert from_excel(44592,CALENDAR_MAC_1904)==from_excel(46054,CALENDAR_WINDOWS_1900)
    cached=load_workbook(tmp_path/"dates.xlsx",data_only=True)
    assert cached["Mac - Data"]["B5"].value==from_excel(44592,CALENDAR_MAC_1904)
    assert cached["Mac - Other's"]["A6"].value==cached["Mac - Other's"]["A7"].value==cached["Mac - Data"]["B5"].value
    assert cached["Mac - Data"]["D8"].value=="Years 2-5"


def test_named_alias_cycles_and_relative_names_are_held(tmp_path):
    d=_fixture(tmp_path,"names","Names",objects=False)
    def update(parts):
        doc=minidom.parseString(parts["xl/workbook.xml"]);defs=doc.getElementsByTagName("definedNames")[0]
        for name,value in [("Loop1","Loop2"),("Loop2","Loop1")]:
            n=doc.createElement("definedName");n.setAttribute("name",name);n.appendChild(doc.createTextNode(value));defs.appendChild(n)
        parts["xl/workbook.xml"]=doc.toxml(encoding="UTF-8")
    _patch(d["workbook"]["path"],update);_fresh_ref(d)
    assert any("Cyclic" in x["reason"] for x in m.inspect_donors([d])["holds"])
    with pytest.raises(m.UnsupportedWorkbook,match="Relative"):
        m.rewrite_formula("Data!A1",{"Data":"X - Data"},defined_name=True)


def _driver():
    path=Path(__file__).resolve().parents[1]/"scripts/prepare_heterogeneous_native_review_pack.py"
    spec=importlib.util.spec_from_file_location("heterogeneous_pack_driver_test",path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


def test_durable_first_emission_guard_and_frozen_preflight(tmp_path,monkeypatch):
    driver=_driver();d=_fixture(tmp_path,"one","One",objects=False)
    monkeypatch.setattr(driver,"DONOR_IDS",("one",))
    config=tmp_path/"config.json";config.write_text(json.dumps({"kind":"fixed_eight_heterogeneous_native_review_pack_recipe","version":1,"donors":[d]}))
    out=tmp_path/"prepared";driver.prepare(config,out);driver.emit(out)
    with pytest.raises(FileExistsError):driver.emit(out)
    assert (out/"emission_started.json").exists()
    x=json.loads((out/"donor_preflight.json").read_text());x["financial_certified"]=True;(out/"donor_preflight.json").write_text(json.dumps(x))
    with pytest.raises(m.UnsupportedWorkbook,match="Frozen"):
        driver.validate_prepared(out)


def test_failed_emission_is_preserved_and_cannot_retry(tmp_path,monkeypatch):
    driver=_driver();d=_fixture(tmp_path,"one","One",objects=False);monkeypatch.setattr(driver,"DONOR_IDS",("one",))
    config=tmp_path/"config.json";config.write_text(json.dumps({"kind":"fixed_eight_heterogeneous_native_review_pack_recipe","version":1,"donors":[d]}));out=tmp_path/"prepared";driver.prepare(config,out)
    def fail(*a):raise RuntimeError("concrete emission bug")
    monkeypatch.setattr(m,"compose",fail)
    with pytest.raises(RuntimeError,match="concrete"):driver.emit(out)
    with pytest.raises(FileExistsError):driver.emit(out)
    assert not (out/"review_pack.xlsx").exists()
