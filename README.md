# GCP Infrastructure Challenge — Día 1

Configuración de infraestructura segura y escalable en Google Cloud Platform. Este repositorio documenta el proceso completo de configuración de un proyecto GCP desde cero, incluyendo almacenamiento, automatización con Cloud Functions y observabilidad mediante Cloud Logging.

---

## Arquitectura

```
Usuario / App
     |
     v
Cloud Storage Bucket (gcp-infra-challenge-bucket)
     |  Evento: google.cloud.storage.object.v1.finalized
     v
Eventarc Trigger
     |
     v
Cloud Function (process-gcs-upload) — Python 3.11, Gen 2
     |  1. Valida el payload del evento
     |  2. Extrae metadatos (nombre, tamaño, tipo MIME)
     |  3. Ejecuta validaciones de negocio
     |  4. Emite log estructurado JSON
     v
Cloud Logging
```

---

## Estructura del repositorio

```
gcp-infra-challenge/
├── cloud-function/
│   ├── main.py              # Lógica principal de la Cloud Function
│   ├── requirements.txt     # Dependencias Python
│   └── tests/
│       └── test_main.py     # Pruebas unitarias (pytest)
├── scripts/
│   ├── setup_gcp.sh         # Script de configuración completa
│   └── teardown_gcp.sh      # Limpieza de recursos
├── docs/
│   └── iam_roles.md         # Detalle de roles IAM configurados
└── README.md
```

---

## Configuración paso a paso

### Prerrequisitos

- `gcloud` CLI instalado y autenticado
- Cuenta GCP con facturación habilitada
- Python 3.11+ y pytest para pruebas locales

### 1. Crear el proyecto y habilitar APIs

```bash
gcloud config set project gcp-infra-challenge

gcloud services enable \
  storage.googleapis.com \
  cloudfunctions.googleapis.com \
  pubsub.googleapis.com \
  logging.googleapis.com \
  cloudbuild.googleapis.com \
  eventarc.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com
```

### 2. Configurar IAM — Service Account con privilegios mínimos

```bash
# Crear el Service Account dedicado para la Cloud Function
gcloud iam service-accounts create func-runner \
  --display-name="Cloud Function Runner" \
  --description="Cuenta de servicio para la Cloud Function, solo permisos mínimos"

# Permiso para leer objetos del bucket
gcloud projects add-iam-policy-binding gcp-infra-challenge \
  --member="serviceAccount:func-runner@gcp-infra-challenge.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# Permiso para escribir en Cloud Logging
gcloud projects add-iam-policy-binding gcp-infra-challenge \
  --member="serviceAccount:func-runner@gcp-infra-challenge.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# Permiso para recibir eventos de Eventarc
gcloud projects add-iam-policy-binding gcp-infra-challenge \
  --member="serviceAccount:func-runner@gcp-infra-challenge.iam.gserviceaccount.com" \
  --role="roles/eventarc.eventReceiver"

# Permiso para que Cloud Run pueda invocar la función
gcloud projects add-iam-policy-binding gcp-infra-challenge \
  --member="serviceAccount:func-runner@gcp-infra-challenge.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

### 3. Inicializar Service Accounts internos de GCP

Durante la configuración es necesario inicializar manualmente los Service Accounts
de Pub/Sub y Cloud Storage que GCP usa internamente para el manejo de eventos.

```bash
# Inicializar SA de Pub/Sub
gcloud beta services identity create \
  --service=pubsub.googleapis.com \
  --project=gcp-infra-challenge

# Inicializar SA de Cloud Storage
gcloud storage service-agent --project=gcp-infra-challenge

# Dar permiso de publicación al SA de Pub/Sub
gcloud projects add-iam-policy-binding gcp-infra-challenge \
  --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# Dar permiso de publicación al SA de Cloud Storage
gcloud projects add-iam-policy-binding gcp-infra-challenge \
  --member="serviceAccount:service-PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# Dar permiso al SA de Eventarc
gcloud projects add-iam-policy-binding gcp-infra-challenge \
  --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --role="roles/eventarc.serviceAgent"

# Dar permiso a Cloud Build
gcloud projects add-iam-policy-binding gcp-infra-challenge \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.builder"
```

> Reemplaza `PROJECT_NUMBER` con el número de tu proyecto:
> `gcloud projects describe gcp-infra-challenge --format="value(projectNumber)"`

### 4. Crear el bucket de Cloud Storage

```bash
# Crear el bucket con acceso uniforme y sin acceso público
gcloud storage buckets create gs://gcp-infra-challenge-bucket \
  --location=us-central1 \
  --uniform-bucket-level-access \
  --public-access-prevention

# Crear archivo de reglas de ciclo de vida
cat > /tmp/lifecycle.json << 'LIFECYCLE'
{
  "lifecycle": {
    "rule": [
      {
        "action": { "type": "SetStorageClass", "storageClass": "NEARLINE" },
        "condition": { "age": 30, "matchesStorageClass": ["STANDARD"] }
      },
      {
        "action": { "type": "SetStorageClass", "storageClass": "COLDLINE" },
        "condition": { "age": 90, "matchesStorageClass": ["NEARLINE"] }
      },
      {
        "action": { "type": "Delete" },
        "condition": { "age": 365 }
      }
    ]
  }
}
LIFECYCLE

# Aplicar reglas al bucket
gcloud storage buckets update gs://gcp-infra-challenge-bucket \
  --lifecycle-file=/tmp/lifecycle.json

# Dar acceso al Service Account sobre el bucket
gcloud storage buckets add-iam-policy-binding gs://gcp-infra-challenge-bucket \
  --member="serviceAccount:func-runner@gcp-infra-challenge.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

### 5. Desplegar la Cloud Function

```bash
gcloud functions deploy process-gcs-upload \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=$HOME/gcp-challenge/cloud-function \
  --entry-point=process_gcs_upload \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=gcp-infra-challenge-bucket" \
  --service-account=func-runner@gcp-infra-challenge.iam.gserviceaccount.com \
  --memory=256Mi \
  --timeout=60s \
  --no-allow-unauthenticated
```

### 6. Prueba de funcionamiento

```bash
# Subir archivo de prueba
echo '{"test": true}' > /tmp/test.json
gcloud storage cp /tmp/test.json gs://gcp-infra-challenge-bucket/test/test.json

# Verificar logs (esperar ~10 segundos)
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=process-gcs-upload" \
  --project=gcp-infra-challenge \
  --limit=5 \
  --format="json"
```

El log generado tiene esta estructura:

```json
{
  "severity": "INFO",
  "event": "file_uploaded",
  "metadata": {
    "bucket": "gcp-infra-challenge-bucket",
    "name": "test/test.json",
    "size_bytes": 16,
    "content_type": "application/json",
    "processed_at": "2024-01-15T10:30:01.234567+00:00"
  },
  "warnings": []
}
```

---

## Pruebas unitarias

```bash
cd cloud-function
pip install -r requirements.txt pytest pytest-mock
pytest tests/ -v
```

Resultado esperado: 14 pruebas pasando, cubriendo flujo exitoso, validación de payloads y validaciones de negocio.

---

## Roles IAM configurados

| Principal | Rol | Justificación |
|---|---|---|
| `func-runner` | `storage.objectViewer` | Leer metadatos del objeto que disparó el evento |
| `func-runner` | `logging.logWriter` | Registrar eventos en Cloud Logging |
| `func-runner` | `eventarc.eventReceiver` | Recibir eventos del trigger de Eventarc |
| `func-runner` | `run.invoker` | Permitir que Cloud Run ejecute la función |

## Reglas de ciclo de vida del bucket

| Condición | Acción |
|---|---|
| Archivo en STANDARD por más de 30 días | Mover a NEARLINE |
| Archivo en NEARLINE por más de 90 días | Mover a COLDLINE |
| Archivo con más de 365 días | Eliminar |

---

## Notas de implementación

**Cloud Functions Gen 2 sobre Gen 1**: La segunda generación corre sobre Cloud Run, lo que permite mejor integración con Eventarc, mayor tiempo de ejecución y soporte de concurrencia por instancia.

**Logs en JSON estructurado**: Facilita la creación de métricas y alertas en Cloud Monitoring sin necesidad de parsear texto libre. El campo `severity` permite filtrar por nivel directamente en Cloud Logging.

**Inicialización manual de Service Accounts internos**: Al crear un proyecto GCP desde cero, varios Service Accounts internos (Pub/Sub, Eventarc, Cloud Storage) no existen hasta que se inicializan explícitamente. Esto es un paso que la documentación oficial no siempre menciona claramente y que requiere troubleshooting en la primera configuración.

**`--no-allow-unauthenticated`**: La función no es invocable desde internet directamente. Solo puede ser activada por el trigger de Eventarc autenticado.
