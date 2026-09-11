"""
Guarda y recupera el trabajo de cada auditor (existencia, kardex, etc.)
en disco, para que no se pierda al cerrar la aplicacion ni tengan que
volver a buscar el archivo cada vez. Cada auditor tiene su propia carpeta,
identificada por su usuario de login.
"""

import json
import os
from datetime import datetime

CARPETA_SESIONES = "sesiones"
os.makedirs(CARPETA_SESIONES, exist_ok=True)


def _ruta_usuario(usuario, nombre_archivo):
    carpeta = os.path.join(CARPETA_SESIONES, usuario)
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, nombre_archivo)


def guardar_existencia(usuario, resultado_existencia):
    """Guarda el resultado de cargar_existencia() en disco para ese usuario."""
    datos = dict(resultado_existencia)
    datos["_guardado_el"] = datetime.now().isoformat()
    ruta = _ruta_usuario(usuario, "existencia.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def cargar_existencia(usuario):
    """Recupera la existencia guardada de ese usuario, o None si no hay ninguna."""
    ruta = _ruta_usuario(usuario, "existencia.json")
    if not os.path.exists(ruta):
        return None
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_kardex(usuario, kardex_dict, meta, detalle_por_sku_tipo=None, resumen_tipos=None):
    """Guarda el kardex (ya sumado por SKU) junto con metadatos
    (bodega, rango de fechas usado, cantidad de movimientos, etc.)
    y el detalle por tipo de documento para el resumen y el analisis por articulo."""
    datos = {
        "kardex": kardex_dict,
        "meta": meta,
        "detalle_por_sku_tipo": detalle_por_sku_tipo or {},
        "resumen_tipos": resumen_tipos or {},
        "_guardado_el": datetime.now().isoformat(),
    }
    ruta = _ruta_usuario(usuario, "kardex.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def cargar_kardex(usuario):
    ruta = _ruta_usuario(usuario, "kardex.json")
    if not os.path.exists(ruta):
        return None
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def borrar_existencia(usuario):
    ruta = _ruta_usuario(usuario, "existencia.json")
    if os.path.exists(ruta):
        os.remove(ruta)


def borrar_kardex(usuario):
    ruta = _ruta_usuario(usuario, "kardex.json")
    if os.path.exists(ruta):
        os.remove(ruta)