import sqlite3
import psycopg2
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from psycopg2.extras import RealDictCursor
import os
app = FastAPI()

# 1. Configuración de CORS para que el navegador no bloquee la web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Función de conexión (ESTA ES LA QUE TE FALTABA)
def conectar_db():
    # Nos conectamos a la nube en lugar de a un archivo local
    conexion = psycopg2.connect('postgresql://neondb_owner:npg_fbspi5NthvQ8@ep-shy-rain-aby96mld-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require')
    return conexion

# 3. Inicialización de la base de datos
def inicializar_db():
    conexion = conectar_db()
    cursor = conexion.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activos (
            id SERIAL PRIMARY KEY,
            categoria TEXT,
            modelo TEXT,
            serie TEXT UNIQUE,
            estado TEXT DEFAULT 'Disponible',
            usuario TEXT DEFAULT 'N/A'
        )
    ''')
    conexion.commit()
    conexion.close()

# Ejecutamos la creación de la tabla al arrancar
inicializar_db()

# --- RUTAS ---

@app.get("/")
def home():
    return FileResponse("index.html")

@app.get("/activos")
def obtener_activos():
    conexion = conectar_db()
    cursor = conexion.cursor()
    cursor.execute("SELECT * FROM activos")
    datos = [dict(row) for row in cursor.fetchall()]
    conexion.close()
    return datos

@app.post("/crear")
def crear_activo(datos: dict = Body(...)):
    conexion = conectar_db()
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "INSERT INTO activos (categoria, modelo, serie) VALUES (?, ?, ?)",
            (datos.get('categoria'), datos.get('modelo'), datos.get('serie'))
        )
        conexion.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conexion.close()

@app.post("/asignar")
def asignar_activo(datos: dict = Body(...)):
    conexion = conectar_db()
    cursor = conexion.cursor()
    cursor.execute(
        "UPDATE activos SET usuario = ?, estado = 'Asignado' WHERE id = ?",
        (datos.get('usuario'), datos.get('id'))
    )
    conexion.commit()
    conexion.close()
    return {"status": "success"}

@app.delete("/eliminar/{id}")
def eliminar_activo(id: int):
    conexion = conectar_db()
    cursor = conexion.cursor()
    cursor.execute("DELETE FROM activos WHERE id = ?", (id,))
    conexion.commit()
    conexion.close()
    return {"status": "success"}