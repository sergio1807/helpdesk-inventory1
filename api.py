import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import pandas as pd
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Optional, List
import os
import secrets
from io import BytesIO
from datetime import datetime, timedelta

app = FastAPI()
security = HTTPBasic()

def check_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, "supersecreto123")
    if not (correct_username and correct_password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ActivoSchema(BaseModel):
    categoria: str
    modelo: str
    serie: str
    numero_activo: str
    delegacion: str
    coste: Optional[float] = 0.0
    fecha_compra: Optional[str] = ""
    fin_garantia: Optional[str] = "" # NUEVO CAMPO

class AsignacionSchema(BaseModel):
    id: int
    usuario: str

class EstadoSchema(BaseModel):
    id: int
    estado: str
    nota: str

class MasivoSchema(BaseModel): # NUEVO PARA BORRADO MASIVO
    ids: List[int]

try:
    db_pool = psycopg2.pool.SimpleConnectionPool(1, 20, dsn=os.getenv("DATABASE_URL"))
    print("✅ BD Conectada")
except Exception as e:
    print(f"❌ Error BD: {e}")

def get_conn():
    if db_pool: return db_pool.getconn()
    raise HTTPException(status_code=500, detail="Error de conexión")

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
                estado TEXT DEFAULT 'Disponible', usuario TEXT DEFAULT 'N/A',
                activo BOOLEAN DEFAULT TRUE,
                numero_activo TEXT DEFAULT '', delegacion TEXT DEFAULT 'Central',
                coste NUMERIC(10,2) DEFAULT 0, fecha_compra TEXT DEFAULT '',
                fin_garantia TEXT DEFAULT ''
            )''')
        # MIGRACIONES AUTOMÁTICAS
        cur.execute("ALTER TABLE activos ADD COLUMN IF NOT EXISTS fin_garantia TEXT DEFAULT ''")
        
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

inicializar_db()

# --- RUTAS ---

@app.get("/")
def home(user: str = Depends(check_credentials)):
    return FileResponse("index.html") if os.path.exists("index.html") else "Sube index.html"

@app.get("/activos", dependencies=[Depends(check_credentials)])
def leer_activos():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM activos WHERE activo = TRUE ORDER BY id DESC")
        return cur.fetchall()
    finally: release_conn(conn)

@app.get("/actividad", dependencies=[Depends(check_credentials)])
def actividad_reciente():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT h.detalle, h.fecha, a.modelo, a.numero_activo FROM historial h JOIN activos a ON h.activo_id = a.id ORDER BY h.fecha DESC LIMIT 10")
        return cur.fetchall()
    finally: release_conn(conn)

@app.post("/crear", dependencies=[Depends(check_credentials)])
def crear(activo: ActivoSchema):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, activo FROM activos WHERE serie = %s", (activo.serie,))
        existe = cur.fetchone()
        if existe:
            if existe[1] is True: return {"status": "error", "message": "Serie duplicada"}
            cur.execute("""UPDATE activos SET activo = TRUE, categoria=%s, modelo=%s, numero_activo=%s, 
                        delegacion=%s, coste=%s, fecha_compra=%s, fin_garantia=%s, estado='Disponible' WHERE id=%s""", 
                        (activo.categoria, activo.modelo, activo.numero_activo, activo.delegacion, 
                         activo.coste, activo.fecha_compra, activo.fin_garantia, existe[0]))
            conn.commit()
            return {"status": "success", "message": "Reactivado"}
        
        cur.execute("""INSERT INTO activos (categoria, modelo, serie, numero_activo, delegacion, coste, fecha_compra, fin_garantia) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                    (activo.categoria, activo.modelo, activo.serie, activo.numero_activo, activo.delegacion, 
                     activo.coste, activo.fecha_compra, activo.fin_garantia))
        conn.commit()
        return {"status": "success"}
    except Exception as e: return {"status": "error", "message": str(e)}
    finally: release_conn(conn)

@app.put("/actualizar/{id}", dependencies=[Depends(check_credentials)])
def actualizar(id: int, activo: ActivoSchema):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""UPDATE activos SET categoria=%s, modelo=%s, serie=%s, numero_activo=%s, 
                    delegacion=%s, coste=%s, fecha_compra=%s, fin_garantia=%s WHERE id=%s""", 
                    (activo.categoria, activo.modelo, activo.serie, activo.numero_activo, 
                     activo.delegacion, activo.coste, activo.fecha_compra, activo.fin_garantia, id))
        conn.commit()
        return {"status": "success"}
    except Exception as e: return {"status": "error", "message": str(e)}
    finally: release_conn(conn)

@app.post("/asignar", dependencies=[Depends(check_credentials)])
def asignar(datos: AsignacionSchema):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE activos SET usuario=%s, estado='Asignado' WHERE id=%s", (datos.usuario, datos.id))
        cur.execute("INSERT INTO historial (activo_id, detalle) VALUES (%s, %s)", (datos.id, f"Asignado a {datos.usuario}"))
        conn.commit()
        return {"status": "success"}
    finally: release_conn(conn)

@app.post("/estado", dependencies=[Depends(check_credentials)])
def estado(datos: EstadoSchema):
    conn = get_conn()
    try:
        cur = conn.cursor()
        u = 'N/A' if datos.estado in ['Disponible', 'En Reparación'] else 'N/A'
        cur.execute("UPDATE activos SET estado=%s, usuario=%s WHERE id=%s", (datos.estado, u, datos.id))
        cur.execute("INSERT INTO historial (activo_id, detalle) VALUES (%s, %s)", (datos.id, f"Estado: {datos.estado}. {datos.nota}"))
        conn.commit()
        return {"status": "success"}
    finally: release_conn(conn)

@app.delete("/eliminar/{id}", dependencies=[Depends(check_credentials)])
def eliminar(id: int):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE activos SET activo = FALSE WHERE id = %s", (id,))
        conn.commit()
        return {"status": "success"}
    finally: release_conn(conn)

# NUEVO: Endpoint para borrado masivo
@app.post("/eliminar-masivo", dependencies=[Depends(check_credentials)])
def eliminar_masivo(datos: MasivoSchema):
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Convertimos la lista de IDs a una tupla para SQL
        if not datos.ids: return {"status": "error", "message": "Nada seleccionado"}
        cur.execute("UPDATE activos SET activo = FALSE WHERE id = ANY(%s)", (datos.ids,))
        conn.commit()
        return {"status": "success"}
    finally: release_conn(conn)

@app.get("/historial/{id}", dependencies=[Depends(check_credentials)])
def historial(id: int):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT detalle, fecha FROM historial WHERE activo_id = %s ORDER BY fecha DESC", (id,))
        return cur.fetchall()
    finally: release_conn(conn)

@app.get("/exportar")
def exportar():
    conn = get_conn()
    try:
        df = pd.read_sql("SELECT * FROM activos WHERE activo = TRUE", conn)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        output.seek(0)
        return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=inventario.xlsx"})
    finally: release_conn(conn)

@app.post("/importar", dependencies=[Depends(check_credentials)])
def importar(file: UploadFile = File(...)):
    conn = get_conn()
    try:
        df = pd.read_excel(BytesIO(file.file.read()), engine='openpyxl')
        for c in ['numero_activo','delegacion','fecha_compra','fin_garantia']: 
            if c not in df.columns: df[c]=''
        if 'coste' not in df.columns: df['coste']=0
        
        cur = conn.cursor()
        n=0
        for _, r in df.iterrows():
            try:
                cur.execute("SELECT id FROM activos WHERE serie=%s",(str(r['serie']),))
                if not cur.fetchone():
                    cur.execute("""INSERT INTO activos (categoria,modelo,serie,numero_activo,delegacion,coste,fecha_compra,fin_garantia) 
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                (r['categoria'],r['modelo'],str(r['serie']),str(r['numero_activo']),str(r['delegacion']),
                                 float(r['coste'] or 0),str(r['fecha_compra']),str(r['fin_garantia'])))
                    n+=1
            except: conn.rollback(); continue
        conn.commit()
        return {"status":"success", "message":f"Importados: {n}"}
    except Exception as e: return {"status":"error", "message":str(e)}
    finally: release_conn(conn)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))