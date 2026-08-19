FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8501

# server.addressはコンテナ内では0.0.0.0にする必要がある
# （ホスト側の公開範囲は `docker run -p 127.0.0.1:8501:8501` 側で127.0.0.1に絞る）
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
