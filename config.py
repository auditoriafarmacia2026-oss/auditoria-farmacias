"""
Lee la configuracion (usuario, contraseña, url del portal, usuarios
auditores) desde el lugar correcto segun donde este corriendo la app:

- En tu computadora: desde el archivo .env
- En Streamlit Community Cloud: desde los "Secrets" que se configuran
  en la pagina web de Streamlit (nunca se sube el .env a internet)

Asi el mismo codigo funciona sin cambios en los dos lugares.
"""

import os

from dotenv import load_dotenv

load_dotenv()  # si existe un .env local, lo carga (no pasa nada si no existe)

try:
    import streamlit as st
    _TIENE_STREAMLIT = True
except ImportError:
    _TIENE_STREAMLIT = False


def obtener(clave, valor_por_defecto=""):
    """Busca 'clave' primero en los Secrets de Streamlit Cloud, y si no
    esta ahi (ej: cuando corres localmente), la busca en el .env / las
    variables de entorno normales."""
    if _TIENE_STREAMLIT:
        try:
            if clave in st.secrets:
                return st.secrets[clave]
        except Exception:
            pass  # no hay archivo de secrets configurado (normal en local)
    return os.getenv(clave, valor_por_defecto)