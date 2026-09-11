"""
Modulo de conciliacion de inventario - FARMACIA
Traduccion a Python de la logica de KielsaControlInventarios.html (modulo Farmacia),
para integrarla directamente en la app de Streamlit del robot.

Formulas y comportamiento identicos a la version web original:
- Paso 1: Existencia del sistema (separa en Padres / Hijos / Negativos)
- Paso 2: Kardex de movimientos (filtrado por ventana de fecha inicio-corte)
- Paso 3: Conteo fisico de auditores (+ reconteos que sustituyen al conteo inicial)
- Paso 4: Listados de Corto Vence / Excesos (para rebajar sobrantes aparentes)
- Calculo final de diferencias con la formula de 3 ramas
"""

import csv
import io
import re
from datetime import datetime

import streamlit as st


def _detectar_delimitador(contenido_texto):
    """Detecta si el archivo usa coma o punto y coma como separador real.
    Algunos reportes de LDCOM usan punto y coma (y coma como separador de
    miles dentro de los numeros, ej: '20,000.00'), y otros usan coma normal.
    Buscamos la fila del encabezado real (la que tiene 'Articulo_Id' o 'SKU')
    y comparamos cual separador aparece mas veces ahi."""
    lineas_muestra = contenido_texto.split("\n")[:20]
    linea_encabezado = None
    for linea in lineas_muestra:
        if "Articulo_Id" in linea or "SKU" in linea:
            linea_encabezado = linea
            break
    if linea_encabezado is None:
        linea_encabezado = lineas_muestra[0] if lineas_muestra else ""
    return ";" if linea_encabezado.count(";") > linea_encabezado.count(",") else ","


def _parsear_csv_texto(contenido_texto):
    """Convierte el texto de un CSV en una lista de listas (filas de columnas),
    detectando automaticamente si el separador real es ',' o ';'."""
    delimitador = _detectar_delimitador(contenido_texto)
    lector = csv.reader(io.StringIO(contenido_texto), delimiter=delimitador)
    return list(lector)


def _leer_texto_archivo(bytes_archivo):
    """Detecta si el archivo tiene BOM UTF-8; si no, usa windows-1252 (latin1),
    igual que la funcion leerArchivoSmart original, para soportar acentos
    sin importar el sistema de origen del CSV."""
    if bytes_archivo[:3] == b"\xef\xbb\xbf":
        return bytes_archivo.decode("utf-8-sig")
    try:
        return bytes_archivo.decode("windows-1252")
    except UnicodeDecodeError:
        return bytes_archivo.decode("utf-8", errors="replace")


def _encontrar_encabezado(lineas, columna):
    """Busca la fila que contiene el nombre de columna dado (los reportes de
    LDCOM traen varias filas de titulo/metadata antes del encabezado real)."""
    for i, fila in enumerate(lineas):
        if columna in fila:
            return i
    return -1


def _limpiar_num(valor):
    if valor is None or valor == "":
        return 0.0
    try:
        return float(str(valor).replace(",", ""))
    except ValueError:
        return 0.0


def _parsear_fecha_hora(texto):
    """Parsea fechas tipo 'DD/MM/YYYY HH:MM:SS AM/PM' como las trae el kardex."""
    if not texto:
        return None
    m = re.search(r"(\d+)/(\d+)/(\d+)\s+(\d+):(\d+):(\d+)\s*(AM|PM)?", str(texto), re.IGNORECASE)
    if not m:
        return None
    dia, mes, anio, hora, minuto, seg, ampm = m.groups()
    hora = int(hora)
    if ampm and ampm.upper() == "PM" and hora != 12:
        hora += 12
    if ampm and ampm.upper() == "AM" and hora == 12:
        hora = 0
    try:
        return datetime(int(anio), int(mes), int(dia), hora, int(minuto), int(seg))
    except ValueError:
        return None


def _limpiar_desc_para_handheld(desc):
    """El handheld interpreta comas y comillas como delimitadores de CSV,
    asi que se eliminan de la descripcion."""
    return (desc or "").replace(",", " ").replace('"', "").strip()


# ══════════════════════════════════════════════════
#  DETECCION DE POSIBLES CRUCES (CANJES)
# ══════════════════════════════════════════════════

_STOPLIST_FORMA = {
    "TAB", "CAP", "JBE", "SUSP", "SOL", "AMP", "INY", "COMP", "CREM", "GEL",
    "GOT", "COL", "REC", "EFER", "FCO", "FRASCO", "POM", "OVUL", "PARCHE",
    "SPRAY", "UI", "SACHET", "SOB", "PARCH", "PLUS",
    "ML", "MG", "GR", "GRS", "KG", "L", "LT", "MCG", "MEQ",  # unidades sueltas (ej: tras separar "100MG/ML")
}

# Palabras "calificativo de variante": no representan un componente activo
# distinto, solo una version/presentacion comercial del MISMO producto
# (ej: ALIVIOL FLEX vs ALIVIOL FORTE siguen siendo el mismo medicamento).
_CALIFICATIVOS_VARIANTE = {
    "FORTE", "FLEX", "EXTRA", "MAX", "PLUS", "COMPUESTO", "NF", "DUO",
    "RAPID", "NIGHT", "DAY", "ORIGINAL", "MEDICADO", "NEUTRO", "SUAVE",
    "INTENSO", "ACTIVO", "TOTAL", "COMPLETE", "ADVANCE", "PREMIUM",
}


def _tokens_core(desc):
    """Extrae las palabras 'importantes' de una descripcion, quitando
    dosis (250MG), presentaciones (X36, X50) y formas farmaceuticas (TAB, CAP)."""
    texto = (desc or "").upper()
    texto = texto.replace("+", " ").replace("/", " ")
    crudos = re.split(r"\s+", texto.strip())
    core = []
    for t in crudos:
        if not t:
            continue
        if re.match(r"^\d+([.,]\d+)?[A-Z]{0,4}$", t):  # dosis: 250MG, 100ML, 36
            continue
        if re.match(r"^X\d+$", t):  # presentacion: X36, X50
            continue
        if t in _STOPLIST_FORMA:
            continue
        core.append(t)
    return core


def _tokens_coinciden(a, b):
    if a == b:
        return True
    minlen = min(len(a), len(b))
    return minlen >= 4 and (a.startswith(b) or b.startswith(a))


def _similitud_descripciones(desc_a, desc_b):
    """Devuelve un puntaje 0-1 de que tan parecidas son dos descripciones,
    ignorando dosis/presentacion, mas si es un 'cruce especial' (mismo
    componente activo, marca distinta) o normal (misma marca).

    Reglas para evitar falsos positivos:
    1. Se exige al menos UNA coincidencia EXACTA (no solo por prefijo corto),
       para evitar cosas como "VITA SKIN..." vs "VITAFLENACO..." (solo
       comparten un prefijo, son productos distintos).
    2. La coincidencia NO puede ser UNICAMENTE la marca (primera palabra):
       si dos productos comparten marca pero el resto de las palabras son
       completamente distintas (ej: "SWF ACETAMINOFEN" vs "SWF IBUPROFENO"),
       NO se considera cruce -- son dos medicamentos diferentes de la misma
       marca, no una variante del mismo producto.
       EXCEPCION: si la palabra distinta es un calificativo de variante
       conocido (FORTE, FLEX, ORIGINAL, MEDICADO, etc.), si se acepta,
       porque sigue siendo el mismo producto en otra presentacion.
    """
    core_a = _tokens_core(desc_a)
    core_b = _tokens_core(desc_b)
    if not core_a or not core_b:
        return 0, False

    usados_b = set()
    coincidencias = 0
    hubo_coincidencia_exacta = False
    hubo_coincidencia_fuera_de_marca = False

    for idx_a, ta in enumerate(core_a):
        for idx_b, tb in enumerate(core_b):
            if idx_b in usados_b:
                continue
            es_posicion_marca = (idx_a == 0 and idx_b == 0)
            if ta == tb:
                coincidencias += 1
                usados_b.add(idx_b)
                hubo_coincidencia_exacta = True
                if not es_posicion_marca:
                    hubo_coincidencia_fuera_de_marca = True
                break
            if _tokens_coinciden(ta, tb):
                coincidencias += 1
                usados_b.add(idx_b)
                if not es_posicion_marca:
                    hubo_coincidencia_fuera_de_marca = True
                break

    if not hubo_coincidencia_exacta:
        return 0, False  # sin ancla exacta, no se considera cruce

    if not hubo_coincidencia_fuera_de_marca:
        # Solo coincidio la marca. Solo lo rechazamos si sobran palabras que
        # NO son calificativos de variante conocidos (serian componentes
        # activos distintos). Si no sobra nada, o todo lo que sobra son
        # calificativos (FLEX/FORTE/etc), si se acepta.
        extras = [t for i, t in enumerate(core_a) if i != 0] + [t for i, t in enumerate(core_b) if i != 0]
        if extras and not all(t in _CALIFICATIVOS_VARIANTE for t in extras):
            return 0, False

    score = coincidencias / min(len(core_a), len(core_b))
    especial = not _tokens_coinciden(core_a[0], core_b[0])
    return score, especial


def detectar_posibles_cruces(resultados, umbral_similitud=0.5):
    """
    Busca posibles 'canjes' (cruces): productos que sobran que podrian
    en realidad ser productos que faltan, contados/despachados por error.

    resultados: la lista que devuelve calcular_diferencias()
    umbral_similitud: que tan parecidas deben ser las descripciones (0 a 1)
                       para sugerir el cruce (0.5 = al menos la mitad de las
                       palabras clave coinciden)

    Devuelve una lista de posibles cruces, ordenada de mayor a menor similitud,
    cada uno con: sku/desc/cantidad de ambos lados, similitud, y si es 'especial'
    (marca diferente, requiere revision manual mas cuidadosa).
    """
    sobrantes = [r for r in resultados if r["estado"] == "SOBRANTE"]
    faltantes = [r for r in resultados if r["estado"] == "FALTANTE"]

    candidatos = []
    for s in sobrantes:
        for f in faltantes:
            score, especial = _similitud_descripciones(s["desc"], f["desc"])
            if score >= umbral_similitud:
                candidatos.append({
                    "sku_sobrante": s["sku"], "desc_sobrante": s["desc"],
                    "cantidad_sobrante": s["diferencia"],
                    "sku_faltante": f["sku"], "desc_faltante": f["desc"],
                    "cantidad_faltante": f["diferencia"],
                    "similitud": round(score, 2), "es_especial": especial,
                })

    # Emparejamos de forma "greedy": el par mas parecido gana primero,
    # y cada SKU solo puede aparecer emparejado una vez.
    candidatos.sort(key=lambda c: c["similitud"], reverse=True)
    usados_sobrante, usados_faltante = set(), set()
    cruces_finales = []
    for c in candidatos:
        if c["sku_sobrante"] in usados_sobrante or c["sku_faltante"] in usados_faltante:
            continue
        cruces_finales.append(c)
        usados_sobrante.add(c["sku_sobrante"])
        usados_faltante.add(c["sku_faltante"])

    return cruces_finales


# ══════════════════════════════════════════════════
#  PASO 1: EXISTENCIA
# ══════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def cargar_existencia(bytes_archivo):
    """
    Lee el CSV de Existencia (el mismo que descarga nuestro robot) y lo separa
    en Padres, Hijos (SKUs que terminan en 'H') y Negativos.

    Devuelve un diccionario con:
      - existencia: {sku: {"desc":..., "existencia":...}}
      - padres, hijos, negativos: listas de dicts {sku, desc, existencia}
      - farmacia: codigo detectado (ej "K002")
      - total, omitidos: contadores
    """
    texto = _leer_texto_archivo(bytes_archivo)
    lineas = _parsear_csv_texto(texto)
    h_idx = _encontrar_encabezado(lineas, "Articulo_Id")
    if h_idx == -1:
        raise ValueError("No se encontro la columna 'Articulo_Id' en el archivo de Existencia.")

    existencia = {}
    padres, hijos, negativos = [], [], []
    farmacia = ""

    for fila in lineas[h_idx + 1:]:
        if not fila or len(fila) < 6:
            continue

        if not farmacia:
            suc = str(fila[0] or "")
            m = re.search(r"K\d{3}", suc)
            if m:
                farmacia = m.group(0)
            else:
                partes = suc.strip().split("-")
                if len(partes) > 1:
                    farmacia = re.sub(r"\s+", "_", partes[1].strip())[:12]

        sku = str(fila[3] or "").strip()
        desc = str(fila[4] or "").strip()
        exist = _limpiar_num(fila[5])
        if not sku:
            continue

        existencia[sku] = {"desc": desc, "existencia": exist}

        if exist < 0:
            negativos.append({"sku": sku, "desc": desc, "existencia": exist})
        elif exist == 0:
            pass  # omitido
        elif re.match(r"^\d+H$", sku.strip(), re.IGNORECASE):
            hijos.append({"sku": sku, "desc": desc, "existencia": exist})
        else:
            padres.append({"sku": sku, "desc": desc, "existencia": exist})

    omitidos = sum(1 for v in existencia.values() if v["existencia"] == 0)

    return {
        "existencia": existencia,
        "padres": padres,
        "hijos": hijos,
        "negativos": negativos,
        "farmacia": farmacia,
        "total": len(existencia),
        "omitidos": omitidos,
    }


def generar_csv_handheld(lista_items, farmacia, tipo):
    """Genera el contenido CSV (texto) para PADRES/HIJOS/NEGATIVOS,
    en el formato que espera el handheld: Articulo_Id,Textbox6,Existencia"""
    lineas = ["Articulo_Id,Textbox6,Existencia"]
    for d in lista_items:
        desc_limpia = _limpiar_desc_para_handheld(d["desc"])
        lineas.append(f"{d['sku']},{desc_limpia},{d['existencia']}")
    contenido = "\n".join(lineas)
    nombre = f"{tipo.upper()}_{farmacia or 'FARM'}.csv"
    return contenido, nombre


# ══════════════════════════════════════════════════
#  PASO 2: KARDEX
# ══════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def cargar_kardex(bytes_archivo, fecha_inicio=None, fecha_corte=None):
    """
    Lee el CSV de Kardex y suma el movimiento neto por SKU, considerando
    solo movimientos dentro de la ventana [fecha_inicio, fecha_corte].
    fecha_inicio / fecha_corte: objetos datetime, o None para no filtrar.

    Ademas del neto por SKU, guarda el detalle por tipo de documento
    (columna Documento_Tipo1: FAC, PED, MTR, MIN, LOC, etc.) para poder
    armar el resumen de movimientos por tipo.
    """
    texto = _leer_texto_archivo(bytes_archivo)
    lineas = _parsear_csv_texto(texto)
    h_idx = _encontrar_encabezado(lineas, "Articulo_Id")
    if h_idx == -1:
        raise ValueError("No se encontro la columna 'Articulo_Id' en el archivo de Kardex.")

    kardex = {}
    detalle_por_sku_tipo = {}  # {sku: {tipo: neto}}
    resumen_tipos = {}  # {tipo: {"neto": x, "movimientos": n}}
    contador_movimientos = 0
    ignorados = 0

    for fila in lineas[h_idx + 1:]:
        if not fila or len(fila) < 13:
            continue
        sku = str(fila[2] or "").strip()
        tipo_doc = str(fila[6] or "SIN_TIPO").strip() or "SIN_TIPO"
        fecha_str = str(fila[8] or "").strip()
        cantidad = _limpiar_num(fila[12])
        if not sku:
            continue

        mov_fecha = _parsear_fecha_hora(fecha_str)
        if mov_fecha:
            if fecha_corte and mov_fecha > fecha_corte:
                ignorados += 1
                continue
            if fecha_inicio and mov_fecha < fecha_inicio:
                ignorados += 1
                continue

        kardex[sku] = kardex.get(sku, 0) + cantidad
        contador_movimientos += 1

        if sku not in detalle_por_sku_tipo:
            detalle_por_sku_tipo[sku] = {}
        detalle_por_sku_tipo[sku][tipo_doc] = detalle_por_sku_tipo[sku].get(tipo_doc, 0) + cantidad

        if tipo_doc not in resumen_tipos:
            resumen_tipos[tipo_doc] = {"neto": 0, "movimientos": 0}
        resumen_tipos[tipo_doc]["neto"] += cantidad
        resumen_tipos[tipo_doc]["movimientos"] += 1

    return {
        "kardex": kardex,
        "detalle_por_sku_tipo": detalle_por_sku_tipo,
        "resumen_tipos": resumen_tipos,
        "movimientos": contador_movimientos,
        "ignorados": ignorados,
        "skus_afectados": len(kardex),
    }


@st.cache_data(show_spinner=False)
def cargar_kardex_movimientos_detallados(bytes_archivo, fecha_inicio=None, fecha_corte=None):
    """
    Lee el Kardex y devuelve la lista CRUDA de movimientos (uno por fila),
    con SKU, tipo de documento, fecha, cantidad y USUARIO que lo aplico.
    A diferencia de cargar_kardex() (que solo suma el neto por SKU), esta
    version conserva cada movimiento individual -- necesaria para el
    Analisis de Devoluciones, que necesita saber CUANDO y QUIEN hizo
    cada ajuste, no solo el total.

    Devuelve una lista de dicts: {sku, desc, tipo, fecha (datetime o None),
    cantidad, usuario}
    """
    texto = _leer_texto_archivo(bytes_archivo)
    lineas = _parsear_csv_texto(texto)
    h_idx = _encontrar_encabezado(lineas, "Articulo_Id")
    if h_idx == -1:
        raise ValueError("No se encontro la columna 'Articulo_Id' en el archivo de Kardex.")

    movimientos = []
    for fila in lineas[h_idx + 1:]:
        if not fila or len(fila) < 13:
            continue
        sku = str(fila[2] or "").strip()
        desc = str(fila[3] or "").strip()
        tipo_doc = str(fila[6] or "SIN_TIPO").strip() or "SIN_TIPO"
        fecha_str = str(fila[8] or "").strip()
        cantidad = _limpiar_num(fila[12])
        usuario = str(fila[16] or "").strip() if len(fila) > 16 else ""
        if not sku:
            continue

        mov_fecha = _parsear_fecha_hora(fecha_str)
        if mov_fecha:
            if fecha_corte and mov_fecha > fecha_corte:
                continue
            if fecha_inicio and mov_fecha < fecha_inicio:
                continue

        movimientos.append({
            "sku": sku, "desc": desc, "tipo": tipo_doc,
            "fecha": mov_fecha, "cantidad": cantidad, "usuario": usuario,
        })

    return movimientos


# Usuarios que representan ajustes AUTOMATICOS del sistema (no una decision
# manual de un auditor/encargado real) -- se excluyen del analisis.
_USUARIOS_AJUSTE_AUTOMATICO = {"ENCARGADO_WEB", "LOGICAL_DATA"}


def _formatear_fecha_texto(fecha):
    """Convierte una fecha datetime a texto legible 'DD/MM/YYYY HH:MM',
    o texto vacio si no hay fecha."""
    if fecha is None:
        return "(sin fecha)"
    return fecha.strftime("%d/%m/%Y %H:%M")


def analizar_devoluciones(movimientos, faltantes_inventario=None):
    """
    Cruza las devoluciones (tipo 'DEV') contra:
      1. Ajustes por faltante posteriores (tipo 'MIN', hechos por un
         usuario real -- no ENCARGADO_WEB ni LOGICAL_DATA -- en una
         fecha POSTERIOR a la devolucion, para el mismo SKU).
      2. El Faltante determinado en el conteo fisico del auditor
         (lista de SKUs, opcional).

    movimientos: lista de dicts de cargar_kardex_movimientos_detallados()
    faltantes_inventario: set/lista de SKUs marcados como FALTANTE en las
                           Diferencias Reales del conteo (opcional)

    Devuelve dos listas por separado (nunca mezcladas):
      - cruce_ajustes: devoluciones cuyo SKU tuvo un ajuste MIN manual
        despues de la devolucion
      - cruce_inventario: devoluciones cuyo SKU aparece en el Faltante
        del conteo del auditor
    """
    faltantes_inventario = set(faltantes_inventario or [])

    devoluciones = [m for m in movimientos if m["tipo"].upper() == "DEV"]
    ajustes_manuales = [
        m for m in movimientos
        if m["tipo"].upper() == "MIN" and m["usuario"].strip().upper() not in _USUARIOS_AJUSTE_AUTOMATICO
    ]

    # Indexamos los ajustes manuales por SKU para buscarlos rapido
    ajustes_por_sku = {}
    for a in ajustes_manuales:
        ajustes_por_sku.setdefault(a["sku"], []).append(a)

    cruce_ajustes = []
    cruce_inventario = []
    fechas_ajuste_por_devolucion = {}  # indice de la devolucion -> lista de fechas de ajuste

    for i, dev in enumerate(devoluciones):
        # --- Cruce 1: contra ajustes por faltante posteriores ---
        candidatos = ajustes_por_sku.get(dev["sku"], [])
        for ajuste in candidatos:
            es_posterior = (
                dev["fecha"] is None or ajuste["fecha"] is None or ajuste["fecha"] > dev["fecha"]
            )
            if es_posterior:
                cruce_ajustes.append({
                    "sku": dev["sku"], "desc": dev["desc"],
                    "fecha_devolucion": dev["fecha"], "cantidad_devuelta": dev["cantidad"],
                    "fecha_ajuste": ajuste["fecha"], "cantidad_ajuste": ajuste["cantidad"],
                    "usuario_ajuste": ajuste["usuario"],
                })
                fechas_ajuste_por_devolucion.setdefault(i, []).append(ajuste["fecha"])

        # --- Cruce 2: contra el Faltante del inventario del auditor ---
        if dev["sku"] in faltantes_inventario:
            cruce_inventario.append({
                "sku": dev["sku"], "desc": dev["desc"],
                "fecha_devolucion": dev["fecha"], "cantidad_devuelta": dev["cantidad"],
            })

    # Marcamos cada devolucion con las alertas que le aplican, para el
    # informe detallado completo (para que sirva por si solo, sin tener
    # que cruzar manualmente con los otros dos resumenes).
    skus_en_cruce_ajustes = {c["sku"] for c in cruce_ajustes}
    skus_en_cruce_inventario = {c["sku"] for c in cruce_inventario}

    detalle_devoluciones = []
    for i, dev in enumerate(devoluciones):
        alertas = []
        if dev["sku"] in skus_en_cruce_ajustes:
            alertas.append("Ajuste por faltante posterior")
        if dev["sku"] in skus_en_cruce_inventario:
            alertas.append("Faltante en conteo del auditor")

        # La fecha de devolucion, y debajo (en la MISMA celda, separado por
        # un salto de linea) la(s) fecha(s) del ajuste que le corresponden,
        # si tuvo alguno.
        texto_fecha = _formatear_fecha_texto(dev["fecha"])
        for fecha_ajuste in fechas_ajuste_por_devolucion.get(i, []):
            texto_fecha += f"\nAjuste: {_formatear_fecha_texto(fecha_ajuste)}"

        detalle_devoluciones.append({
            "sku": dev["sku"], "desc": dev["desc"], "fecha_devolucion": texto_fecha,
            "cantidad_devuelta": dev["cantidad"], "usuario_devolucion": dev["usuario"],
            "alerta": " + ".join(alertas) if alertas else "",
        })

    return {
        "total_devoluciones": len(devoluciones),
        "total_ajustes_manuales": len(ajustes_manuales),
        "cruce_ajustes": cruce_ajustes,
        "cruce_inventario": cruce_inventario,
        "detalle_devoluciones": detalle_devoluciones,
    }


def resumen_movimientos_por_tipo(detalle_por_sku_tipo, existencia_info=None, filtro="todos"):
    """
    Arma un resumen de movimientos agrupado por tipo de documento (FAC, PED,
    MTR, MIN, LOC, etc.), opcionalmente filtrado solo a SKUs 'padres' o 'hijos'.

    detalle_por_sku_tipo: viene de cargar_kardex()["detalle_por_sku_tipo"]
    existencia_info: viene de cargar_existencia() (necesario si filtro != "todos")
    filtro: "todos", "padres" o "hijos"

    Devuelve una lista de dicts: [{"tipo": ..., "neto": ..., "movimientos": ...}, ...]
    ordenada de mayor a menor movimiento neto absoluto.
    """
    skus_permitidos = None
    if filtro == "padres" and existencia_info:
        skus_permitidos = {d["sku"] for d in existencia_info["padres"]}
    elif filtro == "hijos" and existencia_info:
        skus_permitidos = {d["sku"] for d in existencia_info["hijos"]}

    resumen = {}
    for sku, tipos in detalle_por_sku_tipo.items():
        if skus_permitidos is not None and sku not in skus_permitidos:
            continue
        for tipo, cantidad in tipos.items():
            if tipo not in resumen:
                resumen[tipo] = {"neto": 0, "movimientos": 0}
            resumen[tipo]["neto"] += cantidad
            resumen[tipo]["movimientos"] += 1

    lista = [{"tipo": t, "neto": v["neto"], "movimientos": v["movimientos"]} for t, v in resumen.items()]
    lista.sort(key=lambda x: abs(x["neto"]), reverse=True)
    return lista


def detalle_articulo(sku, existencia_info, detalle_por_sku_tipo):
    """Devuelve el detalle completo de un articulo especifico: existencia,
    y el desglose de sus movimientos por tipo (para el 'analisis por articulo')."""
    info_existencia = existencia_info["existencia"].get(sku, {"desc": "", "existencia": 0})
    movimientos = detalle_por_sku_tipo.get(sku, {})
    neto_total = sum(movimientos.values())
    return {
        "sku": sku,
        "desc": info_existencia["desc"],
        "existencia_inicial": info_existencia["existencia"],
        "movimientos_por_tipo": movimientos,
        "neto_total": neto_total,
        "existencia_teorica_actual": info_existencia["existencia"] + neto_total,
    }


# ══════════════════════════════════════════════════
#  PASO 3: CONTEO / RECONTEO
# ══════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def cargar_conteo(bytes_archivo):
    """Lee el CSV de conteo fisico del auditor (columna SKU en pos 0,
    cantidad contada en pos 3). Tambien intenta capturar una descripcion
    (columna 1) por si la existencia no trae descripcion para ese SKU.
    Devuelve {sku: {"cantidad": x, "desc": y}}"""
    texto = _leer_texto_archivo(bytes_archivo)
    lineas = _parsear_csv_texto(texto)
    h_idx = _encontrar_encabezado(lineas, "SKU")
    if h_idx == -1:
        raise ValueError("No se encontro la columna 'SKU' en el archivo de conteo.")

    conteo = {}
    for fila in lineas[h_idx + 1:]:
        if not fila or len(fila) < 4:
            continue
        sku = str(fila[0] or "").strip()
        if not sku:
            continue
        posible_desc = str(fila[1] or "").strip() if len(fila) > 1 else ""
        conteo[sku] = {"cantidad": _limpiar_num(fila[3]), "desc": posible_desc}
    return conteo


def unificar_conteos_de_varios_auditores(lista_de_conteos):
    """
    Combina los conteos de VARIOS auditores que contaron la misma farmacia
    (por ejemplo, 5 personas dividiendose los pasillos). Las cantidades de
    un mismo SKU se SUMAN entre auditores.

    lista_de_conteos: lista de diccionarios, cada uno devuelto por cargar_conteo()

    Devuelve un solo diccionario {sku: {"cantidad": suma, "desc": ...}},
    en el mismo formato que espera calcular_diferencias().
    """
    unificado = {}
    for conteo in lista_de_conteos:
        for sku, datos in conteo.items():
            if sku not in unificado:
                unificado[sku] = {"cantidad": 0, "desc": datos.get("desc", "")}
            unificado[sku]["cantidad"] += datos["cantidad"]
            if not unificado[sku]["desc"] and datos.get("desc"):
                unificado[sku]["desc"] = datos["desc"]
    return unificado


# ══════════════════════════════════════════════════
#  PASO 4: CORTO VENCE / EXCESOS
# ══════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def cargar_listado_especial(bytes_archivo):
    """Lee un listado de Corto Vence o Excesos: columna A=SKU, B=Desc, C=Cantidad.
    Devuelve {sku: {"desc":..., "cantidad":...}}"""
    texto = _leer_texto_archivo(bytes_archivo)
    lineas = _parsear_csv_texto(texto)

    start_row = 0
    if lineas and lineas[0] and re.search(r"sku|articulo|codigo", str(lineas[0][0]), re.IGNORECASE):
        start_row = 1

    resultado = {}
    for fila in lineas[start_row:]:
        if not fila or not fila[0]:
            continue
        sku = str(fila[0]).strip()
        desc = str(fila[1] if len(fila) > 1 else "").strip()
        cantidad = _limpiar_num(fila[2] if len(fila) > 2 else 0)
        if not sku:
            continue
        resultado[sku] = {"desc": desc, "cantidad": cantidad}
    return resultado


# ══════════════════════════════════════════════════
#  CALCULO DE DIFERENCIAS (formula de 3 ramas)
# ══════════════════════════════════════════════════

def calcular_diferencias(existencia, kardex, conteo, reconteo=None,
                          corto=None, exceso=None,
                          aplicar_corto=True, aplicar_exceso=True):
    """
    Replica exacta de la formula del Excel de auditoria:

    dif_aparente = conteo - existencia_inicial
      - Rama 1 (sobrante, dif > 0): resultado = dif - min(dif, corto+exceso disponible)
        (corto/exceso solo se restan si aplicar_corto / aplicar_exceso son True,
        igual que los interruptores T3/T4 del Excel original)
      - Rama 2 (cuadrado, dif = 0): resultado = 0
      - Rama 3 (faltante, dif < 0): resultado = conteo - neto_kardex - existencia
        (si contaste 3, existia 3, y salieron 2 despues del conteo -> faltante real = 0)

    Estados posibles: OK, FALTANTE, SOBRANTE, SOBRANTE FUERA DE KARDEX
    (contado pero el SKU no esta registrado en la existencia de la farmacia),
    NO CONTADO.

    Ademas, si un aparente FALTANTE (conteo < existencia inicial) se convierte
    en OK o SOBRANTE una vez ajustado por los movimientos del Kardex, se marca
    con la observacion "Verificar / posible reconteo" (esto puede pasar en
    auditorias a puertas abiertas, donde la existencia cambia mientras se cuenta).

    Devuelve una lista de dicts, uno por SKU, con todos los campos calculados.
    """
    reconteo = reconteo or {}
    corto = corto or {}
    exceso = exceso or {}

    todos_skus = set(existencia.keys()) | set(conteo.keys()) | set(reconteo.keys())
    resultados = []

    for sku in todos_skus:
        sku_en_existencia = sku in existencia
        ex = existencia.get(sku, {"desc": "", "existencia": 0})
        mov_kardex = kardex.get(sku)
        neto = mov_kardex if mov_kardex is not None else 0
        exist_ajustada = ex["existencia"] + neto

        registro_conteo = conteo.get(sku)
        desc_conteo = registro_conteo["desc"] if registro_conteo else ""
        contado = registro_conteo["cantidad"] if registro_conteo else None

        fue_reconteo = False
        if sku in reconteo:
            contado = reconteo[sku]["cantidad"]
            desc_conteo = reconteo[sku].get("desc", "") or desc_conteo
            fue_reconteo = True

        # Si la existencia no trae descripcion, usamos la del conteo como respaldo.
        # Si tampoco la tiene el conteo, queda vacia (y se evalua solo por SKU).
        desc_final = ex["desc"] or desc_conteo or ""

        observacion = ""
        rebaja_aplicada = 0
        diferencia = None

        if contado is not None:
            dif_bruta = contado - ex["existencia"]
            if dif_bruta > 0:
                disponible = 0
                if aplicar_exceso:
                    disponible += exceso.get(sku, {}).get("cantidad", 0)
                if aplicar_corto:
                    disponible += corto.get(sku, {}).get("cantidad", 0)
                rebaja_aplicada = min(dif_bruta, disponible) if disponible > 0 else 0
                diferencia = dif_bruta - rebaja_aplicada
            elif dif_bruta == 0:
                diferencia = 0
            else:
                diferencia = contado - neto - ex["existencia"]
                if diferencia >= 0:
                    # Parecia faltante a simple vista, pero al ajustar por el
                    # kardex ya no lo es (normal en inventarios a puertas abiertas)
                    observacion = "🔁 Verificar / posible reconteo (ajustado por Kardex)"

        if contado is None:
            estado = "NO CONTADO"
        elif diferencia > 0:
            # Contado pero el SKU no existe en la existencia de la farmacia:
            # es un sobrante que "no deberia existir" segun el sistema.
            estado = "SOBRANTE FUERA DE KARDEX" if not sku_en_existencia else "SOBRANTE"
        elif diferencia < 0:
            estado = "FALTANTE"
        else:
            estado = "OK"

        corto_exceso_disp = corto.get(sku, {}).get("cantidad", 0) + exceso.get(sku, {}).get("cantidad", 0)

        resultados.append({
            "sku": sku, "desc": desc_final, "existencia": ex["existencia"],
            "mov_kardex": mov_kardex, "exist_ajustada": exist_ajustada,
            "contado": contado, "fue_reconteo": fue_reconteo,
            "diferencia": diferencia, "estado": estado, "observacion": observacion,
            "corto_exceso_disp": corto_exceso_disp, "rebaja_aplicada": rebaja_aplicada,
        })

    return resultados


def calcular_rebaja_corto_exceso(resultado, corto, exceso):
    """Calcula cuanto se puede rebajar de un sobrante usando corto/exceso disponible."""
    disponible = corto.get(resultado["sku"], {}).get("cantidad", 0) + \
                 exceso.get(resultado["sku"], {}).get("cantidad", 0)
    if disponible <= 0:
        return 0
    if resultado["diferencia"] is None or resultado["diferencia"] <= 0:
        return 0
    return min(resultado["diferencia"], disponible)


# ══════════════════════════════════════════════════
#  ARCHIVOS DE AJUSTE FINAL (FALTANTES / SOBRANTES)
# ══════════════════════════════════════════════════

def preparar_datos_ajuste(resultados, umbral=0, incluir_ok=False):
    """
    A partir de las diferencias REALES (ya con cruces y reconteos aplicados),
    separa los datos en Faltantes y Sobrantes listos para exportar, igual
    que hacia la herramienta original.

    umbral: ignora diferencias cuyo valor absoluto sea menor a este numero
            (0 = sin filtro, incluye todo)
    incluir_ok: si True, tambien incluye las filas con diferencia = 0
                (utilizado cuando el sistema que recibe el archivo necesita
                'ver' todos los SKUs, aunque sea con cantidad cero)
    """
    datos = []
    for r in resultados:
        if r["diferencia"] is None:
            continue
        if not incluir_ok and r["diferencia"] == 0:
            continue
        if umbral > 0 and r["diferencia"] != 0 and abs(r["diferencia"]) < umbral:
            continue
        datos.append({"sku": r["sku"], "desc": r["desc"], "diferencia": r["diferencia"]})

    faltantes = [d for d in datos if d["diferencia"] < 0]
    if incluir_ok:
        sobrantes = [d for d in datos if d["diferencia"] >= 0]
    else:
        sobrantes = [d for d in datos if d["diferencia"] > 0]

    return faltantes, sobrantes


def generar_excel_ajuste(datos, nombre_hoja="TOMA"):
    """
    Genera, en memoria, un archivo Excel con el mismo formato que usaba la
    herramienta original: dos columnas (Codigo, Cantidad), SKU como texto
    (para no perder ceros a la izquierda), cantidad redondeada.

    Nota: el sistema original generaba .xls (Excel 97-2003) usando la
    libreria 'xlwt', pero esa libreria fue retirada de PyPI y ya no se
    puede instalar en ningun lado. Usamos .xlsx (Excel moderno) en su
    lugar, que la gran mayoria de sistemas aceptan igual.

    Devuelve los bytes del archivo, listos para descargar.
    """
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = nombre_hoja

    ws["A1"] = "Codigo"
    ws["B1"] = "Cantidad"
    ws["A1"].font = Font(bold=True)
    ws["B1"].font = Font(bold=True)

    for i, d in enumerate(datos, start=2):
        codigo = re.sub(r"\.0+$", "", str(d["sku"]).strip())  # por si viene como "12345.0"
        celda_codigo = ws.cell(row=i, column=1, value=codigo)
        celda_codigo.number_format = "@"  # fuerza formato de texto
        ws.cell(row=i, column=2, value=round(d["diferencia"]))

    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 12

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def integrar_alertas_de_cruce(resultados, cruces):
    """
    (Version simple, sin dividir cantidades) Agrega la observacion de
    'Posible Cruce' directamente en la fila de cada SKU involucrado.
    Se mantiene por compatibilidad; para el comportamiento recomendado
    (que reparte cantidades parciales) usar aplicar_cruces_a_resultados().
    """
    por_sku = {r["sku"]: r for r in resultados}
    for c in cruces:
        etiqueta = "🔶 POSIBLE CRUCE ESPECIAL" if c["es_especial"] else "⚠ Posible Cruce"

        if c["sku_sobrante"] in por_sku:
            por_sku[c["sku_sobrante"]]["observacion"] = (
                f"{etiqueta} con SKU {c['sku_faltante']} "
                f"({c['similitud']:.0%} similitud) — {c['desc_faltante']}"
            )
        if c["sku_faltante"] in por_sku:
            por_sku[c["sku_faltante"]]["observacion"] = (
                f"{etiqueta} con SKU {c['sku_sobrante']} "
                f"({c['similitud']:.0%} similitud) — {c['desc_sobrante']}"
            )
    return resultados


def aplicar_cruces_a_resultados(resultados, cruces):
    """
    Aplica los cruces detectados REPARTIENDO LAS CANTIDADES, igual que el
    auditor lo hacia manualmente en Excel: si sobra 1 unidad pero faltan 3
    de un producto relacionado, solo se justifica 1 unidad como cruce; las
    2 unidades restantes se quedan como Faltante genuino sin justificar
    (un sobrante o faltante sin respaldo no debe compensar el resto).

    Cuando la cantidad no se cubre por completo, la fila original se
    'divide' en dos: la porcion cubierta por el cruce, y una fila adicional
    con la porcion que sigue sin explicacion.

    Devuelve una NUEVA lista de resultados (no modifica la original).
    """
    resultados = [dict(r) for r in resultados]  # copia, no tocamos la original
    por_sku = {r["sku"]: r for r in resultados}
    filas_extra = []

    for c in cruces:
        fila_sobra = por_sku.get(c["sku_sobrante"])
        fila_falta = por_sku.get(c["sku_faltante"])
        if not fila_sobra or not fila_falta:
            continue
        if fila_sobra["diferencia"] is None or fila_falta["diferencia"] is None:
            continue

        cantidad_sobra = fila_sobra["diferencia"]           # positivo
        cantidad_falta = abs(fila_falta["diferencia"])      # se compara en positivo
        cantidad_cruzada = min(cantidad_sobra, cantidad_falta)
        if cantidad_cruzada <= 0:
            continue

        etiqueta = "Cruce Especial" if c["es_especial"] else "Cruce"

        # --- Lado que SOBRA ---
        if cantidad_cruzada >= cantidad_sobra:
            fila_sobra["observacion"] = f"{etiqueta} con Cod. {c['sku_faltante']}"
        else:
            resto = cantidad_sobra - cantidad_cruzada
            fila_extra = dict(fila_sobra)
            fila_sobra["diferencia"] = cantidad_cruzada
            fila_sobra["observacion"] = f"{etiqueta} con Cod. {c['sku_faltante']}"
            fila_extra["diferencia"] = resto
            fila_extra["estado"] = "SOBRANTE" if fila_extra["estado"] != "SOBRANTE FUERA DE KARDEX" else fila_extra["estado"]
            fila_extra["observacion"] = "Sobrante sin justificar (cruce parcial)"
            filas_extra.append(fila_extra)

        # --- Lado que FALTA ---
        if cantidad_cruzada >= cantidad_falta:
            fila_falta["observacion"] = f"{etiqueta} con Cod. {c['sku_sobrante']}"
        else:
            resto = cantidad_falta - cantidad_cruzada
            fila_extra = dict(fila_falta)
            fila_falta["diferencia"] = -cantidad_cruzada
            fila_falta["observacion"] = f"{etiqueta} con Cod. {c['sku_sobrante']}"
            fila_extra["diferencia"] = -resto
            fila_extra["estado"] = "FALTANTE"
            fila_extra["observacion"] = "Faltante sin justificar (cruce parcial)"
            filas_extra.append(fila_extra)

    return resultados + filas_extra