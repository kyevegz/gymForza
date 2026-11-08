import os
os.environ["LC_MESSAGES"] = "C"

import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv("DB_URL"))
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM clientes;")
print("Conectado. Clientes:", cur.fetchone()[0])
conn.close()