from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def offline_provider(monkeypatch):
    """Keep the suite hermetic.

    A developer's `.env` or an ambient GEMINI/GOOGLE/OPENAI key must never turn a
    deterministic test into a billed network call. Tests that exercise the provider
    pass an explicit model plus a mock transport, which overrides this.
    """
    for name in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'OPENAI_API_KEY', 'LOADPILOT_LLM_API_KEY', 'LOADPILOT_LLM_BASE_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('LOADPILOT_LLM_MODEL', '')


@pytest.fixture
def checkout_openapi():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Checkout Sandbox", "version": "1.0.0"},
        "servers": [{"url": "http://localhost:8080"}],
        "paths": {
            "/login": {
                "post": {
                    "operationId": "login",
                    "requestBody": {"content": {"application/json": {"schema": {"type": "object", "required": ["email", "password"], "properties": {"email": {"type": "string", "format": "email"}, "password": {"type": "string"}}}}}},
                    "responses": {"200": {"description": "token"}},
                }
            },
            "/cart": {
                "post": {
                    "operationId": "createCart",
                    "requestBody": {"content": {"application/json": {"schema": {"type": "object", "required": ["quantity"], "properties": {"quantity": {"type": "integer", "minimum": 1, "maximum": 5}}}}}},
                    "responses": {"201": {"description": "cart", "content": {"application/json": {"schema": {"type": "object", "properties": {"cart_id": {"type": "string"}}}}}, "links": {"checkout": {"operationId": "checkout", "parameters": {"cart_id": "$response.body#/cart_id"}}}}},
                }
            },
            "/checkout/{cart_id}": {
                "post": {
                    "operationId": "checkout",
                    "parameters": [{"name": "cart_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"201": {"description": "order"}},
                }
            },
        },
    }

