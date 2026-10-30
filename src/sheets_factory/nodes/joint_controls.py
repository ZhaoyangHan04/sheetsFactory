"""Opt-in actual single-omission controls for joint-workbook debugging.

The ordered search certifies one negative control. It makes no assertion about
the individual or marginal effects of any other physical mutation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

import openpyxl
from openpyxl.utils.cell import column_index_from_string

from ..core.node import BaseNode, CooperativeCancelled, TaskRejected
from ..pipelines.joint_repair_activity import (
    METHOD as JOINT_METHOD, validate_joint_certificate, validate_physical_edits,
)
from ..task_adapters.public_input_priority import canonical, checked, ref, require, sha
from ..workbook import compare_workbooks
from . import construction

SETTING = 'joint_observable_controls'
METHOD = 'ordered_actual_single_omission_v1'
DEFAULT_MAX_MISSED_ROOT_ATTEMPTS = 8
UPSTREAM_SHA256 = '9e729242123f58a333b21ba29ff79c63026864ec8851c594e3573de7ead7fcdc'
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
_SINGLE_REFERENCE = re.compile(
    r"^=(?:(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_ .]*))!)?(\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)$")


def _single_reference(formula, default_sheet):
    if not isinstance(formula, str):
        return None
    matched = _SINGLE_REFERENCE.fullmatch(formula)
    if matched is None:
        return None
    quoted, plain, address = matched.groups()
    # External workbooks, 3-D references, ranges and defined names are not this
    # narrow optimization, including when brackets occur in a quoted title.
    sheet = quoted.replace("''", "'") if quoted is not None else plain or default_sheet
    if any(symbol in sheet for symbol in ('[', ']', ':')):
        return None
    address = address.replace('$', '').upper()
    coordinate = re.fullmatch(r'([A-Z]+)([0-9]+)', address)
    if column_index_from_string(coordinate.group(1)) > 16384 or int(coordinate.group(2)) > 1048576:
        return None
    return sheet, address


def prescreen_equal_goal_references(goal, edits):
    """Cheap ordered-search filtering, without a counterfactual activity claim."""
    book = openpyxl.load_workbook(goal, data_only=True, keep_links=False)
    skipped = {}
    try:
        for index, edit in enumerate(edits):
            left = _single_reference(edit.get('before'), edit['sheet'])
            right = _single_reference(edit.get('after'), edit['sheet'])
            if left is None or right is None or left[0] not in book or right[0] not in book:
                continue
            before, after = book[left[0]][left[1]], book[right[0]][right[1]]
            if before.value is None or before.value == '' or before.data_type == 'e':
                continue
            if before.data_type != after.data_type or type(before.value) is not type(after.value) or before.value != after.value:
                continue
            if type(before.value) in (int, float) and not math.isfinite(before.value):
                continue
            skipped[index] = {'plan_edit_index': index, 'state': 'skipped_equal_goal_reference',
                'before_reference': {'sheet': left[0], 'cell': left[1]},
                'after_reference': {'sheet': right[0], 'cell': right[1]},
                'goal_cached_value': before.value, 'cache_data_type': before.data_type,
                'python_value_type': type(before.value).__name__,
                'counterfactual_or_marginal_effect_proved': False}
        return skipped
    finally:
        book.close()


def setting(*, max_missed_root_attempts=DEFAULT_MAX_MISSED_ROOT_ATTEMPTS):
    require(type(max_missed_root_attempts) is int
            and 1 <= max_missed_root_attempts <= DEFAULT_MAX_MISSED_ROOT_ATTEMPTS,
            'max_missed_root_attempts must be an integer from 1 through 8')
    return {'version': 1, 'method': METHOD,
        'max_missed_root_attempts': max_missed_root_attempts,
        'implementation': ref(__file__), 'upstream_controls_sha256': UPSTREAM_SHA256}


def validate_setting(value):
    require(isinstance(value, dict) and type(value.get('version')) is int
            and value['version'] == 1 and value.get('method') == METHOD,
            'Unsupported explicit joint observable controls setting')
    maximum = value.get('max_missed_root_attempts', DEFAULT_MAX_MISSED_ROOT_ATTEMPTS)
    expected = setting(max_missed_root_attempts=maximum)
    require(set(value) in (set(expected), set(expected) - {'max_missed_root_attempts'})
            and {**value, 'max_missed_root_attempts': maximum} == expected,
            'Joint observable controls implementation or frozen policy differs')
    require(sha(construction.__file__) == UPSTREAM_SHA256,
            'The upstream normal ControlsNode implementation changed')
    return maximum


def _valid_grade(result, expected_delta):
    require(isinstance(result, dict) and type(result.get('reward')) is int
            and result['reward'] in (0, 1) and result.get('structure_ok') is True
            and 'error' not in result
            and result.get('expected_change_count') == expected_delta['expected_change_count']
            and result.get('expected_changes') == expected_delta['expected_changes'],
            'A joint control must have a normal, structure-preserving grade on the complete D')


class JointObservableControlsNode(BaseNode):
    node_id = 'precheck'

    def execute(self, ctx):
        # FM and every non-opt-in task retain the original node, including its
        # existing control selection and error behaviour.
        if ctx.mode != 'debugging' or ctx.config.get(SETTING) is None:
            return construction.ControlsNode().execute(ctx)
        maximum = validate_setting(ctx.config[SETTING])
        private = ctx.revision_dir / 'private'
        source, goal = Path(ctx.data['input']), Path(ctx.data['goal'])
        plan = ctx.data['plan']; edits = plan.get('edits')
        require(isinstance(edits, list) and edits, 'Joint controls require the complete physical edit list')
        certificate_file = private / 'joint_repair_certificate.json'
        certificate = json.loads(certificate_file.read_text())
        require(certificate.get('activity_contract') == JOINT_METHOD,
                'Ordered joint controls require an actual joint-workbook construction certificate')
        summary = validate_joint_certificate(certificate, goal, source, edits, ctx.data['delta'])
        require(summary['complete_required_D_count'] > 0, 'A joint control cannot certify a no-effect whole task')
        frozen = {'input': ref(source), 'goal': ref(goal), 'plan_sha256': canonical(plan),
                  'edits_sha256': canonical(edits), 'joint_certificate': ref(certificate_file)}
        prior_failed_attempts = []
        previous_file = private / 'joint_control_selection.json'
        if previous_file.exists():
            previous = json.loads(previous_file.read_text())
            require(previous.get('kind') == 'joint_actual_single_omission_controls'
                    and previous.get('state') in {'failed', 'cancelled'}
                    and previous.get('task_id') == ctx.task_id and previous.get('revision') == ctx.revision,
                    'Joint controls must not overwrite an earlier revision control receipt')
            prior_ref = previous.get('attempt_receipt')
            saved_previous = json.loads(checked(prior_ref).read_text())
            require(saved_previous == {k: v for k, v in previous.items() if k != 'attempt_receipt'}
                    and previous['binding']['goal'] == frozen['goal']
                    and previous['binding']['plan_sha256'] == frozen['plan_sha256'],
                    'A prior failed joint control attempt changed or belongs to another goal or plan')
            prior_failed_attempts = [*previous.get('prior_failed_attempts', []), prior_ref]
            for record in prior_failed_attempts:
                checked(record)
        require(not (private / 'local_controls.json').exists() and not (private / 'controls').exists(),
                'Joint controls must not overwrite an earlier revision control receipt')
        skipped = prescreen_equal_goal_references(goal, edits)
        eligible = [index for index in range(len(edits)) if index not in skipped]
        attempt_id = uuid4().hex
        attempt_prefix = 'joint_control_attempts/' + attempt_id
        attempt_directory = private / attempt_prefix
        folder = attempt_directory / 'controls'; folder.mkdir(parents=True, exist_ok=False)
        receipt = {'kind': 'joint_actual_single_omission_controls', 'version': 1, 'method': METHOD,
            'setting': deepcopy(ctx.config[SETTING]), 'task_id': ctx.task_id, 'revision': ctx.revision,
            'attempt_id': attempt_id, 'prior_failed_attempts': prior_failed_attempts,
            'binding': frozen, 'max_missed_root_attempts': maximum, 'state': 'running', 'passed': False,
            'candidate_order': 'unchanged complete plan.edits order after explicitly recorded pure-reference prefilter',
            'prescreened_physical_edit_count': len(edits), 'skipped_candidates': list(skipped.values()),
            'eligible_plan_edit_indices': eligible,
            'physical_edit_count': len(edits), 'attempts': [], 'engine_calls': [],
            'selected_plan_edit_index': None, 'actual_workbook_LO_started_count': 0,
            'actual_workbook_LO_completed_count': 0, 'individual_or_marginal_activity_claimed': False,
            'all_physical_edits_observable_claimed': False, 'quality_recovery_difficulty_certified': False}

        def save():
            ctx.save(attempt_prefix + '/progress.json', receipt)

        def finalize():
            # Each completed attempt is a new immutable record. Only the latest
            # projection is replaced; it explicitly references that exact record.
            terminal = attempt_directory / 'receipt.json'
            require(not terminal.exists(), 'A terminal joint control attempt cannot be overwritten')
            ctx.save(attempt_prefix + '/receipt.json', receipt)
            ctx.save('joint_control_selection.json', {**receipt, 'attempt_receipt': ref(terminal)})

        def recalculate(raw, destination, label):
            call = {'label': label, 'input': ref(raw), 'output_path': str(destination.resolve()),
                    'completed': False, 'started_at': datetime.now(timezone.utc).isoformat()}
            receipt['engine_calls'].append(call)
            receipt['actual_workbook_LO_started_count'] += 1
            save()
            started = time.monotonic()
            try:
                actual = Path(ctx.engine.recalculate(raw, destination)).resolve()
                require(actual == destination.resolve() and actual.is_file(),
                        'Joint control runtime returned a different output artifact')
            except BaseException as exc:
                call.update(error_type=type(exc).__name__, error=str(exc),
                            finished_at=datetime.now(timezone.utc).isoformat(),
                            duration_ms=round((time.monotonic() - started) * 1000))
                save()
                raise
            call.update(output=ref(actual), completed=True,
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        duration_ms=round((time.monotonic() - started) * 1000))
            receipt['actual_workbook_LO_completed_count'] += 1
            save()
            return actual

        def raw_variant(path, *, edit=None, equivalent=False, extra=False):
            book = openpyxl.load_workbook(goal, keep_links=False)
            try:
                if extra:
                    book[book.sheetnames[0]]['XFD100'] = 'unexpected extra value'
                else:
                    require(book[edit['sheet']][edit['cell']].value == edit['before'],
                            'The selected single-omission before formula differs from the goal')
                    value = '=IF(TRUE(),' + edit['before'][1:] + ',"")' if equivalent else edit['after']
                    book[edit['sheet']][edit['cell']] = value
                book.save(path)
            finally:
                book.close()
            return path

        save()
        controls = {}
        try:
            if not eligible:
                raise TaskRejected('Q05/Q06: no unfiltered single-omission candidate; no negative control was executed')
            expected_delta = compare_workbooks(source, goal, goal)
            _valid_grade(expected_delta, expected_delta)
            require(expected_delta['reward'] == 1 and expected_delta['expected_change_count'] > 0,
                    'Joint controls require a valid reference and nonempty complete D')
            controls['oracle'] = expected_delta
            controls['nop'] = compare_workbooks(source, goal, source)
            _valid_grade(controls['nop'], expected_delta)

            raw = raw_variant(folder / 'equivalent_raw.xlsx', edit=edits[0], equivalent=True)
            candidate = recalculate(raw, folder / 'equivalent.xlsx', 'equivalent')
            controls['equivalent'] = compare_workbooks(source, goal, candidate)
            _valid_grade(controls['equivalent'], expected_delta)

            for attempt_index, index in enumerate(eligible[:maximum]):
                edit = edits[index]
                attempt_dir = folder / 'missed_root_attempts' / f'{attempt_index:03d}'
                attempt_dir.mkdir(parents=True, exist_ok=False)
                raw = raw_variant(attempt_dir / 'raw.xlsx', edit=edit)
                validate_physical_edits(goal, raw, [edit])
                attempt = {'plan_edit_index': index, 'actual_attempt_index': attempt_index,
                           'edit': deepcopy(edit), 'raw': ref(raw),
                           'state': 'executing', 'selected': False}
                receipt['attempts'].append(attempt); save()
                candidate = recalculate(raw, attempt_dir / 'recalculated.xlsx', 'missed_root:' + str(index))
                attempt['output'] = ref(candidate)
                validate_physical_edits(goal, candidate, [edit])
                grade = compare_workbooks(source, goal, candidate)
                _valid_grade(grade, expected_delta)
                controls['missed_root'] = grade
                ctx.save(attempt_prefix + '/controls/missed_root_attempts/' + f'{attempt_index:03d}' + '/comparison.json', grade)
                attempt.update(state='graded', reward=grade['reward'],
                    comparison=ref(attempt_dir / 'comparison.json'))
                if grade['reward'] == 0:
                    require(any(grade.get(key) for key in ('missing_changes', 'extra_changes', 'wrong_values')),
                            'A selected single omission must have a concrete value mismatch')
                    shutil.copyfile(raw, folder / 'missed_root_raw.xlsx')
                    shutil.copyfile(candidate, folder / 'missed_root.xlsx')
                    attempt['selected'] = True
                    receipt['selected_plan_edit_index'] = index
                    receipt['selected_raw'] = ref(folder / 'missed_root_raw.xlsx')
                    receipt['selected_output'] = ref(folder / 'missed_root.xlsx')
                    save()
                    break
                save()

            raw = raw_variant(folder / 'extra_change_raw.xlsx', extra=True)
            candidate = recalculate(raw, folder / 'extra_change.xlsx', 'extra_change')
            controls['extra_change'] = compare_workbooks(source, goal, candidate)
            _valid_grade(controls['extra_change'], expected_delta)
            require(frozen == {'input': ref(source), 'goal': ref(goal), 'plan_sha256': canonical(ctx.data['plan']),
                    'edits_sha256': canonical(ctx.data['plan']['edits']), 'joint_certificate': ref(certificate_file)},
                    'Joint control source, reference, plan or construction proof changed during execution')
            ctx.save(attempt_prefix + '/local_controls.json', controls)
            receipt['local_controls'] = ref(attempt_directory / 'local_controls.json')
            receipt['control_rewards'] = {name: value['reward'] for name, value in controls.items()}
            if receipt['selected_plan_edit_index'] is None:
                raise TaskRejected('Q05/Q06: no observable actual single-omission negative control within the frozen attempt limit')
            if receipt['control_rewards'] != CONTROL_REWARDS:
                raise TaskRejected('Q05/Q06: positive/negative verifier controls did not match')
            canonical_folder = private / 'controls'
            canonical_folder.mkdir(exist_ok=False)
            for name in ('equivalent', 'missed_root', 'extra_change'):
                for suffix in ('_raw.xlsx', '.xlsx'):
                    source_name = name + suffix
                    shutil.copyfile(folder / source_name, canonical_folder / source_name)
            ctx.save('local_controls.json', controls)
            receipt['canonical_local_controls'] = ref(private / 'local_controls.json')
            receipt['canonical_control_artifacts'] = {
                path.name: ref(path) for path in sorted(canonical_folder.iterdir())}
            receipt.update(state='verified', passed=True)
            finalize()
            return {'controls': controls, 'joint_control_selection': deepcopy(receipt)}
        except BaseException as exc:
            receipt.update(state='cancelled' if isinstance(exc, CooperativeCancelled) else 'failed',
                           error_type=type(exc).__name__, error=str(exc))
            if not (attempt_directory / 'receipt.json').exists():
                finalize()
            raise
