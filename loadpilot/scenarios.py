"""Validate declarative journeys before compiling executable workloads."""
import json
import re

from jsonschema import SchemaError, ValidationError, validate

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
        reserved = {'__VU', '__ITER', '__RUN_ID', '__TIMESTAMP'}
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key) or key in reserved for key in journey.datasets):
            raise ValueError('Dataset names must be nonreserved variable names')
        if any(not 1 <= len(values) <= 10000 for values in journey.datasets.values()):
            raise ValueError('Datasets require between one and 10000 rows')
        available = reserved | set(journey.datasets)
        if all(s.when for s in journey.steps):
            raise ValueError('At least one unconditional step is required to establish execution evidence')
        if sum(s.repeat * (s.retries + 1) for s in journey.steps) > 100:
            raise ValueError('A journey may issue at most 100 requests per iteration')
        for step in journey.steps:
            if step.operation_id not in operations:
                raise ValueError(f'Unknown scenario operation: {step.operation_id}')
            endpoint = operations[step.operation_id]
            if (step.until or step.retries) and endpoint.method not in {'GET', 'HEAD'}:
                raise ValueError('Polling and automatic retries require a read-only GET or HEAD operation')
            if step.until and step.repeat < 2:
                raise ValueError('Polling requires repeat >= 2 to define its attempt budget')
            if step.when and step.when.variable not in available:
                raise ValueError('Condition references a variable before extraction')
            refs = set(re.findall(r'\$\{([^}]+)\}', json.dumps([step.inputs, step.headers, step.body, [a.equals for a in step.assertions], step.when.equals if step.when else None, step.until.equals if step.until else None, [part.content for part in step.files.values()]])))
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
                except (ValidationError, SchemaError) as exc:
                    raise ValueError(f'Body for {step.operation_id} violates its schema') from exc
            available.update(step.extract)
    return journeys
