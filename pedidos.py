import os
import traceback
import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# 1) Configuración general
os.environ["PGCLIENTENCODING"] = "latin1"
st.set_page_config(layout="wide")
st.title("📋 Captura de Pedido")

# 2) Leer credenciales
cfg = st.secrets["postgres"]
host, port, database = cfg["host"], cfg["port"], cfg["database"]
user, password = cfg["user"], cfg["password"]

# 3) Conexión a la base de datos
@st.cache_resource
def conectar_db():
    return psycopg2.connect(
        host=host, port=port,
        dbname=database, user=user, password=password
    )
conn = conectar_db()

# 4) Consultas cacheadas
@st.cache_data(ttl=60)
def get_tables():
    try:
        conn.rollback()
        return pd.read_sql("SELECT id, nombre FROM mesas ORDER BY id", conn)
    except Exception:
        st.error("Error al obtener mesas")
        st.error(traceback.format_exc())
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_products():
    try:
        conn.rollback()
        return pd.read_sql("""
            SELECT id, nombre, precio_unitario, categoria 
            FROM productos 
            WHERE precio_unitario IS NOT NULL 
            ORDER BY categoria, nombre
        """, conn)
    except Exception:
        st.error("Error al obtener productos")
        st.error(traceback.format_exc())
        return pd.DataFrame()

@st.cache_data(ttl=30)
def get_open_orders():
    try:
        conn.rollback()
        return pd.read_sql("""
            SELECT o.id, o.mesa_id, o.personas, m.nombre AS mesa
            FROM ordenes o
            JOIN mesas m ON m.id = o.mesa_id
            WHERE o.estado = 'abierto'
            ORDER BY o.id;
        """, conn)
    except Exception:
        st.error("Error al consultar mesas abiertas")
        st.error(traceback.format_exc())
        return pd.DataFrame()

@st.cache_data(ttl=30)
def get_order_items(orden_id):
    try:
        conn.rollback()
        return pd.read_sql("""
            SELECT 
                p.nombre AS producto,
                oi.cantidad,
                oi.precio_unitario,
                oi.subtotal
            FROM orden_items oi
            JOIN productos p ON p.id = oi.producto_id
            WHERE oi.orden_id = %s
            ORDER BY p.nombre;
        """, conn, params=(orden_id,))
    except Exception:
        st.error("Error al consultar items de la orden")
        st.error(traceback.format_exc())
        return pd.DataFrame()

# 5) Lógica de negocio
def get_or_create_order(mesa_id, personas):
    try:
        conn.rollback()
        df = pd.read_sql("""
            SELECT id, personas 
            FROM ordenes 
            WHERE mesa_id = %s AND estado = 'abierto';
        """, conn, params=(mesa_id,))
    except Exception:
        st.error("Error al obtener orden activa")
        st.error(traceback.format_exc())
        return None

    try:
        if not df.empty:
            oid, existing = df.loc[0, ["id", "personas"]]
            if existing != personas:
                with conn.cursor() as cur:
                    cur.execute("UPDATE ordenes SET personas = %s WHERE id = %s;", (personas, oid))
                conn.commit()
            return oid

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ordenes (mesa_id, personas, estado) 
                VALUES (%s, %s, 'abierto') RETURNING id;
            """, (mesa_id, personas))
            oid = cur.fetchone()[0]
        conn.commit()
        return oid
    except Exception:
        conn.rollback()
        st.error("Error al crear nueva orden")
        st.error(traceback.format_exc())
        return None

def add_item(orden_id, producto_id, cantidad, precio):
    try:
        if None in (orden_id, producto_id, cantidad, precio):
            raise ValueError("Uno de los valores del producto es None.")

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO orden_items (orden_id, producto_id, cantidad, precio_unitario)
                VALUES (%s, %s, %s, %s);
            """, (orden_id, producto_id, cantidad, precio))
        conn.commit()
    except Exception:
        conn.rollback()
        st.error("Error al agregar producto")
        st.error(traceback.format_exc())

def finalize_order(orden_id):
    try:
        now = datetime.now()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ordenes
                SET estado = 'pagado', cerrado_at = %s
                WHERE id = %s;
            """, (now, orden_id))
        conn.commit()
    except Exception:
        conn.rollback()
        st.error("Error al finalizar orden")
        st.error(traceback.format_exc())

def generar_ticket_pdf(mesa, personas, orden_id, items, total):
    pdf = FPDF(format="P", unit="mm", margin=10)
    pdf.add_page()
    pdf.set_font("Courier", size=11)
    pdf.cell(0, 6, "====== BAR XYZ ======", ln=True, align="C")
    pdf.cell(0, 6, f"Mesa: {mesa}   Personas: {personas}", ln=True)
    pdf.cell(0, 6, f"Orden: {orden_id}   Fecha: {datetime.now():%Y-%m-%d %H:%M}", ln=True)
    pdf.cell(0, 6, "-"*40, ln=True)
    for r in items.itertuples():
        pdf.cell(0, 6, f"{r.cantidad:>2} x {r.producto:<20} $ {r.subtotal:>6.2f}", ln=True)
    pdf.cell(0, 6, "-"*40, ln=True)
    pdf.cell(0, 6, f"TOTAL: $ {total:.2f}", ln=True, align="R")
    return pdf.output(dest="S").encode("latin1")

# 6) Sidebar
st.sidebar.header("🛒 Mesas Abiertas")
open_orders = get_open_orders()
if open_orders.empty:
    st.sidebar.info("No hay mesas abiertas")
else:
    for ord_row in open_orders.itertuples():
        with st.sidebar.expander(f"{ord_row.mesa} ({ord_row.personas} pers)"):
            df_it = get_order_items(ord_row.id)
            if df_it.empty:
                st.write("Sin consumos aún")
            else:
                st.table(df_it[["producto", "cantidad", "subtotal"]])
                st.write("Total: $", df_it["subtotal"].sum())

# 7) Captura de pedido
mesas_df = get_tables()
if mesas_df.empty:
    st.error("No hay mesas definidas.")
    st.stop()

mesa_sel = st.selectbox("Elige mesa", mesas_df["nombre"])
mesa_id = int(mesas_df.loc[mesas_df["nombre"] == mesa_sel, "id"].iloc[0])
personas = st.number_input("Cantidad de personas", min_value=1, max_value=20, value=1)

orden_id = get_or_create_order(mesa_id, personas)
if orden_id is None:
    st.error("No se pudo obtener o crear una orden. Verifica la conexión o base de datos.")
    st.stop()

st.markdown(f"**Orden activa:** {orden_id}")

productos_df = get_products()
categorias = productos_df["categoria"].dropna().unique().tolist()

if not categorias:
    st.warning("No hay categorías registradas en productos.")
    st.stop()

categoria = st.selectbox("Categoría", categorias)
filtro_df = productos_df[productos_df["categoria"] == categoria]

if filtro_df.empty:
    st.warning("No hay productos en esta categoría.")
    st.stop()

sel_prod = st.selectbox("Producto", filtro_df["nombre"])

if sel_prod not in filtro_df["nombre"].values:
    st.warning("Producto no válido.")
    st.stop()

prod_row = filtro_df[filtro_df["nombre"] == sel_prod].iloc[0]
cant = st.number_input("Cantidad", min_value=1, value=1, key="cant")

if st.button("➕ Añadir al pedido"):
    try:
        add_item(
            orden_id,
            int(prod_row["id"]),
            int(cant),
            float(prod_row["precio_unitario"])
        )
        st.success(f"{cant} x {sel_prod} agregado.")
    except Exception as e:
        st.error("No se pudo añadir el producto.")
        st.error(str(e))

st.subheader("Detalle de la orden")
items = get_order_items(orden_id)
if items.empty:
    st.info("No hay productos agregados aún.")
else:
    st.dataframe(items[["producto", "cantidad", "precio_unitario", "subtotal"]], use_container_width=True)
    total = items["subtotal"].sum()
    st.metric("Total a pagar", f"$ {total:.2f}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💳 Finalizar mesa"):
            finalize_order(orden_id)
            st.success("Mesa finalizada. ¡Gracias!")
    with col2:
        if st.button("🖨️ Imprimir ticket"):
            pdf_bytes = generar_ticket_pdf(mesa_sel, personas, orden_id, items, total)
            st.download_button(
                "⬇️ Descargar PDF",
                data=pdf_bytes,
                file_name=f"ticket_{orden_id}.pdf",
                mime="application/pdf"
            )
