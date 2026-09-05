from __future__ import annotations

import pytest


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

