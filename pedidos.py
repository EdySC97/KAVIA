import streamlit as st
import psycopg2
import pandas as pd
import os

os.environ["PGCLIENTENCODING"] = "latin1"

st.title("Captura de Pedido")

# Credenciales desde .streamlit/secrets.toml
host = st.secrets["postgres"]["host"]
port = st.secrets["postgres"]["port"]
database = st.secrets["postgres"]["database"]
user = st.secrets["postgres"]["user"]
password = st.secrets["postgres"]["password"]
pool_mode = st.secrets["postgres"].get("pool_mode", "session")  # opcional

# Conexión a la base de datos
def conectar_db():
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
        )
        return conn
    except Exception as e:
        st.error(f"Error al conectar con la base de datos: {e}")
        return None


conn = conectar_db()
if conn is None:
    st.stop()
cur = conn.cursor()
