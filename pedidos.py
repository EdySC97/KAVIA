import os
import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# Forzar encoding latino (para tildes y eñes)
os.environ["PGCLIENTENCODING"] = "latin1"

st.title("📋 Captura de Pedido")

# 1. Leer credenciales de .streamlit/secrets.toml
cfg = st.secrets["postgres"]
host     = cfg["host"]
port     = cfg["port"]
database = cfg["database"]
user     = cfg["user"]
password = cfg["password"]

# 2. Conexión a la base de datos como recurso compartido
@st.cache_resource
def conectar_db():
    try:
        return psycopg2.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password
        )
    except Exception as e:
        st.error(f"Error al conectar con la base de datos:\n{e}")
        st.stop()

conn = conectar_db()

# 3. Funciones cacheadas para leer datos
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

def get_order_items(orden_id):
    sql = """
    SELECT
      p.nombre                 AS producto,
      oi.cantidad,
      oi.precio_unitario,
      (oi.cantidad * oi.precio_unitario) AS subtotal
    FROM orden_items oi
    JOIN productos p
      ON p.id = oi.producto_id
    WHERE oi.orden_id = %s;
    """
    try:
        # Quita el cache para depurar
        df = pd.read_sql(sql, conn, params=(orden_id,))
        return df
    except Exception as e:
        # Muestra el mensaje completo de error
        st.error("Error en get_order_items:")
        st.error(str(e))
        # Opcional: también lo imprimes en consola
        import traceback; print(traceback.format_exc())
        return pd.DataFrame()
# 4. Lógica de órdenes
def get_or_create_order(mesa_id):
    df = pd.read_sql(
        "SELECT id FROM ordenes "
        "WHERE mesa_id=%s AND estado='abierto' LIMIT 1",
        conn, params=(mesa_id,)
    )
    if not df.empty:
        return df.loc[0, "id"]
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ordenes (mesa_id, estado) "
        "VALUES (%s,'abierto') RETURNING id;",
        (mesa_id,)
    )
    orden_id = cur.fetchone()[0]
    conn.commit()
    return orden_id

def add_item(orden_id, producto_id, cantidad, precio):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orden_items 
        (orden_id, producto_id, cantidad, precio_unitario)
        VALUES (%s,%s,%s,%s);
    """, (orden_id, producto_id, cantidad, precio))
    conn.commit()

def finalize_order(orden_id):
    ahora = datetime.now()
    cur = conn.cursor()
    cur.execute("""
        UPDATE ordenes
           SET estado='pagado',
               cerrado_at=%s
         WHERE id=%s;
    """, (ahora, orden_id))
    conn.commit()

def generar_ticket_pdf(mesa, orden_id, items_df, total):
    pdf = FPDF(format="P", unit="mm", margin=10)
    pdf.add_page()
    pdf.set_font("Courier", size=11)
    pdf.cell(0, 6, "====== BAR XYZ ======", ln=True, align="C")
    pdf.cell(0, 6, f"Mesa: {mesa}   Fecha: {datetime.now():%Y-%m-%d %H:%M}", ln=True)
    pdf.cell(0, 6, "-"*40, ln=True)
    for _, row in items_df.iterrows():
        line = f"{int(row['cantidad']):>2} x {row['producto']:<20} $ {row['subtotal']:>6.2f}"
        pdf.cell(0, 6, line, ln=True)
    pdf.cell(0, 6, "-"*40, ln=True)
    pdf.cell(0, 6, f"TOTAL: $ {total:.2f}", ln=True, align="R")
    buffer = pdf.output(dest="S").encode('latin1')
    return buffer

# 5. Interfaz de usuario

# 5.1 Mesas
mesas_df = get_tables()
if mesas_df.empty:
    st.warning("No hay mesas definidas. Agrega mesas en la base de datos.")
    st.stop()

# Mapeo nombre → id
mesa_map = dict(zip(mesas_df["nombre"], mesas_df["id"]))
mesa_sel = st.selectbox("Elige mesa", list(mesa_map.keys()))
mesa_id  = mesa_map[mesa_sel]

st.markdown(f"**Orden activa para la mesa:** {mesa_sel} (id: {mesa_id})")

# 5.2 Obtener o crear orden
orden_id = get_or_create_order(mesa_id)

# 5.3 Productos
productos_df = get_products()
prod_sel = st.selectbox("Producto", productos_df["nombre"])
prod_row = productos_df[productos_df["nombre"] == prod_sel].iloc[0]
cant     = st.number_input("Cantidad", min_value=1, step=1, value=1)

if st.button("➕ Añadir al pedido"):
    add_item(
        orden_id,
        int(prod_row["id"]),
        int(cant),
        float(prod_row["precio_unitario"])
    )
    st.success(f"{cant} x {prod_sel} agregado.")

# 5.4 Detalle de la orden
st.subheader("Detalle de la orden")
items_df = get_order_items(orden_id)
if items_df.empty:
    st.info("No hay productos agregados aún.")
else:
    st.dataframe(items_df, use_container_width=True)
    total = items_df["subtotal"].sum()
    st.metric("Total a pagar", f"$ {total:.2f}")

    if st.button("💳 Finalizar y generar ticket"):
        finalize_order(orden_id)
        pdf_bytes = generar_ticket_pdf(mesa_sel, orden_id, items_df, total)
        st.download_button(
            "🖨️ Descargar ticket (.pdf)",
            data=pdf_bytes,
            file_name=f"ticket_{orden_id}.pdf",
            mime="application/pdf"
        )
        st.balloons()
