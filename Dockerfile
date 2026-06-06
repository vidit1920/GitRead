FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.12.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GOOGLE_API_KEY=""

EXPOSE 7860

CMD ["uvicorn", "back_end.main:app", "--host", "0.0.0.0", "--port", "7860"]