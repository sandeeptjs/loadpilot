# Scenario-driven testing

LoadPilot can compile application-specific HTTP journeys instead of relying on a checkout preset. With a configured model, the existing intent call receives operation descriptions, parameters, request schemas and response schemas and can return a complete journey. Missing required business inputs are reported instead of silently guessed. Without a provider, name operation IDs in the prompt or supply explicit journeys. Offline mode does not claim to understand arbitrary prose.

POST `/api/tests` accepts an optional `journeys` array. Each journey has a name, positive weight and ordered steps. Weights control the probability of selecting a journey for each iteration. They are not an exact request traffic split. Each step supports:

- `operation_id`, referencing an operation in the supplied application.
- `inputs`, for path, query, cookie and header parameters.
- `body`, overriding the generated payload with JSON, form fields or text.
- `headers`, including a runtime token such as `Bearer ${token}` or an environment reference such as `env:TARGET_API_KEY`.
- `extract`, mapping variable names to response JSON pointers such as `/ticket/id`.
- `expected_statuses` and `assertions`, which compare a response JSON pointer with an expected value.
- `repeat`, from one to ten, and `think_time_seconds`.

A value consisting solely of `${id}` preserves the extracted JSON type. Embedded references become strings. Variables are isolated to each journey iteration. Explicit journeys define their own bindings; inferred OpenAPI dependencies are used for automatically selected journeys. Repeating an operation explicitly allows workflows with cycles without introducing an unbounded loop.

Example step after a login operation extracted `token`:

```json
{
  "operation_id": "createTicket",
  "headers": {"Authorization": "Bearer ${token}"},
  "body": {"owner": {"name": "Ada"}},
  "expected_statuses": [201],
  "extract": {"ticketId": "/ticket/id"}
}
```

Use environment references for credentials. Never put real credentials in scenario files. Automatic API-key discovery, OAuth browser consent and arbitrary authentication scripts are not implemented. A login HTTP operation, cookie session, or configured authorization header can participate in the journey.

## Preflight and budgets

Before applying load, k6 executes one iteration of every journey, including its bounded repeats, with one virtual user. Failed status checks, assertions, extractions or missing credentials stop the run. Preflight can create records, so use a disposable target with suitable test data. It does not silently retry writes or invent replacement business IDs. Correct the reported input and create a new run.

Preflight has a sixty-second k6 deadline per journey and a sixty-five-second process timeout. Its summaries are separate from measured workload summaries. At most ten journeys, thirty steps per journey and one hundred expanded requests per journey are accepted. Existing target, duration, VU and RPS limits still apply. Unspecified load now defaults to one user and thirty seconds. A short soak exercises the workflow but cannot establish long-term stability.

AI parsing uses one request and result summarization uses one request. There are no automatic model repair loops. `LOADPILOT_LLM_MAX_TOKENS` defaults to 2500, and oversized model input is rejected. Explicit journeys work without provider usage. RPS still requires one HTTP operation because journey rate and HTTP request rate are different quantities.

## Run the independent examples

Start the API using `scripts/start_demo.py` as described in `demo.md`. In another terminal start the small scenario transport fixture:

```powershell
uv run python -m sandbox_target.scenario_fixture --port 8090
```

Then run any saved request through the public API:

```powershell
uv run python scripts/run_scenario.py examples/scenarios/tickets.json
uv run python scripts/run_scenario.py examples/scenarios/search.json
uv run python scripts/run_scenario.py examples/scenarios/graphql.json
uv run python scripts/run_scenario.py examples/scenarios/mixed.json
```

The CLI prints the run ID and final measurements. The same runs appear in the dashboard. The fixture verifies HTTP transport, bindings and assertions; it is not a realistic support-ticket database or a GraphQL engine. The separate checkout sandbox remains the contention/remediation demo.

For another application, replace the source, base URL and journeys. Add its hostname to `LOADPILOT_ALLOWED_HOSTS` before starting the API. OpenAPI supports JSON, form and text bodies. Manual definitions support those encodings too. HAR preserves sanitized JSON requests and query parameters. Postman preserves raw JSON bodies, headers and query parameters and supports supplied `baseUrl`/`base_url`; collection scripts and arbitrary variables are not executed. GraphQL accepts `{ "operations": [{ "name": "query", "query": "query { health }", "variables": {} }] }`. Introspection alone is rejected because it does not establish a valid business query.

Browser UI automation, WebSockets, gRPC, multipart uploads, distributed workers, conditional branches and automatic business-rule repair remain outside this implementation. An application description cannot supply unknown credentials, valid account IDs or undocumented business constraints.

## Verification

The backend suite passes 31 tests. Public API tests execute real k6 against the independent fixture for ticket/login dependencies, search parameters and repetition, GraphQL documents, form and text bodies, and weighted mixed journeys. An invalid resource makes exactly one preflight request before failing. The provider journey contract is tested with a mock response, not a credentialed model call.

The saved mixed example also completed through the CLI and the running API on port 8018 with 18 measured requests, no HTTP or journey failures, and all checks passing. The existing checkout flow completed after the preflight change with seven measured requests and no journey failures. These short runs verify execution, not capacity or long-term stability.
