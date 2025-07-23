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
    try:
        # Para Railway, usaremos variable de entorno
        credentials_json = os.getenv('GOOGLE_CREDENTIALS')
        if credentials_json:
            credentials_dict = json.loads(credentials_json)
            credentials = ee.ServiceAccountCredentials(
                email=credentials_dict['client_email'],
                key_data=credentials_json
            )
        else:
            # Para desarrollo local
            credentials = ee.ServiceAccountCredentials(
                email='ndice-de-sequedad-09a67e84a86e@mapas-212104.iam.gserviceaccount.com',
                key_file='credentials.json'
            )
        
        ee.Initialize(credentials)
        return True
    except Exception as e:
        print(f"Error inicializando EE: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    init_ee()

@app.get("/")
async def root():
    return {"message": "API GEE Índice de Sequedad funcionando", "status": "ok"}

@app.get("/test-gee")
async def test_gee():
    try:
        # Test básico - obtener información de Ecuador
        ecuador = ee.FeatureCollection("FAO/GAUL/2015/level0").filter(ee.Filter.eq("ADM0_NAME","Ecuador"))
        info = ecuador.getInfo()
        return {"message": "GEE conectado exitosamente", "test": "ok", "features": len(info['features'])}
    except Exception as e:
        return {"error": str(e), "message": "Error conectando con GEE"}

@app.get("/indice-sequedad")
async def get_indice_sequedad():
    try:
        # Definir ROI de Ecuador
        roi = ee.FeatureCollection("FAO/GAUL/2015/level0").filter(ee.Filter.eq("ADM0_NAME","Ecuador"))
        
        # Fechas
        fecha_inicio = '2024-01-01'
        fecha_fin = '2025-12-31'
        
        # Máscara para recortar
        mascara_cut = ee.Image(1).clip(roi)
        
        def cortar_coleccion(imagen):
            mascara = mascara_cut.mask()
            return imagen.updateMask(mascara)
        
        # 1. PRECIPITACIÓN GPM
        gpm_coleccion = ee.ImageCollection('NASA/GPM_L3/IMERG_V06') \
            .select('precipitationCal') \
            .filterBounds(roi) \
            .filterDate(fecha_inicio, fecha_fin) \
            .sort('system:time_end', False) \
            .limit(48) \
            .map(cortar_coleccion)
        
        # Duración de precipitación
        duracion_precipitacion = gpm_coleccion.sum().divide(2).rename('duracion')
        
        # 2. TEMPERATURA ERA5
        temp_last = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
            .select('temperature_2m') \
            .filterBounds(roi) \
            .map(cortar_coleccion) \
            .filterDate(fecha_inicio, fecha_fin) \
            .sort('system:time_end', False) \
            .first()
        
        # 3. PUNTO DE ROCÍO
        dewpoint = ee.ImageCollection('ECMWF/ERA5_LAND/DAILY_AGGR') \
            .select('dewpoint_temperature_2m') \
            .filterBounds(roi) \
            .map(cortar_coleccion) \
            .filterDate(fecha_inicio, fecha_fin) \
            .sort('system:time_end', False) \
            .first()
        
        # 4. CÁLCULO HUMEDAD RELATIVA
        tempera_k = temp_last.subtract(273.15)
        dewpoint_k = dewpoint.subtract(273.15)
        pvse = dewpoint_k.multiply(17.27).divide(dewpoint_k.add(237.3)).exp().multiply(6.1078)
        pvses = tempera_k.multiply(17.27).divide(tempera_k.add(237.3)).exp().multiply(6.1078)
        relative_humidity = pvse.divide(pvses).multiply(100).rename('relahumi')
        
        datos = relative_humidity.addBands(temp_last).clip(roi)
        
        # 5. NDVI MODIS
        coleccion_ndvi = ee.ImageCollection("MODIS/061/MOD13A2") \
            .select('NDVI') \
            .filterDate(fecha_inicio, fecha_fin) \
            .filterBounds(roi) \
            .map(cortar_coleccion)
        
        ndvi_last = coleccion_ndvi.sort('system:time_end', False).first().multiply(0.0001)
        
        # 6. NDVI MIN/MAX (usando assets del proyecto)
        min_ndvi_sa = ee.Image('projects/ee-oscarlucassolis/assets/ndvi_min')
        max_ndvi_sa = ee.Image('projects/ee-oscarlucassolis/assets/ndvi_max')
        
        max_ndvi = max_ndvi_sa.multiply(0.0001)
        min_ndvi = min_ndvi_sa.multiply(0.0001)
        
        # 7. CÁLCULO EMC (Equilibrium Moisture Content)
        emc = datos.expression(
            "(b('relahumi') < 10) ? 0.032229+0.281073*b('relahumi')-0.000578*b('relahumi')*b('temperature_2m')" +
            ": (b('relahumi') < 50) ? 2.22749+0.160107*b('relahumi')-0.014784*b('temperature_2m')" +
            ": 21.0606+0.005565*(b('relahumi')**2)-0.00035*b('relahumi')*b('temperature_2m')-0.483199*b('relahumi')"
        ).rename('EMC')
        
        # 8. H100
        h100_inputs = emc.addBands(duracion_precipitacion).clip(roi)
        h100 = h100_inputs.expression(
            "(24 - b('duracion')) * b('EMC') + b('duracion') * (0.5 * b('duracion') + 41)"
        ).divide(24).rename('H100')
        
        # 9. LRmax
        lrmax = max_ndvi.expression(
            '0.30 + 0.30 * ((NDVImax + 0.19) / (0.95 + 0.19))', {
                'NDVImax': max_ndvi.select('b1')
            }
        ).rename('LRmax')
        
        # 10. RG (Relative Greenness)
        rg = ndvi_last.expression(
            '((NDVI - NDVImin) / (NDVImax - NDVImin)) * 100', {
                'NDVI': ndvi_last.select('NDVI'),
                'NDVImin': min_ndvi.select('b1'),
                'NDVImax': max_ndvi.select('b1')
            }
        ).rename('RG')
        
        # 11. LR (Live Fuel Moisture)
        lr = rg.expression(
            'RG * LRmax / 100', {
                'RG': rg,
                'LRmax': lrmax
            }
        ).rename('LR')
        
        # 12. MR (usando assets H100 min/max)
        h100_min = ee.Image('projects/ee-oscarlucassolis/assets/H100_min')
        h100_max = ee.Image('projects/ee-oscarlucassolis/assets/H100_max')
        
        mr = h100.expression(
            '((H100 - H100min) / (H100max - H100min))', {
                'H100': h100,
                'H100min': h100_min.select('b1'),
                'H100max': h100_max.select('b1')
            }
        ).rename('MR')
        
        # 13. FDI (Fire Danger Index)
        fdi_sc = lr.expression(
            '((1 - LR) * (1 - MR)) * 100', {
                'LR': lr,
                'MR': mr
            }
        ).rename('FDI')
        
        # 14. CLASIFICACIÓN FINAL
        imagen_fdi = ee.Image(0) \
            .where(fdi_sc.lt(50), 1) \
            .where(fdi_sc.gte(50).And(fdi_sc.lt(60)), 2) \
            .where(fdi_sc.gte(60).And(fdi_sc.lt(70)), 3) \
            .where(fdi_sc.gte(70).And(fdi_sc.lt(80)), 4) \
            .where(fdi_sc.gte(80).And(fdi_sc.lt(91)), 5) \
            .where(fdi_sc.gte(91), 6).clip(roi)
        
        # Paleta de colores
        simbologia = ['267E00','56E200','FFFC00','FE7400','FF0000','9E00FF']
        
        # Generar tiles
        map_id = imagen_fdi.getMapId({
            'min': 1,
            'max': 6,
            'palette': simbologia,
            'opacity': 0.70
        })
        
        return {
            "tile_url": map_id['tile_fetcher'].url_format,
            "mapid": map_id['mapid'],
            "token": map_id['token'],
            "message": "Índice de Sequedad Combinado generado exitosamente",
            "legend": {
                "labels": [
                    "Muy baja (<50)",
                    "Baja (50-60)",
                    "Media (60-70)",
                    "Alta (70-80)",
                    "Muy alta (80-91)",
                    "Extrema (>91)"
                ],
                "colors": simbologia
            }
        }
        
    except Exception as e:
        return {"error": str(e), "details": "Error procesando índice de sequedad"}

@app.get("/incendios-ecuador")
async def get_incendios_ecuador():
    try:
        # Área de Ecuador
        ecuador = ee.Geometry.Rectangle([-82, -5, -75, 2])
        
        # Datos de incendios MODIS burned area recientes
        dataset = ee.ImageCollection('MODIS/061/MCD64A1') \
                    .filterDate('2024-01-01', '2025-01-01') \
                    .filterBounds(ecuador) \
                    .select('BurnDate')
        
        mosaic = dataset.max().clip(ecuador)
        
        # Generar tiles
        map_id = mosaic.getMapId({
            'min': 1,
            'max': 366,
            'palette': ['000000', '00ff00', 'ffff00', 'ff0000']
        })
        
        return {
            "tile_url": map_id['tile_fetcher'].url_format,
            "mapid": map_id['mapid'],
            "token": map_id['token'],
            "message": "Capa de incendios generada exitosamente"
        }
        
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
