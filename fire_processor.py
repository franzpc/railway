import geopandas as gpd
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from scipy.spatial import Delaunay
import os
from tqdm import tqdm
import warnings
import json
import tempfile
warnings.filterwarnings('ignore')

class DataProcessor:
    def __init__(self):
        self.data_path = os.path.join("data", "ORGANIZACION_TERRITORIAL_PARROQUIAL.shp")
        self.bounds = [-92.0, -5.0, -75.2, 1.7]
        self.api_url = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
        self.api_key = os.getenv('NASA_FIRMS_KEY', '9c57ff9dd1fb752c9c1dc9da87bce875')
        self.sources = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT"]
        self.days = 10
        self.dt = 1000
        self.tl = 3
        
        self.db_url = 'https://neixcsnkwtgdxkucfcnb.supabase.co'
        self.db_key = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5laXhjc25rd3RnZHhrdWNmY25iIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDk1NzQ0OTQsImV4cCI6MjA2NTE1MDQ5NH0.OLcE9XYvYL6vzuXqcgp3dMowDZblvQo8qR21Cj39nyY'
        
    def load_existing_ids(self):
        try:
            url = f"{self.db_url}/rest/v1/incendios_grandes?select=evento_id"
            headers = {
                'apikey': self.db_key,
                'Authorization': f'Bearer {self.db_key}'
            }
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return set([str(item['evento_id']) for item in data if item['evento_id']])
            return set()
        except:
            return set()
    
    def create_tracking_id(self, lng, lat, date, existing_ids):
        base_id = f"{date.timetuple().tm_yday:03d}{abs(int(lng*10)):03d}{abs(int(lat*10)):03d}"
        
        if base_id not in existing_ids:
            return base_id
        
        for i in range(1, 100):
            new_id = f"{base_id}{i:02d}"
            if new_id not in existing_ids:
                return new_id
        
        return base_id
        
    def fetch_data(self, source, date):
        area = ",".join(map(str, self.bounds))
        date_str = date.strftime("%Y-%m-%d")
        url = f"{self.api_url}/{self.api_key}/{source}/{area}/{self.days}/{date_str}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            if response.text.strip():
                from io import StringIO
                df = pd.read_csv(StringIO(response.text))
                
                if not df.empty:
                    gdf = gpd.GeoDataFrame(
                        df, 
                        geometry=gpd.points_from_xy(df.longitude, df.latitude),
                        crs='EPSG:4326'
                    )
                    gdf = gdf.to_crs('EPSG:32717')
                    return gdf
            
            return gpd.GeoDataFrame()
        except Exception as e:
            print(f"Error en {source}: {e}")
            return gpd.GeoDataFrame()
    
    def get_recent_data(self):
        date = datetime.now() - timedelta(days=3)
        all_data = []
        
        print("Obteniendo datos recientes...")
        for source in self.sources:
            data = self.fetch_data(source, date)
            if not data.empty:
                all_data.append(data)
        
        if not all_data:
            return gpd.GeoDataFrame()
        
        combined = pd.concat(all_data, ignore_index=True)
        
        mapping = {
            'bright_ti4': 'BRIGHTNESS',
            'scan': 'SCAN',
            'track': 'TRACK',
            'acq_date': 'ACQ_DATE',
            'acq_time': 'ACQ_TIME',
            'satellite': 'SATELLITE',
            'instrument': 'INSTRUMENT',
            'confidence': 'CONFIDENCE',
            'version': 'VERSION',
            'bright_ti5': 'BRIGHT_T31',
            'frp': 'FRP',
            'daynight': 'DAYNIGHT'
        }
        
        combined = combined.rename(columns=mapping)
        combined['eid'] = None
        combined['ACQ_DATE'] = pd.to_datetime(combined['ACQ_DATE'])
        
        return combined
    
    def step_one(self):
        print("Paso 1...")
        
        new_data = self.get_recent_data()
        if new_data.empty:
            print("Sin datos nuevos")
            return gpd.GeoDataFrame(), set()
        
        existing_ids = self.load_existing_ids()
        print(f"Datos: {len(new_data)}, IDs existentes: {len(existing_ids)}")
        return new_data, existing_ids
    
    def step_two(self, data, existing_ids):
        print("Paso 2...")
        
        data = data[
            (data['ACQ_DATE'] >= '2025-04-01') & 
            (data['ACQ_DATE'] <= '2025-12-31')
        ].copy()
        
        if data.empty:
            return data
        
        data = data.sort_values('ACQ_DATE').reset_index(drop=True)
        data['eid'] = None
        
        print("Procesando...")
        for i in tqdm(range(len(data))):
            if pd.isna(data.loc[i, 'eid']):
                point = data.iloc[i]
                coords = point.geometry.get_coordinates()
                lng, lat = coords.x.iloc[0], coords.y.iloc[0]
                lng_4326 = lng * 180 / 20037508.34
                lat_4326 = lat * 180 / 20037508.34
                
                tracking_id = self.create_tracking_id(lng_4326, lat_4326, point['ACQ_DATE'], existing_ids)
                existing_ids.add(tracking_id)
                
                data.loc[i, 'eid'] = tracking_id
                pts = [i]
                
                while True:
                    new_pts = []
                    
                    for pt_idx in pts:
                        base_pt = data.iloc[pt_idx]
                        unclassified = data[data['eid'].isna()]
                        
                        if unclassified.empty:
                            continue
                        
                        time_diff = (unclassified['ACQ_DATE'] - base_pt['ACQ_DATE']).dt.days
                        time_valid = (time_diff >= 0) & (time_diff <= self.tl)
                        candidates = unclassified[time_valid]
                        
                        if candidates.empty:
                            continue
                        
                        distances = candidates.geometry.distance(base_pt.geometry)
                        dist_valid = distances <= self.dt
                        finals = candidates[dist_valid]
                        
                        for idx in finals.index:
                            data.loc[idx, 'eid'] = tracking_id
                            new_pts.append(idx)
                    
                    if not new_pts:
                        break
                    
                    pts = new_pts
        
        return data
    
    def step_three(self, data):
        print("Paso 3...")
        
        valid_events = data.groupby('eid').size()
        valid_events = valid_events[valid_events >= 5].index
        filtered = data[data['eid'].isin(valid_events)].copy()
        
        print(f"Eventos válidos: {len(valid_events)} de {data['eid'].nunique()}")
        
        if filtered.empty:
            return gpd.GeoDataFrame()
        
        filtered['dt'] = filtered['ACQ_DATE'].dt.strftime('%Y-%m-%d')
        results = []
        unique_events = filtered['eid'].unique()
        
        for event in tqdm(unique_events, desc="Procesando"):
            current = filtered[filtered['eid'] == event].copy()
            current = current.sort_values('dt')
            
            dates = sorted(current['dt'].unique())
            accumulated_pts = []
            prev_poly = None
            
            for current_date in dates:
                day_pts = current[current['dt'] == current_date]
                
                for _, pt in day_pts.iterrows():
                    accumulated_pts.append([pt.geometry.x, pt.geometry.y])
                
                current_poly = None
                
                if len(accumulated_pts) >= 3:
                    try:
                        tri = Delaunay(np.array(accumulated_pts))
                        triangles = []
                        
                        for simplex in tri.simplices:
                            coords = [accumulated_pts[i] for i in simplex]
                            triangle = Polygon(coords)
                            
                            edge_coords = list(triangle.exterior.coords)
                            max_edge = max([
                                Point(edge_coords[i]).distance(Point(edge_coords[i+1])) 
                                for i in range(len(edge_coords)-1)
                            ])
                            
                            area = triangle.area / 10000
                            
                            if max_edge <= 2000 and area <= 500:
                                triangles.append(triangle)
                        
                        if triangles:
                            current_poly = unary_union(triangles)
                            
                            if prev_poly is not None:
                                current_poly = unary_union([current_poly, prev_poly])
                            
                            prev_poly = current_poly
                        else:
                            current_poly = prev_poly
                            
                    except Exception as e:
                        current_poly = prev_poly
                        
                elif len(accumulated_pts) == 2:
                    points = [Point(p) for p in accumulated_pts]
                    current_poly = unary_union(points).convex_hull
                else:
                    current_poly = Point(accumulated_pts[0]) if accumulated_pts else None
                
                if current_poly is not None and not current_poly.is_empty:
                    result = {
                        'eid': event,
                        'fecha': pd.to_datetime(current_date),
                        'geometry': current_poly
                    }
                    results.append(result)
        
        if not results:
            return gpd.GeoDataFrame()
        
        result_gdf = gpd.GeoDataFrame(results, crs='EPSG:32717')
        return result_gdf
    
    def step_four(self, data):
        print("Paso 4...")
        
        data = data.sort_values(['eid', 'fecha']).reset_index(drop=True)
        new_polys = []
        unique_events = data['eid'].unique()
        
        for event in tqdm(unique_events, desc="Limpieza"):
            event_polys = data[data['eid'] == event].copy()
            accumulated_geom = None
            
            for idx, row in event_polys.iterrows():
                current_geom = row.geometry
                
                if current_geom.is_empty:
                    continue
                
                if accumulated_geom is None:
                    unique_geom = current_geom
                else:
                    try:
                        unique_geom = current_geom.difference(accumulated_geom)
                    except:
                        continue
                
                if not unique_geom.is_empty:
                    new_row = row.copy()
                    new_row.geometry = unique_geom
                    new_polys.append(new_row)
                    
                    if accumulated_geom is None:
                        accumulated_geom = unique_geom
                    else:
                        accumulated_geom = unary_union([accumulated_geom, unique_geom])
        
        if not new_polys:
            return gpd.GeoDataFrame()
        
        final_data = gpd.GeoDataFrame(new_polys, crs='EPSG:32717')
        return final_data
    
    def step_five(self, data):
        print("Paso 5...")
        
        try:
            admin = gpd.read_file(self.data_path)
        except Exception as e:
            print(f"Error archivo: {e}")
            return gpd.GeoDataFrame()
        
        if admin.crs != data.crs:
            admin = admin.to_crs(data.crs)
        
        start_points = (data.sort_values(['eid', 'fecha'])
                       .groupby('eid')
                       .first()
                       .reset_index())
        
        location_info = gpd.sjoin(start_points, admin, how='left', predicate='intersects')
        location_info = (location_info.groupby('eid').first().reset_index())
        
        location_cols = ['eid', 'DPA_DESPRO', 'DPA_DESCAN', 'DPA_DESPAR']
        location_info = location_info[location_cols]
        
        location_info = location_info.rename(columns={
            'DPA_DESPRO': 'dpa_despro',
            'DPA_DESCAN': 'dpa_descan',
            'DPA_DESPAR': 'dpa_despar'
        })
        
        data_with_location = data.merge(location_info, on='eid', how='left')
        clean_data = data_with_location.dropna(subset=['eid', 'fecha', 'dpa_despro'])
        
        if clean_data.empty:
            print("Sin datos válidos")
            return gpd.GeoDataFrame()
        
        print("Calculando métricas...")
        clean_data['superficie_ha_individual'] = clean_data.geometry.area / 10000
        calculated = clean_data.copy()
        
        def calc_metrics(group):
            group = group.sort_values('fecha').reset_index(drop=True)
            group['dia_del_incendio'] = range(1, len(group) + 1)
            group['superficie_ha_total'] = group['superficie_ha_individual'].sum()
            group['fecha_inicio'] = group['fecha'].min()
            group['fecha_fin'] = group['fecha'].max()
            group['duracion_dias'] = (group['fecha_fin'] - group['fecha_inicio']).dt.days + 1
            return group
        
        calculated = (calculated.groupby('eid')
                     .apply(calc_metrics)
                     .reset_index(drop=True))
        
        large_events = calculated[calculated['superficie_ha_total'] >= 10].copy()
        
        print(f"Eventos procesados: {calculated['eid'].nunique()}")
        print(f"Eventos grandes: {large_events['eid'].nunique()}")
        print(f"Polígonos: {len(calculated)}")
        print(f"Polígonos grandes: {len(large_events)}")
        
        calculated = calculated.rename(columns={'eid': 'evento_id'})
        return calculated
    
    def save_data(self, data):
        try:
            large_events = data[data['superficie_ha_total'] >= 10].copy()
            large_events = large_events[large_events.geometry.geom_type == 'Polygon'].copy()
            
            if large_events.empty:
                print("Sin polígonos para actualizar")
                return True
            
            existing_ids = self.load_existing_ids()
            new_events = large_events[~large_events['evento_id'].astype(str).isin(existing_ids)].copy()
            
            if new_events.empty:
                print("Sin eventos nuevos")
                return True
            
            data_copy = new_events.copy()
            data_copy = data_copy.to_crs('EPSG:4326')
            data_copy['geom'] = data_copy['geometry'].apply(lambda x: x.wkt)
            data_copy = data_copy.drop('geometry', axis=1)
            
            for col in data_copy.select_dtypes(include=['datetime64']).columns:
                data_copy[col] = data_copy[col].dt.strftime('%Y-%m-%d')
            
            data_copy = data_copy.fillna('')
            records = data_copy.to_dict('records')
            
            url = f"{self.db_url}/rest/v1/incendios_grandes"
            headers = {
                'apikey': self.db_key,
                'Authorization': f'Bearer {self.db_key}',
                'Content-Type': 'application/json',
                'Prefer': 'return=minimal'
            }
            
            for i in range(0, len(records), 1000):
                batch = records[i:i+1000]
                response = requests.post(url, json=batch, headers=headers)
                if response.status_code not in [200, 201]:
                    print(f"Error batch {i//1000 + 1}: {response.status_code}")
                    return False
            
            print(f"Agregados {len(records)} polígonos nuevos")
            return True
        except Exception as e:
            print(f"Error guardando: {e}")
            return False
    
    def run_process(self):
        print("=== PROCESO INCREMENTAL ===\n")
        
        try:
            data, existing_ids = self.step_one()
            if data.empty:
                return {"success": False, "error": "Sin datos"}
            
            data_with_ids = self.step_two(data, existing_ids)
            if data_with_ids.empty:
                return {"success": False, "error": "Error paso 2"}
            
            polygons = self.step_three(data_with_ids)
            if polygons.empty:
                return {"success": False, "error": "Error paso 3"}
            
            no_overlaps = self.step_four(polygons)
            if no_overlaps.empty:
                return {"success": False, "error": "Error paso 4"}
            
            final_data = self.step_five(no_overlaps)
            if final_data is None or final_data.empty:
                return {"success": False, "error": "Error paso 5"}
            
            large_events = final_data[final_data['superficie_ha_total'] >= 10]
            
            success = self.save_data(final_data)
            
            result = {
                "success": True,
                "message": "Proceso incremental completado",
                "stats": {
                    "total_poligonos": len(final_data),
                    "eventos_unicos": final_data['evento_id'].nunique(),
                    "eventos_grandes": len(large_events),
                    "superficie_total": final_data['superficie_ha_individual'].sum(),
                    "uploaded": success
                },
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            
            print(f"\n=== COMPLETADO ===")
            print(f"Total: {len(final_data)}")
            print(f"Eventos: {final_data['evento_id'].nunique()}")
            print(f"Grandes: {len(large_events)}")
            print(f"Guardado: {'OK' if success else 'ERROR'}")
            
            return result
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
