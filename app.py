"""
Interfaz web sencilla para el Robot de Auditoria de Farmacias.

Para abrir esta aplicacion, en la terminal ejecutar:
    streamlit run app.py

Esto abre una pestana en el navegador con botones y menus,
sin necesidad de escribir ni un solo comando de Python.
"""

import io
import os
from datetime import datetime

import pandas as pd
import streamlit as st

from automatizacion import descargar_existencia_por_categoria, descargar_kardex
import modulo_farmacia as mf
import modulo_cedi as mc
import estado_usuario as eu
from auth import requerir_login

st.set_page_config(page_title="Robot de Auditoria de Farmacias", page_icon="🤖", layout="wide")

requerir_login()  # muestra el formulario de usuario/contraseña y detiene aqui si no ha iniciado sesion

st.sidebar.write(f"👤 Sesion: **{st.session_state.get('usuario_actual', '')}**")
if st.sidebar.button("Cerrar sesion"):
    st.session_state.autenticado = False
    st.rerun()

st.title("🤖 Robot de Auditoria de Farmacias")

tab_descargar, tab_farmacia, tab_cedi, tab_devoluciones = st.tabs(
    ["📥 Descargar Reportes", "🏪 Conciliacion Farmacia", "🏭 CEDI", "🕵️ Análisis de Devoluciones"]
)

# ══════════════════════════════════════════════════
#  PESTAÑA 1: DESCARGAR REPORTES (robot de navegacion)
# ══════════════════════════════════════════════════
with tab_descargar:
    st.subheader("Reporte de Existencias por Categoria")
    st.write("Descarga automaticamente el reporte desde el portal LDCOM.")

    codigo_bodega = st.text_input(
        "Codigo de bodega / farmacia",
        placeholder="Ejemplo: K002, K018, K136",
        key="codigo_bodega_descarga",
    ).strip().upper()

    if st.button("Descargar Reporte de Existencias", type="primary", disabled=not codigo_bodega):
        caja_estado = st.empty()
        barra_progreso = st.progress(0, text="Iniciando...")

        pasos_totales = 10
        contador_pasos = {"actual": 0}

        def mostrar_progreso(mensaje):
            contador_pasos["actual"] = min(contador_pasos["actual"] + 1, pasos_totales - 1)
            porcentaje = int((contador_pasos["actual"] / pasos_totales) * 100)
            caja_estado.info(mensaje)
            barra_progreso.progress(porcentaje, text=mensaje)

        try:
            ruta_archivo = descargar_existencia_por_categoria(
                codigo_bodega,
                callback_progreso=mostrar_progreso,
                headless=True,
            )
            barra_progreso.progress(100, text="¡Completado!")
            st.success(f"✅ Reporte descargado correctamente para la bodega {codigo_bodega}")

            with open(ruta_archivo, "rb") as f:
                st.download_button(
                    label="📥 Abrir / Guardar el archivo CSV",
                    data=f,
                    file_name=f"existencias_por_categoria_{codigo_bodega}.csv",
                    mime="text/csv",
                )
            st.caption(f"El archivo tambien quedo guardado en: {ruta_archivo}")

        except Exception as error:
            barra_progreso.empty()
            st.error(f"❌ Ocurrio un problema: {error}")
            st.write("Intenta de nuevo. Si el problema persiste, avisa al equipo tecnico.")

    st.divider()

    st.subheader("Kardex de Movimientos")
    st.write("Descarga automaticamente el Kardex para una bodega y rango de fechas.")

    col_bodega, col_f1, col_f2 = st.columns(3)
    with col_bodega:
        codigo_bodega_kardex = st.text_input(
            "Codigo de bodega / farmacia",
            placeholder="Ejemplo: K002, K018",
            key="codigo_bodega_kardex",
        ).strip().upper()
    with col_f1:
        fecha_inicio_kardex = st.date_input("Fecha Inicio", value=None, key="fecha_inicio_kardex")
    with col_f2:
        fecha_final_kardex = st.date_input("Fecha Final", value=None, key="fecha_final_kardex")

    puede_descargar_kardex = bool(codigo_bodega_kardex and fecha_inicio_kardex and fecha_final_kardex)

    if st.button("Descargar Kardex", type="primary", disabled=not puede_descargar_kardex):
        caja_estado_k = st.empty()
        barra_progreso_k = st.progress(0, text="Iniciando...")

        pasos_totales_k = 10
        contador_pasos_k = {"actual": 0}

        def mostrar_progreso_kardex(mensaje):
            contador_pasos_k["actual"] = min(contador_pasos_k["actual"] + 1, pasos_totales_k - 1)
            porcentaje = int((contador_pasos_k["actual"] / pasos_totales_k) * 100)
            caja_estado_k.info(mensaje)
            barra_progreso_k.progress(porcentaje, text=mensaje)

        try:
            ruta_archivo_k = descargar_kardex(
                codigo_bodega_kardex,
                fecha_inicio_kardex,
                fecha_final_kardex,
                callback_progreso=mostrar_progreso_kardex,
                headless=True,
            )
            barra_progreso_k.progress(100, text="¡Completado!")
            st.success(f"✅ Kardex descargado correctamente para la bodega {codigo_bodega_kardex}")

            with open(ruta_archivo_k, "rb") as f:
                st.download_button(
                    label="📥 Abrir / Guardar el archivo CSV",
                    data=f,
                    file_name=ruta_archivo_k.split("/")[-1].split("\\")[-1],
                    mime="text/csv",
                    key="descarga_kardex",
                )
            st.caption(f"El archivo tambien quedo guardado en: {ruta_archivo_k}")

        except Exception as error:
            barra_progreso_k.empty()
            st.error(f"❌ Ocurrio un problema: {error}")
            st.write("Intenta de nuevo. Si el problema persiste, avisa al equipo tecnico.")


# ══════════════════════════════════════════════════
#  PESTAÑA 2: CONCILIACION FARMACIA
# ══════════════════════════════════════════════════
with tab_farmacia:
    usuario_actual = st.session_state.get("usuario_actual", "anonimo")

    # Al entrar a la pestana, recuperamos lo que este auditor ya tenia guardado
    if "farm_existencia" not in st.session_state:
        st.session_state.farm_existencia = eu.cargar_existencia(usuario_actual)
    if "farm_kardex_info" not in st.session_state:
        st.session_state.farm_kardex_info = eu.cargar_kardex(usuario_actual)
    if "farm_conteo" not in st.session_state:
        st.session_state.farm_conteo = {}
        st.session_state.farm_reconteo = {}
        st.session_state.farm_corto = {}
        st.session_state.farm_exceso = {}

    st.write(f"👤 Trabajando como: **{usuario_actual}**")

    # ────────────────────────────────────────────
    # PASO 1: EXISTENCIA (buscar y descargar, igual que en la otra pestana)
    # ────────────────────────────────────────────
    st.markdown("### Paso 1 — Existencia del Sistema")

    if st.session_state.farm_existencia:
        ex = st.session_state.farm_existencia
        guardado_el = ex.get("_guardado_el", "")[:16].replace("T", " ")
        st.success(f"🏪 Existencia guardada: **{ex['farmacia'] or 'Sin codigo'}** (cargada el {guardado_el})")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("SKUs totales", ex["total"])
        c2.metric("Padres", len(ex["padres"]))
        c3.metric("Hijos", len(ex["hijos"]))
        c4.metric("Negativos", len(ex["negativos"]))
        c5.metric("Omitidos (0)", ex["omitidos"])

        colp, colh, coln = st.columns(3)
        with colp:
            contenido, nombre = mf.generar_csv_handheld(ex["padres"], ex["farmacia"], "padres")
            st.download_button("⬇ PADRES.csv", contenido, file_name=nombre, mime="text/csv", key="dl_padres")
        with colh:
            contenido, nombre = mf.generar_csv_handheld(ex["hijos"], ex["farmacia"], "hijos")
            st.download_button("⬇ HIJOS.csv", contenido, file_name=nombre, mime="text/csv", key="dl_hijos")
        with coln:
            contenido, nombre = mf.generar_csv_handheld(ex["negativos"], ex["farmacia"], "negativos")
            st.download_button("⬇ NEGATIVOS.csv", contenido, file_name=nombre, mime="text/csv", key="dl_negativos")

        if st.button("🗑 Descartar esta existencia y buscar otra farmacia"):
            eu.borrar_existencia(usuario_actual)
            st.session_state.farm_existencia = None
            st.rerun()

    else:
        st.info("Aun no tienes una existencia guardada. Busca tu farmacia para empezar.")
        codigo_bodega_conc = st.text_input(
            "Codigo de bodega / farmacia", placeholder="Ejemplo: K002", key="codigo_bodega_conciliacion"
        ).strip().upper()

        if st.button("🔎 Buscar y Guardar Existencia", type="primary", disabled=not codigo_bodega_conc):
            caja = st.empty()
            barra = st.progress(0, text="Iniciando...")
            contador = {"actual": 0}

            def avisar_existencia(msg):
                contador["actual"] = min(contador["actual"] + 1, 9)
                caja.info(msg)
                barra.progress(int(contador["actual"] / 10 * 100), text=msg)

            try:
                ruta = descargar_existencia_por_categoria(
                    codigo_bodega_conc, callback_progreso=avisar_existencia, headless=True
                )
                with open(ruta, "rb") as f:
                    bytes_archivo = f.read()
                resultado = mf.cargar_existencia(bytes_archivo)
                eu.guardar_existencia(usuario_actual, resultado)
                st.session_state.farm_existencia = eu.cargar_existencia(usuario_actual)
                barra.progress(100, text="¡Listo!")
                st.success(f"✅ Existencia de {resultado['farmacia']} guardada correctamente.")
                st.rerun()
            except Exception as error:
                barra.empty()
                st.error(f"❌ Ocurrio un problema: {error}")

        with st.expander("O sube un archivo de Existencia manualmente"):
            archivo_existencia = st.file_uploader("Archivo de Existencia (CSV)", type="csv", key="up_existencia")
            if archivo_existencia is not None:
                try:
                    resultado = mf.cargar_existencia(archivo_existencia.getvalue())
                    eu.guardar_existencia(usuario_actual, resultado)
                    st.session_state.farm_existencia = eu.cargar_existencia(usuario_actual)
                    st.success(f"🏪 Existencia de {resultado['farmacia']} guardada.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {e}")

    st.divider()

    # ────────────────────────────────────────────
    # PASO 2: KARDEX (buscar y descargar, con fecha+hora exactas)
    # ────────────────────────────────────────────
    st.markdown("### Paso 2 — Kardex de Movimientos")
    st.caption(
        "Importante: el inventario es a puertas abiertas — indica la hora exacta en que "
        "empezaste el conteo, para ignorar movimientos anteriores a esa hora."
    )

    if st.session_state.farm_kardex_info:
        ki = st.session_state.farm_kardex_info
        meta = ki.get("meta", {})
        st.success(
            f"📋 Kardex guardado — {meta.get('movimientos', '?')} movimientos, "
            f"{meta.get('skus_afectados', '?')} SKUs afectados "
            f"(ventana: {meta.get('desde', '?')} a {meta.get('hasta', '?')})"
        )
        st.session_state.farm_kardex = ki["kardex"]

        # --- RESUMEN DE MOVIMIENTOS POR TIPO (FAC, PED, MTR, MIN, LOC, etc.) ---
        with st.expander("📊 Ver resumen de movimientos por tipo", expanded=False):
            filtro_articulos = st.radio(
                "Ver movimientos de:", ["Todos", "Solo Padres", "Solo Hijos"],
                horizontal=True, key="filtro_resumen_tipo",
            )
            mapa_filtro = {"Todos": "todos", "Solo Padres": "padres", "Solo Hijos": "hijos"}

            detalle_tipo = ki.get("detalle_por_sku_tipo", {})
            if detalle_tipo and st.session_state.farm_existencia:
                resumen = mf.resumen_movimientos_por_tipo(
                    detalle_tipo, st.session_state.farm_existencia, mapa_filtro[filtro_articulos]
                )
                if resumen:
                    df_resumen = pd.DataFrame(resumen)
                    df_resumen.columns = ["Tipo de Movimiento", "Neto (unidades)", "Cantidad de movimientos"]
                    st.dataframe(df_resumen, use_container_width=True, hide_index=True)
                else:
                    st.info("No hay movimientos para este filtro.")
            else:
                st.info("Este kardex fue cargado antes de esta funcion. Vuelve a buscarlo para ver el resumen.")

        if st.button("🗑 Descartar este Kardex y volver a cargar"):
            eu.borrar_kardex(usuario_actual)
            st.session_state.farm_kardex_info = None
            st.session_state.farm_kardex = {}
            st.rerun()
    else:
        st.session_state.farm_kardex = {}
        codigo_bodega_kardex_conc = st.text_input(
            "Codigo de bodega / farmacia", placeholder="Ejemplo: K002", key="codigo_bodega_kardex_conciliacion"
        ).strip().upper()

        col_fi, col_hi, col_ff, col_hf = st.columns(4)
        with col_fi:
            fecha_desde = st.date_input("Fecha inicio conteo", value=None, key="kardex_fecha_desde")
        with col_hi:
            hora_desde = st.time_input("Hora inicio conteo", value=None, key="kardex_hora_desde")
        with col_ff:
            fecha_hasta = st.date_input("Fecha cierre conteo", value=None, key="kardex_fecha_hasta")
        with col_hf:
            hora_hasta = st.time_input("Hora cierre conteo", value=None, key="kardex_hora_hasta")

        guardar_copia_local = st.checkbox("Tambien guardar una copia del CSV en mi computadora", value=False)

        puede_buscar_kardex = bool(
            codigo_bodega_kardex_conc and fecha_desde and hora_desde and fecha_hasta and hora_hasta
        )

        if st.button("🔎 Buscar y Guardar Kardex", type="primary", disabled=not puede_buscar_kardex):
            caja_k = st.empty()
            barra_k = st.progress(0, text="Iniciando...")
            contador_k = {"actual": 0}

            def avisar_kardex(msg):
                contador_k["actual"] = min(contador_k["actual"] + 1, 9)
                caja_k.info(msg)
                barra_k.progress(int(contador_k["actual"] / 10 * 100), text=msg)

            try:
                # El portal solo filtra por dia; el filtro fino por HORA lo hacemos
                # nosotros mismos despues, con la fecha+hora exacta que diste.
                dt_desde = datetime.combine(fecha_desde, hora_desde)
                dt_hasta = datetime.combine(fecha_hasta, hora_hasta)

                ruta_k = descargar_kardex(
                    codigo_bodega_kardex_conc, fecha_desde, fecha_hasta,
                    callback_progreso=avisar_kardex, headless=True,
                )
                with open(ruta_k, "rb") as f:
                    bytes_kardex = f.read()

                resultado_k = mf.cargar_kardex(bytes_kardex, dt_desde, dt_hasta)
                meta = {
                    "bodega": codigo_bodega_kardex_conc,
                    "desde": dt_desde.strftime("%d/%m/%Y %H:%M"),
                    "hasta": dt_hasta.strftime("%d/%m/%Y %H:%M"),
                    "movimientos": resultado_k["movimientos"],
                    "skus_afectados": resultado_k["skus_afectados"],
                }
                eu.guardar_kardex(
                    usuario_actual, resultado_k["kardex"], meta,
                    detalle_por_sku_tipo=resultado_k["detalle_por_sku_tipo"],
                    resumen_tipos=resultado_k["resumen_tipos"],
                )
                st.session_state.farm_kardex_info = eu.cargar_kardex(usuario_actual)

                barra_k.progress(100, text="¡Listo!")
                st.success("✅ Kardex guardado correctamente.")

                if guardar_copia_local:
                    st.caption(f"Copia guardada en: {ruta_k}")
                    with open(ruta_k, "rb") as f:
                        st.download_button(
                            "📥 Descargar copia del CSV", f,
                            file_name=os.path.basename(ruta_k), mime="text/csv", key="dl_kardex_copia",
                        )
                st.rerun()
            except Exception as error:
                barra_k.empty()
                st.error(f"❌ Ocurrio un problema: {error}")

        with st.expander("O sube un archivo de Kardex manualmente"):
            archivo_kardex = st.file_uploader("Archivo de Kardex (CSV)", type="csv", key="up_kardex")
            if archivo_kardex is not None and fecha_desde and hora_desde and fecha_hasta and hora_hasta:
                try:
                    dt_desde = datetime.combine(fecha_desde, hora_desde)
                    dt_hasta = datetime.combine(fecha_hasta, hora_hasta)
                    resultado_k = mf.cargar_kardex(archivo_kardex.getvalue(), dt_desde, dt_hasta)
                    meta = {
                        "bodega": codigo_bodega_kardex_conc or "?",
                        "desde": dt_desde.strftime("%d/%m/%Y %H:%M"),
                        "hasta": dt_hasta.strftime("%d/%m/%Y %H:%M"),
                        "movimientos": resultado_k["movimientos"],
                        "skus_afectados": resultado_k["skus_afectados"],
                    }
                    eu.guardar_kardex(
                        usuario_actual, resultado_k["kardex"], meta,
                        detalle_por_sku_tipo=resultado_k["detalle_por_sku_tipo"],
                        resumen_tipos=resultado_k["resumen_tipos"],
                    )
                    st.session_state.farm_kardex_info = eu.cargar_kardex(usuario_actual)
                    st.success("✅ Kardex guardado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {e}")
            elif archivo_kardex is not None:
                st.warning("Completa las 4 fechas/horas de arriba antes de subir el archivo.")

    st.divider()

    # ────────────────────────────────────────────
    # PASO 3: CONTEO / RECONTEO
    # ────────────────────────────────────────────
    st.markdown("### Paso 3 — Conteo Fisico")
    st.caption(
        "Si varios auditores contaron esta misma farmacia (ej: se dividieron los pasillos), "
        "sube todos sus archivos aqui — las cantidades de un mismo SKU se SUMAN entre auditores."
    )
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        archivos_conteo = st.file_uploader(
            "Conteo inicial (CSV) — puedes subir varios",
            type="csv", key="up_conteo", accept_multiple_files=True,
        )
        if archivos_conteo:
            try:
                conteos_individuales = [mf.cargar_conteo(a.getvalue()) for a in archivos_conteo]
                st.session_state.farm_conteo = mf.unificar_conteos_de_varios_auditores(conteos_individuales)
                st.success(
                    f"✅ {len(archivos_conteo)} archivo(s) unificados — "
                    f"{len(st.session_state.farm_conteo)} SKUs contados en total"
                )
            except Exception as e:
                st.error(f"❌ {e}")
    with col_c2:
        archivos_reconteo = st.file_uploader(
            "Reconteo (CSV, opcional) — puedes subir varios",
            type="csv", key="up_reconteo", accept_multiple_files=True,
        )
        if archivos_reconteo:
            try:
                reconteos_individuales = [mf.cargar_conteo(a.getvalue()) for a in archivos_reconteo]
                st.session_state.farm_reconteo = mf.unificar_conteos_de_varios_auditores(reconteos_individuales)
                st.success(
                    f"🔁 {len(archivos_reconteo)} archivo(s) unificados — "
                    f"{len(st.session_state.farm_reconteo)} SKUs sustituidos"
                )
            except Exception as e:
                st.error(f"❌ {e}")

    st.divider()

    # ────────────────────────────────────────────
    # PASO 4: CORTO VENCE / EXCESOS
    # ────────────────────────────────────────────
    st.markdown("### Paso 4 — Corto Vence / Excesos (opcional)")
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        archivo_corto = st.file_uploader("Listado Corto Vence (CSV)", type="csv", key="up_corto")
        if archivo_corto is not None:
            try:
                st.session_state.farm_corto = mf.cargar_listado_especial(archivo_corto.getvalue())
                st.success(f"📦 Corto Vence cargado — {len(st.session_state.farm_corto)} SKUs")
            except Exception as e:
                st.error(f"❌ {e}")
    with col_e2:
        archivo_exceso = st.file_uploader("Listado Excesos (CSV)", type="csv", key="up_exceso")
        if archivo_exceso is not None:
            try:
                st.session_state.farm_exceso = mf.cargar_listado_especial(archivo_exceso.getvalue())
                st.success(f"📦 Excesos cargado — {len(st.session_state.farm_exceso)} SKUs")
            except Exception as e:
                st.error(f"❌ {e}")

    st.divider()

    # ────────────────────────────────────────────
    # RESULTADOS
    # ────────────────────────────────────────────
    st.markdown("### Resultado — Diferencias")

    if st.session_state.farm_existencia and st.session_state.farm_conteo:
        col_toggle1, col_toggle2 = st.columns(2)
        with col_toggle1:
            aplicar_exceso = st.checkbox(
                "Descontar Excesos disponibles a los sobrantes", value=True, key="aplicar_exceso"
            )
        with col_toggle2:
            aplicar_corto = st.checkbox(
                "Descontar Corto Vence disponible a los sobrantes", value=True, key="aplicar_corto"
            )

        resultados = mf.calcular_diferencias(
            st.session_state.farm_existencia["existencia"],
            st.session_state.get("farm_kardex", {}),
            st.session_state.farm_conteo,
            st.session_state.farm_reconteo,
            st.session_state.farm_corto,
            st.session_state.farm_exceso,
            aplicar_corto=aplicar_corto,
            aplicar_exceso=aplicar_exceso,
        )

        umbral = st.slider(
            "Sensibilidad de deteccion de posibles cruces (mas alto = solo muy parecidos)",
            min_value=0.3, max_value=1.0, value=0.5, step=0.05, key="umbral_cruces",
        )
        cruces = mf.detectar_posibles_cruces(resultados, umbral_similitud=umbral)
        # Repartimos las cantidades del cruce (si sobra 1 pero faltan 3, solo se
        # justifica 1; el resto se queda como faltante/sobrante sin justificar)
        resultados = mf.aplicar_cruces_a_resultados(resultados, cruces)

        faltantes = [r for r in resultados if r["estado"] == "FALTANTE"]
        sobrantes = [r for r in resultados if r["estado"] == "SOBRANTE"]
        fuera_kardex = [r for r in resultados if r["estado"] == "SOBRANTE FUERA DE KARDEX"]
        ok = [r for r in resultados if r["estado"] == "OK"]
        no_contado = [r for r in resultados if r["estado"] == "NO CONTADO"]

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total SKUs", len(resultados))
        c2.metric("Faltantes", len(faltantes))
        c3.metric("Sobrantes", len(sobrantes))
        c4.metric("Fuera de Kardex", len(fuera_kardex))
        c5.metric("OK", len(ok))
        c6.metric("No contado", len(no_contado))
        st.caption(f"🔀 {len(cruces)} posible(s) cruce(s) detectado(s) — revisa la columna 'Observación' abajo.")

        df = pd.DataFrame(resultados)

        texto_busqueda_farm = st.text_input(
            "🔍 Buscar SKU o descripcion...", key="buscar_farm"
        ).strip().lower()

        filtro_estado = st.multiselect(
            "Filtrar por estado",
            options=["FALTANTE", "SOBRANTE", "SOBRANTE FUERA DE KARDEX", "OK", "NO CONTADO"],
            default=["FALTANTE", "SOBRANTE", "SOBRANTE FUERA DE KARDEX"],
        )
        df_filtrado = df[df["estado"].isin(filtro_estado)] if filtro_estado else df
        if texto_busqueda_farm:
            mascara_farm = df_filtrado[["sku", "desc"]].apply(
                lambda col: col.astype(str).str.lower().str.contains(texto_busqueda_farm, regex=False)
            ).any(axis=1)
            df_filtrado = df_filtrado[mascara_farm]

        st.dataframe(
            df_filtrado[["sku", "desc", "existencia", "mov_kardex", "exist_ajustada",
                         "contado", "diferencia", "estado", "observacion"]],
            use_container_width=True,
            height=400,
        )

        csv_resultados = df.to_csv(index=False)
        st.download_button(
            "⬇ Descargar tabla completa de resultados (CSV)",
            csv_resultados,
            file_name=f"resultados_conciliacion_{st.session_state.farm_existencia['farmacia']}.csv",
            mime="text/csv",
        )

        # ────────────────────────────────────────────
        # DETALLE DE POSIBLES CRUCES (apoyo visual, lado a lado)
        # ────────────────────────────────────────────
        if cruces:
            with st.expander(f"🔀 Ver detalle de los {len(cruces)} posibles cruces (lado a lado)"):
                for c in cruces:
                    etiqueta = "🔶 CRUCE ESPECIAL — marcas distintas, revisar con cuidado" if c["es_especial"] else "✅ Cruce probable"
                    with st.container(border=True):
                        st.markdown(f"**{etiqueta}** — similitud {c['similitud']:.0%}")
                        col_sob, col_falt = st.columns(2)
                        with col_sob:
                            st.markdown(f"**Sobra ({c['cantidad_sobrante']:+.0f}):**")
                            st.write(f"`{c['sku_sobrante']}` — {c['desc_sobrante']}")
                        with col_falt:
                            st.markdown(f"**Falta ({c['cantidad_faltante']:+.0f}):**")
                            st.write(f"`{c['sku_faltante']}` — {c['desc_faltante']}")

                df_cruces = pd.DataFrame(cruces)
                csv_cruces = df_cruces.to_csv(index=False)
                st.download_button(
                    "⬇ Descargar lista de posibles cruces (CSV)",
                    csv_cruces,
                    file_name=f"posibles_cruces_{st.session_state.farm_existencia['farmacia']}.csv",
                    mime="text/csv",
                )

        # ────────────────────────────────────────────
        # RECONTEO EN VIVO (directamente en la app, sin subir archivos)
        # ────────────────────────────────────────────
        st.divider()
        st.markdown("### 🔁 Reconteo (opcional)")
        st.caption(
            "Para los SKUs que necesiten revision, escribe aqui mismo la cantidad "
            "del reconteo. No hace falta descargar ni volver a subir ningun archivo."
        )

        filas_revisar = [r for r in resultados if r["estado"] in
                          ("FALTANTE", "SOBRANTE", "SOBRANTE FUERA DE KARDEX")]

        if filas_revisar:
            df_reconteo_base = pd.DataFrame([
                {
                    "sku": r["sku"], "desc": r["desc"], "existencia": r["existencia"],
                    "contado_original": r["contado"], "diferencia_previa": r["diferencia"],
                    "Reconteo": st.session_state.farm_reconteo.get(r["sku"], {}).get("cantidad"),
                }
                for r in filas_revisar
            ])

            df_editado = st.data_editor(
                df_reconteo_base,
                column_config={
                    "Reconteo": st.column_config.NumberColumn(
                        "Reconteo (escribe la cantidad real aqui)", min_value=0, step=1
                    )
                },
                disabled=["sku", "desc", "existencia", "contado_original", "diferencia_previa"],
                use_container_width=True,
                height=350,
                key="editor_reconteo",
            )

            if st.button("✅ Aplicar Reconteo y Calcular Diferencias Reales", type="primary"):
                nuevos_reconteos = dict(st.session_state.farm_reconteo)
                for _, fila in df_editado.iterrows():
                    if pd.notna(fila["Reconteo"]):
                        nuevos_reconteos[fila["sku"]] = {"cantidad": float(fila["Reconteo"]), "desc": ""}
                st.session_state.farm_reconteo = nuevos_reconteos
                st.session_state.mostrar_diferencias_reales = True
                st.rerun()
        else:
            st.success("🎉 No hay Faltantes ni Sobrantes pendientes de revisar.")
            st.session_state.mostrar_diferencias_reales = True

        # ────────────────────────────────────────────
        # DIFERENCIAS REALES (finales, tras aplicar reconteo)
        # ────────────────────────────────────────────
        if st.session_state.get("mostrar_diferencias_reales"):
            st.divider()
            st.markdown("### ✅ Diferencias Reales")
            st.caption("Resultado final, con el reconteo y los cruces ya aplicados.")

            resultados_reales = mf.calcular_diferencias(
                st.session_state.farm_existencia["existencia"],
                st.session_state.get("farm_kardex", {}),
                st.session_state.farm_conteo,
                st.session_state.farm_reconteo,
                st.session_state.farm_corto,
                st.session_state.farm_exceso,
                aplicar_corto=aplicar_corto,
                aplicar_exceso=aplicar_exceso,
            )
            cruces_reales = mf.detectar_posibles_cruces(resultados_reales, umbral_similitud=umbral)
            resultados_reales = mf.aplicar_cruces_a_resultados(resultados_reales, cruces_reales)

            # Guardamos el resultado final para que otras pestañas (ej: Analisis
            # de Devoluciones) puedan usar el Faltante de este conteo.
            st.session_state.farm_resultados_reales = resultados_reales
            st.session_state.farm_resultados_reales_farmacia = st.session_state.farm_existencia.get("farmacia", "")

            df_reales = pd.DataFrame(resultados_reales)
            st.dataframe(
                df_reales[["sku", "desc", "existencia", "contado", "diferencia", "estado", "observacion"]],
                use_container_width=True, height=350,
            )

            csv_reales = df_reales.to_csv(index=False)
            st.download_button(
                "⬇ Descargar Diferencias Reales (CSV)", csv_reales,
                file_name=f"diferencias_reales_{st.session_state.farm_existencia['farmacia']}.csv",
                mime="text/csv", key="dl_diferencias_reales",
            )

            # ────────────────────────────────────────────
            # GENERAR ARCHIVOS DE AJUSTE (FALTANTES / SOBRANTES)
            # ────────────────────────────────────────────
            st.divider()
            st.markdown("### 📄 Generar Archivos de Ajuste")
            st.caption(
                "Formato compatible con el sistema original: columnas 'Codigo' y 'Cantidad', "
                "hoja 'TOMA'. Se genera en .xlsx (Excel moderno) ya que .xls clasico ya no "
                "se puede generar (la libreria que lo hacia fue retirada de internet)."
            )

            col_id, col_umbral, col_ok = st.columns(3)
            with col_id:
                codigo_ajuste = st.text_input(
                    "Codigo / ID del ajuste",
                    value=st.session_state.farm_existencia["farmacia"],
                    key="codigo_ajuste",
                )
            with col_umbral:
                umbral_ajuste = st.number_input(
                    "Ignorar diferencias menores a", min_value=0, value=0, step=1, key="umbral_ajuste"
                )
            with col_ok:
                incluir_ok = st.checkbox("Incluir SKUs sin diferencia (cantidad 0)", value=False, key="incluir_ok_ajuste")

            faltantes_aj, sobrantes_aj = mf.preparar_datos_ajuste(
                resultados_reales, umbral=umbral_ajuste, incluir_ok=incluir_ok
            )
            st.write(f"📁 **FALTANTES**: {len(faltantes_aj)} SKUs　·　📁 **SOBRANTES**: {len(sobrantes_aj)} SKUs")

            col_f, col_s = st.columns(2)
            with col_f:
                if faltantes_aj:
                    bytes_faltantes = mf.generar_excel_ajuste(faltantes_aj)
                    st.download_button(
                        "📥 Descargar FALTANTES.xlsx", bytes_faltantes,
                        file_name=f"FALTANTES_{codigo_ajuste}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_faltantes_xlsx",
                    )
                else:
                    st.caption("Sin faltantes para exportar.")
            with col_s:
                if sobrantes_aj:
                    bytes_sobrantes = mf.generar_excel_ajuste(sobrantes_aj)
                    st.download_button(
                        "📥 Descargar SOBRANTES.xlsx", bytes_sobrantes,
                        file_name=f"SOBRANTES_{codigo_ajuste}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="dl_sobrantes_xlsx",
                    )
                else:
                    st.caption("Sin sobrantes para exportar.")
    else:
        st.info("⏳ Necesitas al menos la Existencia (Paso 1) y el Conteo (Paso 3) para ver resultados.")


# ══════════════════════════════════════════════════
#  PESTAÑA 3: CEDI
# ══════════════════════════════════════════════════
with tab_cedi:
    usuario_cedi = st.session_state.get("usuario_actual", "anonimo")

    st.write(
        "A diferencia de Farmacia, aqui se combinan los archivos de **varios auditores**, "
        "agrupados por SKU + Bodega. Un reconteo **sustituye** (no se suma) al conteo inicial "
        "de ese mismo SKU+Bodega."
    )

    if "cedi_existencia" not in st.session_state:
        st.session_state.cedi_existencia = None
    if "cedi_auditores" not in st.session_state:
        st.session_state.cedi_auditores = []
    if "cedi_resultados" not in st.session_state:
        st.session_state.cedi_resultados = None
    if "cedi_conteo_solo" not in st.session_state:
        st.session_state.cedi_conteo_solo = None

    # ────────────────────────────────────────────
    # PASO 1: EXISTENCIA CEDI
    # ────────────────────────────────────────────
    st.markdown("### Paso 1 — Existencia CEDI")
    archivo_existencia_cedi = st.file_uploader(
        "Archivo de Existencia CEDI (CSV)", type="csv", key="up_existencia_cedi"
    )
    if archivo_existencia_cedi is not None:
        try:
            st.session_state.cedi_existencia = mc.cargar_existencia_cedi(archivo_existencia_cedi.getvalue())
            info = st.session_state.cedi_existencia
            st.success(f"✅ Existencia CEDI cargada — {info['total']} registros")
            c1, c2 = st.columns(2)
            c1.write(f"**Casas/Laboratorios detectados:** {len(info['casas'])}")
            c2.write(f"**Bodegas detectadas:** {', '.join(info['bodegas'])}")

            c3, c4, c5 = st.columns(3)
            c3.metric("Padres", len(info["padres"]))
            c4.metric("Hijos", len(info["hijos"]))
            c5.metric("Negativos", len(info["negativos"]))

            colp, colh, coln = st.columns(3)
            with colp:
                contenido, nombre = mc.generar_csv_handheld(info["padres"], "CEDI", "padres")
                st.download_button("⬇ PADRES.csv (Handheld)", contenido, file_name=nombre,
                                    mime="text/csv", key="dl_padres_cedi")
            with colh:
                contenido, nombre = mc.generar_csv_handheld(info["hijos"], "CEDI", "hijos")
                st.download_button("⬇ HIJOS.csv (Handheld)", contenido, file_name=nombre,
                                    mime="text/csv", key="dl_hijos_cedi")
            with coln:
                contenido, nombre = mc.generar_csv_handheld(info["negativos"], "CEDI", "negativos")
                st.download_button("⬇ NEGATIVOS.csv (Handheld)", contenido, file_name=nombre,
                                    mime="text/csv", key="dl_negativos_cedi")
        except Exception as e:
            st.error(f"❌ {e}")

    st.divider()

    # ────────────────────────────────────────────
    # PASO 2: ARCHIVOS DE CONTEO (varios auditores a la vez)
    # ────────────────────────────────────────────
    st.markdown("### Paso 2 — Conteos de los Auditores")
    st.caption("Sube todos los archivos de los auditores de una vez, separados en Iniciales y Reconteos.")

    col_ini, col_rec = st.columns(2)
    with col_ini:
        archivos_iniciales_cedi = st.file_uploader(
            "Conteos INICIALES (puedes seleccionar varios a la vez)",
            type="csv", key="up_iniciales_cedi", accept_multiple_files=True,
        )
    with col_rec:
        archivos_reconteo_cedi = st.file_uploader(
            "Conteos de RECONTEO (opcional, puedes seleccionar varios)",
            type="csv", key="up_reconteo_cedi", accept_multiple_files=True,
        )

    if st.button("➕ Procesar y agregar estos archivos", type="primary"):
        nuevos, errores = [], []
        for archivo in (archivos_iniciales_cedi or []):
            try:
                nuevos.append(mc.procesar_archivo_auditor(archivo.getvalue(), archivo.name, tipo="inicial"))
            except Exception as e:
                errores.append(f"{archivo.name}: {e}")
        for archivo in (archivos_reconteo_cedi or []):
            try:
                nuevos.append(mc.procesar_archivo_auditor(archivo.getvalue(), archivo.name, tipo="reconteo"))
            except Exception as e:
                errores.append(f"{archivo.name}: {e}")

        st.session_state.cedi_auditores.extend(nuevos)
        if nuevos:
            st.success(f"✅ Se agregaron {len(nuevos)} archivo(s) correctamente.")
        for err in errores:
            st.error(f"❌ {err}")
        if nuevos or errores:
            st.rerun()

    if st.session_state.cedi_auditores:
        st.write("**Auditores cargados hasta ahora:**")
        df_auditores = pd.DataFrame([
            {
                "Auditor": a["nombre_auditor"], "Tipo": a["tipo"], "Archivo": a["archivo"],
                "Filas": len(a["filas"]), "Unidades": a["total_unidades"],
            }
            for a in st.session_state.cedi_auditores
        ])
        st.dataframe(df_auditores, use_container_width=True, hide_index=True)

        if st.button("🗑 Quitar todos los auditores"):
            st.session_state.cedi_auditores = []
            st.rerun()

    st.divider()

    # ────────────────────────────────────────────
    # PASO 3: CONSOLIDAR
    # ────────────────────────────────────────────
    st.markdown("### Paso 3 — Consolidar")

    nivel_consolidacion = st.radio(
        "Nivel de consolidación",
        ["Solo por SKU (recomendado)", "Por SKU + Bodega exacta"],
        horizontal=True,
        help=(
            "Si el nombre de la bodega viene distinto entre el archivo de Existencia "
            "y el de Conteo (ej: 'CENTRO DE DISTRIBUCION - 900' vs "
            "'CENTRO DISTRIBUCIÓN KIELSA - 9'), usa 'Solo por SKU' para evitar que un "
            "mismo producto aparezca como Faltante Y Fuera de Existencia a la vez."
        ),
        key="nivel_consolidacion_cedi",
    )
    nivel_cedi = "sku" if nivel_consolidacion.startswith("Solo por SKU") else "sku_bodega"

    puede_consolidar = bool(st.session_state.cedi_existencia and st.session_state.cedi_auditores)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Consolidar contra Existencia", type="primary", disabled=not puede_consolidar):
            st.session_state.cedi_resultados = mc.consolidar_cedi(
                st.session_state.cedi_existencia, st.session_state.cedi_auditores, nivel=nivel_cedi
            )
            st.rerun()
    with col_btn2:
        if st.button("📋 Solo generar Conteo Consolidado", disabled=not bool(st.session_state.cedi_auditores)):
            conteo_solo = mc.consolidar_solo_conteo(st.session_state.cedi_auditores, nivel=nivel_cedi)
            df_conteo_solo = pd.DataFrame(conteo_solo)
            st.session_state.cedi_conteo_solo = df_conteo_solo

    if st.session_state.get("cedi_conteo_solo") is not None:
        st.write("**Conteo consolidado (sin comparar contra existencia):**")
        st.dataframe(st.session_state.cedi_conteo_solo, use_container_width=True, height=300)
        csv_conteo_solo = st.session_state.cedi_conteo_solo.to_csv(index=False, sep=";")
        st.download_button(
            "⬇ Descargar Conteo Consolidado (CSV)",
            csv_conteo_solo, file_name="CONTEO_CONSOLIDADO_CEDI.csv", mime="text/csv",
            key="dl_conteo_solo_cedi",
        )

    if not puede_consolidar:
        faltantes_msg = []
        if not st.session_state.cedi_existencia:
            faltantes_msg.append("la Existencia CEDI (Paso 1)")
        if not st.session_state.cedi_auditores:
            faltantes_msg.append("al menos un archivo de auditor procesado correctamente (Paso 2)")
        st.info(f"⏳ Todavia falta: {' y '.join(faltantes_msg)}.")

    # ────────────────────────────────────────────
    # RESULTADOS
    # ────────────────────────────────────────────
    if st.session_state.cedi_resultados:
        st.divider()
        st.markdown("### Resultado — Diferencias CEDI")

        resultados_cedi = st.session_state.cedi_resultados

        faltantes_c = [r for r in resultados_cedi if r["estado"] == "FALTANTE"]
        sobrantes_c = [r for r in resultados_cedi if r["estado"] == "SOBRANTE"]
        fuera_c = [r for r in resultados_cedi if r["estado"] == "FUERA_EXISTENCIA"]
        ok_c = [r for r in resultados_cedi if r["estado"] == "OK"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Faltantes", len(faltantes_c))
        c2.metric("Sobrantes", len(sobrantes_c))
        c3.metric("Fuera de Existencia", len(fuera_c))
        c4.metric("OK", len(ok_c))

        df_cedi = pd.DataFrame(resultados_cedi)

        texto_busqueda_cedi = st.text_input(
            "🔍 Buscar SKU, descripcion, casa, bodega...", key="buscar_cedi"
        ).strip().lower()

        casas_disponibles = sorted(df_cedi["casa"].unique())
        filtro_casa = st.multiselect("Filtrar por Casa/Laboratorio", casas_disponibles, key="filtro_casa_cedi")
        filtro_estado_cedi = st.multiselect(
            "Filtrar por estado",
            options=["FALTANTE", "SOBRANTE", "FUERA_EXISTENCIA", "OK"],
            default=["FALTANTE", "SOBRANTE", "FUERA_EXISTENCIA"],
            key="filtro_estado_cedi",
        )

        df_filtrado_cedi = df_cedi
        if filtro_casa:
            df_filtrado_cedi = df_filtrado_cedi[df_filtrado_cedi["casa"].isin(filtro_casa)]
        if filtro_estado_cedi:
            df_filtrado_cedi = df_filtrado_cedi[df_filtrado_cedi["estado"].isin(filtro_estado_cedi)]
        if texto_busqueda_cedi:
            columnas_buscar = ["sku", "desc", "casa", "bodega"]
            mascara = df_filtrado_cedi[columnas_buscar].apply(
                lambda col: col.astype(str).str.lower().str.contains(texto_busqueda_cedi, regex=False)
            ).any(axis=1)
            df_filtrado_cedi = df_filtrado_cedi[mascara]

        st.dataframe(
            df_filtrado_cedi[["sku", "desc", "casa", "bodega", "existencia", "contado",
                               "diferencia", "costo_unitario", "valor_diferencia", "estado",
                               "auditores", "detalle", "fue_reconteo"]],
            use_container_width=True, height=400,
        )

        valor_total_diferencias = df_cedi[df_cedi["diferencia"] != 0]["valor_diferencia"].sum()
        st.metric("💰 Valor total de las diferencias (Faltante+Sobrante)", f"${valor_total_diferencias:,.2f}")

        # Exportamos con el mismo formato/nombres de columna y separador (;)
        # que ya usaban en su formato de "Diferencias CEDI" de referencia.
        df_export_cedi = df_cedi.rename(columns={
            "sku": "SKU", "desc": "Descripcion", "casa": "Casa", "bodega": "Bodega",
            "contado": "Contado_Total", "existencia": "Existencia_Sistema",
            "diferencia": "Diferencia", "estado": "Estado",
            "detalle": "Detalle_Localizaciones", "auditores": "Auditores",
            "fue_reconteo": "Fue_Reconteo", "costo_unitario": "Costo_Unitario",
            "valor_diferencia": "Valor_Diferencia",
        })
        df_export_cedi["Ubicacion_Rack"] = ""  # no se consolida por rack individual, se deja en blanco
        df_export_cedi["Fue_Reconteo"] = df_export_cedi["Fue_Reconteo"].map({True: "SI", False: "NO"})
        columnas_orden = ["SKU", "Descripcion", "Casa", "Bodega", "Contado_Total",
                           "Existencia_Sistema", "Diferencia", "Costo_Unitario", "Valor_Diferencia", "Estado",
                           "Detalle_Localizaciones", "Ubicacion_Rack", "Auditores", "Fue_Reconteo"]

        csv_cedi = df_export_cedi[columnas_orden].to_csv(index=False, sep=";")
        st.download_button(
            "⬇ Descargar tabla completa de resultados CEDI (CSV)",
            csv_cedi, file_name="DIFERENCIAS_CEDI.csv", mime="text/csv",
        )


        if st.button("🗑 Empezar de nuevo (borrar existencia, auditores y resultados)"):
            st.session_state.cedi_existencia = None
            st.session_state.cedi_auditores = []
            st.session_state.cedi_resultados = None
            st.rerun()


# ══════════════════════════════════════════════════
#  PESTAÑA 4: ANALISIS DE DEVOLUCIONES
# ══════════════════════════════════════════════════
with tab_devoluciones:
    st.write(
        "Detecta posibles **devoluciones falsas** usadas para desviar dinero: se anula "
        "una venta (tipo 'DEV' en el Kardex), pero el producto nunca vuelve fisicamente "
        "al inventario, y termina apareciendo como Faltante mas adelante."
    )
    st.caption(
        "Usa un rango de fechas INDEPENDIENTE al de Conciliacion Farmacia -- normalmente "
        "un periodo mas amplio, para poder ver la devolucion y lo que paso despues."
    )

    if "dev_movimientos" not in st.session_state:
        st.session_state.dev_movimientos = None

    # ────────────────────────────────────────────
    # DESCARGAR KARDEX PARA ESTE ANALISIS
    # ────────────────────────────────────────────
    st.markdown("### Descargar Kardex para el analisis")

    col_b, col_fi, col_hi, col_ff, col_hf = st.columns(5)
    with col_b:
        codigo_bodega_dev = st.text_input(
            "Codigo de bodega", placeholder="Ej: K002", key="codigo_bodega_dev"
        ).strip().upper()
    with col_fi:
        fecha_desde_dev = st.date_input("Desde", value=None, key="dev_fecha_desde")
    with col_hi:
        hora_desde_dev = st.time_input("Hora desde", value=None, key="dev_hora_desde")
    with col_ff:
        fecha_hasta_dev = st.date_input("Hasta", value=None, key="dev_fecha_hasta")
    with col_hf:
        hora_hasta_dev = st.time_input("Hora hasta", value=None, key="dev_hora_hasta")

    puede_descargar_dev = bool(codigo_bodega_dev and fecha_desde_dev and fecha_hasta_dev)

    if st.button("🔎 Descargar y Analizar", type="primary", disabled=not puede_descargar_dev):
        caja_dev = st.empty()
        barra_dev = st.progress(0, text="Iniciando...")
        contador_dev = {"actual": 0}

        def avisar_dev(msg):
            contador_dev["actual"] = min(contador_dev["actual"] + 1, 9)
            caja_dev.info(msg)
            barra_dev.progress(int(contador_dev["actual"] / 10 * 100), text=msg)

        try:
            dt_desde_dev = datetime.combine(fecha_desde_dev, hora_desde_dev or datetime.min.time())
            dt_hasta_dev = datetime.combine(fecha_hasta_dev, hora_hasta_dev or datetime.max.time().replace(microsecond=0))

            ruta_kardex_dev = descargar_kardex(
                codigo_bodega_dev, fecha_desde_dev, fecha_hasta_dev,
                callback_progreso=avisar_dev, headless=True,
            )
            with open(ruta_kardex_dev, "rb") as f:
                bytes_kardex_dev = f.read()

            st.session_state.dev_movimientos = mf.cargar_kardex_movimientos_detallados(
                bytes_kardex_dev, dt_desde_dev, dt_hasta_dev
            )
            barra_dev.progress(100, text="¡Listo!")
            st.success(f"✅ Kardex descargado — {len(st.session_state.dev_movimientos)} movimientos en el rango.")
            st.rerun()
        except Exception as error:
            barra_dev.empty()
            st.error(f"❌ Ocurrio un problema: {error}")

    with st.expander("O sube un archivo de Kardex manualmente"):
        archivo_kardex_dev = st.file_uploader("Archivo de Kardex (CSV)", type="csv", key="up_kardex_dev")
        if archivo_kardex_dev is not None:
            try:
                dt_desde_dev = datetime.combine(fecha_desde_dev, hora_desde_dev or datetime.min.time()) if fecha_desde_dev else None
                dt_hasta_dev = datetime.combine(fecha_hasta_dev, hora_hasta_dev or datetime.max.time().replace(microsecond=0)) if fecha_hasta_dev else None
                st.session_state.dev_movimientos = mf.cargar_kardex_movimientos_detallados(
                    archivo_kardex_dev.getvalue(), dt_desde_dev, dt_hasta_dev
                )
                st.success(f"✅ Kardex cargado — {len(st.session_state.dev_movimientos)} movimientos en el rango.")
            except Exception as e:
                st.error(f"❌ {e}")

    st.divider()

    # ────────────────────────────────────────────
    # ANALISIS Y RESULTADOS
    # ────────────────────────────────────────────
    if st.session_state.dev_movimientos:
        st.markdown("### Resultado del Analisis")

        faltantes_disponibles = st.session_state.get("farm_resultados_reales")
        origen_faltantes = "ninguno"
        faltantes_set = set()

        if faltantes_disponibles:
            faltantes_set = {r["sku"] for r in faltantes_disponibles if r["estado"] == "FALTANTE"}
            farmacia_origen = st.session_state.get("farm_resultados_reales_farmacia", "")
            origen_faltantes = f"Diferencias Reales de Farmacia ({farmacia_origen}) — {len(faltantes_set)} SKUs Faltantes"
        else:
            st.warning(
                "⚠️ Aun no has calculado 'Diferencias Reales' en la pestaña Farmacia. "
                "El Cruce #2 (contra el Faltante del inventario) estara vacio hasta que lo hagas, "
                "o puedes subir una lista de SKUs Faltantes aparte."
            )
            archivo_faltantes_manual = st.file_uploader(
                "O sube un CSV con una columna 'sku' de Faltantes (opcional)", type="csv", key="up_faltantes_manual"
            )
            if archivo_faltantes_manual is not None:
                try:
                    df_falt_manual = pd.read_csv(archivo_faltantes_manual)
                    columna_sku = next((c for c in df_falt_manual.columns if c.strip().lower() == "sku"), None)
                    if columna_sku:
                        faltantes_set = set(df_falt_manual[columna_sku].astype(str).str.strip())
                        origen_faltantes = f"Archivo subido manualmente — {len(faltantes_set)} SKUs"
                    else:
                        st.error("El archivo no tiene una columna llamada 'sku'.")
                except Exception as e:
                    st.error(f"❌ {e}")

        analisis = mf.analizar_devoluciones(st.session_state.dev_movimientos, faltantes_set)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Devoluciones (DEV)", analisis["total_devoluciones"])
        c2.metric("Ajustes manuales (MIN)", analisis["total_ajustes_manuales"])
        c3.metric("🚩 Cruce con Ajustes", len(analisis["cruce_ajustes"]))
        c4.metric("🚩 Cruce con Faltante", len(analisis["cruce_inventario"]))
        st.caption(f"Faltante usado para el Cruce #2: {origen_faltantes}")

        # ────────────────────────────────────────────
        # INFORME COMPLETO DE DEVOLUCIONES (detalle, para descargar)
        # ────────────────────────────────────────────
        st.markdown("#### 📄 Informe Completo de Devoluciones")
        st.caption(
            "El detalle de TODAS las devoluciones del rango, con la alerta que le "
            "corresponda a cada una (si tuvo ajuste posterior, si salio Faltante en el "
            "conteo, ambas, o ninguna)."
        )

        df_detalle_dev = pd.DataFrame(analisis["detalle_devoluciones"])
        if not df_detalle_dev.empty:
            solo_con_alerta = st.checkbox("Mostrar solo las que tienen alguna alerta 🚩", value=False, key="solo_alerta_dev")
            df_mostrar_dev = df_detalle_dev[df_detalle_dev["alerta"] != ""] if solo_con_alerta else df_detalle_dev
            st.dataframe(df_mostrar_dev, use_container_width=True, height=350)

            col_csv, col_xlsx = st.columns(2)
            with col_csv:
                st.download_button(
                    "⬇ Descargar Informe (CSV)",
                    df_detalle_dev.to_csv(index=False),
                    file_name="informe_devoluciones.csv", mime="text/csv", key="dl_informe_dev_csv",
                )
            with col_xlsx:
                buffer_excel = io.BytesIO()
                with pd.ExcelWriter(buffer_excel, engine="openpyxl") as writer:
                    df_detalle_dev.to_excel(writer, index=False, sheet_name="Devoluciones")

                    # Activamos "ajustar texto" en la columna de fecha, para que
                    # el salto de linea (fecha devolucion + fecha ajuste debajo)
                    # se vea correctamente al abrir el archivo en Excel.
                    from openpyxl.styles import Alignment
                    hoja = writer.sheets["Devoluciones"]
                    columna_fecha_idx = list(df_detalle_dev.columns).index("fecha_devolucion") + 1
                    for fila in range(2, len(df_detalle_dev) + 2):
                        celda = hoja.cell(row=fila, column=columna_fecha_idx)
                        celda.alignment = Alignment(wrap_text=True, vertical="top")
                    hoja.column_dimensions[hoja.cell(row=1, column=columna_fecha_idx).column_letter].width = 28

                    if analisis["cruce_ajustes"]:
                        pd.DataFrame(analisis["cruce_ajustes"]).to_excel(writer, index=False, sheet_name="Cruce Ajustes")
                    if analisis["cruce_inventario"]:
                        pd.DataFrame(analisis["cruce_inventario"]).to_excel(writer, index=False, sheet_name="Cruce Faltante")
                st.download_button(
                    "⬇ Descargar Informe (Excel, 3 hojas)",
                    buffer_excel.getvalue(),
                    file_name="informe_devoluciones.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_informe_dev_xlsx",
                )
        else:
            st.info("No hay devoluciones en este rango de fechas.")

        st.divider()

        st.markdown("#### 🚩 Resumen 1 — Devoluciones con Ajuste por Faltante posterior")
        st.caption(
            "Se anulo una venta (DEV) y despues alguien (no el sistema) ajusto ese mismo "
            "SKU como faltante. Revisar quien hizo el ajuste y por que."
        )
        if analisis["cruce_ajustes"]:
            df_cruce1 = pd.DataFrame(analisis["cruce_ajustes"])
            st.dataframe(df_cruce1, use_container_width=True, height=300)
            st.download_button(
                "⬇ Descargar Resumen 1 (CSV)", df_cruce1.to_csv(index=False),
                file_name="devoluciones_vs_ajustes.csv", mime="text/csv", key="dl_cruce_ajustes",
            )
        else:
            st.info("No se encontraron coincidencias en este cruce.")

        st.markdown("#### 🚩 Resumen 2 — Devoluciones que terminaron como Faltante en el conteo")
        st.caption(
            "El producto se 'devolvio' segun el sistema, pero el auditor no lo encontro "
            "fisicamente durante su conteo."
        )
        if analisis["cruce_inventario"]:
            df_cruce2 = pd.DataFrame(analisis["cruce_inventario"])
            st.dataframe(df_cruce2, use_container_width=True, height=300)
            st.download_button(
                "⬇ Descargar Resumen 2 (CSV)", df_cruce2.to_csv(index=False),
                file_name="devoluciones_vs_faltante_inventario.csv", mime="text/csv", key="dl_cruce_inventario",
            )
        else:
            st.info("No se encontraron coincidencias en este cruce.")

        if st.button("🗑 Empezar de nuevo (borrar Kardex de este analisis)"):
            st.session_state.dev_movimientos = None
            st.rerun()
    else:
        st.info("⏳ Descarga o sube un Kardex arriba para ver el analisis.")