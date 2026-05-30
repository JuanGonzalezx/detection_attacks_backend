# Meta-Prompt 2 — Configuración Meta Business + WhatsApp Cloud API (manual)

> Pega el bloque siguiente en la sesión de Claude para que genere la guía de setup de Meta.

```text
Necesito configurar de cero una cuenta de Meta Business + WhatsApp Cloud API para mi nuevo proyecto `agent-uentupueblo`. Voy a usar una SIM física nueva con un número dedicado. Genera un documento `docs/META_SETUP.md` con el paso a paso completo, explicación de qué se obtiene en cada paso, qué variables de entorno se llenan, y troubleshooting de los errores más comunes.

Cubre estos 9 pasos en orden:

1. **Liberar SIM de WhatsApp normal**: el número NO puede tener WhatsApp personal activo. Si lo tiene, eliminar cuenta desde WhatsApp → Ajustes → Cuenta → Eliminar mi cuenta. Esperar 24-72h antes de usar en Business.

2. **Crear Business Portfolio en Meta**: ir a `business.facebook.com` → Settings → Business Portfolios → Create. Nombre: "Neo Astrum". Asociar el email institucional o personal del owner.

3. **Crear App en Meta for Developers**: ir a `developers.facebook.com/apps` → Create App → tipo "Business" → asociar al Business Portfolio creado. Nombre: "Agent UenTuPueblo".

4. **Añadir producto WhatsApp**: dentro de la app → Add Products → WhatsApp → Set Up. Esto crea automáticamente un WABA (WhatsApp Business Account) de pruebas con un número de test.

5. **Añadir número real**: WhatsApp → API Setup → "Add phone number". Verificar el número vía SMS o llamada. Configurar Display Name (ej. "U en tu Pueblo - UdeCaldas"). Meta revisa el Display Name (24-72h).

6. **Configurar Webhook**:
   - Callback URL: `https://<tu-render-url>.onrender.com/webhook`
   - Verify Token: el string que pongas en `.env` como `VERIFY_TOKEN` (cualquier secreto, ej. `uep_meta_2026_xyz`)
   - Subscribir campos: `messages`, `message_status`

7. **Generar Permanent Access Token**:
   - Ir a Business Settings → System Users → Add. Tipo: Admin.
   - Asignar permisos: `whatsapp_business_messaging`, `whatsapp_business_management`.
   - Generate New Token → seleccionar la app → never expires → copiar token.

8. **Capturar IDs requeridos**:
   - `PHONE_NUMBER_ID`: WhatsApp → API Setup → "From Phone Number ID" (NO es el número visible, es un ID numérico).
   - `WHATSAPP_BUSINESS_ACCOUNT_ID`: Business Settings → Accounts → WhatsApp Accounts → ID.
   - `APP_SECRET`: App Settings → Basic → App Secret (Show).
   - `ACCESS_TOKEN`: el permanent token del paso 7.

9. **Validación**: usar `curl` para enviar un mensaje de prueba:
   curl -X POST "https://graph.facebook.com/v22.0/<PHONE_NUMBER_ID>/messages" \
        -H "Authorization: Bearer <ACCESS_TOKEN>" \
        -H "Content-Type: application/json" \
        -d '{"messaging_product":"whatsapp","to":"<mi_propio_numero_E164>","type":"text","text":{"body":"Hola desde Cloud API"}}'

Incluye sección de troubleshooting con estos errores:
- "Recipient phone number not in allowed list" → en modo dev, añadir números a la lista permitida.
- "Phone number is not registered" → falta el paso de Register en API Setup (POST /register).
- "Display Name rejected" → razones típicas y cómo apelar.
- Webhook handshake falla → verify token no coincide entre Meta y `.env`.

NO escribas código Python en este prompt. Solo el documento Markdown.
```
