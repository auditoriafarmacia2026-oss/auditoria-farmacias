"""
Modulo con la logica del robot de automatizacion.
Separado de la interfaz (terminal o web) para poder reutilizarlo
desde cualquier lado sin duplicar codigo.
"""

import os
import subprocess
import sys
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
USUARIO = os.getenv("LDCOM_USUARIO")
PASSWORD = os.getenv("LDCOM_PASSWORD")
URL = os.getenv("LDCOM_URL")

CARPETA_DESCARGAS = os.path.join(os.path.expanduser("~"), "Downloads")
os.makedirs(CARPETA_DESCARGAS, exist_ok=True)

MAX_INTENTOS = 3


def _asegurar_navegador_instalado():
    """En un servidor nuevo (como Streamlit Cloud), el navegador Chromium
    de Playwright no viene instalado de fabrica. Esta funcion lo instala
    la primera vez que se necesita, y no hace nada las veces siguientes."""
    marcador = os.path.join(os.path.expanduser("~"), ".playwright_instalado")
    if os.path.exists(marcador):
        return
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    with open(marcador, "w") as f:
        f.write("ok")


def _esperar_texto(pagina, texto, timeout_seg):
    for _ in range(timeout_seg):
        try:
            if texto in pagina.content():
                return True
        except Exception:
            pass
        pagina.wait_for_timeout(1000)
    return False


def _establecer_fecha_input(pagina, locator, texto_fecha):
    """Los campos de fecha son de 'solo lectura' (readonly) para el usuario,
    pero se les puede asignar el valor directamente via JavaScript, disparando
    los eventos que el sitio necesita para darse cuenta del cambio."""
    locator.click()  # abre el calendario emergente (queda abierto, no afecta)
    pagina.wait_for_timeout(300)
    locator.evaluate(
        """(el, val) => {
            el.value = val;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            if (window.jQuery) {
                try { jQuery(el).trigger('changeDate'); } catch (e) {}
            }
        }""",
        texto_fecha,
    )
    pagina.keyboard.press("Escape")  # cierra el calendario emergente si sigue abierto
    pagina.wait_for_timeout(300)


def _click_link_con_espera(pagina, nombre_link, timeout_seg=15):
    enlace = pagina.get_by_role("link", name=nombre_link)
    for _ in range(timeout_seg):
        if enlace.count() > 0 and enlace.first.is_visible():
            enlace.first.click()
            return True
        pagina.wait_for_timeout(1000)
    return False


def _marcar_checkbox_con_reintentos(pagina, locator_filas, cantidad, boton, max_intentos=3):
    for i in range(min(cantidad, max_intentos)):
        locator_filas.nth(i).locator(".icon.check-icon").click()
        pagina.wait_for_timeout(1200)
        if boton.is_enabled():
            return True
    return False


def _buscar_y_seleccionar_bodega(pagina, codigo_bodega, avisar):
    """Escribe el codigo de bodega, espera el resultado y marca el checkbox.
    Compartido por Existencia y Kardex (misma pantalla de seleccion de bodega)."""
    resultado_encontrado = False
    for intento in range(1, MAX_INTENTOS + 1):
        avisar(f"Buscando bodega {codigo_bodega} (intento {intento}/{MAX_INTENTOS})...")
        campo_busqueda = pagina.locator("#bodegaBusqueda")
        campo_busqueda.click()
        campo_busqueda.fill("")
        campo_busqueda.press_sequentially(codigo_bodega, delay=150)
        pagina.locator("#btnBuscarBodegaNombre").click()
        if _esperar_texto(pagina, "KIELSA", timeout_seg=20):
            resultado_encontrado = True
            break
    if not resultado_encontrado:
        raise Exception(f"No se encontro la bodega '{codigo_bodega}'. Verifica el codigo.")

    fila_resultado = pagina.locator("li", has_text=codigo_bodega)
    boton_siguiente = pagina.get_by_role("button", name="Siguiente")
    if not _marcar_checkbox_con_reintentos(pagina, fila_resultado, fila_resultado.count(), boton_siguiente):
        raise Exception(f"No se pudo seleccionar la bodega '{codigo_bodega}'.")

    boton_siguiente.click()
    avisar(f"Bodega {codigo_bodega} seleccionada.")
    pagina.wait_for_timeout(1500)


def _generar_y_exportar_csv(pagina, nombre_archivo, avisar):
    """Hace clic en 'Generar Reporte', espera a que termine de renderizar,
    y lo exporta como CSV. Compartido por todos los tipos de reporte."""
    _esperar_texto(pagina, "Generar Reporte", timeout_seg=15)
    with pagina.expect_popup() as info_popup:
        pagina.get_by_role("button", name="Generar Reporte").click()
    pagina_reporte = info_popup.value
    pagina_reporte.wait_for_load_state()
    avisar("Reporte generandose...")

    for _ in range(30):
        try:
            contenido = pagina_reporte.content()
            if "Reporte N" in contenido and "Loading..." not in contenido:
                break
        except Exception:
            pass
        pagina_reporte.wait_for_timeout(1000)
    pagina_reporte.wait_for_timeout(1000)

    avisar("Exportando a CSV...")
    pagina_reporte.get_by_role("link", name="Export drop down menu Export").click()
    pagina_reporte.wait_for_timeout(1500)

    with pagina_reporte.expect_download() as info_descarga:
        with pagina_reporte.expect_popup() as info_popup2:
            pagina_reporte.get_by_role("link", name="CSV (delimitado por comas)").click()
        pagina_extra = info_popup2.value

    descarga = info_descarga.value
    pagina_extra.close()

    ruta_final = os.path.join(CARPETA_DESCARGAS, nombre_archivo)
    descarga.save_as(ruta_final)

    ruta_absoluta = os.path.abspath(ruta_final)
    if not os.path.exists(ruta_absoluta):
        raise Exception("El archivo no se guardo correctamente.")

    avisar(f"Reporte descargado: {ruta_absoluta}")
    return ruta_absoluta


def descargar_existencia_por_categoria(codigo_bodega, callback_progreso=None, headless=True):
    """
    Descarga el Reporte de Existencias por Categoria para una bodega dada.

    codigo_bodega: por ejemplo "K002", "K018"
    callback_progreso: funcion opcional que recibe un texto de estado,
                        para mostrar el avance en una interfaz (web o terminal)
    headless: si True, el navegador corre invisible (recomendado para la app);
              si False, se ve la ventana del navegador (util para probar/depurar)

    Devuelve: la ruta absoluta del archivo CSV descargado.
    Lanza una excepcion (Exception) si algo falla, con un mensaje claro.
    """
    def avisar(mensaje):
        if callback_progreso:
            callback_progreso(mensaje)
        else:
            print(mensaje)

    codigo_bodega = codigo_bodega.strip().upper()
    _asegurar_navegador_instalado()

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=headless)
        contexto = navegador.new_context()
        pagina = contexto.new_page()

        try:
            avisar("Entrando al portal...")
            pagina.goto(URL)

            pagina.get_by_role("textbox", name="Usuario").fill(USUARIO)
            pagina.get_by_role("textbox", name="Usuario").press("Tab")
            pagina.get_by_role("textbox", name="Contraseña").fill(PASSWORD)
            pagina.get_by_role("textbox", name="Contraseña").press("Enter")
            avisar("Sesion iniciada.")

            lista_cargada = False
            for intento in range(1, MAX_INTENTOS + 1):
                avisar(f"Navegando al reporte (intento {intento}/{MAX_INTENTOS})...")
                pagina.get_by_role("textbox", name="Filtrar Menús .").click()
                pagina.wait_for_timeout(500)
                navego_bien = True
                for nombre, espera in [("Reportes", 800), ("Inventario", 800),
                                        ("Existencias ", 800), ("Por Categoría", 0)]:
                    if not _click_link_con_espera(pagina, nombre):
                        navego_bien = False
                        break
                    pagina.wait_for_timeout(espera)
                if navego_bien and _esperar_texto(pagina, "K136", timeout_seg=25):
                    lista_cargada = True
                    break
            if not lista_cargada:
                raise Exception("No se pudo cargar la lista de bodegas. Intenta de nuevo mas tarde.")

            _buscar_y_seleccionar_bodega(pagina, codigo_bodega, avisar)

            _esperar_texto(pagina, "Existencia", timeout_seg=15)
            pagina.get_by_text("Existencia <>").click()
            pagina.wait_for_timeout(500)
            pagina.get_by_role("button", name="Siguiente").click()
            avisar("Filtro de existencia aplicado.")
            pagina.wait_for_timeout(1500)

            _esperar_texto(pagina, "MEDICAMENTOS", timeout_seg=15)
            for selector in ["li:nth-child(4) > .icon.check-icon",
                              "li:nth-child(6) > .icon.check-icon",
                              "li:nth-child(7) > .icon.check-icon"]:
                pagina.locator(selector).click()
                pagina.wait_for_timeout(400)
            pagina.get_by_role("button", name="Siguiente").click()
            avisar("Categorias seleccionadas.")
            pagina.wait_for_timeout(1500)

            _esperar_texto(pagina, "Todos los Artículos", timeout_seg=15)
            pagina.locator(".bootstrap-switch-label").click()
            pagina.wait_for_timeout(500)
            pagina.get_by_role("button", name="Siguiente").click()
            avisar("Preparando generacion del reporte...")
            pagina.wait_for_timeout(1500)

            nombre_archivo = f"existencias_por_categoria_{codigo_bodega}.csv"
            return _generar_y_exportar_csv(pagina, nombre_archivo, avisar)

        finally:
            navegador.close()


def descargar_kardex(codigo_bodega, fecha_inicio, fecha_final, callback_progreso=None, headless=True):
    """
    Descarga el Kardex de Movimientos para una bodega y rango de fechas dado.

    codigo_bodega: por ejemplo "K002", "K018"
    fecha_inicio, fecha_final: objetos date o datetime de Python
                                (ej: datetime(2026, 8, 1))
    callback_progreso: funcion opcional para mostrar el avance
    headless: True = navegador invisible (recomendado), False = se ve la ventana

    Devuelve: la ruta absoluta del archivo CSV descargado.
    """
    def avisar(mensaje):
        if callback_progreso:
            callback_progreso(mensaje)
        else:
            print(mensaje)

    codigo_bodega = codigo_bodega.strip().upper()
    # Formato dia/mes/anio, como se usa en Honduras (ej: 11/08/2026)
    texto_fecha_inicio = fecha_inicio.strftime("%d/%m/%Y")
    texto_fecha_final = fecha_final.strftime("%d/%m/%Y")

    _asegurar_navegador_instalado()

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=headless)
        contexto = navegador.new_context()
        pagina = contexto.new_page()

        try:
            avisar("Entrando al portal...")
            pagina.goto(URL)

            pagina.get_by_role("textbox", name="Usuario").fill(USUARIO)
            pagina.get_by_role("textbox", name="Usuario").press("Tab")
            pagina.get_by_role("textbox", name="Contraseña").fill(PASSWORD)
            pagina.get_by_role("textbox", name="Contraseña").press("Enter")
            avisar("Sesion iniciada.")

            lista_cargada = False
            for intento in range(1, MAX_INTENTOS + 1):
                avisar(f"Navegando al reporte de Kardex (intento {intento}/{MAX_INTENTOS})...")
                pagina.get_by_role("textbox", name="Filtrar Menús .").click()
                pagina.wait_for_timeout(500)
                navego_bien = True
                for nombre, espera in [("Reportes", 800), ("Inventario", 800),
                                        ("Movimientos ", 800), ("Kardex", 0)]:
                    if not _click_link_con_espera(pagina, nombre):
                        navego_bien = False
                        break
                    pagina.wait_for_timeout(espera)
                if navego_bien and _esperar_texto(pagina, "K136", timeout_seg=25):
                    lista_cargada = True
                    break
            if not lista_cargada:
                raise Exception("No se pudo cargar la lista de bodegas. Intenta de nuevo mas tarde.")

            _buscar_y_seleccionar_bodega(pagina, codigo_bodega, avisar)

            # Pantalla siguiente del Kardex (switch, igual patron que Existencia)
            _esperar_texto(pagina, "Siguiente", timeout_seg=15)
            pagina.locator(".bootstrap-switch-label").click()
            pagina.wait_for_timeout(500)
            pagina.get_by_role("button", name="Siguiente").click()
            avisar("Avanzando a seleccion de fechas...")
            pagina.wait_for_timeout(1500)

            # --- RANGO DE FECHAS ---
            avisar(f"Escribiendo fechas: {texto_fecha_inicio} a {texto_fecha_final}...")
            campo_inicio = pagina.get_by_role("textbox", name="Fecha Inicio:")
            _establecer_fecha_input(pagina, campo_inicio, texto_fecha_inicio)

            campo_final = pagina.get_by_role("textbox", name="Fecha Final:")
            _establecer_fecha_input(pagina, campo_final, texto_fecha_final)

            valor_real_inicio = campo_inicio.input_value()
            valor_real_final = campo_final.input_value()
            avisar(f"Fechas confirmadas en pantalla: {valor_real_inicio} a {valor_real_final}")

            pagina.get_by_role("button", name="Siguiente").click()
            avisar("Fechas aplicadas. Preparando reporte...")
            pagina.wait_for_timeout(1500)

            nombre_archivo = f"kardex_{codigo_bodega}_{fecha_inicio.strftime('%Y%m%d')}_{fecha_final.strftime('%Y%m%d')}.csv"
            return _generar_y_exportar_csv(pagina, nombre_archivo, avisar)

        finally:
            navegador.close()