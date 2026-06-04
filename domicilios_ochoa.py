"""
API de Cotización de Domicilios - Rápido Ochoa
Calcula distancia y precio estimado desde una terminal hasta la dirección del cliente.

Endpoints:
  POST /cotizar              → cotiza con terminal explícita
  POST /cotizar-por-guia     → cotiza consultando la guía automáticamente
  GET  /terminales           → lista terminales disponibles
  GET  /zonas                → tarifas por zona
  GET  /health               → estado del servicio
"""

import re
import logging
from typing import Optional
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

import os
MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "")
OSRM_URL     = "http://router.project-osrm.org/route/v1/driving"

RASTREO_BASE = "https://rapidoochoa.tmsolutions.com.co/tmland/faces/public/tmland-carga/cotizador_envios.xhtml"
RASTREO_PARAM = "?parametroInicial=cmFwaWRvb2Nob2E="

# Estados que indican que la encomienda ya está en la terminal destino
ESTADOS_EN_TERMINAL = {
    "RECIBIDA EN BODEGA",
    "RECLAME EN OFICINA",
    "LISTA PARA FACTURAR",
    "ENTREGADA",
}

# Terminales con coordenadas, bbox y velocidad promedio real
TERMINALES = {
    "barranquilla": {
        "nombre": "Terminal Metropolitana de Soledad",
        "ciudad": "Barranquilla",
        "lat": 10.9095520,
        "lon": -74.7942613,
        "bbox": "-74.95,10.85,-74.72,11.05",
        "vel_kmh": 20,
        "departamento": "Atlántico",
    },
    "medellin_norte": {
        "nombre": "Terminal de Transporte Norte",
        "ciudad": "Medellín",
        "lat": 6.2909,
        "lon": -75.5565,
        "bbox": "-75.70,6.10,-75.45,6.42",
        "vel_kmh": 22,
        "departamento": "Antioquia",
    },
    "medellin_sur": {
        "nombre": "Terminal de Transporte Sur",
        "ciudad": "Medellín",
        "lat": 6.1948,
        "lon": -75.5900,
        "bbox": "-75.70,6.10,-75.45,6.42",
        "vel_kmh": 22,
        "departamento": "Antioquia",
    },
    "monteria": {
        "nombre": "Terminal de Transportes de Montería",
        "ciudad": "Montería",
        "lat": 8.7580,
        "lon": -75.8810,
        "bbox": "-76.00,8.65,-75.75,8.85",
        "vel_kmh": 25,
        "departamento": "Córdoba",
    },
    "cartagena": {
        "nombre": "Terminal de Transportes de Cartagena",
        "ciudad": "Cartagena",
        "lat": 10.3996,
        "lon": -75.5144,
        "bbox": "-75.65,10.30,-75.45,10.50",
        "vel_kmh": 22,
        "departamento": "Bolívar",
    },
    "sincelejo": {
        "nombre": "Terminal de Transportes de Sincelejo",
        "ciudad": "Sincelejo",
        "lat": 9.3040,
        "lon": -75.3980,
        "bbox": "-75.55,9.20,-75.25,9.40",
        "vel_kmh": 25,
        "departamento": "Sucre",
    },
    "santa_marta": {
        "nombre": "Terminal de Transportes de Santa Marta",
        "ciudad": "Santa Marta",
        "lat": 11.2274,
        "lon": -74.1889,
        "bbox": "-74.30,11.15,-74.05,11.30",
        "vel_kmh": 22,
        "departamento": "Magdalena",
    },
    "bogota": {
        "nombre": "Terminal de Transportes de Bogotá",
        "ciudad": "Bogotá",
        "lat": 4.6572,
        "lon": -74.1027,
        "bbox": "-74.25,4.50,-73.95,4.83",
        "vel_kmh": 18,
        "departamento": "Cundinamarca",
    },
    "caucasia": {
        "nombre": "Terminal de Caucasia",
        "ciudad": "Caucasia",
        "lat": 7.9893,
        "lon": -75.1993,
        "bbox": "-75.35,7.90,-75.10,8.08",
        "vel_kmh": 25,
        "departamento": "Antioquia",
    },
    "quibdo": {
        "nombre": "Terminal de Quibdó",
        "ciudad": "Quibdó",
        "lat": 5.6919,
        "lon": -76.6583,
        "bbox": "-76.80,5.60,-76.55,5.80",
        "vel_kmh": 22,
        "departamento": "Chocó",
    },
    "riohacha": {
        "nombre": "Terminal de Riohacha",
        "ciudad": "Riohacha",
        "lat": 11.5444,
        "lon": -72.9072,
        "bbox": "-73.05,11.46,-72.80,11.62",
        "vel_kmh": 25,
        "departamento": "La Guajira",
    },
    "maicao": {
        "nombre": "Terminal de Maicao",
        "ciudad": "Maicao",
        "lat": 11.3763,
        "lon": -72.2453,
        "bbox": "-72.35,11.30,-72.15,11.45",
        "vel_kmh": 25,
        "departamento": "La Guajira",
    },
    "planeta_rica": {
        "nombre": "Terminal de Planeta Rica",
        "ciudad": "Planeta Rica",
        "lat": 8.4077,
        "lon": -75.5864,
        "bbox": "-75.70,8.33,-75.50,8.48",
        "vel_kmh": 25,
        "departamento": "Córdoba",
    },
}

# Mapeo de palabras clave en la sede de trazabilidad → terminal
SEDE_A_TERMINAL = {
    "SOLEDAD":       "barranquilla",
    "BARRANQUILLA":  "barranquilla",
    "TERMINAL NORTE": "medellin_norte",
    "MEDELLIN TERMINAL DE TRANSPORTE NORTE": "medellin_norte",
    "TERMINAL SUR":  "medellin_sur",
    "MEDELLIN TERMINAL DE TRANSPORTE SUR": "medellin_sur",
    "MEDELLIN":      "medellin_norte",
    "MONTERIA":      "monteria",
    "CARTAGENA":     "cartagena",
    "SINCELEJO":     "sincelejo",
    "SANTA MARTA":   "santa_marta",
    "BOGOTA":        "bogota",
    "CAUCASIA":      "caucasia",
    "QUIBDO":        "quibdo",
    "RIOHACHA":      "riohacha",
    "MAICAO":        "maicao",
    "PLANETA RICA":  "planeta_rica",
}

# Mapeo ciudad destino (del campo destino de la guía) → terminal
CIUDAD_A_TERMINAL = {
    "BARRANQUILLA": "barranquilla",
    "ATLANTICO":    "barranquilla",
    "SOLEDAD":      "barranquilla",
    "MEDELLIN":     "medellin_norte",
    "ANTIOQUIA":    "medellin_norte",
    "MONTERIA":     "monteria",
    "CORDOBA":      "monteria",
    "CARTAGENA":    "cartagena",
    "BOLIVAR":      "cartagena",
    "SINCELEJO":    "sincelejo",
    "SUCRE":        "sincelejo",
    "SANTA MARTA":  "santa_marta",
    "MAGDALENA":    "santa_marta",
    "BOGOTA":       "bogota",
    "CUNDINAMARCA": "bogota",
    "CAUCASIA":     "caucasia",
    "QUIBDO":       "quibdo",
    "CHOCO":        "quibdo",
    "RIOHACHA":     "riohacha",
    "MAICAO":       "maicao",
    "GUAJIRA":      "riohacha",
    "PLANETA RICA": "planeta_rica",
}

# Tarifas por zona
ZONAS = [
    {"nombre": "Zona 1", "km_min": 0,   "km_max": 7,   "precio": 16000},
    {"nombre": "Zona 2", "km_min": 7,   "km_max": 12,  "precio": 20000},
    {"nombre": "Zona 3", "km_min": 12,  "km_max": 18,  "precio": 25000},
    {"nombre": "Zona 4", "km_min": 18,  "km_max": 25,  "precio": 30000},
    {"nombre": "Zona 5", "km_min": 25,  "km_max": 999, "precio": 38000},
]

# ── Modelos ───────────────────────────────────────────────────────────────────

class CotizarRequest(BaseModel):
    terminal: str
    direccion_destino: str

class CotizarPorGuiaRequest(BaseModel):
    numero_guia: str
    direccion_destino: str

class CotizacionResponse(BaseModel):
    exito: bool
    numero_guia: Optional[str] = None
    estado_guia: Optional[str] = None
    terminal_origen: str
    ciudad: str
    direccion_encontrada: str
    distancia_km: float
    zona: str
    precio_sugerido: int
    precio_minimo: int
    precio_maximo: int
    tiempo_estimado_min: int
    nota: str
    fecha_consulta: str

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="API Domicilios Rápido Ochoa",
    description="Cotización de domicilios desde terminales de Rápido Ochoa",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = httpx.AsyncClient(timeout=20.0)

# ── Rastreo de guía ───────────────────────────────────────────────────────────

async def consultar_guia(numero_guia: str) -> dict:
    """Consulta la guía en el sitio de Rápido Ochoa y retorna sus datos."""
    import re
    from bs4 import BeautifulSoup

    BASE_URL = RASTREO_BASE + RASTREO_PARAM
    POST_URL = RASTREO_BASE

    r1 = await client.get(BASE_URL)
    vs = re.search(r'javax\.faces\.ViewState[^>]*value="([^"]+)"', r1.text)
    if not vs:
        raise HTTPException(500, "Error conectando con el sistema de rastreo")
    view_state = vs.group(1)

    r2 = await client.post(POST_URL, data={
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": "tabpane",
        "javax.faces.partial.execute": "tabpane",
        "javax.faces.partial.render": "tabpane",
        "javax.faces.behavior.event": "tabChange",
        "javax.faces.partial.event": "tabChange",
        "tabpane_activeIndex": "1",
        "tabpane_newTab": "tabpane:j_id_1l",
        "tabpane": "tabpane",
        "tabpane:j_id_m_SUBMIT": "1",
        "javax.faces.ViewState": view_state,
    })
    vs2 = re.search(
        r'id="j_id__v_0:javax\.faces\.ViewState:1"[^>]*>.*?<!\[CDATA\[([^\]]+)\]\]>',
        r2.text, re.DOTALL
    )
    view_state2 = vs2.group(1) if vs2 else view_state

    r3 = await client.post(POST_URL, data={
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": "tabpane:form_entrega:codigoguia",
        "javax.faces.partial.execute": "tabpane:form_entrega",
        "javax.faces.partial.render": "tabpane:form_entrega",
        "javax.faces.behavior.event": "keyup",
        "javax.faces.partial.event": "keyup",
        "tabpane": "tabpane",
        "tabpane:form_entrega:codigoguia": numero_guia,
        "tabpane:form_entrega:documento_anexo": "",
        "tabpane:form_entrega_SUBMIT": "1",
        "javax.faces.ViewState": view_state2,
    })

    cdata_blocks = re.findall(r"<!\[CDATA\[(.*?)\]\]>", r3.text, re.DOTALL)
    for block in cdata_blocks:
        if "form_entrega" not in block or len(block) < 500:
            continue
        soup = BeautifulSoup(block, "html.parser")

        def label(id_):
            el = soup.find("label", id=id_)
            return el.get_text(strip=True) if el else ""

        numero = label("tabpane:form_entrega:j_id_31")
        if not numero:
            return None

        destino = label("tabpane:form_entrega:j_id_3b")
        trazabilidad = []
        for row in soup.find_all("tr", attrs={"data-ri": True}):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 3 and "/" in cells[0]:
                trazabilidad.append({
                    "fecha": cells[0],
                    "detalle": cells[1],
                    "sede": cells[2],
                })

        estado_actual = trazabilidad[-1]["detalle"] if trazabilidad else ""
        sede_actual   = trazabilidad[-1]["sede"]    if trazabilidad else ""

        return {
            "numero": numero,
            "destino": destino,
            "estado_actual": estado_actual,
            "sede_actual": sede_actual,
            "trazabilidad": trazabilidad,
        }

    return None

def detectar_terminal_por_sede(sede: str) -> Optional[str]:
    """Detecta la terminal según el texto de la sede en trazabilidad."""
    sede_upper = sede.upper()
    for keyword, terminal_key in SEDE_A_TERMINAL.items():
        if keyword in sede_upper:
            return terminal_key
    return None

def detectar_terminal_por_destino(destino: str) -> Optional[str]:
    """Detecta la terminal según la ciudad destino de la guía."""
    destino_upper = destino.upper()
    for keyword, terminal_key in CIUDAD_A_TERMINAL.items():
        if keyword in destino_upper:
            return terminal_key
    return None

# ── Geocodificación y distancia ───────────────────────────────────────────────

async def geocodificar(direccion: str, terminal: dict) -> Optional[dict]:
    """Geocodifica dirección con Mapbox. Limpia el # antes de enviar."""
    dir_limpia = direccion.replace("#", "").replace("  ", " ").strip()
    ciudad = terminal["ciudad"]

    # Agregar ciudad si no está en la dirección
    if ciudad.lower() not in dir_limpia.lower():
        dir_completa = f"{dir_limpia}, {ciudad}, Colombia"
    else:
        dir_completa = f"{dir_limpia}, Colombia"

    # Intento 1: con bbox (mejor para direcciones exactas)
    try:
        r = await client.get(
            f"https://api.mapbox.com/geocoding/v5/mapbox.places/{dir_completa}.json",
            params={
                "access_token": MAPBOX_TOKEN,
                "country": "CO",
                "language": "es",
                "limit": 1,
                "bbox": terminal["bbox"],
            }
        )
        features = r.json().get("features", [])
        if features:
            f = features[0]
            lon, lat = f["geometry"]["coordinates"]
            return {"lon": lon, "lat": lat,
                    "direccion_encontrada": f["place_name"],
                    "precision": "exacta"}

        # Intento 2: proximity (para barrios y lugares)
        r2 = await client.get(
            f"https://api.mapbox.com/geocoding/v5/mapbox.places/{dir_completa}.json",
            params={
                "access_token": MAPBOX_TOKEN,
                "country": "CO",
                "language": "es",
                "limit": 1,
                "proximity": f"{terminal['lon']},{terminal['lat']}",
            }
        )
        features2 = r2.json().get("features", [])
        if features2:
            f2 = features2[0]
            lon2, lat2 = f2["geometry"]["coordinates"]
            return {"lon": lon2, "lat": lat2,
                    "direccion_encontrada": f2["place_name"],
                    "precision": "aproximada"}

        return None
    except Exception as e:
        logger.error(f"Error geocodificando: {e}")
        return None

async def calcular_distancia(lon_o, lat_o, lon_d, lat_d) -> Optional[float]:
    """Calcula distancia en km por carretera usando OSRM."""
    try:
        r = await client.get(
            f"{OSRM_URL}/{lon_o},{lat_o};{lon_d},{lat_d}",
            params={"overview": "false"}
        )
        data = r.json()
        if data.get("code") == "Ok":
            return round(data["routes"][0]["distance"] / 1000, 1)
        return None
    except Exception as e:
        logger.error(f"Error OSRM: {e}")
        return None

def obtener_zona(distancia_km: float) -> dict:
    for zona in ZONAS:
        if zona["km_min"] <= distancia_km < zona["km_max"]:
            return zona
    return ZONAS[-1]

def construir_cotizacion(terminal: dict, geo: dict, distancia: float,
                         numero_guia: str = None, estado: str = None) -> CotizacionResponse:
    zona = obtener_zona(distancia)
    tiempo = int((distancia / terminal["vel_kmh"]) * 60) + 7
    precio_min = max(16000, int(zona["precio"] * 0.85 / 1000) * 1000)
    precio_max = int(zona["precio"] * 1.15 / 1000) * 1000

    nota = "Precio estimado. El colaborador verificará y ajustará el valor final."
    if geo["precision"] == "aproximada":
        nota = "Dirección aproximada. Precio referencial con mayor margen de variación."

    return CotizacionResponse(
        exito=True,
        numero_guia=numero_guia,
        estado_guia=estado,
        terminal_origen=terminal["nombre"],
        ciudad=terminal["ciudad"],
        direccion_encontrada=geo["direccion_encontrada"],
        distancia_km=distancia,
        zona=zona["nombre"],
        precio_sugerido=zona["precio"],
        precio_minimo=precio_min,
        precio_maximo=precio_max,
        tiempo_estimado_min=tiempo,
        nota=nota,
        fecha_consulta=datetime.now().isoformat(),
    )

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "nombre": "🛵 API Domicilios Rápido Ochoa",
        "version": "1.0.0",
        "endpoints": {
            "POST /cotizar-por-guia": "Cotiza consultando la guía automáticamente ⭐",
            "POST /cotizar": "Cotiza con terminal explícita",
            "GET /terminales": "Terminales disponibles",
            "GET /zonas": "Tarifas por zona",
            "GET /health": "Estado del servicio",
        }
    }

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/terminales")
async def listar_terminales():
    return {
        "total": len(TERMINALES),
        "terminales": [
            {"slug": k, "nombre": v["nombre"], "ciudad": v["ciudad"],
             "departamento": v["departamento"]}
            for k, v in TERMINALES.items()
        ]
    }

@app.get("/zonas")
async def listar_zonas():
    return {
        "zonas": [
            {"zona": z["nombre"],
             "distancia": f"{z['km_min']} – {z['km_max']} km",
             "precio": z["precio"]}
            for z in ZONAS
        ],
        "nota": "Precios aproximados. El colaborador puede ajustar el valor final."
    }

@app.post("/cotizar-por-guia", response_model=CotizacionResponse)
async def cotizar_por_guia(req: CotizarPorGuiaRequest):
    """
    Cotiza un domicilio consultando automáticamente la guía.
    Detecta la terminal según el estado y ciudad de la encomienda.

    Ejemplo:
    {
        "numero_guia": "E121118799",
        "direccion_destino": "Calle 30 #38-15"
    }
    """
    # Consultar guía
    guia = await consultar_guia(req.numero_guia)
    if not guia:
        raise HTTPException(404, f"No se encontró la guía {req.numero_guia}")

    estado = guia["estado_actual"]
    sede   = guia["sede_actual"]
    destino_guia = guia["destino"]

    logger.info(f"Guía {req.numero_guia}: estado={estado} | sede={sede} | destino={destino_guia}")

    # Detectar terminal — prioridad: sede actual > ciudad destino
    terminal_key = detectar_terminal_por_sede(sede)
    if not terminal_key:
        terminal_key = detectar_terminal_por_destino(destino_guia)
    if not terminal_key:
        raise HTTPException(
            422,
            f"No se pudo determinar la terminal para la guía {req.numero_guia}. "
            f"Destino: {destino_guia} | Sede: {sede}"
        )

    terminal = TERMINALES[terminal_key]

    # Verificar si la encomienda ya está disponible
    disponible = any(e in estado.upper() for e in ESTADOS_EN_TERMINAL)
    if not disponible:
        raise HTTPException(
            409,
            f"La encomienda aún no ha llegado a la terminal. "
            f"Estado actual: {estado}. "
            f"El domicilio solo se puede cotizar cuando el estado sea "
            f"'RECIBIDA EN BODEGA' o 'RECLAME EN OFICINA'."
        )

    # Geocodificar destino
    geo = await geocodificar(req.direccion_destino, terminal)
    if not geo:
        raise HTTPException(
            422,
            f"No se pudo encontrar la dirección '{req.direccion_destino}' en {terminal['ciudad']}. "
            "Intenta con una dirección más específica (ej: Calle 30 #38-15)."
        )

    # Calcular distancia
    distancia = await calcular_distancia(
        terminal["lon"], terminal["lat"],
        geo["lon"], geo["lat"]
    )
    if not distancia:
        raise HTTPException(500, "Error calculando la ruta. Intenta nuevamente.")

    return construir_cotizacion(terminal, geo, distancia, req.numero_guia, estado)

@app.post("/cotizar", response_model=CotizacionResponse)
async def cotizar(req: CotizarRequest):
    """
    Cotiza un domicilio con terminal explícita.
    Útil cuando no se tiene número de guía.
    """
    terminal_key = req.terminal.lower().strip()
    if terminal_key not in TERMINALES:
        raise HTTPException(
            404,
            f"Terminal '{req.terminal}' no encontrada. "
            f"Disponibles: {list(TERMINALES.keys())}"
        )

    terminal = TERMINALES[terminal_key]

    geo = await geocodificar(req.direccion_destino, terminal)
    if not geo:
        raise HTTPException(
            422,
            f"No se pudo encontrar '{req.direccion_destino}'. "
            "Intenta con una dirección más específica."
        )

    distancia = await calcular_distancia(
        terminal["lon"], terminal["lat"],
        geo["lon"], geo["lat"]
    )
    if not distancia:
        raise HTTPException(500, "Error calculando la ruta.")

    return construir_cotizacion(terminal, geo, distancia)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("domicilios_ochoa:app", host="0.0.0.0", port=8001, reload=True)