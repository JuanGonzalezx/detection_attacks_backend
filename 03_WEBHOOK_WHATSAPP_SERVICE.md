# Meta-Prompt 3 — Webhook handler + WhatsApp service

> **Pre-requisito:** tener acceso de lectura a `Agent_T_T/app/services/whatsapp_service.py` y `Agent_T_T/app/controllers/webhook_controller.py`.

```text
Crea los dos archivos que manejan la integración con WhatsApp Cloud API. Estos son COPIAS del proyecto anterior Agent_T_T, ya validados en producción. Copia el código tal cual y solo cambia los textos de logs específicos de TT.

1) `app/services/whatsapp_service.py` — clase `WhatsAppService` con:
   - `__init__`: lee `ACCESS_TOKEN`, `PHONE_NUMBER_ID`, `VERSION` (default `v22.0`) del entorno. Construye `base_url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"`.
   - `validate_credentials() -> (bool, str)`: valida que ACCESS_TOKEN y PHONE_NUMBER_ID estén configurados.
   - `_build_text_message_payload(recipient, text)`: arma JSON `{messaging_product, recipient_type, to, type:"text", text:{preview_url:false, body}}`.
   - `_build_template_message_payload(...)`: arma JSON para templates HSM con components (header opcional + body).
   - `_normalize_phone_number(phone)`: strip + replace de `+`, espacios y guiones.
   - `send_text_message(phone, message) -> (bool, message_id_o_error)`: POST a Graph API con Bearer token, timeout 30s, manejo de Timeout/ConnectionError/Exception. Retorna `(True, message_id)` o `(False, error_msg)`.
   - `send_template_message(...)`: similar pero para plantillas.

   Patrón completo de referencia: `Agent_T_T/app/services/whatsapp_service.py` (326 líneas). Cópialo íntegro.

2) `app/controllers/webhook_controller.py` — Blueprint `webhook_bp` con:
   - Ruta `/webhook` GET (verificación de Meta): lee `hub.mode`, `hub.verify_token`, `hub.challenge` de query params. Si `mode == 'subscribe'` y token == env `VERIFY_TOKEN`, retorna challenge con 200. Si no, 403.
   - Ruta `/webhook` POST (mensajes entrantes):
     - Extrae `body.entry[0].changes[0].value`.
     - Ignora si tiene `statuses` (sent/delivered/read) → retorna 200.
     - Extrae `messages[0]`, valida `id` y `from`.
     - Filtra mensajes de >300s de antigüedad (Meta reintenta los viejos).
     - Llama `get_deduplicator().check_and_mark(msg_id)` — si duplicado, retorna 200 sin procesar.
     - Soporta tipos: `text`, `interactive.button_reply.title`, `interactive.list_reply.title`, `button.text`.
     - Dispara `threading.Thread` con `process_message_background(from_number, text_body, msg_id)` daemon=True.
     - SIEMPRE retorna 200 a Meta (incluso en error) para que no reintente.
   - Función `process_message_background(from_number, text_body, message_id)`:
     - Importa `HumanMessage` de langchain, llama `get_agent()` (de `app.agent.graph`), invoca `agent.invoke({"messages":[HumanMessage(content=text_body)], "phone": from_number})`.
     - Extrae `result['messages'][-1].content` y lo envía con `whatsapp_service.send_text_message(from_number, bot_response)`.
     - Try/except completo, log de errores.

   Patrón completo de referencia: `Agent_T_T/app/controllers/webhook_controller.py` (131 líneas). Cópialo íntegro.

NO cambies la lógica. NO añadas features. Solo cópialos. Cuando termines, reporta líneas creadas en cada archivo.
```
