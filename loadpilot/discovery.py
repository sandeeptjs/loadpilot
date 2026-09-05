from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar
from urllib.parse import parse_qsl, urlsplit

from .audit import redact
from .data import generate_samples
from .models import ApplicationModel, Endpoint, OperationDependency, Parameter


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _schema_example(schema: dict[str, Any], name: str = "value") -> Any:
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    fmt = schema.get("format")
    if kind == "object" or "properties" in schema:
        return {key: _schema_example(value, key) for key, value in schema.get("properties", {}).items() if key in schema.get("required", []) or not value.get("readOnly")}
    if kind == "array":
        return [_schema_example(schema.get("items", {}), name)]
    if fmt == "email":
        return "loadpilot+{{__VU}}@example.test"
    if fmt in {"uuid", "guid"}:
        return "00000000-0000-4000-8000-000000000001"
    if fmt in {"date-time", "datetime"}:
        return "2026-01-01T00:00:00Z"
    if kind in {"integer", "number"}:
        minimum = schema.get("minimum", 1)
        maximum = schema.get("maximum")
        return minimum if maximum is None else (minimum + maximum) / 2
    if kind == "boolean":
        return True
    return {"country": "US", "quantity": "1"}.get(name.lower(), f"test-{name}")


class ApplicationSourceAdapter(ABC):
    @abstractmethod
    def adapt(self, source: Any, *, name: str, base_url: str | None = None) -> ApplicationModel: ...


class OpenAPIAdapter(ApplicationSourceAdapter):
    def adapt(self, source: dict[str, Any], *, name: str, base_url: str | None = None) -> ApplicationModel:
        endpoints: list[Endpoint] = []
        dependencies: list[OperationDependency] = []
        security_schemes = source.get("components", {}).get("securitySchemes", {})
        effective_base = base_url or self._base_url(source)
        for path, path_item in source.get("paths", {}).items():
            path_parameters = path_item.get("parameters", [])
            for method in ("get", "post", "put", "patch", "delete", "options", "head"):
                operation = path_item.get(method)
                if not operation:
                    continue
                op_id = operation.get("operationId") or self._operation_id(method, path)
                parameters = [self._parameter(self._resolve_ref(p, source)) for p in path_parameters + operation.get("parameters", [])]
                request_body = self._resolve_ref(operation.get('requestBody'), source) or {}
                content = request_body.get('content', {})
                content_type = next((kind for kind in ('application/json', 'application/x-www-form-urlencoded', 'text/plain', 'multipart/form-data') if kind in content), None)
                if content and content_type is None:
                    raise ValueError(f'Unsupported request encoding for {op_id}; supply a JSON, form or text operation')
                request_schema = self._resolve_ref(content[content_type].get('schema'), source) if content_type else self._request_schema(operation, source)
                examples = generate_samples(request_schema) if request_schema else []
                response_schemas: dict[str, dict[str, Any]] = {}
                for status, response in operation.get("responses", {}).items():
                    schema = self._resolve_ref(self._content_schema(response), source)
                    if schema:
                        response_schemas[str(status)] = schema
                    for link in response.get("links", {}).values():
                        target = link.get("operationId")
                        for input_name, expression in link.get("parameters", {}).items():
                            if target and isinstance(expression, str):
                                dependencies.append(OperationDependency(
                                    producer_operation_id=op_id,
                                    consumer_operation_id=target,
                                    output_expression=expression,
                                    input_name=input_name,
                                    confidence=1,
                                    source="openapi-link",
                                ))
                auth = [key for requirement in operation.get("security", source.get("security", [])) for key in requirement]
                endpoints.append(Endpoint(
                    operation_id=op_id,
                    method=method.upper(), base_url=(operation.get('servers') or path_item.get('servers') or [{}])[0].get('url'),
                    path=path,
                    summary=operation.get("summary"),
                    parameters=parameters,
                    request_schema=request_schema, content_type=content_type or 'application/json',
                    response_schemas=response_schemas,
                    auth_schemes=auth,
                    tags=operation.get("tags", []),
                    examples=examples,
                ))
        dependencies.extend(self._infer_dependencies(endpoints, dependencies))
        return ApplicationModel(
            name=name,
            base_url=effective_base,
            source_type="openapi",
            source_fingerprint=_fingerprint(source),
            endpoints=endpoints,
            dependencies=dependencies,
            auth_schemes=security_schemes,
            metadata={"openapi": source.get("openapi") or source.get("swagger")},
        )

    @staticmethod
    def _base_url(source: dict[str, Any]) -> str | None:
        if source.get("servers"):
            return source["servers"][0].get("url")
        if source.get("host"):
            scheme = (source.get("schemes") or ["https"])[0]
            return f"{scheme}://{source['host']}{source.get('basePath', '')}"
        return None

    @staticmethod
    def _operation_id(method: str, path: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_")
        return f"{method}_{clean or 'root'}"

    @staticmethod
    def _parameter(value: dict[str, Any]) -> Parameter:
        schema = value.get("schema", {})
        return Parameter(name=value["name"], location=value["in"], required=value.get("required", False), style=value.get("style", "form" if value["in"] in {"query", "cookie"} else "simple"), explode=value.get("explode", value["in"] in {"query", "cookie"}), schema=schema, example=value.get("example", generate_samples(schema, 1)[0]))

    @staticmethod
    def _content_schema(value: dict[str, Any]) -> dict[str, Any] | None:
        content = value.get("content", {})
        for media_type in ("application/json", "application/*+json"):
            if media_type in content:
                return content[media_type].get("schema")
        return value.get("schema")

    def _request_schema(self, operation: dict[str, Any], document: dict[str, Any]) -> dict[str, Any] | None:
        if operation.get("requestBody"):
            return self._resolve_ref(self._content_schema(operation["requestBody"]), document)
        body = next((p for p in operation.get("parameters", []) if p.get("in") == "body"), None)
        return self._resolve_ref(body.get("schema"), document) if body else None

    @classmethod
    def _resolve_ref(cls, schema: dict[str, Any] | None, document: dict[str, Any], seen: set[str] | None = None) -> dict[str, Any] | None:
        if not schema:
            return schema
        seen = seen or set()
        if "$ref" in schema:
            ref = schema["$ref"]
            if not ref.startswith("#/") or ref in seen:
                return schema
            target: Any = document
            for part in ref[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            return cls._resolve_ref(target, document, seen | {ref})
        resolved = dict(schema)
        if "properties" in resolved:
            resolved["properties"] = {key: cls._resolve_ref(value, document, set(seen)) or value for key, value in resolved["properties"].items()}
        for keyword in ("allOf", "oneOf", "anyOf"):
            if keyword in resolved:
                resolved[keyword] = [cls._resolve_ref(item, document, set(seen)) for item in resolved[keyword]]
        if "items" in resolved:
            resolved["items"] = cls._resolve_ref(resolved["items"], document, set(seen)) or resolved["items"]
        return resolved

    @staticmethod
    def _infer_dependencies(endpoints: list[Endpoint], existing: list[OperationDependency]) -> list[OperationDependency]:
        known = {(d.producer_operation_id, d.consumer_operation_id, d.input_name) for d in existing}
        inferred: list[OperationDependency] = []
        producers = [e for e in endpoints if e.method == "POST"]
        for consumer in endpoints:
            params = [p.name for p in consumer.parameters] + re.findall(r"{([^}]+)}", consumer.path)
            for name in params:
                if not name.lower().endswith("id"):
                    continue
                stem = name.lower().removesuffix("_id").removesuffix("id")
                producer = next((p for p in producers if stem and stem in p.path.lower()), None)
                key = (producer.operation_id, consumer.operation_id, name) if producer else None
                if producer and key not in known and producer.operation_id != consumer.operation_id:
                    inferred.append(OperationDependency(producer_operation_id=producer.operation_id, consumer_operation_id=consumer.operation_id, output_expression=f"$response.body#/{name}", input_name=name, confidence=0.72, source="schema-inference"))
        return inferred


class HARAdapter(ApplicationSourceAdapter):
    SENSITIVE: ClassVar[set[str]] = {"authorization", "cookie", "set-cookie", "x-api-key"}

    def adapt(self, source: dict[str, Any], *, name: str, base_url: str | None = None) -> ApplicationModel:
        endpoints: dict[tuple[str, str], Endpoint] = {}
        for entry in source.get("log", {}).get("entries", []):
            request = entry.get("request", {})
            url = request.get("url", "")
            path = urlsplit(url).path or '/'
            base_url = base_url or f'{urlsplit(url).scheme}://{urlsplit(url).netloc}'
            method = request.get("method", "GET").upper()
            key = (method, path)
            headers = [h for h in request.get("headers", []) if h.get("name", "").lower() not in self.SENSITIVE]
            body = request.get("postData", {}).get("text")
            example = None
            if body:
                try:
                    example = redact(json.loads(body))
                except json.JSONDecodeError:
                    example = None
            endpoints[key] = Endpoint(operation_id=f"{method.lower()}_{re.sub(r'[^a-zA-Z0-9]+', '_', path).strip('_')}", method=method, path=path, parameters=[Parameter(name=h["name"], location="header", required=True, example=h.get("value")) for h in headers] + [Parameter(name=k, location="query", required=True, example=v) for k,v in parse_qsl(urlsplit(url).query)], examples=[example] if example is not None else [])
        return ApplicationModel(name=name, base_url=base_url, source_type="har", source_fingerprint=_fingerprint(source), endpoints=list(endpoints.values()), metadata={"sanitized": True})


class ManualAdapter(ApplicationSourceAdapter):
    def adapt(self, source: list[dict[str, Any]], *, name: str, base_url: str | None = None) -> ApplicationModel:
        endpoints = [Endpoint(operation_id=item.get("operation_id") or f"{item['method'].lower()}_{item['path'].strip('/').replace('/', '_')}", method=item["method"].upper(), path=item["path"], base_url=item.get("base_url"), request_schema=item.get("request_schema"), content_type=item.get("content_type", "application/json"), parameters=item.get('parameters', []), examples=item.get('examples') or (generate_samples(item['request_schema']) if item.get('request_schema') else [])) for item in source]
        return ApplicationModel(name=name, base_url=base_url, source_type="manual", source_fingerprint=_fingerprint(source), endpoints=endpoints)


class PostmanAdapter(ApplicationSourceAdapter):
    def adapt(self, source: dict[str, Any], *, name: str, base_url: str | None = None) -> ApplicationModel:
        items: list[dict[str, Any]] = []
        def walk(values: list[dict[str, Any]]) -> None:
            for item in values:
                if "item" in item:
                    walk(item["item"])
                elif "request" in item:
                    req = item["request"]
                    url = req.get("url", {})
                    raw = url if isinstance(url, str) else url.get("raw", "")
                    parsed = urlsplit(raw.replace('{{baseUrl}}', base_url or '').replace('{{base_url}}', base_url or ''))
                    if '{{' in parsed.path:
                        raise ValueError('Resolve Postman URL variables or supply baseUrl')
                    body = req.get('body', {})
                    if body and body.get('mode') != 'raw':
                        raise ValueError('Postman import currently requires a raw JSON body')
                    example = redact(json.loads(body['raw'])) if body.get('raw') else None
                    parameters = [{'name': k, 'location': 'query', 'required': True, 'example': v} for k,v in parse_qsl(parsed.query)]
                    parameters += [{'name': h['key'], 'location': 'header', 'required': True, 'example': h.get('value')} for h in req.get('header', []) if h['key'].lower() not in HARAdapter.SENSITIVE and not h.get('disabled')]
                    items.append({'method': req.get('method', 'GET'), 'path': parsed.path or '/', 'operation_id': re.sub(r'\W+', '_', item.get('name', 'operation')).strip('_'), 'parameters': parameters, 'examples': [example] if example is not None else []})
        walk(source.get("item", []))
        model = ManualAdapter().adapt(items, name=name, base_url=base_url)
        return model.model_copy(update={"source_type": "postman", "source_fingerprint": _fingerprint(source)})


class GraphQLAdapter(ApplicationSourceAdapter):
    def adapt(self, source: dict[str, Any], *, name: str, base_url: str | None = None) -> ApplicationModel:
        if 'operations' in source:
            endpoints = []
            for operation in source['operations']:
                if not isinstance(operation.get('query'), str) or not operation['query'].strip():
                    raise ValueError('GraphQL operations require a query document')
                endpoints.append(Endpoint(operation_id=operation['name'], method='POST', path=source.get('path', '/graphql'), examples=[{'query': operation['query'], 'variables': operation.get('variables', {})}]))
            return ApplicationModel(name=name, base_url=base_url, source_type='graphql', source_fingerprint=_fingerprint(source), endpoints=endpoints)
        raise ValueError('Supply GraphQL operations with name, query and variables; introspection alone does not specify a valid business journey')
