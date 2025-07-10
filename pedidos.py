import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

# 1. Inicializar conexión (se cachea para no recrearla en cada rerun)
@st.experimental_singleton
def init_connection():
    creds = st.secrets["postgres"]
    return psycopg2.connect(
        host=creds["host"],
        port=creds["port"],
        dbname=creds["database"],
        user=creds["user"],
        password=creds["password"],
        cursor_factory=RealDictCursor
    )

conn = init_connection()

# 2. Obtener órdenes abiertas
@st.experimental_memo(ttl=60)
def get_open_orders():
    query = "SELECT id FROM ordenes WHERE estado = 'abierto';"
    return pd.read_sql(query, conn)

orders_df = get_open_orders()
if orders_df.empty:
    st.warning("No hay órdenes abiertas.")
    st.stop()

order_id = st.selectbox("Elige una orden abierta", orders_df["id"])

# 3. Traer ítems de la orden seleccionada
@st.experimental_memo(ttl=30)
def get_order_items(ord_id):
    sql = """
      SELECT
        p.nombre       AS producto,
        oi.cantidad,
        oi.precio_unit AS precio_unitario,
        oi.subtotal
      FROM orden_items oi
      JOIN productos p ON p.id = oi.producto_id
      WHERE oi.orden_id = %s;
    """
    return pd.read_sql(sql, conn, params=(ord_id,))

items_df = get_order_items(order_id)

# 4. Mostrar detalle y total
st.subheader(f"Detalle de la orden {order_id}")
st.dataframe(items_df)

total = items_df["subtotal"].sum()
st.metric("Total a pagar", f"$ {total:.2f}")
