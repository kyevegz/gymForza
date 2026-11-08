import os

from typing import Annotated
from decimal import Decimal 
from typing import Optional

import uuid
import cloudinary
import cloudinary.uploader

import psycopg2
from psycopg2.extras import RealDictCursor
from dbutils.pooled_db import PooledDB

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
import bcrypt

from dotenv import load_dotenv

load_dotenv()

#configuración de la bd para las fotos
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

pool = PooledDB(
    creator=psycopg2,         
    maxconnections=10,        
    mincached=2,              
    maxcached=5,              
    blocking=True,            
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    sslmode=os.getenv("SSL_MODE", "require"), 
    # RealDictCursor convierte los resultados de Postgres (que por defecto son tuplas) 
    cursor_factory=RealDictCursor 
)


def get_db():
    
    conn = pool.connection() #solicita una conexión al pool
    try: #intenta que...
        yield conn 
        #en lugar de usar return, usamos yield para que la función sea un generador y pueda ser usada como dependencia en FastAPI
        #lo que hace es prestar la conexión temporalmente al código que lo solicita, en este punti
        #la función se pausa mientras el programa sigue haciendo consultas, cuando ese código externo
        #termina, el control regrsa a esta función

    finally :#se ejecuta sí o sí, independientemente de si hubo un error o no
        conn.close() #y sirve para liberar la conexión

# 2. Schemas de Pydantic, donde se validan los datos
# Define qué datos debe ENVIAR el cliente para crear una orden.
class RegistroCliente(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    apellido: str = Field(min_length=1, max_length=80)
    telefono: str = Field(pattern=r"^\d{10}$")
    cuota_mensual: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")  # PIN de 4 dígitos

class RegistroClienteResponse(BaseModel):
    id: int
    nombre: str
    apellido: str
    telefono: str
    cuota_mensual: Decimal 
    foto_url: str 
    qr_token: UUID 
    activo: bool
    fecha_registro: datetime

class LoginCliente(BaseModel):
    telefono: str = Field(pattern=r"^\d{10}$") 
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


app = FastAPI(title="Gym Forza API")

@app.get("/")
def inicio():
    return {"mensaje": "API de Gym Forza funcionando"}

@app.post("/clientes", status_code=201)
def registrar_cliente(
    datos: Annotated[RegistroCliente, Form()], #los campos de texto del formulario
    foto: UploadFile = File(...), #los puntits ... hacen que sea obligatoria
    conn=Depends(get_db),
):
    if not foto.content_type or not foto.content_type.startswith("image/"): #determina que sea una imagen
        raise HTTPException(400, "La foto debe ser una imagen")

    #en primer lugar, sube la foto
    subida = cloudinary.uploader.upload(
        foto.file, folder = "gym_forza", public_id = str(uuid.uuid4())
    )

    #en segundo lugar, inserta al cliente ya con la url de su foto
    try:
        with conn.cursor() as cursor:
            pin = bcrypt.hashpw(datos.pin.encode(), bcrypt.gensalt()).decode() #hashea el pin antes de guardarlo
            cursor.execute(
                """
                INSERT INTO clientes (nombre, apellido, telefono, cuota_mensual, foto_url, pin)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, nombre, apellido, telefono, cuota_mensual, foto_url,
                    qr_token, activo, fecha_registro
                """,
                (datos.nombre, datos.apellido, datos.telefono, 
                datos.cuota_mensual, subida["secure_url"], pin),
            )
            cliente = cursor.fetchone()
        conn.commit()
        return cliente
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        cloudinary.uploader.destroy(subida["public_id"]) #borra la foto subida si hubo error
        raise HTTPException(409, "Ya existe un cliente con ese número telefónico")
    except Exception as e:
        conn.rollback()
        cloudinary.uploader.destroy(subida["public_id"])
        raise HTTPException(500, f"Error al registrar al cliente: {e}")



@app.post("/login")
def login_cliente(
    datos: LoginCliente,
    conn = Depends(get_db)
):
    
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, nombre, apellido, telefono, foto_url, cuota_mensual, qr_token, activo, pin
            FROM clientes
            WHERE telefono = %s
            """,
            (datos.telefono,),
        )
        cliente = cursor.fetchone()

    if cliente is None or not bcrypt.checkpw(datos.pin.encode(), cliente["pin"].encode()):
        raise HTTPException(401, "Teléfono o PIN incorrectos")
    if not cliente["activo"]:
        raise HTTPException(403, "El cliente ha sido dado de baja")
    cliente.pop("pin")  # Elimina el pin del diccionario antes de devolverlo
    
    return cliente
    