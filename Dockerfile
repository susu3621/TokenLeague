FROM python:3.12-slim

WORKDIR /app

COPY service/requirements.txt /app/service/requirements.txt
RUN pip install --no-cache-dir -r /app/service/requirements.txt

COPY service/ /app/service/
COPY scripts/ /app/scripts/
COPY docs/ /app/docs/
COPY README.md README_EN.md /app/

ENV PYTHONPATH="/app/service"
EXPOSE 5006

CMD ["bash", "-lc", "python3 /app/scripts/run_migrations.py && python3 /app/service/app.py"]
