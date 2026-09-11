# Este es nuestro primer script de prueba
# Vamos a confirmar que Python y las librerías funcionan correctamente

print("¡Hola! Mi robot de auditoría está empezando a cobrar vida 🤖")

# Probamos que pandas (para manejar Excel) está instalado
import pandas as pd
print("Pandas está funcionando correctamente. Versión:", pd.__version__)

# Probamos que openpyxl (para leer/escribir Excel) está instalado
import openpyxl
print("Openpyxl está funcionando correctamente. Versión:", openpyxl.__version__)

# Probamos que playwright (para controlar el navegador) está instalado
import playwright
print("Playwright está instalado correctamente")

print("\n✅ Todo listo. El ambiente está funcionando perfectamente.")
