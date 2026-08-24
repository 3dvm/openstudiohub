import gazu
import getpass
import os
import sys
import json
from pathlib import Path

# Definimos la ruta del archivo de configuración relativo a este script
CONFIG_FILE = Path(__file__).parent / "kitsu_test_env.json"

def get_credentials():
    """Carga las credenciales desde el JSON o las pide al usuario y las guarda."""
    if CONFIG_FILE.exists():
        print(f"[+] Cargando credenciales cacheadas desde {CONFIG_FILE.name}...")
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("[-] Error: El archivo de configuración está corrupto. Borrándolo...")
            CONFIG_FILE.unlink()
            
    print("[!] Primer inicio detectado. Configura tu entorno de pruebas:")
    host_url = input("URL de Kitsu (ej. https://proyectos.macuare.com.ve/api): ").strip()
    if not host_url.endswith("/api"):
        host_url = f"{host_url.rstrip('/')}/api"
        
    email = input("Email de Admin: ").strip()
    password = getpass.getpass("Contraseña: ")
    
    config_data = {
        "host_url": host_url,
        "email": email,
        "password": password
    }
    
    # Guardamos para el futuro
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4)
    print(f"[+] Credenciales guardadas exitosamente en {CONFIG_FILE.name}\n")
    
    return config_data

def main():
    print("==================================================")
    print("🌱 Kitsu Seed Data Generator - RAW API Edition")
    print("==================================================")
    
    # 1. Recolección de credenciales automatizada
    creds = get_credentials()
    
    print("[+] Conectando a la API...")
    gazu.client.set_host(creds["host_url"])
    
    try:
        gazu.log_in(creds["email"], creds["password"])
        print("[+] Login exitoso.")
    except Exception as e:
        print(f"[-] Error de red/credenciales: {e}")
        # Si la clave cambió, borramos el caché para que pregunte de nuevo la próxima vez
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
            print("[!] Archivo de caché purgado. Vuelve a ejecutar el script.")
        sys.exit(1)

    # 2. Creación del Proyecto
    project_name = "p0004-hub-test"
    print(f"\n[+] Buscando/Creando Proyecto: {project_name}")
    project = gazu.project.get_project_by_name(project_name)
    if not project:
        project = gazu.project.new_project(project_name)
        print(f"    -> Proyecto '{project_name}' creado.")
    else:
        print(f"    -> Proyecto '{project_name}' ya existe.")

    # 3. Creación de Tipología y Asset
    print("\n[+] Configurando Assets...")
    asset_type = gazu.asset.get_asset_type_by_name("Character")
    if not asset_type:
        asset_type = gazu.asset.new_asset_type("Character")
        
    asset_name = "Prota"
    asset = gazu.asset.get_asset_by_name(project, asset_name)
    if not asset:
        asset = gazu.asset.new_asset(project, asset_type, asset_name)
        print(f"    -> Asset '{asset_name}' (Character) creado.")
    else:
        print(f"    -> Asset '{asset_name}' ya existe.")

    # 4. Creación de Secuencia y Shots
    print("\n[+] Configurando Shots...")
    seq_name = "sq01"
    sequence = gazu.shot.get_sequence_by_name(project, seq_name)
    if not sequence:
        sequence = gazu.shot.new_sequence(project, seq_name)
        print(f"    -> Secuencia '{seq_name}' creada.")
        
    shots = ["sh010", "sh020"]
    for shot_name in shots:
        shot = gazu.shot.get_shot_by_name(sequence, shot_name)
        if not shot:
            gazu.shot.new_shot(project, sequence, shot_name)
            print(f"    -> Shot '{shot_name}' creado en '{seq_name}'.")
        else:
            print(f"    -> Shot '{shot_name}' ya existe.")

    # 5. Creación de Usuarios Dummy (RBAC)
    dummy_pwd = os.environ.get("KITSU_DUMMY_PWD", "openstudio123")
    print(f"\n[+] Configurando Usuarios Dummy (Contraseña por defecto: {dummy_pwd})...")
    dummy_users = [
        {"first_name": "Test", "last_name": "Vendor", "email": "vendor@dummy.com", "role": "user", "title": "Vendor"},
        {"first_name": "Test", "last_name": "Artist", "email": "artist@dummy.com", "role": "user", "title": "Artist"},
    ]
    
    created_users = {}
    for du in dummy_users:
        user = gazu.person.get_person_by_email(du["email"])
        if not user:
            try:
                user = gazu.person.new_person(
                    first_name=du["first_name"],
                    last_name=du["last_name"],
                    email=du["email"],
                    role=du["role"],
                    password=dummy_pwd
                )
                print(f"    -> Usuario '{du['email']}' ({du['title']}) creado.")
            except Exception as e:
                print(f"    -> Advertencia: No se pudo crear el usuario {du['email']}. Detalle: {e}")
        else:
            print(f"    -> Usuario '{du['email']}' ya existe.")
        if user:
            created_users[du["title"]] = user

    # 6. Búsqueda Segura de Tipos de Tarea (Vía RAW API)
    print("\n[+] Buscando Tipos de Tarea compatibles vía RAW API...")
    try:
        raw_task_types = gazu.client.get("data/task-types")
        
        shot_task_type = None
        asset_task_type = None
        
        for tt in raw_task_types:
            if tt.get("for_entity") == "Shot" and not shot_task_type:
                shot_task_type = tt
            elif tt.get("for_entity") == "Asset" and tt.get("name") == "Rigging":
                asset_task_type = tt
                
        if not asset_task_type:
            for tt in raw_task_types:
                if tt.get("for_entity") == "Asset":
                    asset_task_type = tt
                    break

        if not shot_task_type or not asset_task_type:
            print("[-] ERROR: Faltan tipos de tarea en Kitsu. Necesitas al menos una tarea configurada para 'Shots' y una para 'Assets'.")
            sys.exit(1)
            
        print(f"    -> Tarea para Shot encontrada: {shot_task_type['name']}")
        print(f"    -> Tarea para Asset encontrada: {asset_task_type['name']}")

    except Exception as e:
        print(f"[-] Error consultando la API cruda: {e}")
        sys.exit(1)

    # 7. Asignaciones
    print("\n[+] Asignando Tareas a Usuarios...")
    
    shot_10 = gazu.shot.get_shot_by_name(sequence, "sh010")
    if shot_10 and created_users.get("Vendor"):
        task = gazu.task.get_task_by_entity(shot_10, shot_task_type)
        if not task: 
            task = gazu.task.new_task(shot_10, shot_task_type)
        gazu.task.assign_task(task, created_users["Vendor"])
        print(f"    -> Tarea '{shot_task_type['name']}' en 'sh010' asignada al Vendor.")

    if asset and created_users.get("Artist"):
        task = gazu.task.get_task_by_entity(asset, asset_task_type)
        if not task: 
            task = gazu.task.new_task(asset, asset_task_type)
        gazu.task.assign_task(task, created_users["Artist"])
        print(f"    -> Tarea '{asset_task_type['name']}' en 'Prota' asignada al Artist.")

    print("\n==================================================")
    print("✅ Siembra de datos completada con éxito.")
    print("==================================================")

if __name__ == "__main__":
    main()
