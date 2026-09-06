from __future__ import annotations

import re
from datetime import timedelta

from .models import PerformanceTestIntent, ScheduleSpec, SLOs, TestType, utcnow

# Requirements arrive as prose, not as form fields. Every pattern here exists because a
# sentence a tester would actually say used to fall through to a default: "12 shoppers at
# once" compiled to one virtual user, and "fewer than 2% failures" left no error budget at
# all, which is worse than refusing the sentence — the run looks like it passed.

_ONES = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
         'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
         'seventeen': 17, 'eighteen': 18, 'nineteen': 19}
_TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
_COMPOUND_WORD = re.compile(rf"\b({'|'.join(_TENS)})[\s-]({'|'.join(_ONES)})\b", re.IGNORECASE)
_SINGLE_WORD = re.compile(rf"\b({'|'.join([*_TENS, *_ONES])})\b", re.IGNORECASE)
_SCALE = re.compile(r'\b(\d[\d,]*(?:\.\d+)?)\s*(hundred|thousand|k|dozen)\b', re.IGNORECASE)
_FRACTIONS = (
    (re.compile(r'\bhalf\s+an?\s+hour\b', re.IGNORECASE), '30 minutes'),
    (re.compile(r'\bhalf\s+a\s+minute\b', re.IGNORECASE), '30 seconds'),
    (re.compile(r'\ban?\s+quarter\s+of\s+an\s+hour\b', re.IGNORECASE), '15 minutes'),
    (re.compile(r'\bquarter\s+of\s+an\s+hour\b', re.IGNORECASE), '15 minutes'),
    (re.compile(r'\ba\s+couple\s+of\b', re.IGNORECASE), '2'),
    (re.compile(r'\ban?\s+dozen\b', re.IGNORECASE), '12'),
    (re.compile(r'\ba\s+few\b', re.IGNORECASE), '3'),
    (re.compile(r'\ban?\s+(?=(?:second|minute|hour|hundred|thousand)s?\b)', re.IGNORECASE), '1 '),
)


# Written numbers arrive in parts: "two hundred fifty" scales to "200 50" and has to be
# added back up. Only a round left side absorbs its neighbour, so "between 50 and 300" and
# "2 hours 30 minutes" are left as the two numbers they are.
_ADDITIVE = re.compile(r'\b(\d{2,})\s+(?:and\s+)?(\d{1,3})\b')


def _fold(match: re.Match[str]) -> str:
    left, right = int(match.group(1)), int(match.group(2))
    absorbs = left > right and left % 10 ** len(match.group(2)) == 0
    return str(left + right) if absorbs else match.group(0)
# Phrases that name a duration without naming a number. Read literally, so a workload that
# outruns the configured ceiling is refused by name rather than quietly shrunk to seconds.
_IMPLIED_DURATION = (
    (re.compile(r"\bovernight\b|\ball\s+night\b", re.IGNORECASE), 8 * 3600, "overnight read as 8 hours"),
    (re.compile(r"\ball\s+day\b|\bfull\s+(?:work(?:ing)?\s+)?day\b", re.IGNORECASE), 8 * 3600, "all day read as 8 hours"),
    (re.compile(r"\ba\s+(?:busy|peak)\s+(?:sale\s+)?hour\b", re.IGNORECASE), 3600, "a busy hour read as 60 minutes"),
)


def normalize_numbers(text: str) -> str:
    """Rewrite written numbers as digits so one set of numeric patterns covers both.

    Only the article in front of a unit becomes "1" ("an hour"), never the article in
    front of an ordinary noun, so "a cart" is left alone.
    """
    for pattern, replacement in _FRACTIONS:
        text = pattern.sub(replacement, text)
    text = _COMPOUND_WORD.sub(lambda m: str(_TENS[m.group(1).lower()] + _ONES[m.group(2).lower()]), text)
    text = _SINGLE_WORD.sub(lambda m: str(_TENS.get(m.group(1).lower()) or _ONES[m.group(1).lower()]), text)
    text = _SCALE.sub(
        lambda m: str(int(float(m.group(1).replace(',', '')) * {'hundred': 100, 'dozen': 12}.get(m.group(2).lower(), 1000))),
        text,
    )
    for _ in range(3):
        folded = _ADDITIVE.sub(_fold, text)
        if folded == text:
            break
        text = folded
    return text


# Who the load is made of. APIs are tested by "users", but requirements are written about
# shoppers, customers, visitors and sessions, and the count belongs to the noun.
_ACTOR = (r'(?:concurrent|simultaneous|parallel|virtual|active|live|paying|test)?\s*'
          r'(?:users?|vus?|shoppers?|customers?|visitors?|sessions?|clients?|people|persons?|buyers?|'
          r'callers?|testers?|browsers?|requesters?|agents?|connections?|threads?|workers?|accounts?)')
# Comparators. "keep p95 under 400 ms", "p95 <= 400ms", "response time at most 400 ms",
# "sub-400ms" and "p95 of 400 ms" are one requirement written five ways. A breach verb names
# the same number from the other side: "until p95 exceeds 400 ms" is still a 400 ms budget.
_LIMIT = (r"(?:\s*(?:stays?|stay|remains?|remain|is|sits?|of|at|=|:|<=?|≤|>=?|≥|under|below|beneath|within|"
          r"less\s+than|lower\s+than|no\s+(?:more|higher|greater)\s+than|not\s+more\s+than|at\s+most|"
          r"max(?:imum)?(?:\s+of)?|cap(?:ped)?(?:\s+at)?|sub-?|faster\s+than|better\s+than|"
          r"exceed(?:s|ed|ing)?|go(?:es|ing)?\s+(?:above|over|beyond|past)|ris(?:es|en|ing)?\s+(?:above|over)|"
          r"climb(?:s|ed|ing)?\s+(?:above|over|past)|cross(?:es|ed|ing)?|breach(?:es|ed|ing)?|"
          r"blow(?:s|n)?\s+(?:past|through)|pass(?:es|ed)?|top(?:s|ped)?|hits?|reach(?:es|ed)?|"
          r"above|over|beyond|past|worse\s+than|slower\s+than|greater\s+than|higher\s+than|more\s+than)\s*)+")
_AMOUNT = r'(\d[\d,]*(?:\.\d+)?)\s*(ms|millis(?:econds?)?|secs?|seconds?|s)?\b(?!\s*%)'
_PERCENT = r'(\d+(?:\.\d+)?)\s*(?:%|percent(?:age)?)'
_PERCENTILE = r'(?:p\s*\(?\s*95\s*\)?|95(?:th)?\s*(?:-|\s)?percentile|ninety[\s-]?fifth\s+percentile)'
_ERRORS = (r'(?:errors?|error\s*rates?|failures?|failure\s*rates?|fail(?:ing|ed|s)?(?:\s+requests?)?|'
           r'5xx(?:\s+responses?)?|500s)')
# The gap between a subject and its limit is short and must not cross into another
# objective: "keep p95 healthy and errors under 2%" is not a 2 ms latency budget.
_GAP = r'(?:(?!error|failure|fail|success|throughput|rps)[^,.;])'

_DURATION = re.compile(r'(?P<value>\d+(?:\.\d+)?)\s*-?\s*(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\b', re.IGNORECASE)
_DURATION_ANCHOR = re.compile(r'\b(?:for|over|during|across|lasting|last|sustained\s+for|holding\s+for|hold\s+for)\s+', re.IGNORECASE)
_VUS = re.compile(rf'(\d[\d,]*)\s*{_ACTOR}\b', re.IGNORECASE)
_VUS_ALT = re.compile(r'\b(?:concurrency|parallelism)\s*(?:level\s*)?(?:of|=|:|at)?\s*(\d[\d,]*)\b', re.IGNORECASE)
_RANGE = re.compile(rf'(\d[\d,]*)\s*(?:to|through|up\s+to|-|–|—|→)\s*(\d[\d,]*)\s*{_ACTOR}\b', re.IGNORECASE)
_RANGE_BETWEEN = re.compile(rf'between\s+(\d[\d,]*)\s*(?:and|to)\s*(\d[\d,]*)\s*{_ACTOR}\b', re.IGNORECASE)
_RPS = re.compile(r'(\d+(?:\.\d+)?)\s*(?:rps|qps|tps|req(?:uest)?s?\s*(?:per|/|a|each)\s*(?:second|sec|s)\b|req(?:uest)?s?/s\b)', re.IGNORECASE)
_P95 = re.compile(_PERCENTILE + _GAP + r'{0,40}?' + _LIMIT + _AMOUNT, re.IGNORECASE)
# "1200 ms at the 95th percentile" states the same budget with the percentile trailing.
_P95_TRAILING = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(ms|millis(?:econds?)?|secs?|seconds?|s)?\s*(?:or\s+(?:better|less|lower|faster)\s*)?'
                           r'(?:(?:at|on|in|for)\s+(?:the\s+)?)?' + _PERCENTILE, re.IGNORECASE)
_LATENCY = re.compile(r'(?:response\s+times?|responses?|latency|duration|round\s*trip)' + _GAP + r'{0,30}?' + _LIMIT + _AMOUNT, re.IGNORECASE)
_ERROR = re.compile(_ERRORS + _GAP + r'{0,30}?' + _LIMIT + _PERCENT, re.IGNORECASE)
_ERROR_LEADING = re.compile(r'(?:under|below|beneath|less\s+than|fewer\s+than|no\s+more\s+than|not\s+more\s+than|at\s+most|within|<=?|≤|max(?:imum)?(?:\s+of)?)\s*'
                            + _PERCENT + r'\s*(?:of\s+(?:all\s+)?(?:requests?|calls?|orders?|traffic)\s*)?(?:that\s+|which\s+)?' + _ERRORS, re.IGNORECASE)
_ERROR_BARE = re.compile(_PERCENT + r'\s*' + _ERRORS, re.IGNORECASE)
_SUCCESS = re.compile(r'success(?:\s*rate)?' + _GAP + r'{0,20}?(?:above|over|at\s+least|no\s+less\s+than|>=?|≥|of)\s*' + _PERCENT, re.IGNORECASE)


# Test-type vocabulary, most specific first. The order is the precedence: a soak that also
# says "stress" is still a soak, and only a "until <something gives>" clause — not the bare
# word "until" — asks for a breakpoint.
_TYPE_RULES: tuple[tuple[TestType, tuple[str, ...]], ...] = (
    (TestType.SOAK, (r'\bsoak\b', r'\bendurance\b', r'gradual\s+degradation', r'(?:resource|memory|connection|handle)\s+leak',
                     r'over\s+(?:an?\s+)?(?:long|extended)\s+(?:period|time|run)', r'\bfor\s+\d+(?:\.\d+)?\s*(?:hours?|hrs?)\b',
                     r'\bovernight\b', r'sustained\s+(?:for|over)\b')),
    (TestType.BREAKPOINT, (r'\bbreak(?:ing)?[\s-]?point\b', r'maximum\s+load', r'\bmax(?:imum)?\s+(?:capacity|throughput|concurrency)\b',
                           r'how\s+(?:far|much|many|high)\b', r'find\s+(?:the\s+)?(?:limit|ceiling|maximum|breaking|edge)',
                           r'\buntil\b[^.]{0,40}?(?:exceed|break|fail|saturat|degrad|collaps|error|p95|limit|slow|tip|refus)',
                           r'capacity\s+(?:limit|ceiling|edge)', r'\bpush\s+(?:it\s+)?(?:until|past|beyond)\b',
                           r'where\s+it\s+(?:breaks|falls|gives)')),
    (TestType.STRESS, (r'\bstress\b', r'beyond\s+(?:normal|expected|peak)', r'\boverload\b', r'\bhammer\b', r'\bsaturat')),
    (TestType.SPIKE, (r'\bspike\b', r'\bbursts?\b', r'sudden\s+(?:surge|jump|increase|influx|rush)', r'flash\s+sale', r'\bsurge\b')),
    (TestType.BASELINE, (r'\bbaseline\b', r'current\s+build', r'\bsmoke\b', r'\bsanity\b', r'as[\s-]is\s+performance')),
)
_TYPE_MATCHERS = tuple((kind, tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)) for kind, patterns in _TYPE_RULES)

# Endpoint families, named the way the API is likely to name them. Object-tolerant particle
# verbs are deliberate: people write "sign a shopper in", not "sign in".
_ENDPOINT_TERMS: tuple[tuple[str, str], ...] = (
    ('checkout', r'\bcheckout\b|\bcheck(?:s|ed|ing)?[\s-]?out\b|\bcheck\s+(?:\w+\s+){1,3}?out\b|\bplace\s+(?:the\s+|an?\s+)?order\b'),
    ('payments', r'\bpay(?:ment|ments|ing)?\b|\bbilling\b|\bcharge\b'),
    ('login', r'\blogin\b|\blog(?:s|ged|ging)?[\s-]?in\b|\bsign(?:s|ed|ing)?[\s-]?in\b|\bsign\s+(?:\w+\s+){1,3}?in\b|\bauthenticat|\bcredential'),
    ('products', r'\bproducts?\b|\bcatalog(?:ue)?\b|\bbrowse\b|\blisting\b|\bsearch\b|\bitems?\b'),
    ('cart', r'\bcart\b|\bbasket\b|\bbag\b'),
    ('orders', r'\borders?\b|\breceipts?\b|\binvoices?\b|\bpurchase\s+history\b'),
    ('profile', r'\bprofile\b|\baccounts?\b'),
    ('register', r'\bregist(?:er|ration)\b|\bsign(?:s|ing)?[\s-]?up\b'),
)
_ENDPOINT_MATCHERS = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _ENDPOINT_TERMS)


class DeterministicIntentCompiler:
    """Safe local compiler and validator; an LLM adapter may enrich its structured result."""

    def compile(self, prompt: str, *, environment: str = "local") -> PerformanceTestIntent:
        text = " ".join(prompt.strip().split())
        numeric = normalize_numbers(text)
        lowered = numeric.lower()
        inferred: dict[str, object] = {}
        ambiguities: list[str] = []

        test_type = TestType.LOAD
        for candidate, matchers in _TYPE_MATCHERS:
            if any(matcher.search(lowered) for matcher in matchers):
                test_type = candidate
                break
        else:
            inferred["test_type"] = "no test shape was named; read as a steady load test"

        duration = self._duration(numeric)
        if duration is None:
            for pattern, seconds, reading in _IMPLIED_DURATION:
                if pattern.search(lowered):
                    duration, inferred["duration_seconds"] = seconds, reading
                    break
            else:
                duration = 30
                inferred["duration_seconds"] = "no duration was stated; held for 30 seconds"

        concurrency, maximum, stated = self._load(numeric)
        if concurrency is None:
            concurrency = 1
            inferred["target_concurrency"] = "no concurrency was stated; a single virtual user"

        rps_match = _RPS.search(numeric)
        target_rps = float(rps_match.group(1)) if rps_match else None
        latency, assumed_percentile = self._latency(numeric)
        if assumed_percentile:
            inferred["latency_percentile"] = "p95 assumed from an unqualified response-time limit"
        error_rate = self._error_rate(numeric)
        if latency is None:
            ambiguities.append("No p95 latency SLO was provided")
        if error_rate is None:
            ambiguities.append("No error-rate SLO was provided")

        endpoints = [name for name, matcher in _ENDPOINT_MATCHERS if matcher.search(lowered)]

        schedule = None
        delay = re.search(r'(?:start|schedule|run|begin|kick\s+off)\s+(?:it\s+)?in\s+(\d+)\s*(seconds?|minutes?|hours?)', lowered)
        if delay:
            unit = delay.group(2)
            scale = 3600 if unit.startswith('hour') else 60 if unit.startswith('minute') else 1
            schedule = ScheduleSpec(run_at=utcnow() + timedelta(seconds=int(delay.group(1)) * scale))
        elif "tomorrow" in lowered or "midnight" in lowered or re.search(r'\bat\s+\d{1,2}:\d{2}', lowered):
            schedule = ScheduleSpec(recurrence="natural-language schedule requires provider resolution")
            ambiguities.append("Schedule needs timezone-aware resolution")

        known = 5 - len(ambiguities)
        confidence = max(0.45, min(0.98, 0.72 + known * 0.04 - len(inferred) * 0.03))
        return PerformanceTestIntent(
            raw_prompt=text,
            test_type=test_type,
            target_environment=environment,
            target_endpoints=endpoints,
            expected_traffic=f"approximately {concurrency} concurrent users" if stated else None,
            target_concurrency=concurrency,
            max_concurrency=maximum,
            target_rps=target_rps,
            duration_seconds=duration,
            slos=SLOs(latency_p95_ms=latency, error_rate=error_rate),
            schedule=schedule,
            inferred_values=inferred,
            ambiguities=ambiguities,
            confidence=confidence,
        )

    @staticmethod
    def _duration(text: str) -> int | None:
        """How long the workload runs, never how long until it starts.

        "Start in 30 seconds. Run it for 5 minutes." carries two durations, and only the
        one introduced by a holding word belongs to the test.
        """
        for anchor in _DURATION_ANCHOR.finditer(text):
            seconds = _seconds(_DURATION.search(text[anchor.end():]))
            if seconds:
                return seconds
        # Unanchored fallback. "response time at most 1.5 seconds" carries a number and a
        # unit, but it is a budget, not a runtime: a duration read out of an objective would
        # silently turn a load test into a one-second one.
        budgets = [match.span() for pattern in (_P95, _P95_TRAILING, _LATENCY) for match in pattern.finditer(text)]
        for match in _DURATION.finditer(text):
            start, end = match.span()
            if any(start < budget_end and budget_start < end for budget_start, budget_end in budgets):
                continue
            return _seconds(match)
        return None

    @staticmethod
    def _load(text: str) -> tuple[int | None, int | None, bool]:
        """Peak concurrency, an optional ceiling for ramps, and whether either was stated."""
        span = _RANGE.search(text) or _RANGE_BETWEEN.search(text)
        if span:
            low, high = (int(value.replace(',', '')) for value in span.groups()[:2])
            if low > 0 and high > 0:
                return min(low, high), max(low, high), True
        match = _VUS.search(text) or _VUS_ALT.search(text)
        if match:
            stated = int(match.group(1).replace(',', ''))
            if stated > 0:
                return stated, None, True
        return None, None, False

    @staticmethod
    def _latency(text: str) -> tuple[float | None, bool]:
        """A p95 budget, and whether the percentile had to be assumed."""
        match = _P95.search(text) or _P95_TRAILING.search(text)
        assumed = False
        if not match:
            match = _LATENCY.search(text)
            assumed = bool(match)
        if not match:
            return None, False
        value = float(match.group(1).replace(',', ''))
        if not (match.group(2) or 'ms').lower().startswith('m'):
            value *= 1000
        return (value, assumed) if value > 0 else (None, False)

    @staticmethod
    def _error_rate(text: str) -> float | None:
        """An error budget written as a ceiling on failures or a floor under successes."""
        for pattern in (_ERROR, _ERROR_LEADING, _ERROR_BARE):
            match = pattern.search(text)
            if match:
                return min(1.0, float(match.group(1)) / 100)
        match = _SUCCESS.search(text)
        if match:
            return min(1.0, max(0.0, 100 - float(match.group(1))) / 100)
        return None


def _seconds(match: re.Match[str] | None) -> int | None:
    if not match:
        return None
    unit = match.group("unit").lower()
    scale = 3600 if unit.startswith(("hour", "hr", "h")) else 60 if unit.startswith(("minute", "min", "m")) else 1
    return int(float(match.group("value")) * scale) or None


class StructuredLLMIntentCompiler:
    """Provider-neutral boundary. Callers supply a function returning schema-compatible JSON."""

    def __init__(self, structured_generate):
        self.structured_generate = structured_generate

    def compile(self, prompt: str, *, environment: str = "local") -> PerformanceTestIntent:
        data = self.structured_generate(prompt, PerformanceTestIntent.model_json_schema())
        data.setdefault("raw_prompt", prompt)
        data.setdefault("target_environment", environment)
        return PerformanceTestIntent.model_validate(data)
