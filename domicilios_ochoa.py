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
        "lat": 6.2786489,
        "lon": -75.5710903,
        "bbox": "-75.70,6.10,-75.45,6.42",
        "vel_kmh": 22,
        "departamento": "Antioquia",
    },
    "medellin_sur": {
        "nombre": "Terminal de Transporte Sur",
        "ciudad": "Medellín",
        "lat": 6.2164482,
        "lon": -75.5872220,
        "bbox": "-75.70,6.10,-75.45,6.42",
        "vel_kmh": 22,
        "departamento": "Antioquia",
    },
    "monteria": {
        "nombre": "Terminal de Transportes de Montería",
        "ciudad": "Montería",
        "lat": 8.7485874,
        "lon": -75.8671895,
        "bbox": "-76.00,8.65,-75.75,8.85",
        "vel_kmh": 25,
        "departamento": "Córdoba",
    },
    "cartagena": {
        "nombre": "Terminal de Transportes de Cartagena",
        "ciudad": "Cartagena",
        "lat": 10.4004639,
        "lon": -75.4583308,
        "bbox": "-75.65,10.30,-75.45,10.50",
        "vel_kmh": 22,
        "departamento": "Bolívar",
    },
    "sincelejo": {
        "nombre": "Terminal de Transportes de Sincelejo",
        "ciudad": "Sincelejo",
        "lat": 9.2953147,
        "lon": -75.3830775,
        "bbox": "-75.55,9.20,-75.25,9.40",
        "vel_kmh": 25,
        "departamento": "Sucre",
    },
    "santa_marta": {
        "nombre": "Terminal de Transportes de Santa Marta",
        "ciudad": "Santa Marta",
        "lat": 11.2217510,
        "lon": -74.1808933,
        "bbox": "-74.30,11.15,-74.05,11.30",
        "vel_kmh": 22,
        "departamento": "Magdalena",
    },
    "bogota": {
        "nombre": "Terminal de Transportes Salitre",
        "ciudad": "Bogotá",
        "lat": 4.6538763,
        "lon": -74.1155898,
        "bbox": "-74.25,4.50,-73.95,4.83",
        "vel_kmh": 18,
        "departamento": "Cundinamarca",
    },
    "caucasia": {
        "nombre": "Terminal de Transportes de Caucasia",
        "ciudad": "Caucasia",
        "lat": 7.9740551,
        "lon": -75.2046546,
        "bbox": "-75.35,7.90,-75.10,8.08",
        "vel_kmh": 25,
        "departamento": "Antioquia",
    },
    "quibdo": {
        "nombre": "Terminal de Transportes de Quibdó",
        "ciudad": "Quibdó",
        "lat": 5.6533339,
        "lon": -76.6445217,
        "bbox": "-76.80,5.60,-76.55,5.80",
        "vel_kmh": 22,
        "departamento": "Chocó",
    },
    "riohacha": {
        "nombre": "Terminal de Transportes de Riohacha",
        "ciudad": "Riohacha",
        "lat": 11.5410043,
        "lon": -72.9112228,
        "bbox": "-73.05,11.46,-72.80,11.62",
        "vel_kmh": 25,
        "departamento": "La Guajira",
    },
    "maicao": {
        "nombre": "Terminal de Transportes Centrama de Maicao",
        "ciudad": "Maicao",
        "lat": 11.3816734,
        "lon": -72.2298330,
        "bbox": "-72.35,11.30,-72.15,11.45",
        "vel_kmh": 25,
        "departamento": "La Guajira",
    },
    "planeta_rica": {
        "nombre": "Terminal de Planeta Rica",
        "ciudad": "Planeta Rica",
        "lat": 8.4076739,
        "lon": -75.5840456,
        "bbox": "-75.70,8.33,-75.50,8.48",
        "vel_kmh": 25,
        "departamento": "Córdoba",
    },
    "arboletes": {
        "nombre": "Terminal de Arboletes",
        "ciudad": "Arboletes",
        "lat": 8.8528266, "lon": -76.4273168,
        "bbox": "-76.55,8.78,-76.35,8.92",
        "vel_kmh": 25, "departamento": "Antioquia",
    },
    "lorica": {
        "nombre": "Terminal de Lorica",
        "ciudad": "Lorica",
        "lat": 9.2394583, "lon": -75.8139786,
        "bbox": "-75.95,9.17,-75.70,9.31",
        "vel_kmh": 25, "departamento": "Córdoba",
    },
    "cerete": {
        "nombre": "Terminal de Cereté",
        "ciudad": "Cereté",
        "lat": 8.8821682, "lon": -75.7901358,
        "bbox": "-75.93,8.83,-75.70,8.94",
        "vel_kmh": 25, "departamento": "Córdoba",
    },
    "la_apartada": {
        "nombre": "Terminal de La Apartada",
        "ciudad": "La Apartada",
        "lat": 8.0484697, "lon": -75.3336510,
        "bbox": "-75.45,8.00,-75.25,8.10",
        "vel_kmh": 25, "departamento": "Córdoba",
    },
    "san_antero": {
        "nombre": "Terminal de San Antero",
        "ciudad": "San Antero",
        "lat": 9.3730160, "lon": -75.7595056,
        "bbox": "-75.85,9.32,-75.70,9.43",
        "vel_kmh": 25, "departamento": "Córdoba",
    },
    "covenas": {
        "nombre": "Terminal de Coveñas",
        "ciudad": "Coveñas",
        "lat": 9.4017581, "lon": -75.6787017,
        "bbox": "-75.75,9.35,-75.62,9.45",
        "vel_kmh": 25, "departamento": "Sucre",
    },
    "tolu": {
        "nombre": "Terminal de Tolú",
        "ciudad": "Tolú",
        "lat": 9.5241138, "lon": -75.5841794,
        "bbox": "-75.65,9.47,-75.53,9.57",
        "vel_kmh": 25, "departamento": "Sucre",
    },
    "san_marcos": {
        "nombre": "Terminal de San Marcos",
        "ciudad": "San Marcos",
        "lat": 8.6618609, "lon": -75.1307644,
        "bbox": "-75.22,8.61,-75.05,8.71",
        "vel_kmh": 25, "departamento": "Sucre",
    },
    "magangue": {
        "nombre": "Terminal de Magangué",
        "ciudad": "Magangué",
        "lat": 9.2412097, "lon": -74.7567413,
        "bbox": "-74.85,9.18,-74.68,9.30",
        "vel_kmh": 25, "departamento": "Bolívar",
    },
    "carmen_bolivar": {
        "nombre": "Terminal de Carmen de Bolívar",
        "ciudad": "Carmen de Bolívar",
        "lat": 9.7200000, "lon": -75.1200000,
        "bbox": "-75.20,9.67,-75.05,9.77",
        "vel_kmh": 25, "departamento": "Bolívar",
    },
    "cienaga": {
        "nombre": "Terminal de Ciénaga",
        "ciudad": "Ciénaga",
        "lat": 11.0049561, "lon": -74.2534483,
        "bbox": "-74.32,10.96,-74.20,11.05",
        "vel_kmh": 25, "departamento": "Magdalena",
    },
    "la_dorada": {
        "nombre": "Terminal de La Dorada",
        "ciudad": "La Dorada",
        "lat": 5.4457655, "lon": -74.6618458,
        "bbox": "-74.75,5.40,-74.60,5.50",
        "vel_kmh": 25, "departamento": "Caldas",
    },
    "puerto_berrio": {
        "nombre": "Terminal de Puerto Berrío",
        "ciudad": "Puerto Berrío",
        "lat": 6.4899205, "lon": -74.4020634,
        "bbox": "-74.48,6.44,-74.35,6.54",
        "vel_kmh": 25, "departamento": "Antioquia",
    },
    "jardin": {
        "nombre": "Terminal de Jardín",
        "ciudad": "Jardín",
        "lat": 5.5990503, "lon": -75.8191833,
        "bbox": "-75.88,5.55,-75.77,5.64",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "urrao": {
        "nombre": "Terminal de Urrao",
        "ciudad": "Urrao",
        "lat": 6.3168685, "lon": -76.1344983,
        "bbox": "-76.20,6.27,-76.07,6.37",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "ciudad_bolivar": {
        "nombre": "Terminal de Ciudad Bolívar",
        "ciudad": "Ciudad Bolívar",
        "lat": 5.8500342, "lon": -76.0208666,
        "bbox": "-76.09,5.80,-75.96,5.90",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "istmina": {
        "nombre": "Terminal de Istmina",
        "ciudad": "Istmina",
        "lat": 5.1593099, "lon": -76.6855280,
        "bbox": "-76.76,5.11,-76.63,5.21",
        "vel_kmh": 22, "departamento": "Chocó",
    },
    "condoto": {
        "nombre": "Terminal de Condoto",
        "ciudad": "Condoto",
        "lat": 5.0956800, "lon": -76.5114837,
        "bbox": "-76.58,5.05,-76.46,5.14",
        "vel_kmh": 22, "departamento": "Chocó",
    },
    "tutunendo": {
        "nombre": "Terminal de Tutunendo",
        "ciudad": "Tutunendo",
        "lat": 5.7443478, "lon": -76.5407756,
        "bbox": "-76.60,5.70,-76.50,5.79",
        "vel_kmh": 22, "departamento": "Chocó",
    },
    "rionegro": {
        "nombre": "Terminal de Rionegro",
        "ciudad": "Rionegro",
        "lat": 6.1511683, "lon": -75.3729322,
        "bbox": "-75.44,6.10,-75.31,6.20",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "san_onofre": {
        "nombre": "Terminal de San Onofre",
        "ciudad": "San Onofre",
        "lat": 9.7386264, "lon": -75.5234228,
        "bbox": "-75.60,9.69,-75.47,9.79",
        "vel_kmh": 25, "departamento": "Bolívar",
    },
    "mompox": {
        "nombre": "Terminal de Mompox",
        "ciudad": "Mompox",
        "lat": 9.2265049, "lon": -74.4178595,
        "bbox": "-74.48,9.19,-74.37,9.27",
        "vel_kmh": 22, "departamento": "Bolívar",
    },
    "valledupar": {
        "nombre": "Terminal de Valledupar",
        "ciudad": "Valledupar",
        "lat": 10.3431115, "lon": -73.3757934,
        "bbox": "-73.46,10.29,-73.29,10.40",
        "vel_kmh": 25, "departamento": "Cesar",
    },
    "yarumal": {
        "nombre": "Terminal de Yarumal",
        "ciudad": "Yarumal",
        "lat": 6.9625927, "lon": -75.4165529,
        "bbox": "-75.48,6.92,-75.37,7.01",
        "vel_kmh": 25, "departamento": "Antioquia",
    },
    "taraza": {
        "nombre": "Terminal de Tarazá",
        "ciudad": "Tarazá",
        "lat": 7.5804751, "lon": -75.3998498,
        "bbox": "-75.47,7.53,-75.34,7.63",
        "vel_kmh": 25, "departamento": "Antioquia",
    },
    "caicedo": {
        "nombre": "Terminal de Caicedo",
        "ciudad": "Caicedo",
        "lat": 6.4059550, "lon": -75.9825592,
        "bbox": "-76.05,6.36,-75.93,6.45",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "giraldo": {
        "nombre": "Terminal de Giraldo",
        "ciudad": "Giraldo",
        "lat": 6.6804539, "lon": -75.9533800,
        "bbox": "-76.01,6.64,-75.90,6.72",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "andes": {
        "nombre": "Terminal de Andes",
        "ciudad": "Andes",
        "lat": 5.6556134, "lon": -75.8776753,
        "bbox": "-75.94,5.61,-75.82,5.70",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "concordia": {
        "nombre": "Terminal de Concordia",
        "ciudad": "Concordia",
        "lat": 6.0457595, "lon": -75.9074199,
        "bbox": "-75.97,6.00,-75.86,6.09",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "betulia": {
        "nombre": "Terminal de Betulia",
        "ciudad": "Betulia",
        "lat": 6.1134294, "lon": -75.9845433,
        "bbox": "-76.05,6.07,-75.93,6.16",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "bolombolo": {
        "nombre": "Terminal de Bolombolo",
        "ciudad": "Bolombolo",
        "lat": 5.9705417, "lon": -75.8372203,
        "bbox": "-75.90,5.93,-75.78,6.01",
        "vel_kmh": 22, "departamento": "Antioquia",
    },
    "sahagun": {
        "nombre": "Terminal de Sahagún",
        "ciudad": "Sahagún",
        "lat": 8.9472964, "lon": -75.4434972,
        "bbox": "-75.52,8.90,-75.39,9.00",
        "vel_kmh": 25, "departamento": "Córdoba",
    },
    "chinu": {
        "nombre": "Terminal de Chinú",
        "ciudad": "Chinú",
        "lat": 9.1063553, "lon": -75.3989007,
        "bbox": "-75.47,9.06,-75.34,9.16",
        "vel_kmh": 25, "departamento": "Córdoba",
    },
}

# Mapeo de palabras clave en la sede de trazabilidad → terminal
# Se evalúan en orden — los más específicos primero
SEDE_A_TERMINAL = {
    # Barranquilla / Soledad
    "SOLEDAD":                              "barranquilla",
    "BARRANQUILLA":                         "barranquilla",
    # Medellín — específicos primero
    "TERMINAL DE TRANSPORTE NORTE":         "medellin_norte",
    "TERMINAL NORTE":                       "medellin_norte",
    "MEDELLIN TERMINAL DE TRANSPORTE NORTE":"medellin_norte",
    "TERMINAL DE TRANSPORTE SUR":           "medellin_sur",
    "TERMINAL SUR":                         "medellin_sur",
    "MEDELLIN TERMINAL DE TRANSPORTE SUR":  "medellin_sur",
    # Chocó → siempre Terminal Sur Medellín
    "QUIBDO":                               "medellin_sur",
    "ISTMINA":                              "medellin_sur",
    "CONDOTO":                              "medellin_sur",
    "TUTUNENDO":                            "medellin_sur",
    # Otras ciudades
    "MONTERIA":                             "monteria",
    "CARTAGENA":                            "cartagena",
    "SINCELEJO":                            "sincelejo",
    "SANTA MARTA":                          "santa_marta",
    "BOGOTA":                               "bogota",
    "CAUCASIA":                             "caucasia",
    "PLANETA RICA":                         "planeta_rica",
    "RIOHACHA":                             "riohacha",
    "MAICAO":                               "maicao",
    "MAGANGUE":                             "cartagena",
    "LORICA":                               "monteria",
    "CERETE":                               "monteria",
    "TOLU":                                 "sincelejo",
    "COVENAS":                              "sincelejo",
    # Medellín genérico → Norte
    "MEDELLIN":                             "medellin_norte",
    # Córdoba
    "ARBOLETES":                            "arboletes",
    "LORICA":                               "lorica",
    "CERETE":                               "cerete",
    "LA APARTADA":                          "la_apartada",
    "SAN ANTERO":                           "san_antero",
    "SAHAGUN":                              "sahagun",
    "CHINU":                                "chinu",
    # Sucre
    "COVENAS":                              "covenas",
    "TOLU":                                 "tolu",
    "SAN MARCOS":                           "san_marcos",
    "SAN ONOFRE":                           "san_onofre",
    # Bolívar
    "MAGANGUE":                             "magangue",
    "CARMEN DE BOLIVAR":                    "carmen_bolivar",
    "MOMPOX":                               "mompox",
    # Magdalena
    "CIENAGA":                              "cienaga",
    # Caldas / Antioquia
    "LA DORADA":                            "la_dorada",
    "PUERTO BERRIO":                        "puerto_berrio",
    "YARUMAL":                              "yarumal",
    "TARAZA":                               "taraza",
    "RIONEGRO":                             "rionegro",
    "CAICEDO":                              "caicedo",
    "GIRALDO":                              "giraldo",
    "ANDES":                                "andes",
    "CONCORDIA":                            "concordia",
    "BETULIA":                              "betulia",
    "BOLOMBOLO":                            "bolombolo",
    "JARDIN":                               "jardin",
    "URRAO":                                "urrao",
    "CIUDAD BOLIVAR":                       "ciudad_bolivar",
    # Chocó
    "ISTMINA":                              "istmina",
    "CONDOTO":                              "condoto",
    "TUTUNENDO":                            "tutunendo",
    # Guajira / Cesar
    "VALLEDUPAR":                           "valledupar",
}

# Mapeo ciudad/departamento destino → terminal
# Medellín Norte: rutas del norte/caribe (subiendo desde Medellín)
# Medellín Sur: rutas del sur/pacífico (bajando desde Medellín)
CIUDAD_A_TERMINAL = {
    # Atlántico
    "BARRANQUILLA": "barranquilla",
    "ATLANTICO":    "barranquilla",
    "SOLEDAD":      "barranquilla",
    # Bolívar
    "CARTAGENA":    "cartagena",
    "BOLIVAR":      "cartagena",
    "MAGANGUE":     "cartagena",
    "CARMEN DE BOLIVAR": "cartagena",
    "MOMPOX":       "cartagena",
    # Córdoba → Terminal Norte Medellín o Montería
    "MONTERIA":     "monteria",
    "CORDOBA":      "monteria",
    "PLANETA RICA": "planeta_rica",
    "CAUCASIA":     "caucasia",
    "LORICA":       "monteria",
    "CERETE":       "monteria",
    "CHINU":        "monteria",
    "LA APARTADA":  "monteria",
    "SAN ANTERO":   "monteria",
    # Sucre
    "SINCELEJO":    "sincelejo",
    "SUCRE":        "sincelejo",
    "TOLU":         "sincelejo",
    "COVENAS":      "sincelejo",
    "SAN MARCOS":   "sincelejo",
    "SAHAGUN":      "sincelejo",
    # Magdalena
    "SANTA MARTA":  "santa_marta",
    "MAGDALENA":    "santa_marta",
    "CIENAGA":      "santa_marta",
    # La Guajira
    "RIOHACHA":     "riohacha",
    "MAICAO":       "maicao",
    "GUAJIRA":      "riohacha",
    # Cundinamarca
    "BOGOTA":       "bogota",
    "CUNDINAMARCA": "bogota",
    "FACATATIVA":   "bogota",
    # Antioquia — norte (Terminal Norte)
    "CAUCASIA":     "caucasia",
    "TARAZA":       "medellin_norte",
    "YARUMAL":      "medellin_norte",
    "ARBOLETES":    "medellin_norte",
    "PUERTO BERRIO": "medellin_norte",
    "LA DORADA":    "medellin_norte",
    "RIONEGRO":     "medellin_norte",
    # Antioquia — sur/pacífico (Terminal Sur)
    "QUIBDO":       "medellin_sur",
    "CHOCO":        "medellin_sur",
    "ISTMINA":      "medellin_sur",
    "CONDOTO":      "medellin_sur",
    "TUTUNENDO":    "medellin_sur",
    "EL SIETE":     "medellin_sur",
    "JARDIN":       "medellin_sur",
    "URRAO":        "medellin_sur",
    "CIUDAD BOLIVAR": "medellin_sur",
    "BOLOMBOLO":    "medellin_sur",
    "ANDES":        "medellin_sur",
    "CONCORDIA":    "medellin_sur",
    "BETULIA":      "medellin_sur",
    "CAICEDO":      "medellin_sur",
    "GIRALDO":      "medellin_sur",
    # Medellín genérico → Norte por defecto
    "MEDELLIN":         "medellin_norte",
    "ANTIOQUIA":        "medellin_norte",
    # Córdoba adicionales
    "ARBOLETES":        "arboletes",
    "LORICA":           "lorica",
    "CERETE":           "cerete",
    "CERETÉ":           "cerete",
    "LA APARTADA":      "la_apartada",
    "SAN ANTERO":       "san_antero",
    "SAHAGUN":          "sahagun",
    "SAHAGÚN":          "sahagun",
    "CHINU":            "chinu",
    "CHINÚ":            "chinu",
    # Sucre adicionales
    "COVENAS":          "covenas",
    "COVEÑAS":          "covenas",
    "TOLU":             "tolu",
    "TOLÚ":             "tolu",
    "SAN MARCOS":       "san_marcos",
    "SAN ONOFRE":       "san_onofre",
    # Bolívar adicionales
    "MAGANGUE":         "magangue",
    "MAGANGUÉ":         "magangue",
    "CARMEN DE BOLIVAR":"carmen_bolivar",
    "MOMPOX":           "mompox",
    # Magdalena adicionales
    "CIENAGA":          "cienaga",
    "CIÉNAGA":          "cienaga",
    # Caldas
    "LA DORADA":        "la_dorada",
    "CALDAS":           "la_dorada",
    # Cesar
    "VALLEDUPAR":       "valledupar",
    "CESAR":            "valledupar",
    # Antioquia adicionales → Sur
    "JARDIN":           "jardin",
    "JARDÍN":           "jardin",
    "URRAO":            "urrao",
    "CIUDAD BOLIVAR":   "ciudad_bolivar",
    "RIONEGRO":         "rionegro",
    "MARINILLA":        "rionegro",
    "YARUMAL":          "yarumal",
    "TARAZA":           "taraza",
    "TARAZÁ":           "taraza",
    "CAICEDO":          "caicedo",
    "GIRALDO":          "giraldo",
    "ANDES":            "andes",
    "CONCORDIA":        "concordia",
    "BETULIA":          "betulia",
    "BOLOMBOLO":        "bolombolo",
    # Chocó adicionales
    "ISTMINA":          "istmina",
    "CONDOTO":          "condoto",
    "TUTUNENDO":        "tutunendo",
    # Puerto Berrío
    "PUERTO BERRIO":    "puerto_berrio",
    "PUERTO BERRÍO":    "puerto_berrio",
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
            "POST /ruta": "Distancia y tiempo entre cualquier punto A → B en Colombia",
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

    # Si ya llegó a la terminal usar sede actual, si no usar ciudad destino
    en_terminal = any(e in estado.upper() for e in ESTADOS_EN_TERMINAL)
    if not en_terminal:
        # Aún en camino — recalcular terminal por ciudad destino
        terminal_key = detectar_terminal_por_destino(destino_guia)
        if not terminal_key:
            raise HTTPException(
                422,
                f"No se pudo determinar la terminal destino para la guía {req.numero_guia}. "
                f"Destino: {destino_guia}"
            )
        terminal = TERMINALES[terminal_key]
        logger.info(f"Encomienda en camino — terminal por destino: {terminal_key}")

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


class RutaRequest(BaseModel):
    origen: str                        # Dirección, ciudad o lugar de origen
    destino: str                       # Dirección, ciudad o lugar de destino
    ciudad_origen: Optional[str] = None   # Ciudad del origen (mejora precisión)
    ciudad_destino: Optional[str] = None  # Ciudad del destino (mejora precisión)
    velocidad_kmh: Optional[int] = None   # Velocidad promedio (default: calculada por ciudad)

class RutaResponse(BaseModel):
    exito: bool
    origen_encontrado: str
    destino_encontrado: str
    origen_coords: dict
    destino_coords: dict
    distancia_km: float
    tiempo_min: int
    tiempo_formato: str
    velocidad_usada: int
    fecha_consulta: str

async def geocodificar_libre(direccion: str, ciudad: Optional[str] = None) -> Optional[dict]:
    """
    Geocodifica cualquier dirección en Colombia.
    Si la dirección coincide con una terminal conocida, usa sus coordenadas exactas.
    Solo consulta Mapbox para direcciones de clientes.
    """
    dir_lower = direccion.lower().strip()

    # Verificar si es una terminal conocida
    for key, terminal in TERMINALES.items():
        nombre_lower = terminal["nombre"].lower()
        ciudad_lower = terminal["ciudad"].lower()
        # Coincide si menciona el nombre de la terminal o la ciudad + "terminal"
        if (nombre_lower in dir_lower or
            dir_lower in nombre_lower or
            (ciudad_lower in dir_lower and "terminal" in dir_lower)):
            # Para Medellín con ambigüedad usar Norte por defecto
            if key == "medellin_sur" and "sur" not in dir_lower:
                continue
            logger.info(f"Terminal reconocida: {terminal['nombre']}")
            return {
                "lon": terminal["lon"],
                "lat": terminal["lat"],
                "nombre": terminal["nombre"],
            }

    # No es terminal — geocodificar con Mapbox
    dir_limpia = direccion.replace("#", "").replace("  ", " ").strip()
    if ciudad and ciudad.lower() not in dir_limpia.lower():
        dir_completa = f"{dir_limpia}, {ciudad}, Colombia"
    else:
        dir_completa = f"{dir_limpia}, Colombia"

    try:
        r = await client.get(
            f"https://api.mapbox.com/geocoding/v5/mapbox.places/{dir_completa}.json",
            params={
                "access_token": MAPBOX_TOKEN,
                "country": "CO",
                "language": "es",
                "limit": 1,
            }
        )
        features = r.json().get("features", [])
        if features:
            f = features[0]
            lon, lat = f["geometry"]["coordinates"]
            return {"lon": lon, "lat": lat, "nombre": f["place_name"]}
        return None
    except Exception as e:
        logger.error(f"Error geocodificando libre: {e}")
        return None

def estimar_velocidad(nombre_lugar: str) -> int:
    """Estima velocidad promedio según el tipo de lugar."""
    nombre = nombre_lugar.upper()
    # Ciudades principales con tráfico denso
    if any(c in nombre for c in ["BOGOTÁ", "BOGOTA", "MEDELLÍN", "MEDELLIN", "CALI"]):
        return 18
    if any(c in nombre for c in ["BARRANQUILLA", "CARTAGENA", "BUCARAMANGA"]):
        return 20
    # Ciudades intermedias
    if any(c in nombre for c in ["MONTERÍA", "MONTERIA", "SINCELEJO", "SANTA MARTA",
                                   "PEREIRA", "MANIZALES", "ARMENIA"]):
        return 22
    # Municipios / carretera
    return 55  # velocidad interurbana si son ciudades diferentes

def formato_tiempo(minutos: int) -> str:
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    mins = minutos % 60
    if mins == 0:
        return f"{horas}h"
    return f"{horas}h {mins}min"

@app.post("/ruta", response_model=RutaResponse)
async def calcular_ruta(req: RutaRequest):
    """
    Calcula distancia y tiempo entre cualquier punto A y punto B en Colombia.
    Útil para: tiempo de viaje en bus, tiempo de entrega de encomienda,
    distancia entre ciudades, etc.

    Ejemplos:
    - Barranquilla → Medellín (ciudades)
    - Calle 30 #38-15 Barranquilla → Villa Country Barranquilla (direcciones)
    - Terminal de Soledad → Calle 84 Barranquilla (mixto)
    """
    # Geocodificar origen y destino
    geo_o = await geocodificar_libre(req.origen, req.ciudad_origen)
    if not geo_o:
        raise HTTPException(422, f"No se pudo encontrar el origen: '{req.origen}'")

    geo_d = await geocodificar_libre(req.destino, req.ciudad_destino)
    if not geo_d:
        raise HTTPException(422, f"No se pudo encontrar el destino: '{req.destino}'")

    # Calcular distancia
    distancia = await calcular_distancia(geo_o["lon"], geo_o["lat"], geo_d["lon"], geo_d["lat"])
    if not distancia:
        raise HTTPException(500, "Error calculando la ruta entre los puntos.")

    # Velocidad: usa la indicada o estima automáticamente
    vel = 80  # default
    if req.velocidad_kmh:
        vel = req.velocidad_kmh
        tiempo_min = int((distancia / vel) * 60)
    elif distancia <= 30:
        vel = estimar_velocidad(geo_d["nombre"])
        tiempo_min = int((distancia / vel) * 60)
    elif distancia <= 150:
        tiempo_min = int((distancia / 80) * 1.20 * 60)
    elif distancia <= 350:
        tiempo_min = int((distancia / 80) * 1.30 * 60)
    elif distancia <= 600:
        tiempo_min = int((distancia / 80) * 1.45 * 60)
    else:
        tiempo_min = int((distancia / 80) * 1.70 * 60)

    return RutaResponse(
        exito=True,
        origen_encontrado=geo_o["nombre"],
        destino_encontrado=geo_d["nombre"],
        origen_coords={"lat": geo_o["lat"], "lon": geo_o["lon"]},
        destino_coords={"lat": geo_d["lat"], "lon": geo_d["lon"]},
        distancia_km=distancia,
        tiempo_min=tiempo_min,
        tiempo_formato=formato_tiempo(tiempo_min),
        velocidad_usada=vel,
        fecha_consulta=datetime.now().isoformat(),
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("domicilios_ochoa:app", host="0.0.0.0", port=8001, reload=True)