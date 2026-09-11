"""
Modulo de conciliacion de inventario - CEDI
Traduccion a Python de la logica de KielsaControlInventarios.html (modulo CEDI).

A diferencia de Farmacia (un solo conteo), CEDI compila los archivos de
VARIOS auditores, agrupados por SKU + Bodega, donde los reconteos
SUSTITUYEN (no se suman) al conteo inicial de ese mismo SKU+Bodega.
"""

import re

import streamlit as st

from modulo_farmacia import (  # reutilizamos los helpers ya probados
    _leer_texto_archivo, _limpiar_num, _parsear_csv_texto, _encontrar_encabezado,
    generar_csv_handheld,
)


# ══════════════════════════════════════════════════
#  PASO 1: EXISTENCIA CEDI (por Casa/Laboratorio y Bodega)
# ══════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def cargar_existencia_cedi(bytes_archivo):
    """
    Lee el CSV de existencia CEDI: columnas Suc_Id, Bodega_Id, Casa_ID,
    Articulo_Id, Textbox6, Existencia, AXS_Costo_Actual.

    La clave de cada registro es "sku|bodega" (igual que hace el handheld
    al reportar 'Bodega_Reporte'), para poder cruzarlos mas adelante.

    Devuelve:
      - existencia: {"sku|bodega": {sku, desc, existencia, casa, bodega, costo}}
      - sku_desc_global: {sku: desc} (para rellenar descripciones vacias)
      - casas, bodegas: sets detectados (para armar filtros en la interfaz)
    """
    texto = _leer_texto_archivo(bytes_archivo)
    lineas = _parsear_csv_texto(texto)
    h_idx = _encontrar_encabezado(lineas, "Articulo_Id")
    if h_idx == -1:
        raise ValueError("No se encontro la columna 'Articulo_Id' en el archivo de Existencia CEDI.")

    existencia = {}
    sku_desc_global = {}
    sku_costo_global = {}
    casas, bodegas = set(), set()

    for fila in lineas[h_idx + 1:]:
        if not fila or len(fila) < 6:
            continue
        sku = str(fila[3] or "").strip()
        desc = str(fila[4] or "").strip()
        exist = _limpiar_num(fila[5])
        costo = _limpiar_num(fila[6]) if len(fila) > 6 else 0
        casa_cruda = str(fila[2] or "").strip()
        bodega = str(fila[1] or "").strip()
        if not sku:
            continue

        # La "casa" viene como "3 - LABORATORIO X" -> nos quedamos solo con el nombre
        m = re.match(r"^\d+\s*-\s*(.+)$", casa_cruda)
        casa = m.group(1).strip() if m else casa_cruda

        clave = f"{sku}|{bodega}"
        existencia[clave] = {"sku": sku, "desc": desc, "existencia": exist,
                              "casa": casa, "bodega": bodega, "costo": costo}
        if desc:
            sku_desc_global[sku] = desc
        if costo:
            sku_costo_global[sku] = costo
        casas.add(casa)
        bodegas.add(bodega)

    # Para el archivo de Handheld (Padres/Hijos), consolidamos por SKU unico,
    # sumando la existencia de todas las bodegas donde aparezca ese SKU.
    existencia_por_sku = {}
    for r in existencia.values():
        if r["sku"] not in existencia_por_sku:
            existencia_por_sku[r["sku"]] = {"sku": r["sku"], "desc": r["desc"], "existencia": 0, "costo": r["costo"]}
        existencia_por_sku[r["sku"]]["existencia"] += r["existencia"]
        if not existencia_por_sku[r["sku"]]["desc"]:
            existencia_por_sku[r["sku"]]["desc"] = r["desc"]
        if not existencia_por_sku[r["sku"]]["costo"]:
            existencia_por_sku[r["sku"]]["costo"] = r["costo"]

    padres, hijos, negativos = [], [], []
    for d in existencia_por_sku.values():
        if d["existencia"] < 0:
            negativos.append(d)
        elif d["existencia"] == 0:
            continue
        elif re.match(r"^\d+H$", d["sku"].strip(), re.IGNORECASE):
            hijos.append(d)
        else:
            padres.append(d)

    return {
        "existencia": existencia,
        "sku_desc_global": sku_desc_global,
        "sku_costo_global": sku_costo_global,
        "casas": sorted(casas),
        "bodegas": sorted(bodegas),
        "total": len(existencia),
        "padres": padres,
        "hijos": hijos,
        "negativos": negativos,
    }


# ══════════════════════════════════════════════════
#  PASO 2: ARCHIVOS DE CONTEO (uno por auditor)
# ══════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def procesar_archivo_auditor(bytes_archivo, nombre_archivo, tipo="inicial"):
    """
    Procesa UN archivo de conteo del handheld. Detecta las columnas POR NOMBRE
    (no por posicion), para que siga funcionando aunque el handheld agregue,
    quite o reordene columnas (ej: 'Ubicacion_Rack').

    Formatos reconocidos:
      - Formato basico (recomendado): columnas SKU, Descripcion,
        Bodega_Reporte, Cantidad (y opcionalmente Localizacion,
        Ubicacion_Rack u otras columnas extra, que se ignoran).
      - Formato viejo: columnas fijas Conteo_ALMACEN / Conteo_DESPACHO /
        Conteo_CUARENTENA.
      - Formato generico (respaldo): si no se reconoce ninguno de los
        anteriores pero SI hay una columna 'SKU' y una columna de cantidad,
        se consolida solo por SKU (sin agrupar por bodega).

    El nombre del auditor se busca en una fila 'Auditor' despues del pie
    'RESUMEN'; si no existe, se intenta extraer del nombre del archivo
    (soporta guiones y guiones bajos, ej: 'Inv_CEDI_Jamil_20260907.csv').

    tipo: "inicial" o "reconteo"

    Devuelve: {nombre_auditor, tipo, filas: [{sku,desc,bodega,localizacion,cantidad}],
               total_unidades, formato}
    """
    texto = _leer_texto_archivo(bytes_archivo)
    lineas = _parsear_csv_texto(texto)
    h_idx = _encontrar_encabezado(lineas, "SKU")
    if h_idx == -1:
        raise ValueError(f"'{nombre_archivo}': no se encontro la columna 'SKU'.")

    encabezado = [str(c or "").strip() for c in lineas[h_idx]]

    def _indice_columna(*nombres_posibles):
        """Busca el indice de la primera columna cuyo nombre coincida
        (sin importar mayusculas/minusculas) con alguno de los nombres dados."""
        for nombre in nombres_posibles:
            for i, col in enumerate(encabezado):
                if col.strip().lower() == nombre.lower():
                    return i
        return -1

    # Buscamos el pie de pagina "RESUMEN" para saber donde terminan los datos reales
    fin_datos = len(lineas)
    for i in range(h_idx + 1, len(lineas)):
        fila = lineas[i]
        if not fila or all((c == "" or c is None) for c in fila):
            continue
        if str(fila[0]).strip().upper() == "RESUMEN":
            fin_datos = i
            break

    # Buscamos el nombre del auditor despues del resumen
    nombre_auditor = ""
    for i in range(fin_datos, len(lineas)):
        fila = lineas[i]
        if fila and str(fila[0]).strip().lower() == "auditor":
            nombre_auditor = str(fila[1] if len(fila) > 1 else "").strip()
            break

    if not nombre_auditor:
        # Respaldo: extraemos el nombre del archivo (soporta "-" y "_" como
        # separador, ej: "Inv_CEDI_Jamil_20260907_1952.csv")
        base = re.sub(r"\.csv$", "", nombre_archivo, flags=re.IGNORECASE)
        partes = re.split(r"[-_]", base)
        palabras_genericas = {"inv", "cedi", "farmacia", "conteo", "reconteo",
                               "reporte", "auditoria", "kielsa"}
        candidatos = [p for p in partes if p.isalpha() and p.lower() not in palabras_genericas]
        nombre_auditor = candidatos[0] if candidatos else base

    idx_desc = _indice_columna("Descripcion", "Descripción")
    idx_bodega = _indice_columna("Bodega_Reporte", "Bodega")
    idx_localizacion = _indice_columna("Localizacion", "Localización")
    idx_localizaciones_combinado = _indice_columna("Localizaciones", "Localizaciónes")
    idx_rack_combinado = _indice_columna("Ubicaciones_Rack", "Ubicacion_Rack", "Ubicaciones_de_Rack")
    idx_cantidad = _indice_columna("Cantidad")
    idx_cantidad_total = _indice_columna("Total_Cantidad", "Cantidad_Total")
    idx_almacen = _indice_columna("Conteo_ALMACEN")
    idx_despacho = _indice_columna("Conteo_DESPACHO")
    idx_cuarentena = _indice_columna("Conteo_CUARENTENA")

    if idx_localizaciones_combinado != -1 and (idx_cantidad_total != -1 or idx_cantidad != -1) and idx_bodega != -1:
        formato = "combinado"
        idx_cantidad_usar = idx_cantidad_total if idx_cantidad_total != -1 else idx_cantidad
    elif idx_cantidad != -1 and idx_bodega != -1:
        formato = "basico"
    elif idx_almacen != -1 or idx_despacho != -1 or idx_cuarentena != -1:
        formato = "viejo"
    elif idx_cantidad != -1 or idx_cantidad_total != -1:
        formato = "generico"  # tiene SKU y Cantidad, pero no bodega -> se consolida solo por SKU
        idx_cantidad_usar = idx_cantidad if idx_cantidad != -1 else idx_cantidad_total
    else:
        raise ValueError(
            f"'{nombre_archivo}': no se reconoce el formato. Se necesita al menos "
            f"una columna 'SKU' y una columna de cantidad."
        )

    filas = []
    for fila in lineas[h_idx + 1: fin_datos]:
        if not fila or not str(fila[0] or "").strip():
            continue
        sku = str(fila[0]).strip()
        desc = str(fila[idx_desc]).strip() if idx_desc != -1 and idx_desc < len(fila) else ""

        if formato == "combinado":
            # Ya viene todo junto en una celda, ej: "Almacen:100 | Picking:400"
            # y los racks: "Almacen=764600210909 | Picking=764600210910"
            bodega = str(fila[idx_bodega]).strip() if idx_bodega < len(fila) else ""
            texto_localizaciones = str(fila[idx_localizaciones_combinado]).strip() if idx_localizaciones_combinado < len(fila) else ""
            texto_racks = str(fila[idx_rack_combinado]).strip() if idx_rack_combinado != -1 and idx_rack_combinado < len(fila) else ""

            racks_por_localizacion = {}
            if texto_racks:
                for parte in texto_racks.split("|"):
                    if "=" in parte:
                        loc_r, rack = parte.split("=", 1)
                        racks_por_localizacion[loc_r.strip()] = rack.strip()

            if texto_localizaciones:
                for parte in texto_localizaciones.split("|"):
                    if ":" not in parte:
                        continue
                    loc, cant_texto = parte.split(":", 1)
                    loc = loc.strip()
                    cantidad = _limpiar_num(cant_texto)
                    if cantidad == 0:
                        continue
                    filas.append({
                        "sku": sku, "desc": desc, "bodega": bodega, "localizacion": loc,
                        "cantidad": cantidad, "rack": racks_por_localizacion.get(loc, ""),
                    })
            else:
                # Sin detalle de localizacion, usamos el total tal cual
                cantidad = _limpiar_num(fila[idx_cantidad_usar]) if idx_cantidad_usar < len(fila) else 0
                if cantidad != 0:
                    filas.append({"sku": sku, "desc": desc, "bodega": bodega,
                                  "localizacion": "", "cantidad": cantidad, "rack": ""})

        elif formato == "basico":
            bodega = str(fila[idx_bodega]).strip() if idx_bodega < len(fila) else ""
            localizacion = str(fila[idx_localizacion]).strip() if idx_localizacion != -1 and idx_localizacion < len(fila) else ""
            cantidad = _limpiar_num(fila[idx_cantidad]) if idx_cantidad < len(fila) else 0
            if cantidad == 0:
                continue
            filas.append({"sku": sku, "desc": desc, "bodega": bodega,
                          "localizacion": localizacion, "cantidad": cantidad, "rack": ""})

        elif formato == "generico":
            # Sin columna de bodega: se consolida solo por SKU (bodega vacia)
            cantidad = _limpiar_num(fila[idx_cantidad_usar]) if idx_cantidad_usar < len(fila) else 0
            if cantidad == 0:
                continue
            filas.append({"sku": sku, "desc": desc, "bodega": "",
                          "localizacion": "", "cantidad": cantidad, "rack": ""})

        else:  # formato == "viejo"
            almacen = _limpiar_num(fila[idx_almacen]) if idx_almacen != -1 and idx_almacen < len(fila) else 0
            despacho = _limpiar_num(fila[idx_despacho]) if idx_despacho != -1 and idx_despacho < len(fila) else 0
            cuarentena = _limpiar_num(fila[idx_cuarentena]) if idx_cuarentena != -1 and idx_cuarentena < len(fila) else 0
            if almacen > 0:
                filas.append({"sku": sku, "desc": desc, "bodega": "__ALMACEN__",
                              "localizacion": "Almacen", "cantidad": almacen, "rack": ""})
            if despacho > 0:
                filas.append({"sku": sku, "desc": desc, "bodega": "__DESPACHO__",
                              "localizacion": "Despacho", "cantidad": despacho, "rack": ""})
            if cuarentena > 0:
                filas.append({"sku": sku, "desc": desc, "bodega": "__CUARENTENA__",
                              "localizacion": "Cuarentena", "cantidad": cuarentena, "rack": ""})

    total_unidades = sum(f["cantidad"] for f in filas)
    return {
        "nombre_auditor": nombre_auditor, "tipo": tipo, "archivo": nombre_archivo,
        "filas": filas, "total_unidades": total_unidades, "formato": formato,
    }


# ══════════════════════════════════════════════════
#  PASO 3: CONSOLIDAR SOLO CONTEO (sin comparar contra existencia)
# ══════════════════════════════════════════════════

def _formatear_detalle(detalle, racks=None):
    """Arma el texto de detalle por localizacion, incluyendo el rack si
    se conoce, ej: 'Almacen:500(764600210909) | Picking:400'"""
    racks = racks or {}
    partes = []
    for loc, cant in detalle.items():
        rack = racks.get(loc, "")
        if rack:
            partes.append(f"{loc}:{cant}({rack})")
        else:
            partes.append(f"{loc}:{cant}")
    return " | ".join(partes)


def consolidar_solo_conteo(auditores, nivel="sku"):
    """
    Combina los archivos de los auditores (con la misma logica de
    reconteo-sustituye-a-inicial), SIN cruzar contra la existencia.
    Util para exportar 'el conteo consolidado' tal cual, como respaldo
    o para revisarlo antes de compararlo contra el sistema.

    Devuelve una lista de dicts: {sku, desc, bodega, cantidad, auditores, detalle}
    """
    def _clave(sku, bodega):
        return sku if nivel == "sku" else f"{sku}|{bodega}"

    def _consolidar_grupo(lista_auditores):
        grupo = {}
        for auditor in lista_auditores:
            for fila in auditor["filas"]:
                clave = _clave(fila["sku"], fila["bodega"])
                if clave not in grupo:
                    grupo[clave] = {"sku": fila["sku"], "desc": fila.get("desc", ""),
                                     "bodegas": set(), "total": 0, "auditores": set(),
                                     "detalle": {}, "racks": {}}
                grupo[clave]["total"] += fila["cantidad"]
                grupo[clave]["auditores"].add(auditor["nombre_auditor"])
                grupo[clave]["bodegas"].add(fila["bodega"] or "(sin bodega)")
                if not grupo[clave]["desc"]:
                    grupo[clave]["desc"] = fila.get("desc", "")
                loc = fila["localizacion"] or "(sin localizacion)"
                grupo[clave]["detalle"][loc] = grupo[clave]["detalle"].get(loc, 0) + fila["cantidad"]
                if fila.get("rack") and loc not in grupo[clave]["racks"]:
                    grupo[clave]["racks"][loc] = fila["rack"]
        return grupo

    iniciales = _consolidar_grupo([a for a in auditores if a["tipo"] == "inicial"])
    reconteos = _consolidar_grupo([a for a in auditores if a["tipo"] == "reconteo"])

    resultados = []
    for clave in set(iniciales.keys()) | set(reconteos.keys()):
        elegido = reconteos.get(clave) or iniciales.get(clave)
        bodega_mostrar = "(varias)" if len(elegido["bodegas"]) > 1 else next(iter(elegido["bodegas"]), "")
        resultados.append({
            "sku": elegido["sku"], "desc": elegido["desc"], "bodega": bodega_mostrar,
            "cantidad": elegido["total"],
            "auditores": ", ".join(sorted(elegido["auditores"])),
            "detalle": _formatear_detalle(elegido["detalle"], elegido.get("racks")),
            "fue_reconteo": clave in reconteos,
        })

    resultados.sort(key=lambda r: r["sku"])
    return resultados


# ══════════════════════════════════════════════════
#  PASO 4: CONSOLIDAR CONTRA EXISTENCIA (varios auditores + reconteos)
# ══════════════════════════════════════════════════

def consolidar_cedi(existencia_info, auditores, nivel="sku"):
    """
    Consolida todos los archivos de auditores cargados:
      1. Suma los conteos 'inicial' (entre auditores y localizaciones)
      2. Suma los 'reconteo' por separado
      3. El reconteo SUSTITUYE al inicial de la misma clave (no se suman)
      4. Cruza contra la existencia del sistema
      5. Calcula diferencia = contado - existencia, y el estado correspondiente

    nivel: "sku" (recomendado) agrupa SOLO por SKU, sumando todas las
           bodegas/ubicaciones juntas. Esto evita el problema de que la
           misma bodega venga escrita distinto entre el archivo de
           Existencia y el de Conteo (ej: "CENTRO DE DISTRIBUCION - 900"
           vs "CENTRO DISTRIBUCIÓN KIELSA - 9"), que de otra forma genera
           un falso Faltante Y un falso Fuera de Existencia para el mismo
           producto. "sku_bodega" agrupa por SKU + Bodega exacta (mas
           preciso si tus archivos SI usan nombres de bodega consistentes).

    existencia_info: viene de cargar_existencia_cedi()
    auditores: lista de resultados de procesar_archivo_auditor()

    Devuelve una lista de dicts:
      {sku, desc, casa, bodega, contado, existencia, diferencia, estado,
       auditores (string), detalle (string por localizacion), fue_reconteo}
    """
    existencia = existencia_info["existencia"]
    sku_desc_global = existencia_info["sku_desc_global"]
    sku_costo_global = existencia_info.get("sku_costo_global", {})
    skus_conocidos = {r["sku"] for r in existencia.values()}

    def _clave(sku, bodega):
        return sku if nivel == "sku" else f"{sku}|{bodega}"

    # Si consolidamos solo por SKU, agrupamos la existencia sumando todas
    # las bodegas de cada SKU en un solo valor.
    if nivel == "sku":
        existencia_agrupada = {}
        for r in existencia.values():
            sku = r["sku"]
            if sku not in existencia_agrupada:
                existencia_agrupada[sku] = {"existencia": 0, "desc": "", "casa": r["casa"], "costo": 0}
            existencia_agrupada[sku]["existencia"] += r["existencia"]
            if not existencia_agrupada[sku]["desc"] and r["desc"]:
                existencia_agrupada[sku]["desc"] = r["desc"]
            if not existencia_agrupada[sku]["costo"] and r.get("costo"):
                existencia_agrupada[sku]["costo"] = r["costo"]
        existencia_por_clave = existencia_agrupada
    else:
        existencia_por_clave = existencia

    def _consolidar_grupo(lista_auditores):
        grupo = {}
        for auditor in lista_auditores:
            for fila in auditor["filas"]:
                clave = _clave(fila["sku"], fila["bodega"])
                if clave not in grupo:
                    grupo[clave] = {"total": 0, "auditores": set(), "detalle": {}, "racks": {},
                                     "desc": fila.get("desc", ""), "bodegas": set()}
                grupo[clave]["total"] += fila["cantidad"]
                grupo[clave]["auditores"].add(auditor["nombre_auditor"])
                grupo[clave]["bodegas"].add(fila["bodega"] or "(sin bodega)")
                if not grupo[clave]["desc"]:
                    grupo[clave]["desc"] = fila.get("desc", "")
                loc = fila["localizacion"] or "(sin localizacion)"
                grupo[clave]["detalle"][loc] = grupo[clave]["detalle"].get(loc, 0) + fila["cantidad"]
                if fila.get("rack") and loc not in grupo[clave]["racks"]:
                    grupo[clave]["racks"][loc] = fila["rack"]
        return grupo

    iniciales = _consolidar_grupo([a for a in auditores if a["tipo"] == "inicial"])
    reconteos = _consolidar_grupo([a for a in auditores if a["tipo"] == "reconteo"])

    conteo_final = {}
    for clave in set(iniciales.keys()) | set(reconteos.keys()):
        rec = reconteos.get(clave)
        ini = iniciales.get(clave)
        elegido = rec or ini
        conteo_final[clave] = {
            "total": elegido["total"] if elegido else 0,
            "auditores": elegido["auditores"] if elegido else set(),
            "detalle": elegido["detalle"] if elegido else {},
            "racks": elegido["racks"] if elegido else {},
            "desc": elegido["desc"] if elegido else "",
            "bodegas": elegido["bodegas"] if elegido else set(),
            "fue_reconteo": bool(rec),
        }

    resultados = []
    todas_las_claves = set(conteo_final.keys()) | set(existencia_por_clave.keys())

    for clave in todas_las_claves:
        if nivel == "sku":
            sku, bodega = clave, ""
        else:
            if "|" not in clave:
                continue
            sku, bodega = clave.split("|", 1)
        if not sku:
            continue

        cnt = conteo_final.get(clave)
        ex = existencia_por_clave.get(clave)

        contado = cnt["total"] if cnt else 0
        exist_sistema = ex["existencia"] if ex else 0
        casa = ex["casa"] if ex else "SIN CASA"
        desc = (ex["desc"] if ex else "") or (cnt["desc"] if cnt else "") or sku_desc_global.get(sku, "") or "(sin descripcion)"
        costo_unitario = (ex.get("costo") if ex else 0) or sku_costo_global.get(sku, 0)

        if contado == 0 and exist_sistema == 0:
            continue

        fuera_existencia = sku not in skus_conocidos and contado > 0
        diferencia = contado - exist_sistema
        valor_diferencia = diferencia * costo_unitario

        if fuera_existencia:
            estado = "FUERA_EXISTENCIA"
        elif diferencia > 0:
            estado = "SOBRANTE"
        elif diferencia < 0:
            estado = "FALTANTE"
        else:
            estado = "OK"

        bodega_mostrar = bodega or ("(varias)" if nivel == "sku" and cnt and len(cnt["bodegas"]) > 1
                                     else next(iter(cnt["bodegas"]), "(sin bodega)") if cnt else "(sin bodega)")

        resultados.append({
            "sku": sku, "desc": desc, "casa": casa, "bodega": bodega_mostrar,
            "contado": contado, "existencia": exist_sistema, "diferencia": diferencia,
            "costo_unitario": costo_unitario, "valor_diferencia": valor_diferencia,
            "estado": estado, "observacion": "",
            "auditores": ", ".join(sorted(cnt["auditores"])) if cnt else "",
            "detalle": _formatear_detalle(cnt["detalle"], cnt.get("racks")) if cnt else "",
            "fue_reconteo": cnt["fue_reconteo"] if cnt else False,
        })

    # Rellenamos la "casa" de SKUs que solo aparecen en conteo, buscando
    # si ese mismo SKU aparece con casa conocida en otra bodega
    mapa_sku_casa = {}
    for r in existencia.values():
        if r["casa"]:
            mapa_sku_casa.setdefault(r["sku"], r["casa"])
    for r in resultados:
        if r["casa"] == "SIN CASA" and r["sku"] in mapa_sku_casa:
            r["casa"] = mapa_sku_casa[r["sku"]]

    resultados.sort(key=lambda r: (r["casa"], r["bodega"], r["sku"]))
    return resultados