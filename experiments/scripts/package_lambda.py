"""
Script CLI para empaquetar la función AWS Lambda de los Agentes ARIA en un archivo ZIP.
"""

import os
import sys
import zipfile

sys.stdout.reconfigure(encoding='utf-8')

def package_lambda():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    zip_path = os.path.join(base_dir, 'output', 'aria_lambda_package.zip')
    
    # NUNCA empaquetar '.env': Lambda debe recibir credenciales via su Rol de
    # Ejecucion IAM (permisos bedrock:InvokeModel), no via archivo embebido en
    # el ZIP. Empaquetar el .env horneaba access key + secret key dentro de un
    # artefacto que se sube a S3/Lambda y puede circular fuera de control.
    files_to_pack = [
        'lambda_function.py',
        'schemas.py',
    ]
    
    agent_files = [
        'agents/__init__.py',
        'agents/perfilador.py',
        'agents/clasificador.py',
        'agents/analista.py',
        'agents/ejecutor.py',
        'agents/documentador.py'
    ]
    
    print(f"📦 Generando paquete ZIP para AWS Lambda...")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in files_to_pack:
            full_path = os.path.join(base_dir, f)
            if os.path.exists(full_path):
                z.write(full_path, arcname=f)
                print(f"  + {f}")
            else:
                print(f"  ⚠️ No encontrado: {f}")
                
        for f in agent_files:
            full_path = os.path.join(base_dir, f)
            if os.path.exists(full_path):
                z.write(full_path, arcname=f)
                print(f"  + {f}")
            else:
                print(f"  ⚠️ No encontrado: {f}")

    size_bytes = os.path.getsize(zip_path)
    print(f"\n✅ Paquete creado exitosamente:")
    print(f"   Ruta: {zip_path}")
    print(f"   Tamaño: {size_bytes / 1024:.2f} KB ({size_bytes} bytes)")
    print(f"\n⚠️  Este ZIP solo trae el código propio. A diferencia de boto3 (incluido")
    print(f"   en el runtime de Lambda), langchain-core/langchain-aws/pydantic NO lo")
    print(f"   están — hace falta una Lambda Layer con esas dependencias (ver requirements.txt).")
    print(f"\n🔐 El .env NO se empaqueta. Configura en la función Lambda:")
    print(f"   - Variables de entorno: BEDROCK_MODEL_ID, AWS_DEFAULT_REGION")
    print(f"   - Rol de Ejecución IAM con permiso bedrock:InvokeModel (sin access keys estáticas)")
    return zip_path

if __name__ == '__main__':
    package_lambda()
