# Documentación de la API de Detección de Fraude (Swagger / OpenAPI)

Este backend, desarrollado en **FastAPI**, cuenta con autogeneración de documentación interactiva basada en la especificación **OpenAPI**.

Puedes interactuar con los endpoints directamente desde tu navegador en producción o en local.

---

## Cómo acceder a la Documentación Interactiva

1. **Swagger UI (Recomendado):**
   - Ofrece una interfaz interactiva donde puedes probar los endpoints en vivo.
   - **URL Local:** `http://localhost:8000/docs`
   - **URL Producción:** `https://detection-attacks-whatsapp.onrender.com/docs`

2. **ReDoc:**
   - Una documentación limpia, enfocada en la lectura y esquemas detallados de datos.
   - **URL Local:** `http://localhost:8000/redoc`
   - **URL Producción:** `https://detection-attacks-whatsapp.onrender.com/redoc`

---

## Resumen de los Endpoints Documentados

### 1. Métricas del Dashboard (Dashboard Metrics)
* **Ruta:** `GET /api/metrics`
* **Etiqueta:** `Métricas del Dashboard`
* **Descripción:** Calcula y devuelve todos los KPIs consolidados (Total de validaciones, porcentaje de cédulas reales vs fotocopias a color), distribuciones de score de confianza (frente y reverso), historial diario para gráficos de área, historial de latencias de AWS/Gemini y la lista de historial de logs.
* **Modelo de Respuesta (`MetricsResponse`):**
  ```json
  {
    "kpis": {
      "total_validations": 211,
      "predicted_real": 207,
      "predicted_photocopy": 4,
      "real_percentage": 98.104,
      "photocopy_percentage": 1.896
    },
    "score_distribution": {
      "front": [207, 4, 0, 0, 0, 0, 0, 0, 0, 0],
      "back": [205, 3, 0, 0, 0, 3, 0, 0, 0, 0]
    },
    "daily_predictions": [
      {
        "date": "2026-07-05",
        "front": 2,
        "back": 2,
        "unsupported": 1,
        "photocopy": 1,
        "total": 5
      }
    ],
    "execution_times": {
      "avg_aws": 1400,
      "avg_gemini": 950,
      "history": [
        {
          "timestamp": "2026-07-05 21:01:45",
          "aws": 1402,
          "gemini": 951
        }
      ]
    },
    "history": [
      {
        "timestamp": "2026-07-05 21:01:45",
        "phone": "573113116974",
        "node": "process_front",
        "score": 0.752,
        "is_photocopy": true,
        "message_id": "wamid.HBgM..."
      }
    ]
  }
  ```

---

### 2. Webhook de WhatsApp (WhatsApp Cloud API)
* **Handshake de Verificación (GET):**
  - **Ruta:** `GET /webhook`
  - **Parámetros Query:** `hub.mode`, `hub.verify_token`, `hub.challenge`
  - **Descripción:** Valida la firma del token secreto registrado en Meta Developers contra la variable de entorno `WHATSAPP_VERIFY_TOKEN`. Retorna el reto `hub.challenge` si la firma coincide.

* **Recepción de Mensajes y Multimedia (POST):**
  - **Ruta:** `POST /webhook`
  - **Descripción:** Escucha de forma asíncrona todos los mensajes entrantes (texto, imágenes y otros formatos). Ejecuta el grafo de estados de LangGraph de manera en segundo plano y responde al usuario a través de WhatsApp.
  - **Payload Esperado (Estructurado por Meta):**
    ```json
    {
      "object": "whatsapp_business_account",
      "entry": [
        {
          "id": "1234567890",
          "changes": [
            {
              "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                  "display_phone_number": "15550000000",
                  "phone_number_id": "990076807518216"
                },
                "messages": [
                  {
                    "from": "573113116974",
                    "id": "wamid.HBgM...",
                    "timestamp": "1783285601",
                    "text": {
                      "body": "reiniciar"
                    },
                    "type": "text"
                  }
                ]
              },
              "field": "messages"
            }
          ]
        }
      ]
    }
    ```

---

### 3. Health Check
* **Ruta:** `GET /`
* **Descripción:** Endpoint simple para verificar que el servicio FastAPI y la base de datos están activos (usado para monitoreo en Render).
* **Respuesta:**
  ```json
  {
    "status": "ok",
    "service": "whatsapp-fraud-orchestrator"
  }
  ```
