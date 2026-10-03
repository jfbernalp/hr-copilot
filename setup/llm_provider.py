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
import google.genai as genai

DEFAULT_MODEL = "gemini-3.6-flash"


def get_model_name() -> str:
    return os.getenv("LLM_MODEL", DEFAULT_MODEL)


class GeminiProvider:
    """Envuelve la llamada a Gemini. Un proveedor futuro (otro modelo u otro
    vendor, para comparar en el arnés de evaluación) implementa la misma
    interfaz: generate(text) -> (texto, tokens_in, tokens_out)."""

    def __init__(self, api_key: str, model_name: str | None = None):
        self._client = genai.Client(api_key=api_key)
        self.model_name = model_name or get_model_name()

    def generate(self, text: str):
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
