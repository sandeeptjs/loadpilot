from functools import lru_cache
from os import environ
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Google exposes Gemini behind an OpenAI-shaped surface, so one bounded JSON client
# serves both providers. Nothing here changes what the model is allowed to do.
GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/openai'
OPENAI_BASE_URL = 'https://api.openai.com/v1'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='LOADPILOT_', env_file='.env', extra='ignore')
    api_token: str = ''
    db: str = 'artifacts/loadpilot.db'
    generated_dir: str = 'artifacts/generated-tests'
    k6_bin: str = 'k6'
    embedded_worker: bool = True
    max_vus: int = Field(default=100, ge=1, le=2000)
    max_duration_seconds: int = Field(default=7200, ge=5, le=86400)
    max_artifact_bytes: int = Field(default=250_000_000, ge=1_000_000)
    max_rps: int = Field(default=100, ge=1)
    allowed_hosts: str = 'localhost,127.0.0.1,::1,sandbox-target'
    sandbox_url: str = 'http://127.0.0.1:8080'
    sandbox_control_token: str = ''
    allow_sandbox_remediation: bool = False
    llm_base_url: str = ''
    llm_model: str = ''
    llm_api_key: str = ''
    llm_timeout: int = Field(default=45, ge=1, le=120)
    llm_json_mode: bool = True
    llm_max_tokens: int = Field(default=2500, ge=256, le=8000)
    llm_retries: int = Field(default=2, ge=0, le=5)

    @model_validator(mode='after')
    def resolve_provider(self):
        """Name a model and the provider is settled; the key may come from the ambient
        Google or OpenAI variable so no secret has to be duplicated into this project."""
        if self.llm_model and not self.llm_api_key:
            names = ('GEMINI_API_KEY', 'GOOGLE_API_KEY') if self.is_gemini else ('OPENAI_API_KEY',)
            self.llm_api_key = next((environ[name] for name in names if environ.get(name)), '')
        if not self.llm_base_url:
            self.llm_base_url = GEMINI_BASE_URL if self.is_gemini else OPENAI_BASE_URL
        return self

    @property
    def is_gemini(self):
        return self.llm_model.lower().startswith(('gemini', 'models/gemini', 'learnlm'))

    @property
    def ai_enabled(self):
        return bool(self.llm_model and self.llm_api_key)

    def check_target(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Target must be an HTTP(S) URL without embedded credentials')
        if parsed.query or parsed.fragment:
            raise ValueError('Target base URL must not contain query parameters or fragments')
        allowed = {host.strip().lower() for host in self.allowed_hosts.split(',') if host.strip()}
        if parsed.hostname.lower() not in allowed:
            raise ValueError(f'Target host {parsed.hostname!r} is not in LOADPILOT_ALLOWED_HOSTS')
        return url.rstrip('/')


@lru_cache
def get_settings():
    return Settings()
