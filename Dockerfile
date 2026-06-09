# rebuild v2
FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GOOGLE_API_KEY=""
ENV PYTHONPATH=/app

EXPOSE 7860

CMD ["uvicorn", "back_end.main:app", "--host", "0.0.0.0", "--port", "7860"]