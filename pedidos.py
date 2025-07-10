import os
import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
from fpdf import FPDF

os.environ["PGCLIENTENCODING"] = "latin1"
st.set_page_config(layout="wide")
st.title("📋 Captura de Pedido")

# 1. Leer credenciales
cfg      = st.secrets["postgres"]
host     = cfg["host"]
port     = cfg["port"]
database = cfg["database"]
user     = cfg["user"]
password = cfg["password"]

# 2. Conectar DB
@st.cache_resource
def conectar_db():
    return psycopg2.connect(
        host=host, port=port,
        dbname=database, user=user, password=password
    )
conn = conectar_db()

# 3. Funciones de lectura
@st.cache_data(ttl=60)
def get_tables():
    return pd.read_sql("SELECT id, nombre FROM mesas ORDER BY id", conn)

@st.cache_data(ttl=60)
def get_products():
    return pd.read_sql(
        "SELECT id, nombre, precio_unitario FROM productos ORDER BY nombre",
        conn
    )

def get_open_orders():
    sql = """
      SELECT o.id, o.mesa_id, o.personas, m.nombre AS mesa
      FROM ordenes o
      JOIN mesas m ON m.id=o.mesa_id
      WHERE estado='abierto';
    """
    return pd.read_sql(sql, conn)

@st.cache_data(ttl=30)
def get_order_items(orden_id):
    sql = """
      SELECT p.nombre                 AS producto,
             oi.cantidad,
             oi.precio_unitario,
             (oi.cantidad * oi.precio_unitario) AS subtotal
      FROM orden_items oi
      JOIN productos p ON p.id=oi.producto_id
      WHERE oi.orden_id=%s;
    """
    return pd.read_sql(sql, conn, params=(orden_id,))

# 4. Funciones de negocio
def get_or_create_order(mesa_id, personas):
    df = pd.read_sql(
      "SELECT id, personas FROM ordenes WHERE mesa_id=%s AND estado='abierto'",
      conn, params=(mesa_id,)
    )
    if not df.empty:
        oid, existing = df.loc[0, ["id","personas"]]
        # si cambió el número de personas, actualiza
        if existing != personas:
            cur = conn.cursor()
            cur.execute(
              "UPDATE ordenes SET personas=%s WHERE id=%s",
              (personas, oid)
            )
            conn.commit()
        return oid
    # crear nueva orden
    cur = conn.cursor()
    cur.execute(
      "INSERT INTO ordenes (mesa_id, personas, estado) VALUES (%s,%s,'abierto') RETURNING id;",
      (mesa_id, personas)
    )
    oid = cur.fetchone()[0]
    conn.commit()
    return oid

def add_item(orden_id, producto_id, cantidad, precio):
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO orden_items
        (orden_id, producto_id, cantidad, precio_unitario)
      VALUES (%s,%s,%s,%s);
    """, (orden_id, producto_id, cantidad, precio))
    conn.commit()

def finalize_order(orden_id):
    now = datetime.now()
    cur = conn.cursor()
    cur.execute("""
      UPDATE ordenes SET estado='pagado', cerrado_at=%s WHERE id=%s;
    """, (now, orden_id))
    conn.commit()

def generar_ticket_pdf(mesa, personas, oid, items, total):
    pdf = FPDF(margin=10)
    pdf.add_page(); pdf.set_font("Courier", size=11)
    pdf.cell(0,6, "====== BAR XYZ ======", ln=True, align="C")
    pdf.cell(0,6, f"Mesa: {mesa}  Personas: {personas}", ln=True)
    pdf.cell(0,6, f"Orden: {oid}   Fecha: {datetime.now():%Y-%m-%d %H:%M}", ln=True)
    pdf.cell(0,6, "-"*40, ln=True)
    for r in items.itertuples():
        line = f"{r.cantidad:>2} x {r.producto:<20} $ {r.subtotal:>6.2f}"
        pdf.cell(0,6, line, ln=True)
    pdf.cell(0,6, "-"*40, ln=True)
    pdf.cell(0,6, f"TOTAL: $ {total:.2f}", ln=True, align="R")
    return pdf.output(dest="S").encode("latin1")

# 5. Barra lateral: carrito de mesas abiertas
st.sidebar.header("🛒 Mesas Abiertas")
open_orders = get_open_orders()
if open_orders.empty:
    st.sidebar.info("No hay mesas abiertas")
else:
    for row in open_orders.itertuples():
        with st.sidebar.expander(f"{row.mesa} ({row.personas} pers)"):
            df_items = get_order_items(row.id)
            if df_items.empty:
                st.write("Sin consumos aún")
            else:
                st.table(df_items[["producto","cantidad","subtotal"]])
                st.write("Total: $", df_items["subtotal"].sum())

# 6. Área principal: tomar pedido
tables = get_tables()
mesa_sel = st.selectbox("Elige mesa", tables["nombre"])
mesa_id  = tables.loc[tables["nombre"]==mesa_sel, "id"].iloc[0]
personas = st.number_input("Cantidad de personas", min_value=1, max_value=20, value=1)

# crea/recupera orden
orden_id = get_or_create_order(mesa_id, personas)
st.markdown(f"**Orden activa:** {orden_id}")

# agregar producto
prods   = get_products()
sel     = st.selectbox("Producto", prods["nombre"])
row     = prods.loc[prods["nombre"]==sel].iloc[0]
cant    = st.number_input("Cantidad", min_value=1, value=1, key="cant")
if st.button("➕ Añadir al pedido"):
    add_item(orden_id, int(row.id), int(cant), float(row.precio_unitario))
    st.success(f"{cant} x {sel} agregado.")

# detalle de la orden en principal
st.subheader("Detalle de tu orden")
items = get_order_items(orden_id)
if items.empty:
    st.info("Aún no agregaste nada.")
else:
    st.dataframe(items[["producto","cantidad","precio_unitario","subtotal"]], use_container_width=True)
    tot = items["subtotal"].sum()
    st.metric("Total a pagar", f"$ {tot:.2f}")

    if st.button("💳 Finalizar y generar ticket PDF"):
        buf = generar_ticket_pdf(mesa_sel, personas, orden_id, items, tot)
        st.download_button("🖨️ Descargar ticket (.pdf)", data=buf,
                           file_name=f"ticket_{orden_id}.pdf", mime="application/pdf")
        st.balloons()
