"""Seeded semantic definition faults over an unchanged audited financial goal.

This compiler performs no model or workbook-engine calls. Every nonzero member
of the bound scope is compiled or the whole proposal is rejected. Selection is
fixed by the declared seed, public field identity and calendar bucket. It does
not select policies from model scores. Source financial truth is not changed.
"""
from collections import Counter,defaultdict
from datetime import date,datetime
import hashlib,heapq,math,re

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import get_column_letter,column_index_from_string,range_boundaries

from .composite_full_family_v2 import (ADAPTER_ID as SCOPE_ID,INPUT_PRIORITY_RULE,
    canonical_sha,_normal,_reference_parts,_related_rows,_retains_complete_operand)
from .lease_family import ref
from ..workbook.profile import formula_references

ADAPTER_ID='composite_complete_semantic_graph_v3'

class SemanticCoverageError(ValueError):
    def __init__(self,report):
        self.report=report
        super().__init__('Complete semantic coverage rejected: '+str(len(report['unsatisfied_roots']))+' roots')


def _money(cell):
    """Scalar type guard only; this does not establish a monetary unit."""
    return type(cell.value)in(int,float)and math.isfinite(cell.value)and not cell.is_date and cell.data_type!='e'


def _render(tokens):return'='+''.join(t.value for t in tokens)


def _key(sheet,cell):return sheet+'!'+cell


def _rank(seed,*parts):
    return hashlib.sha256(('\x1f'.join([str(seed),*map(str,parts)])).encode()).hexdigest()


class DependencyOrder:
    """Complete original ancestor graph; new references respect its SCC order.

    Changing edges to earlier components cannot introduce a new cyclic island.
    Changes within an original economic SCC make no uniqueness claim about the
    erroneous counterfactual. Every reference expansion is checked, not guessed.
    """
    def __init__(self,book,roots):
        self.book=book;self.graph={};self.refs={};self.range_tokens={};self.function_tokens={};self.related_cache={};pending=list(roots);seen=set()
        while pending:
            key=pending.pop()
            if key in seen:continue
            seen.add(key);sheet,cell=key.rsplit('!',1)
            if sheet not in book:raise ValueError('Unknown dependency sheet: '+sheet)
            c=book[sheet][cell]
            if c.data_type!='f':continue
            details=formula_references(c.value,sheet,max_expansion=500000)
            if not details['fully_supported']:
                raise ValueError('Unsupported original financial ancestor '+key+': '+str(details['unsupported']))
            refs={_key(x['sheet'],x['cell'])for x in details['references']}
            if any(x.rsplit('!',1)[0]not in book for x in refs):raise ValueError('Missing dependency sheet')
            self.refs[key]=refs
            tokens=Tokenizer(c.value).items
            self.range_tokens[key]={t.value for t in tokens if t.type=='OPERAND'and t.subtype=='RANGE'}
            self.function_tokens[key]={t.value.upper()for t in tokens if t.type=='FUNC'and t.subtype=='OPEN'}
            deps={x for x in refs if book[x.rsplit('!',1)[0]][x.rsplit('!',1)[1]].data_type=='f'}
            self.graph[key]=deps;pending.extend(deps-seen)
        # Iterative Kosaraju avoids recursion limits on long calendar chains.
        order=[];visited=set()
        for start in sorted(self.graph):
            if start in visited:continue
            visited.add(start);stack=[(start,iter(self.graph[start]))]
            while stack:
                node,it=stack[-1]
                child=next(it,None)
                if child is None:order.append(node);stack.pop();continue
                if child not in visited:
                    visited.add(child);stack.append((child,iter(self.graph.get(child,()))))
        reverse=defaultdict(set)
        for node,deps in self.graph.items():
            for dep in deps:reverse[dep].add(node)
        membership={};components=[]
        for start in reversed(order):
            if start in membership:continue
            i=len(components);nodes=[];stack=[start];membership[start]=i
            while stack:
                node=stack.pop();nodes.append(node)
                for child in reverse[node]:
                    if child not in membership:membership[child]=i;stack.append(child)
            components.append(nodes)
        deps={i:{membership[x]for node in nodes for x in self.graph[node]}-{i}for i,nodes in enumerate(components)}
        users=defaultdict(set)
        for i,ds in deps.items():
            for d in ds:users[d].add(i)
        sheet_position={name:i for i,name in enumerate(book.sheetnames)}
        def component_priority(i):
            def coordinate_priority(key):
                sheet,address=key.rsplit('!',1);cell=book[sheet][address]
                # Numeric period/row order is stable across processes. A
                # lexicographic order would place AA before Z and row10 before
                # row8, and needlessly exclude earlier financial snapshots.
                return(cell.column,cell.row,sheet_position[sheet],key)
            return min(coordinate_priority(k)for k in components[i])
        queue=[(component_priority(i),i)for i,d in deps.items()if not d];heapq.heapify(queue)
        ranks={}
        while queue:
            _,i=heapq.heappop(queue);ranks[i]=len(ranks)
            for user in users[i]:
                deps[user].remove(i)
                if not deps[user]:heapq.heappush(queue,(component_priority(user),user))
        if len(ranks)!=len(components):raise ValueError('Condensed original dependency graph is not a DAG')
        self.membership=membership;self.order={k:ranks[i]for k,i in membership.items()}
        self.summary={'formula_nodes':len(self.graph),'formula_dependency_edges':sum(map(len,self.graph.values())),
            'original_SCC_count':len(components),'original_cyclic_SCC_count':sum(len(n)>1 or n[0] in self.graph[n[0]] for n in components),
            'complete_reference_expansion':True,'new_cross_component_back_edges_allowed':False,
            'erroneous_counterfactual_global_uniqueness_claimed':False}

    def allowed(self,root,candidate):
        if root==candidate:return False
        if candidate not in self.order:
            s,c=candidate.rsplit('!',1)
            return s in self.book and self.book[s][c].data_type!='f'
        return self.order[candidate]<=self.order[root]

    def related_rows(self,sheet,row):
        key=(sheet,row)
        if key not in self.related_cache:self.related_cache[key]=tuple(_related_rows(self.book[sheet],row))
        return self.related_cache[key]


def _scalar_reference_tokens(tokens,default):
    return [(i,_reference_parts(t.value,default))for i,t in enumerate(tokens)
        if t.type=='OPERAND'and t.subtype=='RANGE'and _reference_parts(t.value,default)]


def _quoted(sheet,cell):return"'"+sheet.replace("'","''")+"'!"+cell


def _calendar_bucket(book,sheet,cell):
    # Annual and monthly grouping uses the public header. It is not chosen from
    # observed rewards or expected financial activity.
    for row in (2,1):
        value=book[sheet].cell(row,cell.column).value
        if isinstance(value,(datetime,date)):return str(value.year)
        if type(value)is int and 2020<=value<=2100:return str(value)
    if sheet.startswith('Operating '):return 'operating-year-'+str(max(0,(cell.column-3)//12))
    return 'calendar-block-'+str(max(0,(cell.column-3)//12))


def _primitive_money_keys(book,values):
    """Identify narrowly labelled monetary primitives, not generic numbers.

    This makes an input eligible as a monetary operand. It does not certify
    currency or reporting-unit compatibility between different accounts.
    """
    keys=set()
    rowsheets={'Operating Scenario','Holding Inputs','Partner Inputs','Reopener Inputs'}
    amounts=re.compile(r'\b(cash|sales|expense|cost|capex|principal|capital|equity|commitment|fee|facility|retained|nol|collection cap)\b')
    nonamounts=re.compile(r'\b(rate|fraction|ratio|multiple|percent|months|years|days|date|life|lag|index|hurdle|haircut|enabled|flag)\b')
    for sheet in rowsheets.intersection(book.sheetnames):
        for row in book[sheet].iter_rows(min_col=1,max_col=2):
            label=_normal(row[0].value);c=row[1]
            if amounts.search(label)and not nonamounts.search(label)and c.data_type!='f'and _money(values[sheet][c.coordinate]):
                keys.add(_key(sheet,c.coordinate))
    # The event table's public H1 header explicitly identifies the fee column.
    if'Lease Events'in book and _normal(book['Lease Events']['H1'].value)=='cash termination fee':
        for row in range(2,book['Lease Events'].max_row+1):
            cell=book['Lease Events'].cell(row,8)
            if cell.data_type!='f'and _money(values['Lease Events'][cell.coordinate]):keys.add(_key('Lease Events',cell.coordinate))
    return keys


def _binding_options(family,cell,tokens,book,values,money,order):
    """Use real related accounts, components or earlier financial snapshots."""
    root=_key(cell.parent.title,cell.coordinate);options=[]
    for index,parts in _scalar_reference_tokens(tokens,cell.parent.title):
        sheet,col,row=parts;address=col.replace('$','')+row.replace('$','');source=_key(sheet,address)
        if sheet not in book:continue
        source_cell=book[sheet][address]
        if not _money(values[sheet][address]):continue
        candidates=[]
        if sheet=='Reopener Assets' and col.replace('$','') in {'F','G'}:
            opposite='G' if col.replace('$','')=='F' else 'F'
            candidates.append((_key(sheet,opposite+row.replace('$','')),'nominal_real_cost_basis'))
        # These are actual related public accounts. Currency/unit compatibility
        # is not inferred merely from a finite numeric value or a field label.
        for other in order.related_rows(sheet,int(row.replace('$',''))):
            candidate=col.replace('$','')+str(other)
            candidates.append((_key(sheet,candidate),'related_public_account'))
        # Earlier, rather than future, monetary snapshots preserve the actual
        # cash-settlement calendar and provided-zero support.
        if source in money:
            n=int(row.replace('$',''))if sheet=='Holding Operating Link'else column_index_from_string(col.replace('$',''))
            for lag in (1,3,12):
                if n-lag>=3:
                    address=(col.replace('$','')+str(n-lag)if sheet=='Holding Operating Link'else get_column_letter(n-lag)+row.replace('$',''))
                    candidate=_key(sheet,address)
                    if candidate in money:candidates.append((candidate,'stale_financial_snapshot_'+str(lag)))
        # Replacing a named total with one of its own monetary components is a
        # gross/net or stock/flow error. It does not keep the original total as
        # a nested intact expression and adds no new dependency back edge.
        if source_cell.data_type=='f':
            source_tokens=Tokenizer(source_cell.value).items
            computes_amount=any(t.type=='OPERATOR-INFIX'or(t.type=='FUNC'and t.subtype=='OPEN'and t.value.upper()not in{'ROUND(','IFERROR('})for t in source_tokens)
            for dependency in sorted(order.refs.get(source,())):
                if computes_amount and dependency in money:candidates.append((dependency,'component_instead_of_total'))
                # Opening balances may be a simple alias to a supplied input.
                # Bind to another explicitly labelled financial input instead
                # of adding an arbitrary answer offset to the correct alias.
                s,c=dependency.rsplit('!',1)
                if dependency in money and book[s][c].data_type!='f':
                    for other in order.related_rows(s,book[s][c].row):
                        related=_key(s,get_column_letter(book[s][c].column)+str(other))
                        if related in money:candidates.append((related,'related_provided_account'))
        seen=set()
        for candidate,kind in candidates:
            if candidate in seen or candidate==source or not order.allowed(root,candidate):continue
            seen.add(candidate);s,c=candidate.rsplit('!',1)
            if not _money(values[s][c]):continue
            changed=[copy_token(t)for t in tokens];changed[index].value=_quoted(s,c)
            options.append((_render(changed),kind,
                'Bind '+family['field']+' to '+str(book[s].cell(book[s][c].row,1).value)+' at '+candidate+' instead of '+source+'.'))
    return options


def copy_token(token):
    from copy import copy
    return copy(token)


def _definition_options(family,cell,tokens,money,book=None,values=None):
    """Business operations at several internal positions, without a global inverse."""
    result=[];sheet=cell.parent.title;role=family['role']
    refs={i:p for i,p in _scalar_reference_tokens(tokens,sheet)}
    def monetary(i):
        if i not in refs:return False
        s,c,r=refs[i];return _key(s,c.replace('$','')+r.replace('$',''))in money
    for i,t in enumerate(tokens):
        if t.type=='OPERATOR-INFIX'and t.value in'+-'and(monetary(i-1)or monetary(i+1)):
            changed=[copy_token(x)for x in tokens];changed[i].value='-'if t.value=='+'else'+'
            result.append((_render(changed),'named_movement_sign','Reverse the financial posting of a named component in '+family['field']+'.'))
            # Omit one movement in an accounting roll-forward. This operation
            # removes information instead of exposing a reversible operator.
            if monetary(i+1):
                changed=[copy_token(x)for x in tokens];del changed[i:i+2]
                result.append((_render(changed),'omitted_financial_movement','Omit a monetary movement from the '+family['field']+' roll-forward.'))
        if t.type=='OPERATOR-INFIX'and t.value=='/'and i+1<len(tokens):
            n=tokens[i+1]
            replacement={'12':'4','2':'1','365':'360'}.get(n.value)if n.type=='OPERAND'and n.subtype=='NUMBER'else None
            if replacement:
                changed=[copy_token(x)for x in tokens];changed[i+1].value=replacement
                result.append((_render(changed),'incorrect_financial_period_basis','Use a quarterly/full-year/banker-year basis in '+family['field']+' where the public contract specifies another period.'))
            if i+1 in refs and book is not None:
                s,c,r=refs[i+1];address=c.replace('$','')+r.replace('$','')
                label=_normal(book[s].cell(int(r.replace('$','')),1).value)
                if re.search(r'\b(months|life|periods|days|payments)\b',label)and _money(values[s][address])and values[s][address].value>0:
                    changed=[copy_token(x)for x in tokens];changed[i+1].value='('+n.value+'+1)'
                    result.append((_render(changed),'inclusive_financial_period_count','Count an extra period in the supplied amortisation or construction allocation basis for '+family['field']+'.'))
        if t.type=='FUNC'and t.subtype=='OPEN'and t.value.upper()in{'MIN(','MAX('}:
            changed=[copy_token(x)for x in tokens];changed[i].value='MAX('if t.value.upper()=='MIN('else'MIN('
            result.append((_render(changed),'wrong_cap_or_priority','Apply the opposite financial cap or floor to '+family['field']+'.'))
        if t.type=='FUNC'and t.subtype=='OPEN'and t.value.upper()in{'SUM(','SUMIF(','SUMIFS('}:
            changed=[copy_token(x)for x in tokens]
            # MAX/MIN summarize a peak or trough rather than the required
            # financial flow. SUMIF(S) uses a targeted range/account error below.
            if t.value.upper()=='SUM(':
                changed[i].value='MAX('if role in{'aggregate','cash_settlement','funding'}else'MIN('
                result.append((_render(changed),'peak_or_trough_instead_of_flow','Report a peak/trough financial amount instead of the total '+family['field']+'.'))
        if t.type=='OPERAND'and t.subtype=='RANGE'and ':'in t.value:
            raw=t.value;prefix,ran=(raw.rsplit('!',1)if'!'in raw else('',raw))
            try:left,top,right,bottom=range_boundaries(ran)
            except Exception:continue
            target=prefix.strip("'").replace("''", "'")if prefix else sheet
            # A partial-year or partial-vintage reporting window is a financial
            # cutoff error. Do not move a date array or nonmonetary state range.
            if top==bottom and right>left and any(_key(target,get_column_letter(c)+str(top))in money for c in range(left,right+1)):
                for trim in (1,min(3,right-left)):
                    changed=[copy_token(x)for x in tokens]
                    changed[i].value=(prefix+'!'if prefix else'')+get_column_letter(left)+str(top)+':'+get_column_letter(right-trim)+str(bottom)
                    result.append((_render(changed),'incomplete_financial_reporting_window','Exclude the final financial periods or vintage amount from '+family['field']+'.'))
            if left==right and bottom>top and any(_key(target,get_column_letter(left)+str(r)) in money for r in range(top,bottom+1)):
                changed=[copy_token(x)for x in tokens]
                # Keep the SUMIF criteria height but align its financial amount
                # range to the following month. Interior references remain in
                # the original ancestor set; the final extra row must be blank
                # or outside the financial scope, rather than another formula.
                if _key(target,get_column_letter(left)+str(bottom+1)) not in money:
                    changed[i].value=(prefix+'!'if prefix else'')+get_column_letter(left)+str(top+1)+':'+get_column_letter(right)+str(bottom+1)
                    result.append((_render(changed),'misaligned_fiscal_amount_range','Associate the next monthly amount with each fiscal-calendar label in '+family['field']+'.'))
    return result


def _return_options(family,cell):
    f=cell.value;label=_normal(family['field']);out=[]
    if'XIRR('in f.upper()and label=='lp xirr':
        pattern=r'(\$?B\$?)27(:\$?[A-Z]+\$?)27'
        gp=re.sub(pattern,r'\g<1>28\g<2>28',f)
        if gp!=f:out.append((gp,'wrong_partner_return_stream','Compute the LP return using the GP dated cash flows.'))
        # Conventional periodic IRR instead of actual dated XIRR. This is a
        # genuine return convention difference; its cent-normalized effect is
        # not assumed, and legal blank return templates remain provided.
        out.append((re.sub(r'XIRR\(([^,]+),([^,\)]+)(,-0\.5)?\)',r'IRR(\1)',f),
            'periodic_instead_of_dated_return','Treat actual investor dates as equally spaced annual periods.'))
    if'irr'in label and re.search(r'\^12\b',f):
        out.append((re.sub(r'\^12\b','^4',f),'quarterly_annualisation','Compound the monthly owner return using quarterly periods.'))
    return out


def _valid_options(before,options):
    unique={}
    for after,kind,reason in options:
        if after==before or not after.startswith('=')or _retains_complete_operand(before,after):continue
        try:Tokenizer(after)
        except Exception:continue
        unique.setdefault(after,(after,kind,reason))
    return list(unique.values())


def _ordered_options(root,options,order):
    """All newly introduced references must preserve the original SCC order."""
    source_sheet=root.rsplit('!',1)[0];existing=order.refs.get(root,set());result=[]
    for option in options:
        tokens=Tokenizer(option[0]).items
        functions={t.value.upper()for t in tokens if t.type=='FUNC'and t.subtype=='OPEN'}
        if functions-order.function_tokens[root]-{'MIN(','MAX(','IRR('}:continue
        # Reference parsing is context-independent for this supported static
        # grammar. Expand only changed range operands; original operands were
        # already expanded completely in DependencyOrder, including aliases.
        # This avoids repeatedly expanding the same 240-month ranges for each
        # sign/cap alternative without weakening the edge check.
        changed={t.value for t in tokens if t.type=='OPERAND'and t.subtype=='RANGE'}-order.range_tokens[root]
        added=set();supported=True
        for expression in changed:
            detail=formula_references('='+expression,source_sheet,max_expansion=500000)
            if not detail['fully_supported']:supported=False;break
            added.update(_key(r['sheet'],r['cell'])for r in detail['references'])
        if not supported:continue
        added-=existing
        if all(order.allowed(root,candidate)for candidate in added):result.append(option)
    return result


def validate_policy(policy):
    if policy.get('adapter')!=ADAPTER_ID or type(policy.get('seed'))is not int:raise ValueError('Explicit v3 adapter and integer seed are required')
    if type(policy.get('max_roots'))is not int or not 1<=policy['max_roots']<=100000:raise ValueError('Invalid complete root bound')
    if policy.get('compound_nonalias_definitions')is not True:raise ValueError('V3 requires explicit mixed semantic composition')


def compile_semantic_report(presented_baseline,scope_inventory,policy):
    validate_policy(policy)
    if scope_inventory.get('adapter')!=SCOPE_ID:raise ValueError('The complete audited source scope is required')
    families=scope_inventory['families'];slots=[(f,c)for f in families for c in f['cells']]
    money={_key(f['sheet'],c['cell'])for f,c in slots}
    roots={_key(f['sheet'],c['cell'])for f,c in slots if c['source_kind']=='finite_numeric_nonzero'}
    if len(money)!=len(slots)or len(roots)!=scope_inventory['prospective_nonzero_roots']or not 0<len(roots)<=policy['max_roots']:raise ValueError('Incomplete, duplicate or oversized scope; no subset is allowed')
    book=openpyxl.load_workbook(presented_baseline,keep_links=False);values=openpyxl.load_workbook(presented_baseline,data_only=True,keep_links=False)
    edits=[];failures=[];fields=[]
    try:
        money|=_primitive_money_keys(book,values)
        order=DependencyOrder(book,roots)
        for family in families:
            fid=family['algorithm']+'/'+family['sheet']+'/'+str(family['row']);compiled=0;failed=0
            for item in family['cells']:
                cell=book[family['sheet']][item['cell']]
                try:
                    if item['source_kind']=='exact_numeric_zero':
                        if not _money(cell)or cell.value!=0:raise ValueError('A provided source zero changed')
                        continue
                    if cell.data_type!='f'or hashlib.sha256(cell.value.encode()).hexdigest()!=item.get('formula_sha256'):raise ValueError('Bound original formula differs')
                    tokens=Tokenizer(cell.value).items
                    root=_key(family['sheet'],cell.coordinate)
                    opts=_ordered_options(root,_valid_options(cell.value,_return_options(family,cell)+_binding_options(family,cell,tokens,book,values,money,order)+_definition_options(family,cell,tokens,money,book,values)),order)
                    if not opts:raise ValueError('No compatible semantic policy for full financial field')
                    bucket=_calendar_bucket(book,family['sheet'],cell)
                    opts.sort(key=lambda o:_rank(policy['seed'],fid,bucket,o[1],o[0]))
                    after,kind,reason=opts[0];kinds=[kind];reasons=[reason]
                    # Definitions with several operands receive a second,
                    # different business change, rather than a uniform inverse.
                    if len(tokens)>2:
                        first=after;other=_ordered_options(root,_valid_options(cell.value,_definition_options(family,cell,Tokenizer(first).items,money,book,values)),order)
                        other=[o for o in other if o[1]!=kind and o[0]!=first and o[0]!=cell.value]
                        other.sort(key=lambda o:_rank(policy['seed'],'composition',fid,bucket,o[1],o[0]))
                        if other:after,second,why=other[0];kinds.append(second);reasons.append(why)
                    # Never mutate the book during compilation: source graph,
                    # semantics and hashes are tied to the same original goal.
                    edits.append({'sheet':family['sheet'],'cell':cell.coordinate,'before':cell.value,'after':after,
                        'family_id':fid,'algorithm':family['algorithm'],'field':family['field'],'role':family['role'],
                        'mechanism':'+'.join(kinds),'semantic_policies':kinds,'reason':' '.join(reasons),
                        'calendar_bucket':bucket,'business_rule':'Apply the unchanged public financial contracts and explicit scenario inputs.'})
                    compiled+=1
                except (ValueError,KeyError,IndexError)as error:
                    failed+=1;failures.append({'sheet':family['sheet'],'cell':item['cell'],'field':family['field'],'reason':str(error)})
            fields.append({'family_id':fid,'compiled_roots':compiled,'unsatisfied_roots':failed})
        complete=not failures and {_key(e['sheet'],e['cell'])for e in edits}==roots
        return {'schema_version':3,'adapter':ADAPTER_ID,'offline_compile_complete':complete,
            'status':'offline_complete_actual_execution_pending'if complete else'rejected_incomplete_coverage',
            'source':ref(presented_baseline),'original_scope_source':scope_inventory['source'],
            'scope_inventory_sha256':canonical_sha(scope_inventory),'policy':policy,'policy_sha256':canonical_sha(policy),
            'root_count':len(roots),'compiled_root_count':len(edits),'family_count':len(families),'family_reports':fields,
            'unsatisfied_roots':failures,'edits':edits,'edits_sha256':canonical_sha(edits),
            'counts_by_algorithm':dict(Counter(e['algorithm']for e in edits)),
            'counts_by_policy':dict(Counter(p for e in edits for p in e['semantic_policies'])),
            'composed_definition_count':sum(len(e['semantic_policies'])>1 for e in edits),'original_dependency_order':order.summary,
            'provided_zero_count':len(slots)-len(roots),'legal_nullable_return_references':scope_inventory.get('provided_nullable_return_templates',[]),
            'global_correct_donor_absence_claimed':False,'actual_activity_or_stability_tested':False,
            'actual_LO_calls':0,'model_calls':0,'qualified':False,'task_count':0,'selected':[]}
    finally:book.close();values.close()


def compile_semantic_mutation(presented_baseline,scope_inventory,policy):
    r=compile_semantic_report(presented_baseline,scope_inventory,policy)
    if not r['offline_compile_complete']:raise SemanticCoverageError(r)
    return {'title':'Audit interconnected financial policies and reporting',
        'public_instruction':'Audit and repair inconsistent financial formulas in the model. Apply the public business contracts, preserve provided inputs, fixed zero monetary entries and original regulatory context, and save /app/output.xlsx.',
        'public_rules':[INPUT_PRIORITY_RULE,'The original currencies, reporting periods and contractual accounting policies govern the financial model.'],
        'reference_evidence':['The unchanged financial goal is backed by independent source audits, complete exact typed source equivalence and explicit public numeric-policy replay.'],
        'edits':r['edits'],'mask_ranges':[],'assumptions_added':[],
        'family_adapter':{'id':ADAPTER_ID,'status':'planned_not_execution_proven',
            **{k:r[k]for k in ['root_count','family_count','edits_sha256','policy_sha256','scope_inventory_sha256','source','counts_by_algorithm','counts_by_policy','composed_definition_count','provided_zero_count','global_correct_donor_absence_claimed']},
            'qualified':False,'task_count':0,'difficulty_measured':False}}
