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
