import os
import uuid
import traceback
from datetime import datetime

import streamlit as st
import pandas as pd
from fpdf import FPDF
from sqlalchemy import create_engine, text

# 1) Configuración
os.environ["PGCLIENTENCODING"] = "latin1"
st.set_page_config(layout="wide")
st.title("📋 Captura de Pedido")

# 2) Credenciales
cfg = st.secrets["postgres"]
engine = create_engine(
    f"postgresql+psycopg2://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['database']}"
)

# 3) Funciones cacheadas
@st.cache_data(ttl=60)
def get_tables():
    try:
        with engine.connect() as conn:
            return pd.read_sql("SELECT id, nombre FROM mesas ORDER BY id", conn)
    except:
        st.error("❌ Error al obtener mesas")
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
        st.error("❌ Error al obtener productos")
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
                ORDER BY o.id
            """, conn)
    except:
        st.error("❌ Error al consultar órdenes abiertas")
        st.error(traceback.format_exc())
        return pd.DataFrame()

@st.cache_data(ttl=30)
def get_order_items(orden_id):
    try:
        orden_uuid = uuid.UUID(str(orden_id))
        with engine.connect() as conn:
            return pd.read_sql("""
                SELECT 
                    p.nombre AS producto,
                    oi.cantidad,
                    oi.precio_unitario,
                    oi.subtotal
                FROM orden_items oi
                JOIN productos p ON p.id = oi.producto_id
                WHERE oi.orden_id = %s
                ORDER BY p.nombre
            """, conn, params=(orden_uuid,))
    except:
        st.error("❌ Error al obtener items de la orden")
        st.error(traceback.format_exc())
        return pd.DataFrame()

# 4) Lógica principal
def get_or_create_order(mesa_id, personas):
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT id, personas FROM ordenes WHERE mesa_id = :mesa_id AND estado = 'abierto'"),
                {"mesa_id": mesa_id}
            ).fetchone()

            if result:
                oid, actual_personas = result
                if actual_personas != personas:
                    conn.execute(
                        text("UPDATE ordenes SET personas = :p WHERE id = :id"),
                        {"p": personas, "id": oid}
                    )
                return str(oid)

            result = conn.execute(
                text("INSERT INTO ordenes (mesa_id, personas, estado) VALUES (:mesa_id, :personas, 'abierto') RETURNING id"),
                {"mesa_id": mesa_id, "personas": personas}
            )
            return str(result.scalar())
    except:
        st.error("❌ Error en get_or_create_order")
        st.error(traceback.format_exc())
        return None

def add_item(orden_id, producto_id, cantidad, precio):
    try:
        orden_uuid = uuid.UUID(str(orden_id))
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO orden_items (orden_id, producto_id, cantidad, precio_unitario)
                    VALUES (:orden_id, :producto_id, :cantidad, :precio)
                """),
                {
                    "orden_id": orden_uuid,
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
        orden_uuid = uuid.UUID(str(orden_id))
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE ordenes SET estado = 'pagado', cerrado_at = :fecha WHERE id = :id"),
                {"fecha": datetime.now(), "id": orden_uuid}
            )
    except:
        st.error("❌ Error al finalizar orden")
        st.error(traceback.format_exc())


from datetime import datetime

def generar_ticket_pdf(mesa, personas, orden_id, items, total):
    # Tamaño de ticket: 58 mm de ancho x 297 mm de alto (puede ser más corto, pero 297 mm es estándar máximo)
    pdf = FPDF(orientation="P", unit="mm", format=(58, 297))
    pdf.add_page()

    # Fuente más pequeña para que quepa todo
    pdf.set_font("Courier", size=7)

    # Encabezado
    
    pdf.cell(0, 5, "====== BAR KAVIA ======", ln=True, align="C")
    pdf.cell(0, 5, f"Mesa: {mesa}   Pers: {personas}", ln=True)
    pdf.cell(0, 5, f"Orden: {str(orden_id)[:8]}",ln=True)
    pdf.cell(0, 5, f"Fecha: {datetime.now():%Y-%m-%d %H:%M}", ln=True)
    pdf.cell(0, 5, "-" * 38, ln=True)

    # Detalle de productos
    for r in items.itertuples():
        nombre = str(r.producto)[:22]  # Limita el largo del nombre para que no se corte
        linea = f"{r.cantidad} x {nombre}  ${r.subtotal:.2f}"
        pdf.multi_cell(0, 5, linea, align="L")

    pdf.cell(0, 5, "-" * 38, ln=True)
    pdf.set_font("Courier", size=8, style="B")
    pdf.cell(0, 6, f"TOTAL: ${total:.2f}", ln=True, align="R")
    pdf.ln(5)

    # Mensaje final
    pdf.set_font("Courier", size=6)
    pdf.cell(0, 5, "Gracias por su visita.", ln=True, align="C")
    pdf.cell(0, 5, "Ticket generado por Bar Kavia", ln=True, align="C")

    return pdf.output(dest="S").encode("latin1")



# 5) Sidebar de mesas abiertas
st.sidebar.header("🛒 Mesas Abiertas")
open_orders = get_open_orders()
if open_orders.empty:
    st.sidebar.info("No hay mesas abiertas")
else:
    for row in open_orders.itertuples():
        with st.sidebar.expander(f"{row.mesa} ({row.personas} pers)"):
            df_items = get_order_items(row.id)
            if df_items.empty:
                st.write("Sin productos aún")
            else:
                st.table(df_items[["producto", "cantidad", "subtotal"]])
                st.write("Total: $", df_items["subtotal"].sum())

# 6) Área principal
mesas_df = get_tables()
if mesas_df.empty:
    st.error("❌ No hay mesas definidas.")
    st.stop()

mesa_sel = st.selectbox("🍽️ Elige mesa", mesas_df["nombre"])
mesa_id = int(mesas_df[mesas_df["nombre"] == mesa_sel]["id"].iloc[0])
personas = st.number_input("👥 Cantidad de personas", min_value=1, max_value=20, value=1)

orden_id = get_or_create_order(mesa_id, personas)
if not orden_id:
    st.stop()
st.markdown(f"**🧾 Orden activa:** `{orden_id}`")

# 7) Selección de producto
productos_df = get_products()
categorias = productos_df["categoria"].dropna().unique().tolist()
categoria = st.selectbox("🍽️ Categoría", categorias)
filtro_df = productos_df[productos_df["categoria"] == categoria]
sel_prod = st.selectbox("📦 Producto", filtro_df["nombre"])

prod_row = filtro_df[filtro_df["nombre"] == sel_prod].iloc[0]
cant = st.number_input("🔢 Cantidad", min_value=1, value=1, key="cant")

if st.button("➕ Añadir al pedido"):
    add_item(
        orden_id,
        int(prod_row["id"]),
        int(cant),
        float(prod_row["precio_unitario"])
    )
    get_order_items.clear()  # <---- Limpiar caché para que se refresque el detalle
    st.success(f"{cant} x {sel_prod} agregado.")

# 8) Mostrar orden
st.subheader("🧾 Detalle de la orden")
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
