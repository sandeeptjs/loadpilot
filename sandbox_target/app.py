from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

REQUESTS = Counter("sandbox_http_requests_total", "Requests", ["method", "path", "status"])
LATENCY = Histogram("sandbox_http_request_duration_seconds", "Request duration", ["path"])
DB_POOL_ACTIVE = Gauge("sandbox_db_pool_active", "Active modeled database connections")
DB_POOL_SIZE = Gauge("sandbox_db_pool_size", "Configured modeled database pool size")
DB_WAIT = Histogram("sandbox_db_pool_wait_seconds", "Time waiting for a modeled DB connection")
DB_SATURATION_EVENTS = Counter("sandbox_db_pool_saturation_events_total", "Requests that arrived while every modeled DB connection was busy")
CACHE_HITS = Counter("sandbox_cache_hits_total", "Cache hits")
CACHE_MISSES = Counter("sandbox_cache_misses_total", "Cache misses")
ORDERS = Counter("sandbox_orders_total", "Completed orders")


@dataclass
class Controls:
    db_pool_size: int = int(os.getenv("SANDBOX_DB_POOL_SIZE", "12"))
    db_latency_ms: int = int(os.getenv("SANDBOX_DB_LATENCY_MS", "35"))
    checkout_latency_ms: int = int(os.getenv("SANDBOX_CHECKOUT_LATENCY_MS", "25"))
    cache_enabled: bool = True
    memory_growth_kb: int = 0


controls = Controls()
db_pool = asyncio.Semaphore(controls.db_pool_size)
carts: dict[str, dict] = {}
orders: dict[str, dict] = {}
cache: OrderedDict[str, list[dict]] = OrderedDict()
retained_memory: list[bytes] = []
PRODUCTS = [{"id": f"product-{index}", "name": f"Performance Widget {index}", "price": 9.99 + index} for index in range(1, 11)]


class LoginPayload(BaseModel):
    email: str
    password: str


class CartPayload(BaseModel):
    product_id: str = "product-1"
    quantity: int = Field(default=1, ge=1, le=20)


class ControlPayload(BaseModel):
    db_pool_size: int | None = Field(default=None, ge=1, le=200)
    db_latency_ms: int | None = Field(default=None, ge=0, le=5_000)
    checkout_latency_ms: int | None = Field(default=None, ge=0, le=5_000)
    cache_enabled: bool | None = None
    memory_growth_kb: int | None = Field(default=None, ge=0, le=5_000)


@asynccontextmanager
async def database_slot():
    started = time.perf_counter()
    if db_pool.locked():
        DB_SATURATION_EVENTS.inc()
    await db_pool.acquire()
    waited = time.perf_counter() - started
    DB_WAIT.observe(waited)
    DB_POOL_ACTIVE.inc()
    try:
        await asyncio.sleep(controls.db_latency_ms / 1000)
        yield
    finally:
        DB_POOL_ACTIVE.dec()
        db_pool.release()


app = FastAPI(title="LoadPilot Checkout Sandbox", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
DB_POOL_SIZE.set(controls.db_pool_size)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        REQUESTS.labels(request.method, path, str(status)).inc()
        LATENCY.labels(path).observe(time.perf_counter() - started)


@app.post("/login", operation_id="login")
async def login(payload: LoginPayload):
    async with database_slot():
        if not payload.email or not payload.password:
            raise HTTPException(401, "Invalid credentials")
        return {"access_token": f"sandbox-{uuid4()}", "token_type": "bearer"}


@app.get("/products", operation_id="listProducts")
async def products():
    if controls.cache_enabled and "products" in cache:
        CACHE_HITS.inc()
        return cache["products"]
    CACHE_MISSES.inc()
    async with database_slot():
        result = list(PRODUCTS)
    if controls.cache_enabled:
        cache["products"] = result
    return result


@app.post("/cart", status_code=201, operation_id="createCart")
async def create_cart(payload: CartPayload, authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(401, "Bearer token required")
    async with database_slot():
        cart_id = str(uuid4())
        carts[cart_id] = {"cart_id": cart_id, **payload.model_dump()}
        return carts[cart_id]


@app.post("/checkout/{cart_id}", status_code=201, operation_id="checkout")
async def checkout(cart_id: str, authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(401, "Bearer token required")
    async with database_slot():
        cart = carts.get(cart_id)
        if not cart:
            raise HTTPException(404, "Cart not found")
        await asyncio.sleep(controls.checkout_latency_ms / 1000)
        order_id = str(uuid4())
        order = {"order_id": order_id, "cart_id": cart_id, "status": "confirmed"}
        orders[order_id] = order
        if controls.memory_growth_kb:
            retained_memory.append(b"x" * controls.memory_growth_kb * 1024)
        ORDERS.inc()
        return order


@app.get("/orders", operation_id="listOrders")
async def list_orders(authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(401, "Bearer token required")
    async with database_slot():
        return list(orders.values())[-100:]


@app.post("/control", include_in_schema=False)
async def configure(payload: ControlPayload, x_control_token: str | None = Header(default=None)):
    expected = os.getenv("SANDBOX_CONTROL_TOKEN")
    if expected and x_control_token != expected:
        raise HTTPException(403, "Invalid control token")
    global db_pool
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(controls, key, value)
    if payload.db_pool_size is not None:
        db_pool = asyncio.Semaphore(payload.db_pool_size)
        DB_POOL_SIZE.set(payload.db_pool_size)
    return controls.__dict__


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    checkout_response = schema["paths"]["/cart"]["post"]["responses"]["201"]
    checkout_response["links"] = {"checkout": {"operationId": "checkout", "parameters": {"cart_id": "$response.body#/cart_id"}}}
    schema["servers"] = [{"url": "http://sandbox-target:8080"}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
