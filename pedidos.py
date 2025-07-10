import os
import traceback
import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# 1. Configuración general
st.set_page_config(layout="wide")
st.title("📋 Captura de Pedido")

# 2. Conexión a base de datos con SQLAlchemy
cfg = st.secrets["postgres"]
engine = create_engine(f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['database']}")

# 3. Funciones de consulta
@st.cache_data(ttl=60)
def get_tables():
    try:
        with engine.connect() as conn:
            return pd.read_sql("SELECT id, nombre FROM mesas ORDER BY id", conn)
    except:
        st.error("❌ Error al cargar mesas")
        st.error(traceback.format_exc())
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_products():
    try:
        with engine.connect() as conn:
            return pd.read_sql("""
                SELECT id, nombre, precio_unitario, categoria
                FROM productos
                WHERE precio_unitario IS NOT NULL
                ORDER BY categoria, nombre
            """, conn)
    except:
        st.error("❌ Error al cargar productos")
        st.error(traceback.format_exc())
        return pd.DataFrame()

@st.cache_data(ttl=30)
def get_open_orders():
    try:
        with engine.connect() as conn:
            return pd.read_sql("""
                SELECT o.id, o.mesa_id, o.personas, m.nombre AS mesa
                FROM ordenes o
                JOIN mesas m ON m.id = o.mesa_id
                WHERE o.estado = 'abierto'
                ORDER BY o.id;
            """, conn)
    except:
        st.error("❌ Error al consultar órdenes abiertas")
        st.error(traceback.format_exc())
        return pd.DataFrame()

@st.cache_data(ttl=30)
def get_order_items(orden_id):
    try:
        with engine.connect() as conn:
            return pd.read_sql("""
                SELECT p.nombre AS producto, oi.cantidad, oi.precio_unitario, oi.subtotal
                FROM orden_items oi
                JOIN productos p ON p.id = oi.producto_id
                WHERE oi.orden_id = %s
                ORDER BY p.nombre;
            """, conn, params=(orden_id,))
    except:
        st.error("❌ Error al consultar productos de la orden")
        st.error(traceback.format_exc())
        return pd.DataFrame()

# 4. Lógica principal
def get_or_create_order(mesa_id, personas):
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT id, personas FROM ordenes WHERE mesa_id = :mesa_id AND estado = 'abierto';"),
                {"mesa_id": mesa_id}
            ).fetchone()

            if result:
                oid, current_personas = result
                if current_personas != personas:
                    conn.execute(
                        text("UPDATE ordenes SET personas = :p WHERE id = :id;"),
                        {"p": personas, "id": oid}
                    )
                return oid

            result = conn.execute(
                text("INSERT INTO ordenes (mesa_id, personas, estado) VALUES (:mesa_id, :personas, 'abierto') RETURNING id;"),
                {"mesa_id": mesa_id, "personas": personas}
            )
            return result.scalar()
    except:
        st.error("❌ Error al obtener o crear orden")
        st.error(traceback.format_exc())
        return None

def add_item(orden_id, producto_id, cantidad, precio):
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO orden_items (orden_id, producto_id, cantidad, precio_unitario)
                    VALUES (:orden_id, :producto_id, :cantidad, :precio)
                """),
                {
                    "orden_id": orden_id,
                    "producto_id": producto_id,
                    "cantidad": cantidad,
                    "precio": precio
                }
            )
    except:
        st.error("❌ Error al agregar producto")
        st.error(traceback.format_exc())

def finalize_order(orden_id):
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE ordenes SET estado = 'pagado', cerrado_at = :now WHERE id = :id"),
                {"now": datetime.now(), "id": orden_id}
            )
    except:
        st.error("❌ Error al finalizar orden")
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

# 5. Sidebar: órdenes abiertas
st.sidebar.header("🛒 Mesas Abiertas")
open_orders = get_open_orders()
if open_orders.empty:
    st.sidebar.info("No hay mesas abiertas")
else:
    for ord_row in open_orders.itertuples():
        with st.sidebar.expander(f"{ord_row.mesa} ({ord_row.personas} pers)"):
            df_it = get_order_items(ord_row.id)
            if df_it.empty:
                st.write("Sin productos aún")
            else:
                st.table(df_it[["producto", "cantidad", "subtotal"]])
                st.write("Total: $", df_it["subtotal"].sum())

# 6. Área principal
mesas_df = get_tables()
if mesas_df.empty:
    st.error("No hay mesas definidas.")
    st.stop()

mesa_sel = st.selectbox("🪑 Elige mesa", mesas_df["nombre"])
mesa_id = int(mesas_df.loc[mesas_df["nombre"] == mesa_sel, "id"].iloc[0])
personas = st.number_input("👥 Cantidad de personas", min_value=1, max_value=20, value=1)

orden_id = get_or_create_order(mesa_id, personas)
if orden_id is None:
    st.stop()

st.markdown(f"**🧾 Orden activa:** `{orden_id}`")

# Productos
productos_df = get_products()
categorias = productos_df["categoria"].dropna().unique().tolist()
categoria = st.selectbox("🍽️ Categoría", categorias)
filtro_df = productos_df[productos_df["categoria"] == categoria]
sel_prod = st.selectbox("📦 Producto", filtro_df["nombre"])
prod_row = filtro_df[filtro_df["nombre"] == sel_prod].iloc[0]
cant = st.number_input("🔢 Cantidad", min_value=1, value=1, key="cant")

# Botón para añadir producto
if st.button("➕ Añadir al pedido"):
    add_item(
        int(orden_id),
        int(prod_row["id"]),
        int(cant),
        float(prod_row["precio_unitario"])
    )
    st.success(f"{cant} x {sel_prod} agregado.")

# Mostrar detalle
st.subheader("🧾 Detalle de la orden")
items = get_order_items(orden_id)
if items.empty:
    st.info("No hay productos agregados aún.")
else:
    st.dataframe(items[["producto", "cantidad", "precio_unitario", "subtotal"]], use_container_width=True)
    total = items["subtotal"].sum()
    st.metric("💰 Total a pagar", f"$ {total:.2f}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💳 Finalizar mesa"):
            finalize_order(orden_id)
            st.success("Orden finalizada. ✅")
    with col2:
        if st.button("🖨️ Imprimir ticket"):
            pdf_bytes = generar_ticket_pdf(mesa_sel, personas, orden_id, items, total)
            st.download_button(
                "⬇️ Descargar PDF",
                data=pdf_bytes,
                file_name=f"ticket_{orden_id}.pdf",
                mime="application/pdf"
            )
