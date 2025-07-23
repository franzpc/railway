from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import ee
import os
import json
import tempfile

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "API NDVI Debug", "status": "ok"}

@app.get("/check-creds")
async def check_credentials():
    """Verificar que las credenciales estén disponibles"""
    creds = os.getenv('GOOGLE_CREDENTIALS')
    
    if not creds:
        return {"error": "GOOGLE_CREDENTIALS no encontrado"}
    
    try:
        creds_dict = json.loads(creds)
        return {
            "creds_found": True,
            "creds_length": len(creds),
            "has_private_key": "private_key" in creds_dict,
            "has_client_email": "client_email" in creds_dict,
            "client_email": creds_dict.get("client_email", "No encontrado"),
            "project_id": creds_dict.get("project_id", "No encontrado")
        }
    except Exception as e:
        return {"error": f"Error parseando JSON: {e}"}

@app.get("/init-method1")
async def init_method1():
    """Método 1: ServiceAccountCredentials con key_data"""
    try:
        creds = os.getenv('GOOGLE_CREDENTIALS')
        if not creds:
            return {"error": "No credentials"}
            
        creds_dict = json.loads(creds)
        credentials = ee.ServiceAccountCredentials(
            email=creds_dict['client_email'],
            key_data=creds
        )
        ee.Initialize(credentials)
        
        # Test
        test = ee.Image(1).getInfo()
        return {"success": True, "method": "key_data", "test": "passed"}
        
    except Exception as e:
        return {"success": False, "method": "key_data", "error": str(e)}

@app.get("/init-method2")
async def init_method2():
    """Método 2: Archivo temporal"""
    try:
        creds = os.getenv('GOOGLE_CREDENTIALS')
        if not creds:
            return {"error": "No credentials"}
            
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(creds)
            temp_file = f.name
        
        credentials = ee.ServiceAccountCredentials('', temp_file)
        ee.Initialize(credentials)
        
        os.unlink(temp_file)  # Limpiar
        
        # Test
        test = ee.Image(1).getInfo()
        return {"success": True, "method": "temp_file", "test": "passed"}
        
    except Exception as e:
        if 'temp_file' in locals():
            try:
                os.unlink(temp_file)
            except:
                pass
        return {"success": False, "method": "temp_file", "error": str(e)}

@app.get("/init-method3")
async def init_method3():
    """Método 3: Directo con diccionario"""
    try:
        creds = os.getenv('GOOGLE_CREDENTIALS')
        if not creds:
            return {"error": "No credentials"}
            
        creds_dict = json.loads(creds)
        
        # Crear credenciales desde diccionario
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        
        ee.Initialize(credentials)
        
        # Test
        test = ee.Image(1).getInfo()
        return {"success": True, "method": "service_account_info", "test": "passed"}
        
    except Exception as e:
        return {"success": False, "method": "service_account_info", "error": str(e)}

@app.get("/init-method4")
async def init_method4():
    """Método 4: Con scopes específicos"""
    try:
        creds = os.getenv('GOOGLE_CREDENTIALS')
        if not creds:
            return {"error": "No credentials"}
            
        creds_dict = json.loads(creds)
        
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/earthengine']
        )
        
        ee.Initialize(credentials)
        
        # Test
        test = ee.Image(1).getInfo()
        return {"success": True, "method": "with_scopes", "test": "passed"}
        
    except Exception as e:
        return {"success": False, "method": "with_scopes", "error": str(e)}

@app.get("/test-simple")
async def test_simple():
    """Test básico de EE"""
    try:
        # Intentar operación simple
        img = ee.Image(1)
        info = img.getInfo()
        return {"success": True, "message": "EE funciona", "info": info}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
