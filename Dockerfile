FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

# 1. Dependencies first: this layer is cached until requirements.txt changes.
#    Runtime packages only (no pytest/ruff).
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2. Application code only (no secrets: the API key is supplied at runtime).
COPY app/ app/
COPY streamlit_app.py .

# 3. Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8080

# Listen on Cloud Run's $PORT; `exec` lets Streamlit receive stop signals for a clean shutdown.
# No HEALTHCHECK: Cloud Run uses its own probes (Streamlit serves /_stcore/health).
CMD ["sh", "-c", "exec streamlit run streamlit_app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
