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

def init_gee():
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if not creds_json:
            print("❌ No hay GOOGLE_CREDENTIALS")
            return False
            
        # Crear archivo temporal
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(creds_json)
            creds_file = f.name
        
        # Inicializar con archivo
        ee.Initialize(ee.ServiceAccountCredentials('', creds_file))
        
        # Limpiar archivo temporal
        os.unlink(creds_file)
        
        print("✅ EE inicializado correctamente")
        return True
        
    except Exception as e:
        print(f"❌ Error inicializando: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    init_gee()

@app.get("/")
async def root():
    return {"message": "API NDVI Test", "status": "ok"}

@app.get("/init")
async def force_init():
    """Forzar inicialización"""
    success = init_gee()
    return {"success": success, "message": "Inicialización " + ("exitosa" if success else "fallida")}

@app.get("/ndvi")
async def get_ndvi():
    try:
        # Reintentar inicialización si es necesario
        try:
            test = ee.Image(1).getInfo()
        except:
            print("🔄 Reintentando inicialización...")
            if not init_gee():
                return {"error": "No se pudo inicializar Earth Engine"}
        
        # Ecuador bbox
        ecuador = ee.Geometry.Rectangle([-82, -5, -75, 2])
        
        # NDVI más reciente
        ndvi = ee.ImageCollection('MODIS/061/MOD13A2') \
            .select('NDVI') \
            .filterBounds(ecuador) \
            .filterDate('2024-01-01', '2024-12-31') \
            .sort('system:time_start', False) \
            .first() \
            .multiply(0.0001)
        
        # Clip a Ecuador
        ndvi_ecuador = ndvi.clip(ecuador)
        
        # Generar tiles
        map_id = ndvi_ecuador.getMapId({
            'min': 0,
            'max': 1,
            'palette': ['red', 'yellow', 'green']
        })
        
        return {
            "tile_url": map_id['tile_fetcher'].url_format,
            "message": "NDVI cargado exitosamente"
        }
        
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
