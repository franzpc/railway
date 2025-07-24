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

def init_ee():
    """Inicializar Earth Engine"""
    try:
        creds = os.getenv('GOOGLE_CREDENTIALS')
        if not creds:
            return False
            
        creds_dict = json.loads(creds)
        credentials = ee.ServiceAccountCredentials(
            email=creds_dict['client_email'],
            key_data=creds
        )
        ee.Initialize(credentials)
        return True
    except Exception as e:
        print(f"Error inicializando EE: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    success = init_ee()
    print(f"EE Initialization: {'Success' if success else 'Failed'}")

@app.get("/")
async def root():
    return {"message": "API NDVI Ecuador", "status": "ok"}

@app.get("/test-ee")
async def test_ee():
    """Test básico de Earth Engine"""
    try:
        img = ee.Image(1)
        info = img.getInfo()
        return {"success": True, "message": "Earth Engine funcionando"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/ndvi")
async def get_ndvi():
    """Obtener capa NDVI de Ecuador (recortado exacto)"""
    try:
        # Usar límite administrativo exacto de Ecuador (más preciso que rectángulo)
        ecuador = ee.FeatureCollection("FAO/GAUL/2015/level0") \
            .filter(ee.Filter.eq("ADM0_NAME", "Ecuador")) \
            .geometry()
        
        # Obtener NDVI más reciente de MODIS
        ndvi_collection = ee.ImageCollection('MODIS/061/MOD13A2') \
            .select('NDVI') \
            .filterBounds(ecuador) \
            .filterDate('2024-01-01', '2024-12-31') \
            .sort('system:time_start', False)
        
        # Tomar la imagen más reciente
        ndvi_latest = ndvi_collection.first().multiply(0.0001)
        
        # Recortar EXACTAMENTE a los límites de Ecuador
        ndvi_ecuador = ndvi_latest.clip(ecuador)
        
        # Aplicar máscara para mostrar solo Ecuador
        ndvi_masked = ndvi_ecuador.updateMask(ndvi_ecuador.gte(-1))
        
        # Generar visualización mejorada
        vis_params = {
            'min': 0,
            'max': 1,
            'palette': [
                '#8B0000',  # Rojo oscuro (sin vegetación)
                '#CD5C5C',  # Rojo claro
                '#F0E68C',  # Amarillo (vegetación baja)
                '#9ACD32',  # Verde amarillento
                '#32CD32',  # Verde lima
                '#228B22',  # Verde bosque
                '#006400'   # Verde oscuro (vegetación densa)
            ]
        }
        
        # Obtener URL de tiles
        map_id = ndvi_masked.getMapId(vis_params)
        
        return {
            "success": True,
            "tile_url": map_id['tile_fetcher'].url_format,
            "mapid": map_id['mapid'],
            "token": map_id['token'],
            "message": "NDVI recortado exactamente para Ecuador",
            "date_range": "2024-01-01 a 2024-12-31",
            "description": "NDVI más reciente de MODIS recortado con límites administrativos de Ecuador",
            "boundary_source": "FAO GAUL 2015"
        }
        
    except Exception as e:
        # Si falla, intentar reinicializar
        if "not initialized" in str(e).lower():
            if init_ee():
                return await get_ndvi()  # Reintentar
        
        return {"success": False, "error": str(e)}

@app.get("/ndvi-info")
async def get_ndvi_info():
    """Información sobre el dataset NDVI"""
    try:
        ecuador = ee.Geometry.Rectangle([-82, -5, -75, 2])
        
        collection = ee.ImageCollection('MODIS/061/MOD13A2') \
            .select('NDVI') \
            .filterBounds(ecuador) \
            .filterDate('2024-01-01', '2024-12-31')
        
        # Obtener información de la colección
        size = collection.size().getInfo()
        
        if size > 0:
            latest = collection.sort('system:time_start', False).first()
            date_info = latest.get('system:time_start').getInfo()
            date_readable = ee.Date(date_info).format('YYYY-MM-dd').getInfo()
            
            return {
                "success": True,
                "total_images": size,
                "latest_date": date_readable,
                "dataset": "MODIS/061/MOD13A2",
                "spatial_resolution": "500m",
                "temporal_resolution": "16 days"
            }
        else:
            return {"success": False, "error": "No hay imágenes disponibles"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
