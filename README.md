# HR Copilot — Práxedes S.A.S. 🚀

**HR Copilot** es una innovadora plataforma de Inteligencia Artificial Generativa diseñada para transformar la manera en que los líderes de Recursos Humanos interactúan con la información de su equipo de trabajo.

A través de un motor avanzado de **Text-to-SQL**, los usuarios pueden hacer preguntas complejas sobre los datos del talento humano utilizando lenguaje natural (ej. *"¿Cuál es la rotación de personal en el equipo de ventas este año?"*), y el sistema se encargará de consultar la base de datos, extraer la información y renderizar gráficos interactivos automáticamente.

## 🌟 Características Principales

* **📊 Interfaz Conversacional (Dash/Plotly):** Una experiencia de usuario moderna y profesional construida en Python, adaptada estrictamente al manual de marca de la compañía. Cuenta con retroalimentación visual, glassmorphism y métricas rápidas (KPIs).
* **🧠 Motor RAG con Vanna AI & Gemini:** Utiliza la arquitectura Retrieval-Augmented Generation (RAG) mediante ChromaDB para enseñar a la IA el esquema de la base de datos (DDL). Posteriormente, el modelo Gemini (LLM) traduce el lenguaje natural en consultas SQL con alta precisión y determina cómo graficar los resultados.
* **🛡️ Gobernanza y Seguridad (RLS):** Implementa un poderoso interceptor de seguridad que evalúa cada consulta SQL antes de ejecutarla. Controla dinámicamente qué puede ver cada usuario mediante *Row-Level Security* (filtrando departamentos permitidos) y *Column-Level Security* (bloqueando métricas sensibles como los salarios según el nivel de acceso).
* **☁️ Listo para Producción:** Preparado para despliegue en entornos PaaS como Render o Railway mediante Gunicorn.

## 🛠️ Tecnologías Utilizadas

* **Backend:** Python, Flask, Dash
* **Inteligencia Artificial:** Google Gemini, Vanna AI
* **Base de Datos:** SQLite (Estructurada), ChromaDB (Vectorial)
* **Visualización:** Plotly
* **Despliegue:** Gunicorn, Procfile

## 🚀 Instalación y Uso Local

1. Clona este repositorio:
   ```bash
   git clone https://github.com/TU_USUARIO/hr-copilot.git
   cd hr-copilot
   ```

2. Crea y activa un entorno virtual:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # En macOS/Linux
   ```

3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

4. Configura tu variable de entorno:
   Crea un archivo `.env` en la raíz del proyecto y agrega tu API Key de Gemini:
   ```env
   GEMINI_API_KEY=tu_api_key_aqui
   ```

5. Ejecuta la aplicación:
   ```bash
   python app/dashboard_praxedes_v2.py
   ```
   La aplicación se abrirá en `http://127.0.0.1:8051`

---
*Desarrollado para la transformación digital en la analítica de Recursos Humanos.*

## 🚦 Cómo correr el laboratorio

```bash
source .venv/bin/activate
python setup/build_database.py        # 1. BD base IBM (si no existe)
python setup/build_synthetic_data.py  # 2. Tablas sintéticas (asistencia, nómina, vacantes...)
python setup/seed_users.py            # 3. Usuarios demo
python app/dashboard.py               # 4. → http://127.0.0.1:8051
```

Variables en `.env`: `GEMINI_API_KEY` (obligatoria), `SECRET_KEY` (sesiones; se genera
una en el primer setup), `USE_CHROMA=1` (opcional: RAG con ChromaDB local, requiere
correr antes `python setup/train_vanna.py`).

## 👤 Usuarios demo (solo laboratorio)

| Usuario | Contraseña | Rol | Alcance |
|---|---|---|---|
| `admin` | `Praxedes2026!` | hr_admin | Todo + página de métricas |
| `sales.manager` | `Sales2026!` | sales_manager | Solo departamento Sales |
| `rd.manager` | `RD2026!` | rd_manager | Solo departamento R&D |
| `viewer` | `Viewer2026!` | employee_viewer | Sin cifras salariales |

5 intentos fallidos bloquean la cuenta por 5 minutos. La sesión vive en el servidor
(cookie firmada con `SECRET_KEY`); "Salir →" la destruye.

## 🧪 Tests

```bash
python tests/ai_regression.py   # 14 preguntas canónicas: SQL + tipo de gráfico + paleta
```

## ☁️ Deploy en Render (Free Tier)

El dashboard corre en **modo RAG estático**: todo el corpus de entrenamiento viaja en el
prompt de cada consulta (~8.5K tokens ≈ $0.0006/consulta con Gemini Flash). **ChromaDB no
se instala ni se carga en el servidor** — eso eliminó el OOM del plan gratuito (el
dashboard usa ~170 MB de los 512 MB disponibles). El entrenamiento vectorial es opcional
y solo local (`pip install chromadb && python setup/train_vanna.py` + `USE_CHROMA=1`).

Pasos:
1. Push del repo (la BD `data/hr_analytics.db` con datos sintéticos y usuarios va incluida).
2. En Render: Web Service → Python, build `pip install -r requirements.txt`,
   start command tomado del `Procfile`.
3. Variables de entorno: `GEMINI_API_KEY` y `SECRET_KEY` (obligatorias).
4. Nota: el filesystem de Render Free es efímero — `usage_metrics`, el caché de consultas
   y la auditoría RLS se reinician con cada deploy (aceptable para el laboratorio).
