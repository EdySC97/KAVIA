# ... [todo el código que ya tienes hasta llegar a la sección principal sigue igual] ...

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

# Productos
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

# Añadir producto
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

# Detalle final
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
