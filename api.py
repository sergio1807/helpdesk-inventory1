import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import pandas as pd
from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
import os
from io import BytesIO

app = FastAPI()

# 1. Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. POOL DE CONEXIONES (Optimización Clave)
# Esto mantiene entre 1 y 10 conexiones vivas para no reconectar constantemente.
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(
        1, 20, 
        dsn=os.getenv("DATABASE_URL")
    )
    print("✅ Pool de conexiones PostgreSQL iniciado correctamente.")
except Exception as e:
    print(f"❌ Error conectando a la BD: {e}")

def get_db_connection():
    """Obtiene una conexión del pool y asegura que se devuelva al final."""
    if db_pool:
        return db_pool.getconn()
    else:
        raise HTTPException(status_code=500, detail="No se pudo conectar a la BD")

def release_db_connection(conn):
    """Devuelve la conexión al pool para que otro usuario la use."""
    if db_pool and conn:
        db_pool.putconn(conn)

# 3. Inicialización de Tablas (CORREGIDO: Faltaba la tabla historial)
def inicializar_db():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Tabla Activos
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

        # Tabla Historial (¡ESTA FALTABA!)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS historial (
                id SERIAL PRIMARY KEY,
                activo_id INTEGER REFERENCES activos(id) ON DELETE CASCADE,
                detalle TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cursor.close()
        print("✅ Tablas verificadas/creadas correctamente.")
    except Exception as e:
        print(f"❌ Error inicializando DB: {e}")
    finally:
        release_db_connection(conn)

# Ejecutamos al inicio
inicializar_db()

# --- RUTAS ---

@app.get("/")
def home():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"message": "API Activa. Sube tu index.html"}

@app.get("/activos")
def obtener_activos():
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM activos ORDER BY id DESC") # Ordenado por más reciente
        filas = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in filas]
    finally:
        release_db_connection(conn)

@app.post("/crear")
def crear_activo(d: dict = Body(...)):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Validación de duplicados
        cursor.execute("SELECT id FROM activos WHERE serie = %s", (d['serie'],))
        if cursor.fetchone():
            return {"status": "error", "message": "¡El número de serie ya existe!"}

        cursor.execute(
            "INSERT INTO activos (categoria, modelo, serie) VALUES (%s, %s, %s)", 
            (d['categoria'], d['modelo'], d['serie'])
        )
        conn.commit()
        cursor.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        release_db_connection(conn)

@app.post("/asignar")
def asignar(d: dict = Body(...)):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        activo_id = d.get('id')
        usuario = d.get('usuario')

        # 1. Actualizar estado del activo
        cursor.execute(
            "UPDATE activos SET usuario = %s, estado = 'Asignado' WHERE id = %s", 
            (usuario, activo_id)
        )
        
        # 2. Insertar en historial
        cursor.execute(
            "INSERT INTO historial (activo_id, detalle) VALUES (%s, %s)", 
            (activo_id, f"Asignado a {usuario}")
        )
        
        conn.commit()
        cursor.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        release_db_connection(conn)

@app.delete("/eliminar/{id}")
def eliminar_activo(id: int):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM activos WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        return {"status": "success"}
    finally:
        release_db_connection(conn)

@app.get("/historial/{activo_id}")
def obtener_historial(activo_id: int):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Traemos también la fecha formateada
        cursor.execute("""
            SELECT detalle, fecha 
            FROM historial 
            WHERE activo_id = %s 
            ORDER BY fecha DESC
        """, (activo_id,))
        res = cursor.fetchall()
        cursor.close()
        return res
    finally:
        release_db_connection(conn)

@app.get("/exportar")
def exportar():
    conn = get_db_connection()
    try:
        # Pandas necesita una conexión raw (no del pool directamente, pero psycopg2 standard funciona)
        # Nota: pd.read_sql a veces da warnings con conexiones de pool, pero suele funcionar.
        # Si falla, usamos una conexión directa temporal.
        df = pd.read_sql("SELECT * FROM activos", conn)
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Inventario')
        
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=inventario_it.xlsx"}
        )
    except Exception as e:
        print(f"Error exportando: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        release_db_connection(conn)

# --- ARRANQUE ---
if __name__ == "__main__":
    import uvicorn
    # Render asigna el puerto dinámicamente
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)