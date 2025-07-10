import os
import traceback
import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# 1) Configuración de entorno y layout
os.environ["PGCLIENTENCODING"] = "latin1"
st.set_page_config(layout="wide")
st.title("📋 Captura de Pedido")

# 2) Leer credenciales
cfg      = st.secrets["postgres"]
host     = cfg["host"]
port     = cfg["port"]
database = cfg["database"]
user     = cfg["user"]
password = cfg["password"]

# 3) Conexión compartida a la base de datos
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
    return pd.read_sql("SELECT id, nombre FROM mesas ORDER BY id", conn)

@st.cache_data(ttl=60)
def get_products():
    return pd.read_sql(
        "SELECT id, nombre, precio_unitario, categoria "
        "FROM productos ORDER BY categoria, nombre",
        conn
    )

@st.cache_data(ttl=30)
def get_open_orders():
    return pd.read_sql(
        """
        SELECT o.id, o.mesa_id, o.personas, m.nombre AS mesa
        FROM ordenes o
        JOIN mesas m ON m.id = o.mesa_id
        WHERE o.estado = 'abierto'
        ORDER BY o.id;
        """,
        conn
    )

@st.cache_data(ttl=30)
def get_order_items(orden_id):
    return pd.read_sql(
        """
        SELECT 
          p.nombre            AS producto,
          oi.cantidad,
          oi.precio_unitario,
          oi.subtotal
        FROM orden_items oi
        JOIN productos p 
          ON p.id = oi.producto_id
        WHERE oi.orden_id = %s
        ORDER BY p.nombre;
        """,
        conn, params=(orden_id,)
    )

# 5) Lógica de negocio con depuración en get_or_create_order
def get_or_create_order(mesa_id, personas):
    try:
        df = pd.read_sql(
            "SELECT id, personas FROM ordenes "
            "WHERE mesa_id=%s AND estado='abierto';",
            conn, params=(mesa_id,)
        )
    except Exception as e:
        st.error("Error en get_or_create_order:")
        st.error(str(e))
        st.error(traceback.format_exc())
        cols = pd.read_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='ordenes';",
            conn
        )
        st.write("Columnas en ordenes:", cols["column_name"].tolist())
        st.stop()

    if not df.empty:
        oid, existing = df.loc[0, ["id","personas"]]
        if existing != personas:
            cur = conn.cursor()
            cur.execute(
                "UPDATE ordenes SET personas=%s WHERE id=%s;",
                (personas, oid)
            )
            conn.commit()
        return oid

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ordenes(mesa_id,personas,estado) "
        "VALUES(%s,%s,'abierto') RETURNING id;",
        (mesa_id, personas)
    )
    oid = cur.fetchone()[0]
    conn.commit()
    return oid

def add_item(orden_id, producto_id, cantidad, precio):
    # subtotal es GENERATED ALWAYS; no se inserta
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO orden_items
        (orden_id, producto_id, cantidad, precio_unitario)
      VALUES (%s, %s, %s, %s);
    """, (orden_id, producto_id, cantidad, precio))
    conn.commit()

def finalize_order(orden_id):
    now = datetime.now()
    cur = conn.cursor()
    cur.execute("""
      UPDATE ordenes
        SET estado='pagado', cerrado_at=%s
      WHERE id=%s;
    """, (now, orden_id))
    conn.commit()

def generar_ticket_pdf(mesa, personas, orden_id, items, total):
    pdf = FPDF(format="P", unit="mm", margin=10)
    pdf.add_page()
    pdf.set_font("Courier", size=11)
    pdf.cell(0,6, "====== BAR XYZ ======", ln=True, align="C")
    pdf.cell(0,6, f"Mesa: {mesa}   Personas: {personas}", ln=True)
    pdf.cell(0,6, f"Orden: {orden_id}   Fecha: {datetime.now():%Y-%m-%d %H:%M}", ln=True)
    pdf.cell(0,6, "-"*40, ln=True)
    for r in items.itertuples():
        pdf.cell(0,6, f"{r.cantidad:>2} x {r.producto:<20} $ {r.subtotal:>6.2f}", ln=True)
    pdf.cell(0,6, "-"*40, ln=True)
    pdf.cell(0,6, f"TOTAL: $ {total:.2f}", ln=True, align="R")
    return pdf.output(dest="S").encode("latin1")

# 6) Sidebar: carrito de mesas abiertas
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
                st.table(df_it[["producto","cantidad","subtotal"]])
                st.write("Total: $", df_it["subtotal"].sum())

# 7) Área principal: tomar pedido
mesas_df = get_tables()
if mesas_df.empty:
    st.error("No hay mesas definidas.")
    st.stop()

mesa_sel = st.selectbox("Elige mesa", mesas_df["nombre"])
mesa_id  = mesas_df.loc[mesas_df["nombre"] == mesa_sel, "id"].iloc[0]
personas = st.number_input("Cantidad de personas", min_value=1, max_value=20, value=1)

orden_id = get_or_create_order(mesa_id, personas)
st.markdown(f"**Orden activa:** {orden_id}")

# 7.1) Filtrar por categoría (incluye Bebidas)
productos_df = get_products()
categorias  = productos_df["categoria"].unique().tolist()
categoria   = st.selectbox("Categoría", categorias)
filtro_df   = productos_df[productos_df["categoria"] == categoria]

sel_prod = st.selectbox("Producto", filtro_df["nombre"])
prod_row = filtro_df[filtro_df["nombre"] == sel_prod].iloc[0]
cant     = st.number_input("Cantidad", min_value=1, value=1, key="cant")

if st.button("➕ Añadir al pedido"):
    add_item(
        orden_id,
        int(prod_row["id"]),
        int(cant),
        float(prod_row["precio_unitario"])
    )
    st.success(f"{cant} x {sel_prod} agregado.")

# 7.2) Detalle, total, finalizar e imprimir
st.subheader("Detalle de la orden")
items = get_order_items(orden_id)
if items.empty:
    st.info("No hay productos agregados aún.")
else:
    st.dataframe(
        items[["producto","cantidad","precio_unitario","subtotal"]],
        use_container_width=True
    )
    total = items["subtotal"].sum()
    st.metric("Total a pagar", f"$ {total:.2f}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💳 Finalizar mesa"):
            finalize_order(orden_id)
            st.success("Mesa finalizada. ¡Gracias!")
    with col2:
        if st.button("🖨️ Imprimir ticket"):
            pdf_bytes = generar_ticket_pdf(
                mesa_sel, personas, orden_id, items, total
            )
            st.download_button(
                "⬇️ Descargar PDF",
                data=pdf_bytes,
                file_name=f"ticket_{orden_id}.pdf",
                mime="application/pdf"
            )
