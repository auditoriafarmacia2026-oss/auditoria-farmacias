"""
Sistema simple de usuario y contraseña para proteger la app cuando este
publicada en internet. No usa librerias externas complejas: es un
mecanismo sencillo pero funcional, pensado para un equipo pequeno de
auditores (no para miles de usuarios).

Los usuarios y contraseñas se definen mediante una variable de entorno
AUDITORES_JSON con este formato (las contraseñas van "hasheadas", nunca
en texto plano):

  AUDITORES_JSON={"jperez": "<hash>", "mgomez": "<hash>"}

Para generar el hash de una contraseña, correr en la terminal:
  python auth.py generar_hash "laContraseñaQueQuieras"
"""

import hashlib
import json
import os
import sys

import streamlit as st


def _hash_password(password_texto_plano):
    """Convierte una contraseña en un 'hash' irreversible (SHA-256).
    Nunca guardamos la contraseña real, solo esta huella digital."""
    return hashlib.sha256(password_texto_plano.encode("utf-8")).hexdigest()


def _cargar_usuarios():
    """Lee la lista de usuarios permitidos (Secrets en la nube, o .env local)."""
    from config import obtener
    crudo = obtener("AUDITORES_JSON", "{}")
    try:
        return json.loads(crudo)
    except json.JSONDecodeError:
        return {}


def requerir_login():
    """
    Muestra un formulario de usuario/contraseña y detiene la ejecucion
    del resto de la app hasta que el login sea correcto.
    Se debe llamar al principio de app.py, antes de mostrar cualquier otra cosa.
    """
    if st.session_state.get("autenticado"):
        return  # ya inicio sesion antes en esta misma pestana del navegador

    st.title("🔒 Robot de Auditoria de Farmacias")
    st.write("Ingresa tu usuario y contraseña para continuar.")

    with st.form("form_login"):
        usuario = st.text_input("Usuario")
        clave = st.text_input("Contraseña", type="password")
        enviado = st.form_submit_button("Ingresar")

    if enviado:
        usuarios = _cargar_usuarios()
        hash_ingresado = _hash_password(clave)
        if usuario in usuarios and usuarios[usuario] == hash_ingresado:
            st.session_state.autenticado = True
            st.session_state.usuario_actual = usuario
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")

    st.stop()  # no dejamos que el resto de la app se muestre hasta hacer login


if __name__ == "__main__":
    # Uso desde terminal: python auth.py generar_hash "miContraseña"
    if len(sys.argv) == 3 and sys.argv[1] == "generar_hash":
        print(_hash_password(sys.argv[2]))
    else:
        print('Uso: python auth.py generar_hash "laContraseñaDeseada"')