from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import ee
import os
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ee_initialized = False

def init_ee():
    global ee_initialized
    try:
        credentials_json = os.getenv('GOOGLE_CREDENTIALS')
        
        if credentials_json:
            print("✓ Credenciales encontradas")
            credentials_dict = json.loads(credentials_json)
            
            # Usar método que funciona mejor en Railway
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write(credentials_json)
                temp_file = f.name
            
            # Inicializar con archivo temporal
            ee.Initialize(ee.ServiceAccountCredentials('', temp_file))
            os.unlink(temp_file)  # Eliminar archivo temporal
            
            print("✓ Earth Engine inicializado!")
            ee_initialized = True
            return True
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    init_ee()

@app.get("/")
async def root():
    return {"message": "API Sequedad GEE", "ee_initialized": ee_initialized}

@app.get("/indice-sequedad")
async def get_indice_sequedad():
    try:
        if not ee_initialized:
            if not init_ee():
                return {"error": "No se pudo inicializar Earth Engine"}
        
        # ROI Ecuador
        roi = ee.FeatureCollection("FAO/GAUL/2015/level0").filter(ee.Filter.eq("ADM0_NAME","Ecuador"))
        
        # Fechas
        fecha_inicio = '2024-01-01'
        fecha_fin = '2024-12-31'
        
        # VERSIÓN SIMPLIFICADA - Solo usando datos públicos
        
        # 1. NDVI MODIS más reciente
        ndvi_collection = ee.ImageCollection("MODIS/061/MOD13A2") \
            .select('NDVI') \
            .filterDate(fecha_inicio, fecha_fin) \
            .filterBounds(roi)
        
        # NDVI actual (más reciente)
        ndvi_actual = ndvi_collection.sort('system:time_end', False).first().multiply(0.0001)
        
        # NDVI histórico para calcular min/max (usando datos públicos)
        ndvi_stats = ndvi_collection.reduce(ee.Reducer.minMax())
        ndvi_min = ndvi_stats.select('NDVI_min').multiply(0.0001)
        ndvi_max = ndvi_stats.select('NDVI_max').multiply(0.0001)
        
        # 2. Precipitación (últimos 30 días)
        precipitacion = ee.ImageCollection('NASA/GPM_L3/IMERG_V06') \
            .select('precipitationCal') \
            .filterBounds(roi) \
            .filterDate('2024-11-01', '2024-12-31') \
            .sum()
        
        # 3. Temperatura ERA5 más reciente
        temperatura = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
            .select('temperature_2m') \
            .filterBounds(roi) \
            .filterDate(fecha_inicio, fecha_fin) \
            .sort('system:time_end', False) \
            .first() \
            .subtract(273.15)  # Convertir a Celsius
        
        # 4. CÁLCULO SIMPLIFICADO DE SEQUEDAD
        
        # Relative Greenness (normalizado 0-1)
        rg = ndvi_actual.subtract(ndvi_min).divide(ndvi_max.subtract(ndvi_min))
        
        # Factor de sequedad basado en precipitación (invertido)
        factor_precip = precipitacion.multiply(-1).add(100).divide(100).clamp(0, 1)
        
        # Factor temperatura (temperaturas altas = más sequía)
        factor_temp = temperatura.subtract(15).divide(20).clamp(0, 1)
        
        # Índice de sequedad combinado (0-100)
        indice_sequedad = rg.multiply(-1).add(1) \
            .multiply(factor_precip) \
            .multiply(factor_temp.add(0.5)) \
            .multiply(100) \
            .clamp(0, 100)
        
        # Clasificación en 6 niveles
        imagen_clasificada = ee.Image(0) \
            .where(indice_sequedad.lt(15), 1) \
            .where(indice_sequedad.gte(15).And(indice_sequedad.lt(30)), 2) \
            .where(indice_sequedad.gte(30).And(indice_sequedad.lt(45)), 3) \
            .where(indice_sequedad.gte(45).And(indice_sequedad.lt(60)), 4) \
            .where(indice_sequedad.gte(60).And(indice_sequedad.lt(75)), 5) \
            .where(indice_sequedad.gte(75), 6) \
            .clip(roi)
        
        # Paleta de colores
        colores = ['267E00','56E200','FFFC00','FE7400','FF0000','9E00FF']
        
        # Generar tiles
        map_id = imagen_clasificada.getMapId({
            'min': 1,
            'max': 6,
            'palette': colores,
            'opacity': 0.7
        })
        
        return {
            "tile_url": map_id['tile_fetcher'].url_format,
            "mapid": map_id['mapid'],
            "token": map_id['token'],
            "message": "Índice de Sequedad generado exitosamente",
            "legend": {
                "labels": [
                    "Muy baja (<15)",
                    "Baja (15-30)", 
                    "Media (30-45)",
                    "Alta (45-60)",
                    "Muy alta (60-75)",
                    "Extrema (>75)"
                ],
                "colors": colores
            }
        }
        
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
