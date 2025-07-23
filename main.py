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

@app.on_event("startup")
async def startup_event():
    try:
        # Obtener credenciales
        creds = os.getenv('GOOGLE_CREDENTIALS')
        if creds:
            creds_dict = json.loads(creds)
            # Método directo
            ee.Initialize(ee.ServiceAccountCredentials(
                creds_dict['client_email'], 
                key_data=creds
            ))
            print("✅ EE inicializado")
        else:
            print("❌ Sin credenciales")
    except Exception as e:
        print(f"❌ Error: {e}")

@app.get("/")
async def root():
    return {"message": "API NDVI Test", "status": "ok"}

@app.get("/ndvi")
async def get_ndvi():
    try:
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
