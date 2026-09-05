"""Validate declarative journeys before compiling executable workloads."""
import json
import re

from jsonschema import validate

from .models import UserJourney


def validate_journeys(values, application):
    journeys = [UserJourney.model_validate(v) for v in values]
    if not 1 <= len(journeys) <= 10:
        raise ValueError('Supply between one and ten journeys')
    operations = {e.operation_id: e for e in application.endpoints}
    if len(operations) != len(application.endpoints):
        raise ValueError('Operation IDs must be unique')
    if len({j.name for j in journeys}) != len(journeys):
        raise ValueError('Journey names must be unique')
    for journey in journeys:
        journey.infer_dependencies = False
        available = set()
        if sum(s.repeat for s in journey.steps) > 100:
            raise ValueError('A journey may issue at most 100 requests per iteration')
        for step in journey.steps:
            if step.operation_id not in operations:
                raise ValueError(f'Unknown scenario operation: {step.operation_id}')
            endpoint = operations[step.operation_id]
            refs = set(re.findall(r'\$\{([^}]+)\}', json.dumps([step.inputs, step.headers, step.body, [a.equals for a in step.assertions]])))
            missing = refs - available
            if missing:
                raise ValueError(f'{step.operation_id} uses variables before extraction: {sorted(missing)}')
            if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key) for key in step.extract):
                raise ValueError('Extraction names must be simple variable names')
            if any(not pointer.startswith('/') for pointer in step.extract.values()):
                raise ValueError('Extractions require response JSON pointers beginning with /')
            if any(code < 100 or code > 599 for code in step.expected_statuses):
                raise ValueError('Expected statuses must be HTTP status codes')
            if step.body is not None and endpoint.request_schema and not refs:
                try:
                    validate(step.body, endpoint.request_schema)
                except Exception as exc:
                    raise ValueError(f'Body for {step.operation_id} violates its schema') from exc
            available.update(step.extract)
    return journeys
