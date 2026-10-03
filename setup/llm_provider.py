"""
llm_provider.py
----------------
Punto único de configuración del modelo LLM del copiloto. Antes "gemini-3.6-flash"
estaba escrito a mano en 4 lugares (HRCopilot y _StaticCopilot en dashboard.py,
HRCopilot y entrenar() en train_vanna_postgres.py) — cambiar de modelo, o comparar
modelos en el arnés de evaluación, significaba editar código en cada uno.

Ahora: una sola variable de entorno (LLM_MODEL) y una sola clase que hace la
llamada real a Gemini. HRCopilot y _StaticCopilot ya no duplican esa llamada.
"""
import os
import time
import google.genai as genai
from google.genai import errors as genai_errors

DEFAULT_MODEL = "gemini-3.6-flash"

# 2026-10-03: el proyecto está en Nivel 1 (prepago) confirmado en AI Studio, pero
# gemini-3.6-flash es un modelo nuevo (lanzado jul-2026) y se han visto bloqueos
# intermitentes que se sienten como límite de free tier. Reintenta con backoff
# ante 429/RESOURCE_EXHAUSTED y deja rastro en stdout (docker logs) con el detalle
# real de Google — la próxima vez que ocurra, queda documentado qué cuota fue.
MAX_RETRIES  = 3
BASE_DELAY_S = 2.0


def get_model_name() -> str:
    return os.getenv("LLM_MODEL", DEFAULT_MODEL)


def _is_rate_limit(err: "genai_errors.APIError") -> bool:
    status = (getattr(err, "status", "") or "").upper()
    return getattr(err, "code", None) == 429 or status == "RESOURCE_EXHAUSTED"


class GeminiProvider:
    """Envuelve la llamada a Gemini. Un proveedor futuro (otro modelo u otro
    vendor, para comparar en el arnés de evaluación) implementa la misma
    interfaz: generate(text) -> (texto, tokens_in, tokens_out)."""

    def __init__(self, api_key: str, model_name: str | None = None):
        self._client = genai.Client(api_key=api_key)
        self.model_name = model_name or get_model_name()

    def generate(self, text: str):
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=text,
                    config=genai.types.GenerateContentConfig(
                        thinking_config=genai.types.ThinkingConfig(thinking_budget=0)
                    ),
                )
                tokens_in = tokens_out = 0
                try:
                    tokens_in  = response.usage_metadata.prompt_token_count
                    tokens_out = response.usage_metadata.candidates_token_count
                except Exception:
                    pass
                return response.text, tokens_in, tokens_out
            except genai_errors.APIError as e:
                rate_limited = _is_rate_limit(e)
                kind = "RATE_LIMIT" if rate_limited else "API_ERROR"
                print(f"[llm_provider] {kind} intento {attempt}/{MAX_RETRIES + 1} "
                      f"modelo={self.model_name} code={getattr(e, 'code', '?')} "
                      f"status={getattr(e, 'status', '?')} msg={getattr(e, 'message', str(e))[:300]}")
                if rate_limited and attempt <= MAX_RETRIES:
                    time.sleep(BASE_DELAY_S * (2 ** (attempt - 1)))
                    continue
                raise
