"""Schema-valid sample pools, with readable examples preferred over fuzz data."""
import math
from copy import deepcopy

from hypothesis import Phase, given, settings
from hypothesis_jsonschema import from_schema
from jsonschema import Draft202012Validator, FormatChecker

from .audit import SECRET_KEYS


def normalized(schema, name=''):
    result = deepcopy(schema)
    if isinstance(result, dict):
        if SECRET_KEYS.search(name):
            for annotation in ('example', 'examples', 'default'):
                result.pop(annotation, None)
        if result.pop('nullable', False) and isinstance(result.get('type'), str):
            result['type'] = [result['type'], 'null']
        for key in ('exclusiveMinimum', 'exclusiveMaximum'):
            if isinstance(result.get(key), bool):
                exclusive = result.pop(key)
                bound = 'minimum' if key == 'exclusiveMinimum' else 'maximum'
                if exclusive and bound in result:
                    result[key] = result.pop(bound)
        for key, value in list(result.items()):
            if isinstance(value, dict):
                result[key] = normalized(value, key)
            elif isinstance(value, list):
                result[key] = [normalized(v) if isinstance(v, dict) else v for v in value]
    return result


def readable(schema, index=0, name='value'):
    if 'const' in schema:
        return schema['const']
    if schema.get('enum'):
        return schema['enum'][index % len(schema['enum'])]
    if 'default' in schema:
        return schema['default']
    if 'example' in schema:
        return schema['example']
    kind = schema.get('type')
    if isinstance(kind, list):
        kind = next((value for value in kind if value != 'null'), 'null')
    if kind == 'object' or 'properties' in schema:
        return {key: readable(value, index, key) for key, value in schema.get('properties', {}).items() if not value.get('readOnly')}
    if kind == 'array':
        return [readable(schema.get('items', {}), index + i, name) for i in range(max(1, schema.get('minItems', 0)))]
    if kind in {'integer', 'number'}:
        low = schema.get('minimum', schema.get('exclusiveMinimum', 0) + 1)
        high = schema.get('maximum', schema.get('exclusiveMaximum', low + 10) - 1)
        value = min(high, low + index)
        multiple = schema.get('multipleOf', 1 if kind == 'integer' else .1)
        value = math.ceil(value / multiple) * multiple
        return int(value) if kind == 'integer' else value
    if kind == 'boolean':
        return index % 2 == 0
    if schema.get('format') == 'email' or name == 'email':
        return f'shopper{index}@example.test'
    if schema.get('format') == 'uuid':
        return f'00000000-0000-4000-8000-{index + 1:012d}'
    if schema.get('format') == 'date-time':
        return '2026-01-01T00:00:00Z'
    value = f'test-{name}-{index}'
    return value.ljust(schema.get('minLength', 0), 'x')[:schema.get('maxLength', 80)]


def generate_samples(schema, count=8):
    schema = normalized(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    candidates = [readable(schema, index) for index in range(count)]
    valid = [value for value in candidates if validator.is_valid(value)]
    if valid:
        return valid
    # Constraint-heavy schemas fall back to the established Hypothesis generator.
    @settings(max_examples=count, derandomize=True, database=None, deadline=None, phases=[Phase.generate])
    @given(from_schema(schema, allow_x00=False))
    def collect(value):
        if validator.is_valid(value):
            valid.append(value)
    collect()
    if not valid:
        raise ValueError('Could not generate a valid payload for this schema')
    return valid
