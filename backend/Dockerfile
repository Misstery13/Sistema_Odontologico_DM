FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m app
USER app
EXPOSE 8000
# los datos demo (usuarios con clave conocida) nunca se cargan en producción
CMD ["sh", "-c", "python manage.py migrate --noinput && if [ \"$DJANGO_ENV\" != production ]; then python manage.py seed; fi && exec gunicorn config.wsgi -b 0.0.0.0:8000 -w ${GUNICORN_WORKERS:-3} -k gthread --threads ${GUNICORN_THREADS:-4} --access-logfile -"]
