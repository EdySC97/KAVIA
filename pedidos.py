import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

# 1. Conexión a PostgreSQL


@st.experimental_singleton
def init_connection():
    cfg = st.secrets["postgres"]
    return psycopg2.connect(
        host=cfg["host"],
        port=cfg["port"],
        dbname=cfg["database"],
        user=cfg["user"],
        password=cfg["password"],
        cursor_factory=RealDictCursor
    )


conn = init_connection()

# 2. Funciones de acceso a datos


def get_tables():
    return pd.read_sql("SELECT id, nombre FROM mesas ORDER BY id", conn)


def get_products():
    return pd.read_sql("SELECT id, nombre, precio_unitario FROM productos ORDER BY categoria, nombre", conn)


def get_or_create_order(mesa_id):
    # Busca orden abierta
    sql = "SELECT id FROM ordenes WHERE mesa_id = %s AND estado = 'abierto' LIMIT 1"
    df = pd.read_sql(sql, conn, params=(mesa_id,))
    if not df.empty:
        return df.loc[0, "id"]
    # Crea nueva orden
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ordenes (mesa_id, estado) VALUES (%s, 'abierto') RETURNING id;",
            (mesa_id,)
        )
        orden_id = cur.fetchone()["id"]
        conn.commit()
        return orden_id


def add_item(orden_id, producto_id, cantidad, precio_unitario):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO orden_items (orden_id, producto_id, cantidad, precio_unitario)
            VALUES (%s, %s, %s, %s);
        """, (orden_id, producto_id, cantidad, precio_unitario))
        conn.commit()


def get_order_items(orden_id):
    sql = """
      SELECT p.nombre AS producto,
             oi.cantidad,
             oi.precio_unitario,
             oi.subtotal
      FROM orden_items oi
      JOIN productos p ON p.id = oi.producto_id
      WHERE oi.orden_id = %s;
    """
    return pd.read_sql(sql, conn, params=(orden_id,))


def finalize_order(orden_id):
    now = datetime.now()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ordenes
               SET estado = 'pagado',
                   cerrado_at = %s
             WHERE id = %s;
        """, (now, orden_id))
        conn.commit()


# 3. Selección de mesa y obtención/creación de la orden
st.title("📋 Pedido de Bar")

mesas_df = get_tables()
mesa = st.selectbox("Elige mesa", mesas_df["nombre"])
mesa_id = mesas_df[mesas_df["nombre"] == mesa]["id"].iloc[0]

orden_id = get_or_create_order(mesa_id)
st.markdown(f"**Orden activa:** `{orden_id}`")

# 4. Formulario para añadir ítems
st.subheader("Agregar producto")
productos_df = get_products()
prod_sel = st.selectbox("Producto", productos_df["nombre"])
producto = productos_df[productos_df["nombre"] == prod_sel].iloc[0]
cant = st.number_input("Cantidad", min_value=1, step=1, value=1)

if st.button("➕ Añadir al pedido"):
    add_item(
        orden_id,
        int(producto["id"]),
        int(cant),
        float(producto["precio_unitario"])
    )
    st.success(f"{cant} x {prod_sel} agregado.")

# 5. Mostrar detalle actual de la orden
st.subheader("Detalle de la orden")
items_df = get_order_items(orden_id)
if items_df.empty:
    st.info("Aún no has agregado productos.")
else:
    st.dataframe(items_df, use_container_width=True)
    total = items_df["subtotal"].sum()
    st.metric("Total a pagar", f"$ {total:.2f}")

    # 6. Finalizar y generar ticket imprimible
    if st.button("💳 Finalizar y generar ticket"):
        finalize_order(orden_id)

        # Generar texto de ticket
        lines = []
        lines.append("====== BAR XYZ ======")
        lines.append(f"Mesa: {mesa}   Fecha: {datetime.now():%Y-%m-%d %H:%M}")
        lines.append("---------------------")
        for _, row in items_df.iterrows():
            lines.append(
                f"{row['cantidad']:>2} x {row['producto']:<20} $ {row['subtotal']:.2f}")
        lines.append("---------------------")
        lines.append(f"TOTAL: $ {total:.2f}")
        lines.append("=====================")
        ticket_txt = "\n".join(lines)

        st.text_area("Ticket", ticket_txt, height=300)
        st.download_button(
            "🖨️ Descargar ticket (.txt)",
            data=ticket_txt,
            file_name=f"ticket_{orden_id}.txt",
            mime="text/plain"
        )
        st.balloons()
