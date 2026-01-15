import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import os
from io import BytesIO
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

app = FastAPI()

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELOS DE DATOS (Validación) ---
class ActivoSchema(BaseModel):
    categoria: str
    modelo: str
    serie: str

class AsignacionSchema(BaseModel):
    id: int
    usuario: str

# --- BASE DE DATOS (Pool de Conexiones) ---
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(1, 20, dsn=os.getenv("DATABASE_URL"))
    print("✅ BD Conectada")
except Exception as e:
    print(f"❌ Error BD: {e}")

def get_conn():
    if db_pool: return db_pool.getconn()
    raise HTTPException(status_code=500, detail="Error de conexión a BD")

def release_conn(conn):
    if db_pool and conn: db_pool.putconn(conn)

def inicializar_db():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS activos (
                id SERIAL PRIMARY KEY,
                categoria TEXT, modelo TEXT, serie TEXT UNIQUE,
                estado TEXT DEFAULT 'Disponible', usuario TEXT DEFAULT 'N/A'
            )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS historial (
                id SERIAL PRIMARY KEY,
                activo_id INTEGER REFERENCES activos(id) ON DELETE CASCADE,
                detalle TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        conn.commit()
        cur.close()
    finally:
        release_conn(conn)

def check_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    # Cambia esto por un usuario y contraseña seguros
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, "supersecreto123")
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

inicializar_db()

# --- RUTAS ---

@app.get("/", dependencies=[Depends(check_credentials)])
def home():
    return FileResponse("index.html") if os.path.exists("index.html") else "Sube el archivo index.html"

@app.get("/activos", dependencies=[Depends(check_credentials)])
def leer_activos():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM activos ORDER BY id DESC")
        return cur.fetchall()
    finally:
        cur.close()
        release_conn(conn)

@app.post("/crear", dependencies=[Depends(check_credentials)])
def crear(activo: ActivoSchema):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM activos WHERE serie = %s", (activo.serie,))
        if cur.fetchone():
            return {"status": "error", "message": "Ese número de serie ya existe"}
        
        cur.execute("INSERT INTO activos (categoria, modelo, serie) VALUES (%s, %s, %s)",
                    (activo.categoria, activo.modelo, activo.serie))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        release_conn(conn)

@app.put("/actualizar/{id}", dependencies=[Depends(check_credentials)])
def actualizar(id: int, activo: ActivoSchema):
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Verificar que la serie no pertenezca a otro equipo
        cur.execute("SELECT id FROM activos WHERE serie = %s AND id != %s", (activo.serie, id))
        if cur.fetchone():
            return {"status": "error", "message": "Serie duplicada en otro equipo"}

        cur.execute(
            "UPDATE activos SET categoria=%s, modelo=%s, serie=%s WHERE id=%s",
            (activo.categoria, activo.modelo, activo.serie, id)
        )
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        release_conn(conn)

@app.post("/asignar", dependencies=[Depends(check_credentials)])
def asignar(datos: AsignacionSchema):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE activos SET usuario=%s, estado='Asignado' WHERE id=%s", (datos.usuario, datos.id))
        cur.execute("INSERT INTO historial (activo_id, detalle) VALUES (%s, %s)", (datos.id, f"Asignado a {datos.usuario}"))
        conn.commit()
        return {"status": "success"}
    finally:
        release_conn(conn)

@app.delete("/eliminar/{id}", dependencies=[Depends(check_credentials)])
def eliminar(id: int):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM activos WHERE id = %s", (id,))
        conn.commit()
        return {"status": "success"}
    finally:
        release_conn(conn)

@app.get("/historial/{id}", dependencies=[Depends(check_credentials)])
def historial(id: int):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT detalle, fecha FROM historial WHERE activo_id = %s ORDER BY fecha DESC", (id,))
        return cur.fetchall()
    finally:
        release_conn(conn)

@app.get("/exportar", dependencies=[Depends(check_credentials)])
def exportar():
    conn = get_conn()
    try:
        # Pandas requiere conexión directa o sqlalchemy, aquí usamos raw connection con warning silenciado
        df = pd.read_sql("SELECT * FROM activos", conn)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=inventario_it.xlsx"})
    finally:
        release_conn(conn)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)