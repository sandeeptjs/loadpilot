from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='LOADPILOT_', env_file='.env', extra='ignore')
    db: str = 'artifacts/loadpilot.db'
    generated_dir: str = 'artifacts/generated-tests'
    k6_bin: str = 'k6'
    embedded_worker: bool = True
    max_vus: int = Field(default=100, ge=1, le=2000)
    max_duration_seconds: int = Field(default=7200, ge=5, le=86400)
    max_rps: int = Field(default=100, ge=1)
    allowed_hosts: str = 'localhost,127.0.0.1,::1,sandbox-target'
    sandbox_url: str = 'http://127.0.0.1:8080'
    sandbox_control_token: str = ''
    allow_sandbox_remediation: bool = False
    llm_base_url: str = 'https://api.openai.com/v1'
    llm_model: str = ''
    llm_api_key: str = ''
    llm_timeout: int = Field(default=45, ge=1, le=120)
    llm_json_mode: bool = True
    llm_max_tokens: int = Field(default=2500, ge=256, le=8000)

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
