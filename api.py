import sqlite3
import psycopg2
import pandas as pd
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from psycopg2.extras import RealDictCursor
import os
from io import BytesIO
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
    conexion = psycopg2.connect(os.getenv("DATABASE_URL"))
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
    # Usamos RealDictCursor para que dict(row) funcione correctamente
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM activos")
    filas = cursor.fetchall()
    conexion.close()
    return [dict(row) for row in filas]

@app.post("/crear")
def crear_activo(d: dict = Body(...)):
    conexion = conectar_db()
    cursor = conexion.cursor()
    try:
        # 1. VALIDACIÓN: ¿Ya existe este número de serie?
        cursor.execute("SELECT id FROM activos WHERE serie = %s", (d['serie'],))
        if cursor.fetchone():
            return {"status": "error", "message": "¡Error! Ese Número de Serie ya está registrado."}

        # 2. REGISTRO
        cursor.execute(
            "INSERT INTO activos (categoria, modelo, serie) VALUES (%s, %s, %s)", 
            (d['categoria'], d['modelo'], d['serie'])
        )
        conexion.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conexion.close()

@app.post("/asignar")
def asignar(d: dict = Body(...)):
    conexion = conectar_db()
    cursor = conexion.cursor()
    try:
        # Actualizamos el activo
        cursor.execute("UPDATE activos SET usuario = %s, estado = 'Asignado' WHERE id = %s", (d['usuario'], d['id']))
        
        # HISTORIAL: Guardamos quién lo recibió y cuándo
        cursor.execute(
            "INSERT INTO historial (activo_id, detalle) VALUES (%s, %s)", 
            (d['id'], f"Equipo entregado a {d['usuario']}")
        )
        
        conexion.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conexion.close()

@app.delete("/eliminar/{id}")
def eliminar_activo(id: int):
    conexion = conectar_db()
    cursor = conexion.cursor()
    # CAMBIO: Usamos %s en lugar de ?
    cursor.execute("DELETE FROM activos WHERE id = %s", (id,))
    conexion.commit()
    conexion.close()
    return {"status": "success"}

@app.get("/exportar")
def exportar():
    try:
        conexion = conectar_db()
        # Importante: Pandas necesita la conexión directa
        df = pd.read_sql("SELECT * FROM activos", conexion)
        conexion.close()

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Inventario_IT')
        
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=reporte_it.xlsx"}
        )
    except Exception as e:
        # Esto te dirá el error real en los Logs de Render
        print(f"Error en exportar: {e}")
        return {"status": "error", "message": str(e)}