"""Private, opt-in textual guidance signals; no quality or difficulty verdict.

Inputs are text and asserted edits supplied by the caller. This module opens no
files and reads no workbook, cached answer, or goal. Matches are conservative,
incomplete review cues. Findings contain public-text offsets and excerpts only;
private edit records and unmatched formula definitions are never returned.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re

MAX_TEXT_CHARACTERS = 4 * 1024**2
MAX_TOTAL_CHARACTERS = 16 * 1024**2
EXCERPT_CHARACTERS = 160
_ADDRESS = r'\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}'
_QUALIFIED = re.compile(r"(?<![\w'])('(?:[^'\r\n]|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!(" + _ADDRESS + r')(?::(' + _ADDRESS + r'))?(?![A-Za-z0-9_])')
_INLINE = re.compile(r'(?<!`)`([^`\r\n]+)`(?!`)')
_FORMULA_LINE = re.compile(r'(?m)^[ \t]*(=[^\r\n]+?)[ \t]*$')
_JSON_FENCE = re.compile(r'(?m)^```json[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*$',re.IGNORECASE)
_BARE = re.compile(r'(?<![A-Za-z0-9_!])(' + _ADDRESS + r')(?::(' + _ADDRESS + r'))?(?![A-Za-z0-9_])')
_CELL_CUE = re.compile(r'\bcells?\s+([^\r\n.;]+)',re.IGNORECASE)


def _require(condition,message):
    if not condition:raise ValueError(message)


def _cell(text):
    match=re.fullmatch(r'\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})',text)
    if match is None:return None
    column=0
    for letter in match[1].upper():column=26*column+ord(letter)-64
    row=int(match[2])
    if column>16384 or row>1048576:return None
    return match[1].upper()+str(row),column,row


def _formula(text):
    """Fold ASCII case outside Excel double-quoted strings; preserve spaces.

    Whitespace can be Excel's intersection operator. Removing it would invent
    matches. Double-quoted text, including escaped quotes, is case-sensitive.
    """
    result=[];quoted=False;index=0
    while index<len(text):
        char=text[index]
        if char=='"':
            result.append(char)
            if quoted and index+1<len(text) and text[index+1]=='"':
                result.append('"');index+=2;continue
            quoted=not quoted
        else:result.append(chr(ord(char)+32) if not quoted and 'A'<=char<='Z' else char)
        index+=1
    return ''.join(result).strip()


def _texts(values,label):
    _require(isinstance(values,(list,tuple)) and all(type(v) is str for v in values),label+' must be a bounded list or tuple of public strings')
    _require(all(len(v)<=MAX_TEXT_CHARACTERS for v in values),label+' contains an oversized public text')
    return values


def _no_duplicate_keys(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def _contract_object(text):
    try:
        value=json.loads(text,object_pairs_hook=_no_duplicate_keys,
                         parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (ValueError,RecursionError):return False
    if not isinstance(value,dict):return False
    if isinstance(value.get('$schema'),str) and isinstance(value.get('properties'),dict):return True
    version=value.get('schema_version',value.get('version'))
    if type(version) not in (int,str):return False
    # This recognizes an explicit structural contract, not its completeness or
    # financial sufficiency. A small 0/1 assumption object is not a schema.
    fields=('entities','projects','scenarios','loans','periods','years','months','rules','fields','properties')
    return sum(isinstance(value.get(key),(list,dict)) and bool(value[key]) for key in fields)>=2


def audit_prompt_guidance(instruction,*,mode,private_edits=(),public_contract_texts=(),public_formula_texts=()):
    """Return private review-only signals with Unicode character offsets.

    ``private_edits`` uses ordinary sheet/cell/before edit records. Only exact
    public-text matches are reported. ``public_formula_texts`` identifies
    legitimately surviving public formulas; matching those creates a neutral
    context cue instead of a repair-formula cue. Structured JSON must be a whole
    explicitly supplied public text or an instruction's fenced ``json`` block.
    No edit, prompt, policy, file or verdict is changed.
    """
    _require(type(instruction) is str and len(instruction)<=MAX_TEXT_CHARACTERS,'A bounded public instruction is required')
    _require(mode in ('debugging','financial_modeling'),'An explicit supported task mode is required')
    contracts=_texts(public_contract_texts,'public_contract_texts')
    formulas=_texts(public_formula_texts,'public_formula_texts')
    _require(len(instruction)+sum(map(len,contracts))+sum(map(len,formulas))<=MAX_TOTAL_CHARACTERS,'The explicit public-text audit budget is exceeded')
    _require(isinstance(private_edits,(list,tuple)),'private_edits must be a list or tuple of asserted edits')
    roots={};repairs=set()
    for edit in private_edits:
        _require(isinstance(edit,dict) and type(edit.get('sheet')) is str and bool(edit['sheet'])
            and type(edit.get('cell')) is str,'An asserted edit needs a sheet and cell')
        cell=_cell(edit['cell']);_require(cell is not None,'An asserted edit coordinate is invalid')
        key=(edit['sheet'].casefold(),cell[0]);_require(key not in roots,'Duplicate asserted edit coordinate')
        roots[key]=(cell[1],cell[2])
        if type(edit.get('before')) is str and edit['before'].startswith('='):repairs.add(_formula(edit['before']))
    surviving={_formula(value) for value in formulas if value.strip().startswith('=')}
    sources=[('instruction',instruction),*((f'public_contract_texts[{index}]',text) for index,text in enumerate(contracts))]
    source_map=dict(sources);findings=[];seen=set();exposed=set();coordinate_mentions=[]

    def add(code,source,start,end,description,**details):
        identity=(code,source,start,end)
        if identity in seen:return
        seen.add(identity);text=source_map[source]
        findings.append({'id':f'{code}:{source}:{start}:{end}','signal':code,'severity':'review_only',
            'source':source,'start':start,'end':end,'excerpt':text[start:min(end,start+EXCERPT_CHARACTERS)],
            'excerpt_truncated':end-start>EXCERPT_CHARACTERS,'description':description,'details':details})

    formula_spans=[m.span(1) for m in _INLINE.finditer(instruction) if m[1].lstrip().startswith('=')]
    formula_spans.extend(m.span(1) for m in _FORMULA_LINE.finditer(instruction))
    qualified_spans=[]
    for match in _QUALIFIED.finditer(instruction):
        first=_cell(match[2]);last=_cell(match[3]) if match[3] else None
        if first is None or (match[3] and last is None):continue
        if any(left<=match.start()<right for left,right in formula_spans):continue
        sheet=match[1];sheet=sheet[1:-1].replace("''", "'") if sheet.startswith("'") else sheet
        qualified_spans.append(match.span());coordinate_mentions.append(match.span())
        if match[3]:continue  # Range declarations may be legitimate model scope.
        key=(sheet.casefold(),first[0])
        if mode=='debugging' and key in roots:
            exposed.add(key)
            add('PG001','instruction',*match.span(),'A qualified address matches an asserted debugging edit; review how directly the fault is identified.',
                exact_sheet_and_cell_match=True,automatic_gold_leak_verdict=False)

    # Bare addresses are recognized only in code spans or explicit cell callouts,
    # so prose years such as FY2024 do not silently become target addresses.
    coordinate_contexts=[(m.start(1),m[1]) for m in _INLINE.finditer(instruction) if not m[1].lstrip().startswith('=')]
    coordinate_contexts.extend((m.start(1),m[1]) for m in _CELL_CUE.finditer(instruction))
    bare_mentions=set()
    root_cells=Counter(key[1] for key in roots)
    for offset,text in coordinate_contexts:
        for match in _BARE.finditer(text):
            start,end=offset+match.start(),offset+match.end()
            if any(left<=start<right for left,right in qualified_spans):continue
            if any(left<=start<right for left,right in formula_spans):continue
            cell=_cell(match[1]);last=_cell(match[2]) if match[2] else None
            if cell is None or (match[2] and last is None):continue
            if (start,end) in bare_mentions:continue
            bare_mentions.add((start,end));coordinate_mentions.append((start,end))
            if mode=='debugging' and not match[2] and cell[0] in root_cells:
                add('PG008','instruction',start,end,'An unqualified cell token also occurs among asserted edits; the worksheet is not established.',
                    worksheet_not_established=True,automatic_gold_leak_verdict=False)
    if len(set(coordinate_mentions))>=2 or any(':' in instruction[start:end] for start,end in coordinate_mentions):
        start,end=min(coordinate_mentions)[0],max(coordinate_mentions)[1]
        add('PG003','instruction',start,end,'The public instruction enumerates cell coordinates or ranges; compare this with its business scope.',
            recognized_coordinate_mentions=len(set(coordinate_mentions)),financial_modeling_target_scope_is_legitimate=mode=='financial_modeling')

    candidates=[(m.start(1),m.end(1),m[1]) for m in _INLINE.finditer(instruction)]
    candidates.extend((m.start(1),m.end(1),m[1]) for m in _FORMULA_LINE.finditer(instruction))
    for start,end,text in candidates:
        if not text.strip().startswith('='):continue
        token=_formula(text)
        if token in surviving:
            add('PG005','instruction',start,end,'This formula is explicitly identified as already surviving in the public workbook; its presence alone is not a gold leak.',
                caller_identified_public_surviving_formula=True)
        elif token in repairs:
            add('PG002','instruction',start,end,'A whole formula snippet matches an asserted original definition; review whether the text teaches the repair.',
                exact_asserted_original_formula_match=True,automatic_gold_leak_verdict=False)

    for source,text in sources:
        spans=[]
        stripped=text.strip()
        if source!='instruction' and stripped.startswith('{'):
            start=len(text)-len(text.lstrip());spans.append((start,len(text.rstrip()),stripped))
        spans.extend((m.start(1),m.end(1),m[1]) for m in _JSON_FENCE.finditer(text))
        for start,end,payload in spans:
            if _contract_object(payload):
                add('PG004',source,start,end,'Explicit parsed JSON contains recognizable contract structure; completeness and necessity still require review.',
                    parsed_explicit_public_JSON=True,contract_completeness_verified=False)

    cues=[('PG006',re.compile(r'\b(?:assum(?:e|ption)s?|given|provided|fixed plan|round(?:ing)?|ties away)\b',re.IGNORECASE),
           'Assumption or calculation-rule language is present; necessary business definitions are not treated as leaks.'),
          ('PG007',re.compile(r'/app/(?:input|output)\.xlsx|\b(?:save|preserve|worksheet|submission)\b',re.IGNORECASE),
           'Submission or preservation language is present; operational constraints are neutral context.'),
          ('PG009',re.compile(r'\b(?:interest|tax|covenant|loan|cash|distribution|facility|entity|entities|financial|debt|revenue|profit)\b',re.IGNORECASE),
           'Financial business-scope language is present; keyword recognition does not prove semantic adequacy.')]
    for code,pattern,description in cues:
        match=pattern.search(instruction)
        if match:add(code,'instruction',*match.span(),description,neutral_context_only=True)
    findings.sort(key=lambda finding:(finding['source'],finding['start'],finding['end'],finding['signal']))
    return {'kind':'private_prompt_guidance_signal_audit','version':1,'mode':mode,'private_only':True,'public_export_allowed':False,
        'severity_policy':'review_only','offset_unit':'Unicode code points','findings':findings,
        'public_sources':[{'source':name,'characters':len(text),'sha256':hashlib.sha256(text.encode()).hexdigest()}
            for name,text in [*sources,*((f'public_formula_texts[{index}]',text) for index,text in enumerate(formulas))]],
        'summary':{'asserted_edit_count':len(roots),'qualified_debugging_edit_addresses_visible':len(exposed),
            'signal_counts':dict(sorted(Counter(f['signal'] for f in findings).items()))},
        'coverage_complete':False,'no_finding_is_not_proof_of_absence':True,
        'automatic_Q01_Q02_verdict':False,'difficulty_verdict':None,'gold_leak_verdict':None,
        'private_edit_records_serialized':False,'goal_or_gold_values_read':False,'prompts_or_policies_modified':False,
        'limitations':['Only qualified addresses and explicit bare-cell contexts are recognized.',
            'Formula matching uses whole inline-code snippets or whole formula lines; semantic equivalence is not tested.',
            'Explicit JSON structure is recognized, without proving complete financial definitions.',
            'Caller-supplied public surviving formulas are context, not an independent workbook scan.']}
