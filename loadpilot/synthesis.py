"""Offline natural-language scenario synthesis.

Turns a free-text requirement into an ordered, dependency-wired journey over the
operations discovery actually found. No model provider is involved: the mapping is
lexical, ranked and explainable, so every step carries the evidence that chose it
and the interface can show the user what was understood before anything executes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .intent import normalize_numbers
from .models import ApplicationModel, Endpoint, JourneyStep, UserJourney
from .scenarios import validate_journeys


def _words(text: str) -> frozenset[str]:
    """Vocabulary lists read as prose here; one line per set beats a 40-item literal."""
    return frozenset(text.split())


def _ref(variable: str) -> str:
    """A k6 runtime reference: resolved against journey state, not by Python."""
    return '${' + variable + '}'


# Words that carry no operation meaning. Deliberately grammatical only: content
# nouns such as "users" or "orders" are real operation names in many APIs and are
# removed by the load-specification filter below when they belong to a load clause.
_GRAMMAR = _words(
    'a an the and or then with without for of to from in into on at by as is are be being been it its that this these '
    'those my our your their some any each all every up out over under about after before while when if so do does did '
    'can could should would will also please just very more most both there here who whom which what how'
)

# The quantity a threshold clause ends at. Bounding the clause here matters: a
# requirement may state its objective before its workflow, and a clause that ran to
# the end of the sentence would swallow the steps the user actually described.
_QUANTITY_TAIL = r'\d[\d,]*(?:\.\d+)?\s*(?:ms|millis(?:econds?)?|secs?|seconds?|s|%)?'

# Who the load is made of, as a requirement writes it. A count belongs to its noun, so
# "12 shoppers" is stripped with the noun rather than left to compete with an operation.
_ACTORS = (r'(?:concurrent\s+|simultaneous\s+|parallel\s+|virtual\s+|active\s+|live\s+|paying\s+|test\s+)?'
           r'(?:vus?|users?|shoppers?|customers?|visitors?|sessions?|clients?|people|persons?|buyers?|'
           r'callers?|testers?|browsers?|requesters?|agents?|connections?|threads?|workers?|accounts?)')
_PERCENTILES = r'(?:p\s*\(?\s*(?:50|75|90|95|99)\s*\)?|(?:50|75|90|95|99)(?:th)?\s*(?:-|\s)?percentile)'
_FAILURES = (r'(?:errors?|error\s*rates?|failures?|failure\s*rates?|fail(?:ing|ed|s)?(?:\s+requests?)?|'
             r'5xx(?:\s+responses?)?|500s)')
_PERCENT_TAIL = r'\d+(?:\.\d+)?\s*(?:%|percent(?:age)?)'

# Load-specification clauses. Stripped before segmentation so "500 users" never
# competes with an operation named "users", and "for 2 minutes" never becomes a step.
_LOAD_CLAUSES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r'\b\d[\d,]*\s*(?:to|through|up\s+to|-|–|—)\s*\d[\d,]*\s*' + _ACTORS + r'\b',
        r'\bbetween\s+\d[\d,]*\s+(?:and|to)\s+\d[\d,]*\s*' + _ACTORS + r'\b',
        r'\b(?:roughly|approximately|approx\.?|about|around|up\s+to|at\s+least|at|with)?\s*\d[\d,]*\s*' + _ACTORS + r'\b',
        r'\b(?:concurrency|parallelism)\s*(?:level\s*)?(?:of|=|:|at)?\s*\d[\d,]*\b',
        r'\b\d+(?:\.\d+)?\s*(?:rps|qps|tps|requests?\s*(?:per|/|a)\s*(?:second|sec|s)\b)',
        r'\b(?:for|over|during|across|lasting|sustained\s+for|hold(?:ing)?\s+for)\s+\d+(?:\.\d+)?\s*(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\b',
        r'\b\d+(?:\.\d+)?(?:\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)|[smh])\b',
        # Objectives, in the orders people write them: percentile first, quantity first,
        # or the "sub-300ms" shorthand. Each is bounded by its number so a workflow clause
        # stated in the same sentence survives the strip.
        r'\b(?:the\s+)?' + _PERCENTILES + r'[^,.;\n]*?' + _QUANTITY_TAIL,
        _QUANTITY_TAIL + r'\s*(?:or\s+(?:better|less|lower|faster)\s*)?(?:(?:at|on|in|for)\s+(?:the\s+)?)?' + _PERCENTILES + r'\b',
        r'\bsub-?\s*' + _QUANTITY_TAIL,
        r'\b(?:nothing|nobody|no\s+requests?|no\s+calls?)\s+(?:slower|worse|longer|higher)\s+than\b[^,.;\n]*?' + _QUANTITY_TAIL,
        # Error budgets, written as a ceiling on failures or a floor under successes.
        r'\b(?:under|below|beneath|less\s+than|fewer\s+than|no\s+more\s+than|not\s+more\s+than|at\s+most|within|<=?)\s*'
        + _PERCENT_TAIL + r'\s*(?:of\s+(?:all\s+)?(?:requests?|calls?|orders?|traffic)\s*)?(?:that\s+|which\s+)?' + _FAILURES + r'\b',
        r'\b' + _PERCENT_TAIL + r'\s*' + _FAILURES + r'\b',
        r'\b' + _FAILURES + r'\b[^,.;\n]{0,28}?' + _PERCENT_TAIL,
        r'\bsuccess(?:\s*rates?)?\b[^,.;\n]{0,28}?' + _PERCENT_TAIL,
        r'\b(?:latency|response\s+times?|duration)\b\s*(?:stays?|remains?|of|is|under|below|<)[^,.;\n]*?' + _QUANTITY_TAIL,
        r'\b(?:keep|keeping|ensure|ensuring|make\s+sure|verify|assert|so\s+that)\b[^,.;\n]*?(?:under|below|less\s+than|<)[^,.;\n]*?' + _QUANTITY_TAIL,
        r'\b(?:baseline|load|stress|soak|spike|breakpoint|smoke|endurance)\s+(?:test|run|workload)\b',
        r'\b(?:start|schedule|begin|kick\s+off)\s+(?:it\s+)?in\s+\d+\s*(?:seconds?|minutes?|hours?)\b',
        r'\b(?:ramp|ramping|scale|scaling)\s+(?:up|down|from|to)\b',
        r'\bthroughput\b',
    )
)

# Step separators. "and" is included: "log in and browse the catalogue" really is
# two steps, and a residual load clause on either side is dropped by scoring.
# A colon, a question mark and a full stop end a clause as surely as "then" does: people
# state the objective, punctuate, and only then describe the workflow.
_SEPARATORS = re.compile(
    r'(?:\bafter\s+that\b|\band\s+then\b|\bthen\b|\bnext\b|\bfollowed\s+by\b|\bfinally\b|\blastly\b|\bafterwards?\b|'
    r'\bbefore\b|\bwhile\b|\bafter\b|\band\b|\bplus\b|[,;.:?!\n\r•·|]|->|=>|→|\d+[.)]\s)',
    re.IGNORECASE,
)

# Particle verbs people write as two words but APIs name as one.
_COMPOUNDS = tuple(
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in (
        (r'\blogs?\s+in\b', 'login'),
        (r'\blogs?\s+out\b', 'logout'),
        (r'\blogged\s+in\b', 'login'),
        (r'\blogging\s+in\b', 'login'),
        (r'\bsigns?\s+in\b', 'signin'),
        (r'\bsigning\s+in\b', 'signin'),
        (r'\bsigned\s+in\b', 'signin'),
        (r'\bsigning\s+up\b', 'signup'),
        (r'\bsigns?\s+up\b', 'signup'),
        (r'\bsigns?\s+out\b', 'signout'),
        (r'\bchecks?\s+out\b', 'checkout'),
        (r'\bchecking\s+out\b', 'checkout'),
        (r'\bchecked\s+out\b', 'checkout'),
        (r'\bcheck-out\b', 'checkout'),
        (r'\bsets?\s+up\b', 'setup'),
        (r'\bhealth\s+check\b', 'healthcheck'),
        (r'\bpicks?\s+up\b', 'pickup'),
        # The same verbs with their object in the middle: nobody writes "sign in a
        # shopper", they write "sign a shopper in".
        (r'\bcheck(?:s|ed|ing)?\s+(?:\w+\s+){1,3}?out\b', 'checkout'),
        (r'\blog(?:s|ged|ging)?\s+(?:\w+\s+){1,3}?in\b', 'login'),
        (r'\bsign(?:s|ed|ing)?\s+(?:\w+\s+){1,3}?in\b', 'signin'),
        (r'\bsign(?:s|ed|ing)?\s+(?:\w+\s+){1,3}?up\b', 'signup'),
    )
)

_METHOD_VERBS: dict[str, frozenset[str]] = {
    'GET': _words('get list browse view read fetch load check show display query see open inspect poll watch look retrieve find search filter'),
    'POST': _words('post create add submit send place start begin login log signin signup sign register enroll upload buy purchase checkout order book pay authenticate authorise authorize issue publish trigger invoke'),
    'PUT': _words('put update replace set change edit modify overwrite save store rename'),
    'PATCH': _words('patch update edit modify adjust amend tweak partially'),
    'DELETE': _words('delete remove cancel clear drop discard purge revoke deactivate'),
}
_ALL_VERBS = frozenset().union(*_METHOD_VERBS.values())


@dataclass
class StepMatch:
    """One resolved step, with the evidence that resolved it."""

    phrase: str
    operation_id: str
    method: str
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    origin: str = 'described'  # or 'dependency': added so an earlier value exists

    def as_dict(self) -> dict:
        return {
            'phrase': self.phrase,
            'operation_id': self.operation_id,
            'method': self.method,
            'path': self.path,
            'confidence': round(min(0.99, 0.35 + self.score / 14), 2),
            'reasons': self.reasons,
            'origin': self.origin,
        }


@dataclass
class SynthesisResult:
    matches: list[StepMatch] = field(default_factory=list)
    journeys: list[UserJourney] | None = None
    unmatched: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def operation_ids(self) -> list[str]:
        return [match.operation_id for match in self.matches]

    def as_dict(self) -> dict:
        return {
            'steps': [match.as_dict() for match in self.matches],
            'unrecognized_phrases': self.unmatched,
            'notes': self.notes,
            'journey_synthesized': self.journeys is not None,
        }


def _split_identifier(value: str) -> list[str]:
    spaced = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', value or '')
    return [token for token in re.split(r'[^A-Za-z0-9]+', spaced) if token]


def _normalize(token: str) -> str:
    lowered = token.lower()
    if len(lowered) > 4 and lowered.endswith('ies'):
        return lowered[:-3] + 'y'
    if len(lowered) > 4 and lowered.endswith(('ches', 'shes', 'sses', 'xes')):
        return lowered[:-2]
    if len(lowered) > 3 and lowered.endswith('s') and not lowered.endswith('ss'):
        return lowered[:-1]
    return lowered


def _token_list(text: str) -> list[str]:
    """Content tokens in written order; order decides which verb leads the phrase."""
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in _split_identifier(text):
        token = _normalize(raw)
        if len(token) < 2 or token in _GRAMMAR or token.isdigit() or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def _tokenize(text: str) -> set[str]:
    return set(_token_list(text))


# Vocabulary bridges: the words people write versus the words APIs are named with.
# A synonym match is discounted so a literal hit always wins.
_SYNONYM_WEIGHT = 0.75
_SYNONYMS: dict[str, tuple[str, ...]] = {
    'account': ('user', 'profile', 'customer'),
    'auth': ('login', 'token', 'session'),
    'authenticate': ('login', 'auth', 'session', 'token'),
    'bag': ('cart', 'basket'),
    'basket': ('cart',),
    'browse': ('list', 'index', 'catalog'),
    'buy': ('checkout', 'order', 'purchase', 'cart'),
    'catalog': ('product', 'item', 'listing'),
    'catalogue': ('product', 'item', 'catalog', 'listing'),
    'credential': ('login', 'auth', 'token'),
    'customer': ('user', 'account', 'profile'),
    'goods': ('product', 'item'),
    'history': ('order', 'list', 'log'),
    'homepage': ('home', 'index', 'root'),
    'inventory': ('product', 'stock', 'item'),
    'invoice': ('order', 'billing', 'payment'),
    'item': ('product', 'sku', 'line'),
    'listing': ('product', 'list'),
    'password': ('login', 'auth', 'credential'),
    'pay': ('payment', 'checkout', 'billing'),
    'payment': ('pay', 'checkout', 'billing'),
    'order': ('checkout', 'purchase'),
    'purchase': ('checkout', 'order', 'payment'),
    'receipt': ('order', 'invoice'),
    'register': ('signup', 'user', 'account'),
    'shopper': ('user', 'customer'),
    'signin': ('login', 'session', 'auth', 'token'),
    'signup': ('register', 'user', 'account'),
    'stock': ('inventory', 'product'),
    'store': ('shop', 'product', 'catalog'),
    'token': ('auth', 'login', 'session'),
    'view': ('get', 'detail', 'show'),
}


def _expand(tokens: list[str]) -> dict[str, float]:
    """Literal tokens at full weight, their synonyms ranked behind them."""
    weighted = {token: 1.0 for token in tokens}
    for token in tokens:
        for synonym in _SYNONYMS.get(token, ()):
            weighted.setdefault(_normalize(synonym), _SYNONYM_WEIGHT)
    return weighted


def _vocabulary(endpoint: Endpoint) -> dict[str, float]:
    """Weighted token bag: an operation's own name identifies it best, then its path."""
    bag: dict[str, float] = {}

    def add(text: str, weight: float) -> None:
        for raw in _split_identifier(text):
            token = _normalize(raw)
            if len(token) < 2 or token in _GRAMMAR or token.isdigit():
                continue
            bag[token] = max(bag.get(token, 0.0), weight)

    add(endpoint.operation_id, 3.0)
    for segment in endpoint.path.split('/'):
        add(segment.replace('{', ' ').replace('}', ' '), 2.4)
    add(endpoint.summary or '', 1.2)
    for tag in endpoint.tags:
        add(tag, 1.6)
    return bag


def _strip_load_clauses(prompt: str) -> str:
    text = normalize_numbers(prompt)
    for pattern, replacement in _COMPOUNDS:
        text = pattern.sub(replacement, text)
    for pattern in _LOAD_CLAUSES:
        text = pattern.sub(' ', text)
    return text


# Words that describe the shape of the load rather than a step of the workflow.
_LOAD_WORDS = _words(
    'load stress soak spike baseline breakpoint smoke endurance capacity test tests testing run runs ramp ramping '
    'hold hammer simulate simulating measure measuring benchmark benchmarking concurrent concurrency user users vu '
    'vus rps qps tps throughput latency duration minute minutes second seconds hour hours error errors rate p50 p90 '
    'p95 p99 percentile threshold thresholds slo slos ms sla peak sustained traffic virtual '
    # Imperatives that introduce an objective. A threshold clause is stripped by the
    # patterns above; the verb that introduced it can survive, and is not a step.
    'keep keeping ensure ensuring verify verifying assert asserting stay stays staying remain remains below above '
    'within under over between around approximately roughly about '
    # The people a load is made of, and the words an objective is made of.
    'shopper shoppers customer customers visitor visitors session sessions client clients tester testers buyer '
    'buyers caller callers browser browsers requester requesters thread threads worker workers connection '
    'connections person people account accounts percent percentage percentile failure failures fail failing '
    'failed success budget objective target response responses time times slower faster worse better exceed '
    'exceeds exceeded exceeding past nothing nobody once simultaneously sub than '
    # Durations a person states as an occasion rather than a number of minutes.
    'overnight night nightly daily hourly weekend'
)

# Words that frame a request without describing a step. Somebody asking to be told whether
# their storefront survives is not asking for an operation called "survive".
_FRAMING_WORDS = _words(
    'tell told me know knows knowing let lets show shows shown report reports reporting find finds found out want '
    'wants wanted wish wondering wonder curious would like need needs needed see seeing saw look looking whether '
    'expect expects expecting hope hopes hoping require requires survive survives survived surviving hold holds '
    'held healthy okay ok fine happen happens happened confirm confirms confirming prove proves proof think thinks '
    'sure question answer answers result results please well cope copes coping handle handles handling behave '
    'behaves behaviour behavior good bad enough really actually maybe possibly still yet'
)

# How a requirement opens when it is framing a question rather than naming a step. The
# match deliberately swallows the framing verb and any knowing verb after it, so what is
# left is the part that would have to name an operation: in "we wanted to find out how
# the shop behaves" nothing is left, while in "I want you to delete the invoices" the
# instruction survives and is reported.
_FRAMING_OPENERS = re.compile(
    r'^(?:so|and|but|also|now)?\s*(?:'
    r'(?:i|we|you|they|it|lets?|let\s+us|somebody|someone)\b[^,;]{0,40}?'
    r'\b(?:want|wants|wanted|need|needs|needed|wonder(?:s|ed|ing)?|like|liked|hope|hoped|'
    r'expect(?:s|ed|ing)?|curious|find\s+out|figure\s+out|work\s+out|know|see|check|learn|understand|tell|measure|prove)'
    r'\b(?:\s+(?:to|us|you|me|if|whether|that|the)\b)*\s*(?:find\s+out|figure\s+out|work\s+out|know|see|check|learn|understand|tell|measure|prove)?'
    r'|(?:does|do|did|is|are|was|were|can|could|will|would|should|shall|has|have|had|any)\b'
    r'|(?:what|how|why|when|where|whether)\b'
    r'|(?:simulate|simulating|imagine|picture|pretend|assume|suppose|consider|evaluate|assess|'
    r'investigate|analyse|analyze|determine)\b'
    r')',
    re.IGNORECASE,
)


def _segments(prompt: str) -> list[str]:
    """Split a requirement into candidate step phrases, longest-first order preserved."""
    cleaned = _strip_load_clauses(prompt)
    parts = [re.sub(r'\s+', ' ', part).strip(' -–—:\t') for part in _SEPARATORS.split(cleaned)]
    return [part for part in parts if len(part) > 1 and re.search(r'[A-Za-z]', part)]


_QUANTITY_TOKEN = re.compile(r'^\d[\d,.]*(?:ms|s|m|h|sec|secs|min|mins|hr|hrs|rps|qps|tps|vu|vus|k)?$', re.IGNORECASE)


def _describes_no_step(phrase: str) -> bool:
    """A remnant of the load specification, or the framing around it, is not a step.

    "spike to" survives once "200 users" is stripped, and "we need to know whether" is how
    a requirement opens; reporting either as a phrase nobody could match would be noise.
    Such a segment is still ranked — a path called /users must stay matchable — it simply
    is not worth complaining about. One content word outside these lists ("update the
    thing") is enough to be reported, because that really is a step nobody could resolve.
    """
    tokens = set(_token_list(phrase))
    if not tokens:
        return False
    if all(token in _LOAD_WORDS or token in _FRAMING_WORDS or _QUANTITY_TOKEN.match(token) for token in tokens):
        return True
    # Prose that opens by framing a question and names no action of its own is the
    # requirement's preamble, not a step: "we need to know whether the storefront survives a
    # busy sale hour" asks for nothing to be called. An imperative overrides this, so "I
    # want you to delete the invoices" is still reported when no operation answers it.
    opener = _FRAMING_OPENERS.match(phrase.strip())
    return bool(opener) and not set(_token_list(phrase.strip()[opener.end():])) & _ALL_VERBS


_STEM_LENGTH = 5


def _related(token: str, other: str) -> bool:
    """Loose morphological kinship: "creation" and "create" share a stem, "check"
    prefixes "checkout". Shorter words must match exactly to avoid noise."""
    if len(token) < 4 or len(other) < 4:
        return False
    if token.startswith(other) or other.startswith(token):
        return True
    return len(token) >= _STEM_LENGTH and len(other) >= _STEM_LENGTH and token[:_STEM_LENGTH] == other[:_STEM_LENGTH]


def _names_operation(token: str, vocabulary: dict[str, float]) -> bool:
    return any(entry.startswith(token) or token.startswith(entry) for entry in vocabulary)


def _method_affinity(tokens: list[str], vocabulary: dict[str, float], method: str) -> tuple[float, str | None]:
    """Read the phrase's verb, ignoring words that are really the operation's own name.

    "list orders" must not read "order" as an imperative, or every write operation
    would outrank the read the sentence actually described.
    """
    candidates = [token for token in tokens if token in _ALL_VERBS and not _names_operation(token, vocabulary)]
    if not candidates:
        return 0.0, None
    verbs = _METHOD_VERBS.get(method.upper(), frozenset())
    matching = [token for token in candidates if token in verbs]
    if matching:
        return 1.5, f'verb "{matching[0]}" implies {method.upper()}'
    return -1.0, None


def _rank(phrase: str, endpoints: list[Endpoint], vocabularies: dict[str, dict[str, float]]) -> list[tuple[float, Endpoint, list[str]]]:
    """Score every operation against one phrase.

    A phrase must lexically touch an operation to score at all, so a stray verb can
    never invent a step the sentence did not ask for.
    """
    literal = _token_list(phrase)
    expanded = _expand(literal)
    lowered = phrase.lower()
    ranked: list[tuple[float, Endpoint, list[str]]] = []
    for endpoint in endpoints:
        vocabulary = vocabularies[endpoint.operation_id]
        overlap: dict[str, float] = {}
        for token, weight in vocabulary.items():
            factor = expanded.get(token)
            if factor is not None:
                overlap[token] = weight * factor
                continue
            if len(token) < 4:
                continue
            # "check" should still reach "checkout"; "creation" should reach "create".
            near = [
                other_factor * 0.6
                for other, other_factor in expanded.items()
                if _related(token, other)
            ]
            if near:
                overlap[token] = weight * max(near)
        reasons: list[str] = []
        score = sum(overlap.values())
        verbatim = False
        if re.search(r'\b' + re.escape(endpoint.operation_id.lower()) + r'\b', lowered):
            score += 6.0
            verbatim = True
            reasons.append(f'names {endpoint.operation_id} verbatim')
        elif len(endpoint.path) > 3 and endpoint.path.lower().rstrip('/') in lowered:
            score += 5.0
            verbatim = True
            reasons.append(f'names {endpoint.path} verbatim')
        if not overlap and not verbatim:
            continue
        if overlap:
            ordered = sorted(overlap, key=lambda token: -overlap[token])[:4]
            reasons.insert(0, 'matched ' + ', '.join(f'"{token}"' for token in ordered))
        affinity, reason = _method_affinity(literal, vocabulary, endpoint.method)
        score += affinity
        if reason:
            reasons.append(reason)
        # Prefer the operation whose whole name the phrase covers over a partial brush.
        score -= 0.15 * max(0, len(vocabulary) - len(overlap)) / max(len(vocabulary), 1)
        if score > 0:
            ranked.append((score, endpoint, reasons))
    ranked.sort(key=lambda item: (-item[0], len(item[1].path), item[1].operation_id))
    return ranked


def _dependency_closure(order: list[str], application: ApplicationModel) -> tuple[list[str], set[str]]:
    """Insert producers the described steps silently depend on, keeping described order."""
    known = {endpoint.operation_id for endpoint in application.endpoints}
    resolved = list(order)
    inserted: set[str] = set()
    for _ in range(len(known) + 1):
        added = False
        for position, operation_id in enumerate(list(resolved)):
            producers = [
                dependency.producer_operation_id
                for dependency in application.dependencies
                if dependency.consumer_operation_id == operation_id
                and dependency.producer_operation_id in known
                and dependency.producer_operation_id != operation_id
            ]
            for producer in dict.fromkeys(producers):
                if producer in resolved[:position]:
                    continue
                if producer in resolved:
                    resolved.remove(producer)
                    resolved.insert(resolved.index(operation_id), producer)
                else:
                    resolved.insert(position, producer)
                    inserted.add(producer)
                added = True
                break
            if added:
                break
        if not added:
            break
    return resolved, inserted


def _variable(producer_operation_id: str, input_name: str) -> str:
    raw = f'{producer_operation_id}_{input_name}'
    sanitized = re.sub(r'[^A-Za-z0-9_]+', '_', raw).strip('_')
    if not sanitized or not sanitized[0].isalpha():
        sanitized = f'v_{sanitized}'
    return sanitized[:60]


def _pointer(output_expression: str) -> str | None:
    pointer = output_expression.removeprefix('$response.body#')
    return pointer if pointer.startswith('/') else None


def _wire(order: list[str], application: ApplicationModel) -> list[JourneyStep]:
    """Build self-wired steps: producers extract, consumers reference ${variables}."""
    endpoints = {endpoint.operation_id: endpoint for endpoint in application.endpoints}
    positions = {operation_id: index for index, operation_id in enumerate(order)}
    steps: list[JourneyStep] = []
    available: set[str] = set()
    for index, operation_id in enumerate(order):
        endpoint = endpoints[operation_id]
        path_parameters = set(re.findall(r'\{([^}]+)\}', endpoint.path))
        body_properties = set((endpoint.request_schema or {}).get('properties', {}))
        inputs: dict[str, object] = {}
        headers: dict[str, str] = {}
        body_overrides: dict[str, object] = {}
        extract: dict[str, str] = {}

        for dependency in application.dependencies:
            pointer = _pointer(dependency.output_expression)
            if pointer is None:
                continue
            variable = _variable(dependency.producer_operation_id, dependency.input_name)
            if dependency.producer_operation_id == operation_id:
                consumers = [
                    positions.get(other.consumer_operation_id, -1)
                    for other in application.dependencies
                    if other.producer_operation_id == operation_id and other.input_name == dependency.input_name
                ]
                if any(position > index for position in consumers):
                    extract[variable] = pointer
                continue
            if dependency.consumer_operation_id != operation_id or variable not in available:
                continue
            if dependency.input_name.lower() == 'authorization':
                headers['Authorization'] = 'Bearer ' + _ref(variable)
            elif dependency.input_name in path_parameters:
                inputs[dependency.input_name] = _ref(variable)
            elif dependency.input_name in body_properties:
                body_overrides[dependency.input_name] = _ref(variable)
            else:
                inputs[dependency.input_name] = _ref(variable)

        body: object | None = None
        if body_overrides:
            example = endpoint.examples[0] if endpoint.examples and isinstance(endpoint.examples[0], dict) else {}
            body = {**example, **body_overrides}
        steps.append(
            JourneyStep(
                operation_id=operation_id,
                inputs=inputs,
                headers=headers,
                body=body,
                extract=extract,
                think_time_seconds=0.3 if index < len(order) - 1 else 0.5,
            )
        )
        available.update(extract)
    return steps


_MATCH_THRESHOLD = 2.0
_MAX_DESCRIBED_STEPS = 12
_MAX_TOTAL_STEPS = 20


def _journey_name(order: list[str]) -> str:
    head = ' -> '.join(order[:4])
    return (head + (' -> ...' if len(order) > 4 else '')) or 'scenario'


def synthesize_scenario(prompt: str, application: ApplicationModel) -> SynthesisResult:
    """Map free-text requirements onto a runnable, dependency-complete journey."""
    result = SynthesisResult()
    endpoints = list(application.endpoints)
    if not endpoints:
        result.notes.append('No operations were discovered, so the scenario has nothing to map onto.')
        return result

    vocabularies = {endpoint.operation_id: _vocabulary(endpoint) for endpoint in endpoints}
    described: list[StepMatch] = []
    seen: set[str] = set()
    for phrase in _segments(prompt):
        ranked = _rank(phrase, endpoints, vocabularies)
        if not ranked or ranked[0][0] < _MATCH_THRESHOLD:
            if _tokenize(phrase) and not _describes_no_step(phrase) and len(result.unmatched) < 6:
                result.unmatched.append(phrase)
            continue
        score, endpoint, reasons = ranked[0]
        if endpoint.operation_id in seen:
            continue
        if len(described) >= _MAX_DESCRIBED_STEPS:
            result.notes.append(f'Only the first {_MAX_DESCRIBED_STEPS} described steps were used.')
            break
        seen.add(endpoint.operation_id)
        described.append(
            StepMatch(
                phrase=phrase,
                operation_id=endpoint.operation_id,
                method=endpoint.method,
                path=endpoint.path,
                score=score,
                reasons=reasons,
            )
        )

    if not described:
        result.notes.append('No phrase named a discovered operation, so every readable operation is exercised instead.')
        return result

    order, inserted = _dependency_closure([match.operation_id for match in described], application)
    order = order[:_MAX_TOTAL_STEPS]
    by_id = {match.operation_id: match for match in described}
    endpoints_by_id = {endpoint.operation_id: endpoint for endpoint in endpoints}
    for operation_id in order:
        if operation_id in by_id:
            result.matches.append(by_id[operation_id])
            continue
        endpoint = endpoints_by_id[operation_id]
        result.matches.append(
            StepMatch(
                phrase='implied prerequisite',
                operation_id=operation_id,
                method=endpoint.method,
                path=endpoint.path,
                score=4.0,
                reasons=['inserted so a later step receives the value it depends on'],
                origin='dependency',
            )
        )
    if inserted:
        result.notes.append('Added ' + ', '.join(sorted(inserted)) + ' so dependent steps receive real values.')

    unbound = [
        operation_id
        for operation_id in order
        if endpoints_by_id[operation_id].auth_schemes
        and not any(
            dependency.consumer_operation_id == operation_id and dependency.input_name.lower() == 'authorization'
            for dependency in application.dependencies
        )
    ]
    if unbound:
        result.notes.append('These operations require credentials: ' + ', '.join(sorted(set(unbound))) + '.')

    try:
        steps = _wire(order, application)
        result.journeys = validate_journeys([UserJourney(name=_journey_name(order), steps=steps).model_dump(mode='json')], application)
    except Exception as exc:  # noqa: BLE001 - fall back to endpoint selection rather than failing the run
        result.journeys = None
        result.notes.append(f'Sequenced the operations without an explicit journey ({exc}).')
    return result
