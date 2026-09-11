"""Versioned, dependency-free feature recipes shared by preview, training and scoring."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import math
import json
import statistics
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class FeatureRecipeValidationError(ValueError):
    pass


_OPERATIONS = {'select', 'number', 'abs', 'log', 'add', 'subtract', 'multiply', 'divide',
               'hour', 'weekday', 'elapsed_seconds', 'filter', 'count', 'sum', 'mean',
               'median', 'min', 'max', 'distinct_count', 'recency', 'ratio', 'difference', 'categorize',
               'to_array', 'to_boolean', 'fill_missing'}
_OUTPUT_TYPES = ('number', 'string', 'boolean')
_MISSING = object()

# (consumes, produces) per operation - the single source of truth for the step
# chain's type-inference walk in validate_feature_definition below, and for
# describe_operations()'s public capability listing. 'array'/'scalar' consumes
# means "requires (not) an array"; a step not listed here defaults to
# ('scalar', 'scalar') - the plain numeric-transform operations (number, abs,
# log, add, subtract, multiply, divide, hour, weekday, elapsed_seconds, ratio,
# difference).
_OPERATION_TYPES: dict[str, tuple[str, str]] = {
    'filter': ('array', 'array'),
    'count': ('array', 'scalar'), 'sum': ('array', 'scalar'), 'mean': ('array', 'scalar'),
    'median': ('array', 'scalar'), 'min': ('array', 'scalar'), 'max': ('array', 'scalar'),
    'distinct_count': ('array', 'scalar'), 'recency': ('array', 'scalar'),
    'select': ('array', 'unknown'),
    'categorize': ('scalar', 'unknown'),
    'to_array': ('scalar', 'array'),
    'to_boolean': ('scalar', 'unknown'),
    'fill_missing': ('scalar', 'unknown'),
}

# Operations that silently pass a missing/null input straight through instead
# of acting on it - the _step dispatch below short-circuits on `_MISSING`/None
# for anything not in this complement (see the `if value is _MISSING or value
# is None: return value` guard). Only 'fill_missing' turns a missing value
# into something the rest of the chain can use; 'select'/'filter'/the array
# aggregates handle (or explicitly reject) a missing input themselves. A step
# in this set placed before any 'fill_missing' step is a no-op whenever its
# input is actually missing - evaluate_feature_definition flags that in the
# trace (`skipped`) and describe_operations() exposes it so the frontend can
# warn about it while editing, without hand-copying this list.
_PASSTHROUGH_ON_MISSING_OPS = _OPERATIONS - {
    'select', 'filter', 'fill_missing',
    'count', 'sum', 'mean', 'median', 'min', 'max', 'distinct_count', 'recency',
}


def describe_operations() -> list[dict]:
    """Public capability listing for the mapping/transformations editor - lets
    the frontend build its operation picker (and gate which ops make sense at
    a given point in a recipe's step chain) from this module instead of
    hand-copying _OPERATIONS, avoiding the drift a hardcoded frontend list
    is prone to whenever an operation is added here."""
    return [
        {'id': op, 'consumes': _OPERATION_TYPES.get(op, ('scalar', 'scalar'))[0],
         'produces': _OPERATION_TYPES.get(op, ('scalar', 'scalar'))[1],
         'skips_on_missing_input': op in _PASSTHROUGH_ON_MISSING_OPS}
        for op in sorted(_OPERATIONS)
    ]


def describe_capabilities() -> dict:
    return {'operations': describe_operations(), 'output_types': list(_OUTPUT_TYPES)}


def _json_container(value: Any) -> Any:
    """Decode valid JSON containers while preserving delimited text.

    Some alert sources represent a primitive list as ``[A, B]`` rather than
    JSON's ``["A", "B"]``. That is text for the `to_array` step to normalize,
    not a malformed object the path walker should reject before the recipe
    gets a chance to transform it.
    """
    if isinstance(value, str) and value.lstrip().startswith(('{', '[')):
        if len(value) > 5_000_000:
            raise ValueError('JSON field exceeds 5 MB limit')
        try:
            return json.loads(value)
        except (ValueError, RecursionError):
            return value
    return value


def _path(value: Any, path: str) -> Any:
    if not path or path == '$':
        return value
    path = path.removeprefix('$.')
    for part in path.split('.'):
        value = _json_container(value)
        if isinstance(value, dict):
            value = value.get(part, _MISSING)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
    return _json_container(value)


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None or value is _MISSING:
        raise ValueError('Expected a finite number')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Expected a finite number') from None
    if not math.isfinite(result):
        raise ValueError('Expected a finite number')
    return result


def _date(value: Any, zone: ZoneInfo) -> datetime:
    if not isinstance(value, str):
        raise ValueError('Expected an ISO timestamp')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid ISO timestamp') from None
    if result.tzinfo is None:
        early, late = result.replace(tzinfo=zone, fold=0), result.replace(tzinfo=zone, fold=1)
        if early.utcoffset() != late.utcoffset():
            raise ValueError('Ambiguous or nonexistent local timestamp; supply a UTC offset')
        result = early
    return result.astimezone(timezone.utc)


def _canonical_path(path: str) -> str:
    return '' if path == '$' else path.removeprefix('$.')


def referenced_current_paths(definition: dict) -> set[str]:
    """Current-row inputs used by enabled recipes (for target leakage checks)."""
    paths: set[str] = set()
    mappings = definition.get('mappings', {})
    for recipe in definition.get('recipes', []):
        if not recipe.get('enabled', True):
            continue
        if recipe.get('source') == 'history':
            paths.update(mappings[k] for k in ('reference_time', 'entity', 'history') if mappings.get(k))
        selected_path = _canonical_path(recipe.get('path', '')) if recipe.get('source') == 'current' else None
        for step in recipe.get('steps', []):
            if not step.get('enabled', True):
                continue
            if step.get('operation') in ('elapsed_seconds', 'recency') and mappings.get('reference_time'):
                paths.add(mappings['reference_time'])
            if step.get('current_path'):
                paths.add(step['current_path'])
            if selected_path is not None and step.get('operation') == 'select' and step.get('path'):
                selected_path = '.'.join(filter(None, (selected_path, _canonical_path(step['path']))))
            for condition in step.get('conditions', []):
                if condition.get('current_path'):
                    paths.add(condition['current_path'])
        if selected_path is not None:
            paths.add(selected_path)
    return {_canonical_path(p) for p in paths}


def validate_feature_definition(definition: dict, forbidden_paths: Iterable[str] = ()) -> dict:
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise FeatureRecipeValidationError(message)
    require(isinstance(definition, dict), 'Definition must be an object')
    require(type(definition.get('schema_version')) is int and definition['schema_version'] in (1, 2), 'Unsupported schema_version; expected 1 or 2')
    try:
        require(len(json.dumps(definition, allow_nan=False)) <= 2_000_000, 'Definition exceeds 2 MB limit')
    except (TypeError, ValueError, RecursionError) as exc:
        raise FeatureRecipeValidationError('Definition must contain finite JSON values and fit the 2 MB limit') from exc
    mappings = definition.get('mappings', {})
    require(isinstance(mappings, dict), 'mappings must be an object')
    mapping_keys = {'history', 'timezone'} if definition['schema_version'] == 2 else {'reference_time', 'history', 'history_time', 'entity', 'history_entity', 'timezone'}
    for key, value in mappings.items():
        require(key in mapping_keys, f'Unknown mapping: {key}')
        require(isinstance(value, str) and bool(value.strip()), f'Mapping {key} must be a nonempty string')
    try:
        ZoneInfo(mappings.get('timezone', 'UTC'))
    except (ZoneInfoNotFoundError, ValueError):
        raise FeatureRecipeValidationError('Unknown timezone') from None
    require(bool(mappings.get('entity')) == bool(mappings.get('history_entity')), 'entity and history_entity must be mapped together')
    recipes = definition.get('recipes')
    require(isinstance(recipes, list) and 0 < len(recipes) <= 200, 'Provide 1 to 200 recipes')
    names, ids = set(), set()
    for recipe in recipes:
        require(isinstance(recipe, dict), 'Recipe must be an object')
        for key, seen in [('id', ids), ('name', names)]:
            value = recipe.get(key)
            require(isinstance(value, str) and bool(value.strip()) and len(value) <= 128, f'Recipe {key} is required (max 128 characters)')
            require(value not in seen, f'Duplicate recipe {key}: {value}')
            seen.add(value)
        require(isinstance(recipe.get('enabled', True), bool), 'enabled must be boolean')
        require(recipe.get('source') in ('current', 'history'), 'source must be current or history')
        require(recipe.get('output_type', 'number') in _OUTPUT_TYPES, 'Invalid output_type')
        if 'path' in recipe:
            require(isinstance(recipe['path'], str), 'path must be a string')
        if recipe['source'] == 'history':
            required = ('history',) if definition['schema_version'] == 2 else ('reference_time', 'history', 'history_time')
            require(all(mappings.get(k) for k in required), 'History requires ' + ', '.join(required) + ' mappings')
        if 'window_seconds' in recipe:
            require(definition['schema_version'] == 1, 'Use an explicit datetime filter instead of window_seconds in version 2')
            require(isinstance(recipe['window_seconds'], (float, int)) and not isinstance(recipe['window_seconds'], bool) and math.isfinite(recipe['window_seconds']) and recipe['window_seconds'] > 0, 'window_seconds must be positive and finite')
        missing = recipe.get('missing', {'policy': 'missing'})
        require(isinstance(missing, dict) and missing.get('policy') in ('missing', 'constant', 'error'), 'Invalid missing policy')
        require(missing.get('policy') != 'constant' or 'value' in missing, 'Constant missing policy requires value')
        if missing.get('policy') == 'constant':
            constant = missing['value']
            require(constant is None or isinstance(constant, (str, int, float, bool)), 'Missing constant must be a scalar')
            if constant is not None and recipe.get('output_type', 'number') == 'number':
                try:
                    _number(constant)
                except ValueError as exc:
                    raise FeatureRecipeValidationError('Missing constant must match number output_type') from exc
            if recipe.get('output_type') == 'boolean':
                require(isinstance(constant, bool), 'Missing constant must match boolean output_type')
        steps = recipe.get('steps')
        require(isinstance(steps, list) and len(steps) <= 50, 'steps must contain at most 50 operations')
        step_ids = set()
        inferred_type = 'array' if recipe['source'] == 'history' else 'unknown'
        for step in steps:
            require(isinstance(step, dict) and isinstance(step.get('operation'), str) and step['operation'] in _OPERATIONS, 'Unknown step operation')
            require(isinstance(step.get('id'), str) and bool(step['id']) and step['id'] not in step_ids, 'Step IDs must be nonempty and unique within a recipe')
            step_ids.add(step['id'])
            require(isinstance(step.get('enabled', True), bool), 'Step enabled must be boolean')
            # Disabled steps are draft configuration: they must identify a known
            # operation, but do not need to satisfy that operation's inputs until
            # they are enabled.  This lets clients retain an unfinished step.
            if not step.get('enabled', True):
                continue
            for path_key in ('path', 'current_path'):
                if path_key in step:
                    require(isinstance(step[path_key], str) and bool(step[path_key]), f'{path_key} must be a nonempty string')
            op = step['operation']
            consumes, produces = _OPERATION_TYPES.get(op, ('scalar', 'scalar'))
            if consumes == 'array':
                require(inferred_type in ('array', 'unknown'), f'{op} expects an array, received {inferred_type}')
            else:
                require(inferred_type != 'array', f'{op} expects a scalar, received array')
            inferred_type = produces
            if definition['schema_version'] == 2 and op in {'recency', 'elapsed_seconds'}:
                require(bool(step.get('current_path')), f'{op} requires current_path')
                if op == 'recency': require(bool(step.get('path')), 'recency requires path')
            if op == 'select':
                require(bool(step.get('path')), 'select requires path')
            if op in {'add', 'subtract', 'multiply', 'divide', 'ratio', 'difference'}:
                require(('value' in step) != ('current_path' in step), f'{op} requires exactly one of value or current_path')
                if 'value' in step:
                    try:
                        _number(step['value'])
                    except ValueError as exc:
                        raise FeatureRecipeValidationError(f'{op} requires a numeric operand') from exc
            if op == 'filter':
                conditions = step.get('conditions')
                require(isinstance(conditions, list) and 0 < len(conditions) <= 50, 'filter requires 1 to 50 conditions')
                require(step.get('match', 'all') in ('all', 'any'), 'filter match must be all or any')
                for c in conditions:
                    require(isinstance(c, dict), 'Filter condition must be an object')
                    require('path' not in c or isinstance(c['path'], str), 'Condition path must be a string when provided')
                    require(c.get('value_type', 'auto') in ('auto', 'datetime'), 'Unknown condition value_type')
                    if c.get('value_type') == 'datetime':
                        require(c.get('operator') in ('eq', 'ne', 'gt', 'gte', 'lt', 'lte'), 'Invalid datetime operator')
                    if 'offset_seconds' in c:
                        require(c.get('value_type') == 'datetime', 'offset_seconds requires datetime comparison')
                        require(type(c['offset_seconds']) in (int, float) and math.isfinite(c['offset_seconds']) and abs(c['offset_seconds']) <= 315576000000, 'Invalid datetime offset_seconds')
                    require(c.get('operator') in ('eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'contains'), 'Unknown filter operator')
                    require(('value' in c) != ('current_path' in c), 'Condition requires exactly one of value or current_path')
                    require('current_path' not in c or isinstance(c['current_path'], str) and bool(c['current_path']), 'Condition current_path must be nonempty')
            if op == 'to_array' and 'delimiter' in step:
                require(isinstance(step['delimiter'], str) and bool(step['delimiter']), 'to_array delimiter must be a nonempty string')
            if op == 'to_boolean' and 'truthy_values' in step:
                truthy_values = step['truthy_values']
                require(isinstance(truthy_values, list) and 0 < len(truthy_values) <= 100, 'to_boolean truthy_values must contain 1 to 100 values')
                require(all(v is None or isinstance(v, (str, int, float, bool)) for v in truthy_values), 'to_boolean truthy_values must be scalars')
            if op == 'fill_missing':
                require('value' in step, 'fill_missing requires a replacement value')
                replacement = step['value']
                primitive_list = (
                    isinstance(replacement, list) and len(replacement) <= 10_000
                    and all(item is None or isinstance(item, (str, int, float, bool)) for item in replacement)
                )
                require(
                    replacement is not None and (isinstance(replacement, (str, int, float, bool)) or primitive_list),
                    'fill_missing replacement must be a non-null scalar or primitive array',
                )
                require(isinstance(step.get('treat_blank_string_as_missing', True), bool), 'treat_blank_string_as_missing must be boolean')
            if op == 'categorize':
                rules = step.get('rules')
                require(isinstance(rules, list) and 0 < len(rules) <= 100, 'categorize requires 1 to 100 rules')
                intervals = []
                equals = []
                for rule in rules:
                    require(isinstance(rule, dict) and 'value' in rule, 'Category rule requires value')
                    require(rule['value'] is None or isinstance(rule['value'], (str, int, float, bool)), 'Category value must be scalar')
                    require(all(isinstance(rule.get(k, True), bool) for k in ('include_min', 'include_max')), 'Category boundary flags must be boolean')
                    if 'equals' in rule:
                        require(not any(k in rule for k in ('min', 'max')), 'Cannot combine equals and interval')
                        require(rule['equals'] not in equals, 'Duplicate category equality rule')
                        equals.append(rule['equals'])
                    else:
                        require('min' in rule or 'max' in rule, 'Category rule needs equals or a boundary')
                        try:
                            lo = _number(rule['min']) if 'min' in rule else -math.inf
                            hi = _number(rule['max']) if 'max' in rule else math.inf
                        except ValueError as exc:
                            raise FeatureRecipeValidationError(str(exc)) from None
                        require(lo < hi, 'Category minimum must be below maximum')
                        intervals.append((lo, hi, rule.get('include_min', True), rule.get('include_max', False)))
                intervals.sort()
                for left, right in zip(intervals, intervals[1:]):
                    require(left[1] < right[0] or left[1] == right[0] and not (left[3] and right[2]), 'Overlapping category intervals')
                require(not (equals and intervals), 'Use equality rules or intervals in one category step')
    forbidden = {_canonical_path(p) for p in forbidden_paths}
    for path in referenced_current_paths(definition):
        require(not any(not path or not target or path == target or path.startswith(target + '.') or target.startswith(path + '.') for target in forbidden), f'Target leakage: {path}')
    return deepcopy(definition)


def _condition(item: Any, condition: dict, row: dict, zone: ZoneInfo) -> bool:
    left = _path(item, condition.get('path', ''))
    right = _path(row, condition['current_path']) if 'current_path' in condition else condition['value']
    if left is _MISSING or right is _MISSING or left is None or right is None:
        return False
    op = condition['operator']
    if condition.get('value_type') == 'datetime':
        left = _date(left, zone)
        right = _date(right, zone) + timedelta(seconds=condition.get('offset_seconds', 0))
        return {'eq': left == right, 'ne': left != right, 'gt': left > right, 'gte': left >= right, 'lt': left < right, 'lte': left <= right}[op]
    if op == 'eq': return left == right
    if op == 'ne': return left != right
    if op == 'in': return left in right if isinstance(right, (list, str)) else False
    if op == 'contains': return right in left if isinstance(left, (list, str)) else False
    left, right = _number(left), _number(right)
    return {'gt': left > right, 'gte': left >= right, 'lt': left < right, 'lte': left <= right}[op]


def _step(value: Any, step: dict, row: dict, mappings: dict, zone: ZoneInfo) -> Any:
    op = step['operation']
    if isinstance(value, list) and len(value) > 10_000:
        raise ValueError('Array exceeds 10000 record limit')
    if op == 'select': return _path(value, step['path'])
    if op == 'filter':
        if not isinstance(value, list): raise ValueError('filter expects an array')
        fn = all if step.get('match', 'all') == 'all' else any
        return [item for item in value if fn(_condition(item, c, row, zone) for c in step['conditions'])]
    if op in {'count', 'sum', 'mean', 'median', 'min', 'max', 'distinct_count', 'recency'}:
        if not isinstance(value, list): raise ValueError(f'{op} expects an array')
        if op == 'count': return len(value)
        items = [_path(item, step.get('path', '')) for item in value]
        if op == 'distinct_count':
            if any(item is _MISSING or item is None for item in items): raise ValueError('Missing value in array')
            return len({str(type(item)) + ':' + repr(item) for item in items})
        if op == 'recency':
            if not value: return None
            dates = [_date(_path(item, step.get('path', mappings.get('history_time', ''))), zone) for item in value]
            return (_date(_path(row, step.get('current_path', mappings.get('reference_time', ''))), zone) - max(dates)).total_seconds()
        if not items: return 0 if op == 'sum' else None
        nums = [_number(item) for item in items]
        return {'sum': sum, 'mean': statistics.mean, 'median': statistics.median, 'min': min, 'max': max}[op](nums)
    if op == 'fill_missing':
        blank = isinstance(value, str) and not value.strip() and step.get('treat_blank_string_as_missing', True)
        return step['value'] if value is _MISSING or value is None or blank else value
    if value is _MISSING or value is None: return value
    if op in {'hour', 'weekday', 'elapsed_seconds'}:
        date = _date(value, zone)
        if op == 'hour': return date.astimezone(zone).hour
        if op == 'weekday': return date.astimezone(zone).weekday()
        return (_date(_path(row, step.get('current_path', mappings.get('reference_time', ''))), zone) - date).total_seconds()
    if op == 'to_array':
        if isinstance(value, list): return value
        if not isinstance(value, str): raise ValueError('to_array expects a string or array value')
        text = value.strip()
        if text.startswith('[') and text.endswith(']'): text = text[1:-1]
        delimiter = step.get('delimiter', ',')
        return [item.strip() for item in text.split(delimiter) if item.strip()]
    if op == 'to_boolean':
        if isinstance(value, bool): return value
        truthy_values = step.get('truthy_values')
        if truthy_values is not None: return value in truthy_values
        return _number(value) != 0
    if op == 'categorize':
        for rule in step['rules']:
            if 'equals' in rule:
                if value == rule['equals']: return rule['value']
            else:
                number = _number(value)
                lo = _number(rule['min']) if 'min' in rule else -math.inf
                hi = _number(rule['max']) if 'max' in rule else math.inf
                if (number >= lo if rule.get('include_min', True) else number > lo) and (number <= hi if rule.get('include_max', False) else number < hi): return rule['value']
        return step.get('fallback')
    number = _number(value)
    if op == 'number': return number
    if op == 'abs': return abs(number)
    if op == 'log':
        if number <= 0: raise ValueError('log requires a positive value')
        return math.log(number)
    operand = _number(_path(row, step['current_path']) if 'current_path' in step else step['value'])
    if op == 'add': result = number + operand
    elif op == 'subtract': result = number - operand
    elif op == 'multiply': result = number * operand
    elif op in ('divide', 'ratio'):
        numerator, denominator = (operand, number) if op == 'ratio' else (number, operand)
        if denominator == 0: raise ValueError('Division by zero')
        result = numerator / denominator
    else: result = operand - number
    return _number(result)


def _trace_entry(step_id: str, operation: str, value: Any, *, skipped: bool = False) -> dict:
    return {
        'step_id': step_id,
        'operation': operation,
        'value': None if value is _MISSING else deepcopy(value[:100] if isinstance(value, list) else value),
        'truncated': isinstance(value, list) and len(value) > 100,
        'total_items': len(value) if isinstance(value, list) else None,
        'skipped': skipped,
    }


def evaluate_feature_definition(definition: dict, row: dict, *, validated: bool = False) -> dict:
    """Evaluate one JSON row. Errors are explicit and never silently imputed."""
    if not validated:
        definition = validate_feature_definition(definition)
    if not isinstance(row, dict):
        raise FeatureRecipeValidationError('Input row must be an object')
    mappings = definition.get('mappings', {})
    zone = ZoneInfo(mappings.get('timezone', 'UTC'))
    result = {'values': {}, 'features': []}
    for recipe in definition['recipes']:
        feature = {'id': recipe['id'], 'name': recipe['name'], 'value': None, 'status': 'disabled', 'error': None, 'trace': [], 'history': {'included': [], 'excluded': []}}
        result['features'].append(feature)
        if not recipe.get('enabled', True): continue
        value = None
        try:
            if recipe['source'] == 'history':
                history = _json_container(_path(row, mappings['history']))
                if not isinstance(history, list): raise ValueError('Mapped history must be an array')
                if len(history) > 10_000: raise ValueError('History exceeds 10000 record limit')
                if definition['schema_version'] == 2:
                    value = [_json_container(item) for item in history]
                    if any(not isinstance(item, dict) for item in value):
                        raise ValueError('History records must be JSON objects')
                    feature['history']['included'] = list(range(len(value)))
                else:
                    reference = _date(_path(row, mappings['reference_time']), zone)
                    entity = _path(row, mappings['entity']) if mappings.get('entity') else None
                    if mappings.get('entity') and (entity is _MISSING or entity is None): raise ValueError('Missing current entity')
                    value = []
                    for index, item in enumerate(history):
                        item = _json_container(item)
                        if not isinstance(item, dict): raise ValueError('History records must be JSON objects')
                        reason = None
                        try:
                            date = _date(_path(item, mappings['history_time']), zone)
                            age = (reference - date).total_seconds()
                            if age <= 0: reason = 'at_or_after_reference'
                            elif 'window_seconds' in recipe and age > recipe['window_seconds']: reason = 'outside_window'
                            elif mappings.get('history_entity') and _path(item, mappings['history_entity']) != entity: reason = 'different_entity'
                        except ValueError as exc:
                            reason = str(exc)
                        if reason:
                            feature['history']['excluded'].append({'index': index, 'reason': reason})
                        else:
                            feature['history']['included'].append(index)
                            value.append(item)
            else:
                value = _path(row, recipe.get('path', ''))
            feature['trace'].append(_trace_entry('_input', 'input', value))
            track_history = definition['schema_version'] == 2 and recipe['source'] == 'history'
            for step in recipe['steps']:
                if not step.get('enabled', True):
                    continue
                if step['operation'] == 'select':
                    track_history = False
                entering_value = value
                if track_history and step['operation'] == 'filter' and isinstance(value, list):
                    before = value
                    value = _step(value, step, row, mappings, zone)
                    # Only track the original event list, before any extraction.
                    indices = feature['history']['included']
                    if len(indices) == len(before):
                        kept = {id(item) for item in value}
                        feature['history']['excluded'].extend(
                            {'index': index, 'reason': 'filter:' + step['id']}
                            for index, item in zip(indices, before) if id(item) not in kept)
                        feature['history']['included'] = [index for index, item in zip(indices, before) if id(item) in kept]
                else:
                    value = _step(value, step, row, mappings, zone)
                skipped = (
                    step['operation'] in _PASSTHROUGH_ON_MISSING_OPS
                    and (entering_value is _MISSING or entering_value is None)
                    and value is entering_value
                )
                feature['trace'].append(_trace_entry(step['id'], step['operation'], value, skipped=skipped))
            if isinstance(value, (dict, list)):
                raise ValueError('A feature must resolve to a scalar; add an extraction or aggregation step')
            if isinstance(value, float) and not math.isfinite(value): raise ValueError('Nonfinite feature output')
            if value is _MISSING or value is None:
                raise ValueError('Missing feature value')
            output_type = recipe.get('output_type', 'number')
            if output_type == 'number': value = _number(value)
            elif output_type == 'string': value = str(value)
            elif output_type == 'boolean' and not isinstance(value, bool): raise ValueError('Expected boolean output')
            feature['status'] = 'ok'
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            policy = recipe.get('missing', {}).get('policy', 'missing')
            feature['error'] = str(exc)
            value = recipe.get('missing', {}).get('value') if policy == 'constant' else None
            if policy == 'constant' and value is not None:
                if recipe.get('output_type', 'number') == 'number': value = _number(value)
                elif recipe.get('output_type') == 'string': value = str(value)
            feature['status'] = 'error' if policy == 'error' else ('ok' if policy == 'constant' and value is not None else 'missing')
        feature['value'] = value
        result['values'][recipe['name']] = value
    return result
