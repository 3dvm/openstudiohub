# =========================================================================================
# OPENSTUDIOHUB
# Herramienta de Desarrollo: seed_project_template.py
# Rol: Configura el esqueleto AAA en Kitsu (Departamentos, Task Types y Plantilla)
# =========================================================================================

import gazu
import os

def get_credentials():
    """Obtiene las credenciales del entorno o usa los valores por defecto de desarrollo."""
    host = os.environ.get("KITSU_HOST", "http://localhost:8080/api")
    email = os.environ.get("KITSU_USER", "admin@example.com")
    pwd = os.environ.get("KITSU_PWD", "")  # required via env; never hardcode
    return host, email, pwd

def main():
    print("\n" + "="*50)
    print("🎬 OPENSTUDIO HUB - KITSU TEMPLATE SEEDER 🎬")
    print("="*50)

    host, email, pwd = get_credentials()
    
    try:
        print(f"[*] Conectando a Kitsu en: {host}")
        gazu.client.set_host(host)
        gazu.log_in(email, pwd)
        print("[*] ✓ Autenticación exitosa.")

        # 1. LOCALIZAR O CREAR LA PLANTILLA
        template_name = "standard-3d-production"
        template = gazu.project_template.get_project_template_by_name(template_name)
        
        if not template:
            print(f"[*] Plantilla '{template_name}' no encontrada. Creándola...")
            template = gazu.project_template.new_project_template(
                name=template_name,
                description="OpenStudioHub Default",
                production_style="3d",
                fps="24",
                ratio="16:9",
                resolution="1920x1080"
            )
            print(f"[*] ✓ Plantilla creada con ID: {template['id']}")
        else:
            print(f"[*] ✓ Plantilla '{template_name}' localizada.")

        # 2. ASEGURAR DEPARTAMENTOS
        print("\n[*] Verificando Departamentos...")
        depts = gazu.person.all_departments()
        
        dept_storyboard = next((d for d in depts if d["name"].lower() == "storyboard"), None)
        if not dept_storyboard:
            dept_storyboard = gazu.person.new_department(name="Storyboard")
            print("    ↳ ✓ Departamento 'Storyboard' creado.")
            
        dept_edit = next((d for d in depts if d["name"].lower() == "editorial" or d["name"].lower() == "edit"), None)
        if not dept_edit:
            dept_edit = gazu.person.new_department(name="Editorial")
            print("    ↳ ✓ Departamento 'Editorial' creado.")

        # 3. ASEGURAR TASK TYPES Y VINCULARLOS A LA PLANTILLA
        print("\n[*] Verificando Task Types (Tipos de Tareas)...")
        all_tts = gazu.task.all_task_types()
        template_tts = gazu.project_template.all_task_types_for_project_template(template)
        template_tt_ids = [tt["id"] for tt in template_tts]

        # A. STORYBOARD (Asignado a Secuencias)
        stb_tt = next((tt for tt in all_tts if tt["name"].lower() == "storyboard" and tt["for_entity"].lower() == "sequence"), None)
        if not stb_tt:
            stb_tt = gazu.task.new_task_type(name="Storyboard", for_entity="Sequence", department_id=dept_storyboard["id"], color="#F97316")
            print("    ↳ ✓ Task Type 'Storyboard' (Sequence) creado.")
        
        if stb_tt["id"] not in template_tt_ids:
            gazu.project_template.add_task_type_to_project_template(template, stb_tt)
            print("    ↳ ✓ 'Storyboard' anclado a la plantilla.")

        # B. EDITORIAL (Asignado a Edits)
        edit_tt = next((tt for tt in all_tts if tt["name"].lower() == "editorial" and tt["for_entity"].lower() == "edit"), None)
        if not edit_tt:
            edit_tt = gazu.task.new_task_type(name="Editorial", for_entity="Edit", department_id=dept_edit["id"], color="#3B82F6")
            print("    ↳ ✓ Task Type 'Editorial' (Edit) creado.")
            
        if edit_tt["id"] not in template_tt_ids:
            gazu.project_template.add_task_type_to_project_template(template, edit_tt)
            print("    ↳ ✓ 'Editorial' anclado a la plantilla.")

        # 4. CREAR UN PROYECTO DE PRUEBA
        test_project_name = "Neon Chase Hub Test"
        print(f"\n[*] Creando proyecto de prueba: '{test_project_name}'...")
        
        existing_proj = gazu.project.get_project_by_name(test_project_name)
        if existing_proj:
            print(f"[*] ⚠️ El proyecto '{test_project_name}' ya existe. Saltando creación.")
        else:
            new_proj = gazu.project.new_project(name=test_project_name, project_template=template)
            print(f"[*] ✓ Proyecto '{test_project_name}' creado exitosamente a partir de la plantilla.")

        print("\n" + "="*50)
        print("✅ SEEDING COMPLETADO CON ÉXITO")
        print("="*50 + "\n")

    except Exception as e:
        print(f"\n[!] ERROR CRÍTICO: {e}")

if __name__ == "__main__":
    main()
