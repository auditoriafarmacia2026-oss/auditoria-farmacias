"""
PASO 1: Robot de descarga automatica del Reporte de Existencias por Categoria
Portal: LDCOM (Kielsa Farmaceutica)

Este script:
1. Inicia sesion en el portal
2. Navega hasta Reportes > Inventario > Existencias > Por Categoria
3. Selecciona la bodega K002
4. Filtra por Existencia <> 0
5. Selecciona las categorias: Consumo, Medicamentos, Otros
6. Incluye todos los articulos
7. Genera el reporte y lo descarga como CSV en la carpeta "descargas"
"""

import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# --- Configuracion ---
load_dotenv()
USUARIO = os.getenv("LDCOM_USUARIO")
PASSWORD = os.getenv("LDCOM_PASSWORD")
URL = os.getenv("LDCOM_URL")

CARPETA_DESCARGAS = os.path.join(os.path.expanduser("~"), "Downloads")
os.makedirs(CARPETA_DESCARGAS, exist_ok=True)

MAX_INTENTOS = 3  # cuantas veces reintentar pasos que dependen de la velocidad del servidor


def esperar_texto(pagina, texto, timeout_seg):
    """Revisa el HTML de la pagina cada segundo, hasta encontrar el texto dado
    o hasta agotar el tiempo. El sitio web tarda un tiempo variable en cargar,
    asi que esto es mas confiable que una pausa fija."""
    for _ in range(timeout_seg):
        try:
            if texto in pagina.content():
                return True
        except Exception:
            pass  # la pagina puede estar navegando justo en este instante; se ignora y se reintenta
        pagina.wait_for_timeout(1000)
    return False


def click_link_con_espera(pagina, nombre_link, timeout_seg=15):
    """Espera a que un enlace del menu este visible antes de hacer clic."""
    enlace = pagina.get_by_role("link", name=nombre_link)
    for _ in range(timeout_seg):
        if enlace.count() > 0 and enlace.first.is_visible():
            enlace.first.click()
            return True
        pagina.wait_for_timeout(1000)
    return False


def navegar_al_reporte(pagina):
    """Navega desde el menu principal hasta la pantalla 'Por Categoria'."""
    pagina.get_by_role("textbox", name="Filtrar Menús .").click()
    pagina.wait_for_timeout(500)
    for nombre, espera in [("Reportes", 800), ("Inventario", 800),
                            ("Existencias ", 800), ("Por Categoría", 0)]:
        if not click_link_con_espera(pagina, nombre):
            return False
        pagina.wait_for_timeout(espera)
    return True


def marcar_checkbox_con_reintentos(pagina, locator_filas, cantidad, boton_a_habilitar, max_intentos=3):
    """Prueba marcar el checkbox de cada fila candidata hasta que el
    boton 'Siguiente' se habilite (a veces la fila correcta no es la primera)."""
    for i in range(min(cantidad, max_intentos)):
        locator_filas.nth(i).locator(".icon.check-icon").click()
        pagina.wait_for_timeout(1200)
        if boton_a_habilitar.is_enabled():
            return True
    return False


def main():
    # Le preguntamos al usuario que bodega quiere descargar, antes de abrir el navegador
    codigo_bodega = input("¿Que codigo de bodega/farmacia quieres descargar? (ej: K002, K018): ").strip().upper()
    if not codigo_bodega:
        print("No se escribio ningun codigo. Cancelando.")
        return
    print(f"Se buscara la bodega: {codigo_bodega}\n")

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=False)
        contexto = navegador.new_context()
        pagina = contexto.new_page()

        print("Entrando al portal...")
        pagina.goto(URL)

        # --- LOGIN ---
        pagina.get_by_role("textbox", name="Usuario").fill(USUARIO)
        pagina.get_by_role("textbox", name="Usuario").press("Tab")
        pagina.get_by_role("textbox", name="Contraseña").fill(PASSWORD)
        pagina.get_by_role("textbox", name="Contraseña").press("Enter")
        print("Login realizado.")

        # --- NAVEGACION + CARGA DE LISTA DE BODEGAS (con reintentos) ---
        lista_cargada = False
        for intento in range(1, MAX_INTENTOS + 1):
            print(f"Navegando al reporte (intento {intento}/{MAX_INTENTOS})...")
            if navegar_al_reporte(pagina) and esperar_texto(pagina, "K136", timeout_seg=25):
                print("Lista de bodegas cargada.")
                lista_cargada = True
                break

        if not lista_cargada:
            print("ERROR: no se pudo cargar la lista de bodegas tras varios intentos.")
            navegador.close()
            return

        # --- BUSCAR Y SELECCIONAR LA BODEGA INDICADA ---
        resultado_encontrado = False
        for intento in range(1, MAX_INTENTOS + 1):
            print(f"Buscando bodega {codigo_bodega} (intento {intento}/{MAX_INTENTOS})...")
            campo_busqueda = pagina.locator("#bodegaBusqueda")
            campo_busqueda.click()
            campo_busqueda.fill("")
            campo_busqueda.press_sequentially(codigo_bodega, delay=150)  # tecleo real, letra por letra
            pagina.locator("#btnBuscarBodegaNombre").click()
            if esperar_texto(pagina, "KIELSA", timeout_seg=20):
                print(f"Bodega {codigo_bodega} encontrada.")
                resultado_encontrado = True
                break

        if not resultado_encontrado:
            print(f"ERROR: no se encontro la bodega {codigo_bodega}.")
            navegador.close()
            return

        fila_resultado = pagina.locator("li", has_text=codigo_bodega)
        boton_siguiente = pagina.get_by_role("button", name="Siguiente")

        if not marcar_checkbox_con_reintentos(pagina, fila_resultado, fila_resultado.count(), boton_siguiente):
            print(f"ERROR: no se pudo marcar la bodega {codigo_bodega}.")
            navegador.close()
            return

        boton_siguiente.click()
        print(f"Bodega {codigo_bodega} seleccionada.")
        pagina.wait_for_timeout(1500)

        # --- EXISTENCIA <> 0 ---
        esperar_texto(pagina, "Existencia", timeout_seg=15)
        pagina.get_by_text("Existencia <>").click()
        pagina.wait_for_timeout(500)
        pagina.get_by_role("button", name="Siguiente").click()
        print("Filtro 'Existencia <> 0' aplicado.")
        pagina.wait_for_timeout(1500)

        # --- CATEGORIAS: Consumo, Medicamentos, Otros ---
        esperar_texto(pagina, "MEDICAMENTOS", timeout_seg=15)
        for selector in ["li:nth-child(4) > .icon.check-icon",
                          "li:nth-child(6) > .icon.check-icon",
                          "li:nth-child(7) > .icon.check-icon"]:
            pagina.locator(selector).click()
            pagina.wait_for_timeout(400)
        pagina.get_by_role("button", name="Siguiente").click()
        print("Categorias seleccionadas (Consumo, Medicamentos, Otros).")
        pagina.wait_for_timeout(1500)

        # --- TODOS LOS ARTICULOS: SI ---
        esperar_texto(pagina, "Todos los Artículos", timeout_seg=15)
        pagina.locator(".bootstrap-switch-label").click()
        pagina.wait_for_timeout(500)
        pagina.get_by_role("button", name="Siguiente").click()
        print("'Todos los articulos' activado.")
        pagina.wait_for_timeout(1500)

        # --- GENERAR REPORTE ---
        esperar_texto(pagina, "Generar Reporte", timeout_seg=15)
        with pagina.expect_popup() as info_popup:
            pagina.get_by_role("button", name="Generar Reporte").click()
        pagina_reporte = info_popup.value
        pagina_reporte.wait_for_load_state()
        print("Reporte generado en nueva pestaña.")

        # Esperamos a que el reporte TERMINE de renderizarse (no solo que se abra)
        print("Esperando a que el reporte termine de generarse...")
        for _ in range(30):
            try:
                contenido = pagina_reporte.content()
                if "Reporte N" in contenido and "Loading..." not in contenido:
                    break
            except Exception:
                pass  # pagina navegando en ese instante; normal, se reintenta
            pagina_reporte.wait_for_timeout(1000)
        pagina_reporte.wait_for_timeout(1000)

        # --- EXPORTAR COMO CSV ---
        pagina_reporte.get_by_role("link", name="Export drop down menu Export").click()
        pagina_reporte.wait_for_timeout(1500)

        with pagina_reporte.expect_download() as info_descarga:
            with pagina_reporte.expect_popup() as info_popup2:
                pagina_reporte.get_by_role("link", name="CSV (delimitado por comas)").click()
            pagina_extra = info_popup2.value

        descarga = info_descarga.value
        pagina_extra.close()

        nombre_archivo = f"existencias_por_categoria_{codigo_bodega}.csv"
        ruta_final = os.path.join(CARPETA_DESCARGAS, nombre_archivo)
        descarga.save_as(ruta_final)

        ruta_absoluta = os.path.abspath(ruta_final)
        if os.path.exists(ruta_absoluta):
            print(f"\n✅ REPORTE DESCARGADO EXITOSAMENTE EN: {ruta_absoluta}")
        else:
            print(f"\n❌ ERROR: el archivo no se guardo correctamente en {ruta_absoluta}")

        navegador.close()


if __name__ == "__main__":
    main()