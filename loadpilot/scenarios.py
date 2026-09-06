"""Validate declarative journeys before compiling executable workloads."""
import json
import re

from jsonschema import SchemaError, ValidationError, validate

from .models import UserJourney

_REFERENCE = re.compile(r'\$\{([^}]+)\}')
_RESERVED = frozenset({'__VU', '__ITER', '__RUN_ID', '__TIMESTAMP'})
# How OpenAPI states where a response value sits, and therefore where a journey must read it.
_POINTER = '$response.body#'


def _unproduced(value, available, broken=frozenset()) -> bool:
    """Whether this value should be cleared so the schema-conforming pool can fill it.

    A reference nothing in the journey mentions describes a value rather than carries one, and
    clearing it lets a generated one stand in. A reference whose producer was removed is a
    broken pipe: clearing it would quietly send the request without the credential or
    identifier it depends on, so it stays for the validation gate to reject.
    """
    missing = set(_REFERENCE.findall(json.dumps(value))) - available
    return bool(missing) and not missing & broken


def _declared_outputs(application, operation_id) -> dict[str, str]:
    """Pointers the application's own contract says this response carries, keyed by the input
    each one feeds. A documented link is a fact about the body; a pointer a model wrote is a
    guess about it, so the two are not weighed equally."""
    return {
        dependency.input_name.lower(): dependency.output_expression[len(_POINTER):]
        for dependency in (application.dependencies if application else [])
        if dependency.producer_operation_id == operation_id and dependency.output_expression.startswith(_POINTER + '/')
    }


def _carries(pointer, schema) -> bool:
    """Whether a body of this shape can hold this JSON pointer. Anything the schema leaves
    open answers yes: only an explicit property list can establish that a field is absent."""
    for token in pointer.strip('/').split('/'):
        if not isinstance(schema, dict) or '$ref' in schema:
            return True
        properties, items = schema.get('properties'), schema.get('items')
        if token.isdigit() and items is not None:
            schema = items
        elif properties is not None:
            if token not in properties:
                return False
            schema = properties[token]
        else:
            return schema.get('additionalProperties') is not False
    return True


def _repair_extractions(step, application, endpoint, repaired) -> set[str]:
    """Reconcile the pointers a model wrote with the response its contract documents.

    A workflow can be right about the handoff and wrong about where the value sits: a login
    that answers with access_token does not stop being the step that produces the token
    because the model wrote /token. Where the contract names the pointer it wins and the
    correction is reported; where nothing can say what was meant the extraction is removed and
    the journey is left to fail validation rather than run on a value that never arrives.
    Returns the names whose producer was withdrawn, so a later step cannot silently drop the
    reference to one. An undocumented response is unknown rather than wrong and is left alone.
    """
    declared = _declared_outputs(application, step.operation_id)
    pointers = set(declared.values())
    schemas = [schema for code, schema in (endpoint.response_schemas if endpoint else {}).items() if code.startswith('2') or code == 'default']
    withdrawn = set()
    for name, pointer in list(step.extract.items()):
        if pointer in pointers or any(_carries(pointer, schema) for schema in schemas) or not (schemas or declared):
            continue
        truth = declared.get(name.lower()) or (next(iter(pointers)) if len(pointers) == 1 and len(step.extract) == 1 else None)
        if truth:
            step.extract[name] = truth
        else:
            step.extract.pop(name)
            withdrawn.add(name)
        repaired.append(f'{step.operation_id}.extract.{name}')
    return withdrawn


def _conforms(body, schema) -> bool:
    if not schema:
        return True
    try:
        validate(body, schema)
    except (ValidationError, SchemaError):
        return False
    return True


def drop_unproduced_references(values, application=None):
    """Clear ${variable} references nothing in the journey produces.

    A model that writes ${email} on the first step described a workflow, not a variable
    an earlier step extracted. Clearing exactly those fields keeps the workflow and lets
    the schema-conforming pool supply the values, which serves the requirement better
    than discarding an otherwise runnable journey. Path and required parameters are left
    alone: those have no generated fallback at runtime, so a journey that misuses one is
    better rejected than half-repaired. Returns the journeys and what was cleared, so the
    interface can say where the executed workflow departs from what the model wrote.
    """
    endpoints = {e.operation_id: e for e in application.endpoints} if application else {}
    journeys = [UserJourney.model_validate(value) for value in values]
    repaired: list[str] = []
    for journey in journeys:
        available = set(_RESERVED) | set(journey.datasets)
        broken: set[str] = set()
        for step in journey.steps:
            endpoint = endpoints.get(step.operation_id)
            parameters = {p.name: p for p in endpoint.parameters} if endpoint else {}
            for key in [key for key, value in step.inputs.items() if _unproduced(value, available, broken)]:
                parameter = parameters.get(key)
                if parameter is None or (not parameter.required and parameter.location != 'path'):
                    step.inputs.pop(key)
                    repaired.append(f'{step.operation_id}.inputs.{key}')
            for key in [key for key, value in step.headers.items() if _unproduced(value, available, broken)]:
                step.headers.pop(key)
                repaired.append(f'{step.operation_id}.headers.{key}')
            if isinstance(step.body, dict):
                cleared = [key for key, value in step.body.items() if _unproduced(value, available, broken)]
                for key in cleared:
                    step.body.pop(key)
                    repaired.append(f'{step.operation_id}.body.{key}')
                if cleared and not _conforms(step.body, endpoint.request_schema if endpoint else None):
                    # What survives a half-variable body may no longer satisfy the schema;
                    # a generated example is a whole valid body rather than a partial one.
                    step.body = None
                    repaired.append(f'{step.operation_id}.body')
            elif _unproduced(step.body, available, broken):
                step.body = None
                repaired.append(f'{step.operation_id}.body')
            broken |= _repair_extractions(step, application, endpoint, repaired)
            available.update(step.extract)
    return journeys, repaired


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
        reserved = set(_RESERVED)
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
