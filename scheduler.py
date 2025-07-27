import schedule
import time
import requests
import threading
from datetime import datetime
import os

class FireScheduler:
    def __init__(self):
        self.api_base = os.getenv('RAILWAY_API_BASE', 'http://localhost:8000')
        self.running = False
        
    def process_fires_job(self):
        print(f"[{datetime.now()}] 🔥 Iniciando procesamiento programado de incendios...")
        
        try:
            response = requests.post(f"{self.api_base}/process-fires", timeout=3600)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    stats = result.get('stats', {})
                    print(f"✅ Procesamiento exitoso:")
                    print(f"   📊 Total polígonos: {stats.get('total_poligonos', 'N/A')}")
                    print(f"   🆔 Eventos únicos: {stats.get('eventos_unicos', 'N/A')}")
                    print(f"   🔥 Eventos grandes: {stats.get('eventos_grandes', 'N/A')}")
                    print(f"   📏 Superficie total: {stats.get('superficie_total', 'N/A'):.1f} ha")
                    print(f"   📤 Subida: {'OK' if stats.get('uploaded') else 'ERROR'}")
                else:
                    print(f"❌ Error en procesamiento: {result.get('error')}")
            else:
                print(f"❌ Error HTTP: {response.status_code}")
                print(f"Response: {response.text}")
                
        except requests.exceptions.Timeout:
            print("⏰ Timeout - El procesamiento está tomando más tiempo del esperado")
        except requests.exceptions.ConnectionError:
            print("🔌 Error de conexión - No se pudo conectar a la API")
        except Exception as e:
            print(f"❌ Error en job programado: {e}")
    
    def test_connection(self):
        """Test de conexión inicial"""
        try:
            response = requests.get(f"{self.api_base}/", timeout=10)
            if response.status_code == 200:
                print("✅ Conexión API exitosa")
                return True
            else:
                print(f"⚠️ API responde pero status {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ No se puede conectar a la API: {e}")
            return False
    
    def start_scheduler(self):
        print("🚀 Iniciando scheduler de incendios...")
        print("📅 Horarios programados: 06:00, 12:00, 18:00 UTC")
        print(f"🔗 API Base: {self.api_base}")
        
        # Test de conexión inicial
        if not self.test_connection():
            print("⚠️ Continuando sin conexión inicial...")
        
        # Programar trabajos cada 6 horas
        schedule.every().day.at("06:00").do(self.process_fires_job)
        schedule.every().day.at("12:00").do(self.process_fires_job) 
        schedule.every().day.at("18:00").do(self.process_fires_job)
        
        # Mostrar próximas ejecuciones
        self.show_next_runs()
        
        self.running = True
        
        print("⏳ Scheduler activo, esperando horarios programados...")
        
        while self.running:
            schedule.run_pending()
            time.sleep(60)
    
    def show_next_runs(self):
        """Muestra las próximas 3 ejecuciones programadas"""
        print("\n📋 Próximas ejecuciones:")
        jobs = schedule.get_jobs()
        for i, job in enumerate(jobs[:3]):
            next_run = job.next_run
            if next_run:
                print(f"   {i+1}. {next_run.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print()
    
    def start_in_background(self):
        """Inicia el scheduler en background para que no bloquee FastAPI"""
        def run_scheduler():
            self.start_scheduler()
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        print("🔄 Fire scheduler ejecutándose en background")
        
        # Mostrar info del scheduler
        print("📋 Configuración del scheduler:")
        print("   ⏰ Frecuencia: Cada 6 horas")
        print("   🕕 Horarios: 06:00, 12:00, 18:00 UTC")
        print("   🔄 Modo: Procesamiento incremental")
        print("   📊 Tracking: Eventos continuos mantienen mismo ID")
        
    def stop(self):
        """Detiene el scheduler"""
        self.running = False
        schedule.clear()
        print("🛑 Fire scheduler detenido")
    
    def force_run(self):
        """Ejecuta el job inmediatamente (para testing)"""
        print("🚀 Ejecutando procesamiento manual...")
        self.process_fires_job()
    
    def get_status(self):
        """Retorna el estado actual del scheduler"""
        jobs = schedule.get_jobs()
        next_run = jobs[0].next_run if jobs else None
        
        return {
            "running": self.running,
            "jobs_scheduled": len(jobs),
            "next_run": next_run.strftime('%Y-%m-%d %H:%M:%S UTC') if next_run else None,
            "api_base": self.api_base,
            "schedule": "06:00, 12:00, 18:00 UTC"
        }

# Instancia global del scheduler
scheduler_instance = FireScheduler()

if __name__ == "__main__":
    print("🔥 Iniciando Fire Scheduler...")
    print("💡 Tip: Ctrl+C para detener")
    
    try:
        scheduler_instance.start_scheduler()
    except KeyboardInterrupt:
        print("\n👋 Deteniendo scheduler...")
        scheduler_instance.stop()
        print("✅ Scheduler detenido correctamente")
