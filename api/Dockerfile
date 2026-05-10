FROM python:slim-trixie

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

COPY wait-for-db.sh /wait-for-db.sh
RUN sed -i 's/\r//' /wait-for-db.sh && chmod +x /wait-for-db.sh

ENV FLASK_APP=initAlchemy.py

EXPOSE 5000

CMD ["/wait-for-db.sh"]