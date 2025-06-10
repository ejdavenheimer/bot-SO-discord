import discord
from openai import OpenAI
import json
import os
import re
from threading import Thread
from flask import Flask
import requests
import time

# Configuración de Flask para keep-alive
app = Flask(__name__)

@app.route("/")
def healthcheck():
    return {"status": "Bot activo", "message": "Discord bot está funcionando"}, 200

@app.route("/health")
def health():
    return "OK", 200

def run_web_server():
    """Ejecuta el servidor Flask en segundo plano"""
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

def keep_alive():
    """Función para mantener viva la aplicación haciendo requests periódicos"""
    def ping_self():
        while True:
            try:
                time.sleep(600)  # Esperar 10 minutos
                # Obtener la URL de diferentes formas posibles
                url = (os.environ.get("RENDER_EXTERNAL_URL") or 
                       os.environ.get("RENDER_SERVICE_URL") or 
                       f"http://localhost:{os.environ.get('PORT', 8080)}")
                
                # Hacer request a sí mismo para mantener activo
                response = requests.get(f"{url}/health", timeout=10)
                print(f"✅ Keep-alive ping enviado - Status: {response.status_code}")
            except Exception as e:
                print(f"⚠️ Error en keep-alive ping: {e}")
                # Continuar intentando aunque falle
    
    Thread(target=ping_self, daemon=True).start()

# Configuración de intents
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Configuración de Groq (API gratuita compatible con OpenAI)
groq_client = OpenAI(api_key=os.getenv("GROQ_API_KEY"),
                     base_url="https://api.groq.com/openai/v1")

# Variables globales
preguntas = []
indice_actual = 0
respuestas_usuarios = {}
puntajes = {}

# Token de Discord
TOKEN_DISCORD = os.getenv("DISCORD_BOT_TOKEN")


def cargar_preguntas():
    """Carga las preguntas desde el archivo JSON"""
    global preguntas
    try:
        with open("preguntas.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            preguntas = data["preguntas"]
        print(f"✅ Cargadas {len(preguntas)} preguntas")
    except FileNotFoundError:
        print("❌ Error: No se encontró el archivo preguntas.json")
        preguntas = []
    except json.JSONDecodeError:
        print("❌ Error: El archivo preguntas.json tiene formato inválido")
        preguntas = []


def validar_respuesta_minima(respuesta):
    """Valida que la respuesta tenga contenido mínimo relevante y no sea absurda"""
    # Eliminar espacios y caracteres especiales
    respuesta_limpia = re.sub(r'[^\w\s]', '', respuesta.lower().strip())

    # Lista ampliada de respuestas inválidas/absurdas
    respuestas_invalidas = [
        '', 'no', 'si', 'nose', 'no se', 'nada', 'nose que', 'no sé',
        'caranada', 'cualquier cosa', 'no idea', 'ni idea', 'asdasd', 'qwerty',
        'test', 'prueba', 'hola', 'chau', 'xd', 'jaja', 'jeje', 'jacaranda',
        'banana', 'pizza', 'futbol', 'perro', 'gato', 'auto', 'casa', 'mesa',
        'silla', 'agua', 'fuego', 'tierra', 'aire', 'lorem ipsum', 'blablabla',
        'lalala', 'nanana', 'jejeje', 'jajaja', 'aaaaaa', 'bbbbbb', 'cccccc',
        'dddddd', 'eeeeee', 'ffffff', 'abcdef', 'qwerty', 'asdfgh', 'zxcvbn',
        'mnbvcx', 'poiuyt', 'random', 'aleatorio', 'whatever', 'meh', 'ok',
        'vale', 'bueno', 'malo', 'regular', 'normal', 'raro', 'extraño',
        'loco', 'genial', 'excelente', 'terrible', 'horrible', 'perfecto',
        'imperfecto'
    ]

    # Verificar si la respuesta es muy corta (menos de 15 caracteres para ser más estricto)
    if len(respuesta_limpia) < 15:
        return False

    # Verificar si está en la lista de respuestas inválidas
    if respuesta_limpia in respuestas_invalidas:
        return False

    # Verificar si contiene alguna palabra absurda de la lista
    palabras_respuesta = respuesta_limpia.split()
    for palabra in palabras_respuesta:
        if palabra in respuestas_invalidas:
            return False

    # Verificar si tiene solo caracteres repetidos o sin sentido
    if len(set(respuesta_limpia.replace(
            ' ', ''))) < 4:  # Aumentado a 4 caracteres únicos mínimo
        return False

    # Verificar si es solo números sin contexto
    if respuesta_limpia.isdigit():
        return False

    # Verificar si contiene solo vocales o consonantes repetidas
    vocales = 'aeiou'
    consonantes = 'bcdfghjklmnpqrstvwxyz'

    solo_vocales = all(c in vocales or c == ' ' for c in respuesta_limpia)
    solo_consonantes = all(c in consonantes or c == ' '
                           for c in respuesta_limpia)

    if solo_vocales or solo_consonantes:
        return False

    # Verificar si es una secuencia de teclado común
    secuencias_teclado = [
        'qwertyuiop', 'asdfghjkl', 'zxcvbnm', 'qazwsxedc', 'rfvtgbyhn',
        'ujmyhnbgt', 'plokijnuhb', 'mnbvcxz', '1234567890', '0987654321'
    ]

    for secuencia in secuencias_teclado:
        if secuencia in respuesta_limpia.replace(' ', ''):
            return False

    return True


def dividir_mensaje(texto, limite=1800):
    """Divide un mensaje largo en partes más pequeñas manteniendo la estructura"""
    if len(texto) <= limite:
        return [texto]

    partes = []
    while len(texto) > limite:
        # Buscar el mejor punto de corte
        punto_corte = texto.rfind('\n\n', 0, limite)  # Párrafos
        if punto_corte == -1:
            punto_corte = texto.rfind('\n', 0, limite)  # Líneas
        if punto_corte == -1:
            punto_corte = texto.rfind('. ', 0, limite)  # Oraciones
        if punto_corte == -1:
            punto_corte = texto.rfind(' ', 0, limite)  # Palabras
        if punto_corte == -1:
            punto_corte = limite  # Corte forzado

        partes.append(texto[:punto_corte])
        texto = texto[punto_corte:].lstrip()

    if texto:
        partes.append(texto)

    return partes


async def enviar_mensaje_largo(channel, mensaje):
    """Envía un mensaje largo dividiéndolo si es necesario"""
    partes = dividir_mensaje(mensaje)
    for i, parte in enumerate(partes):
        if i > 0:
            # Añadir indicador de continuación más sutil
            parte = f"📄 *(cont.)*\n{parte}"
        await channel.send(parte)


@client.event
async def on_ready():
    print(f'✅ Bot conectado como {client.user}')
    print(f'🌐 Servidor web activo en puerto {os.environ.get("PORT", 8080)}')
    cargar_preguntas()


@client.event
async def on_message(message):
    global indice_actual

    # Ignorar mensajes del propio bot
    if message.author == client.user:
        return

    contenido = message.content.lower()

    # Comando para mostrar pregunta actual (solo para la primera pregunta)
    if contenido.startswith("!p"):
        if not preguntas:
            await message.channel.send(
                "❌ No hay preguntas cargadas. Verifica el archivo preguntas.json"
            )
            return

        if indice_actual > 0:
            await message.channel.send(
                "❌ Usa `!siguiente` para avanzar entre preguntas. `!p` solo funciona para la primera pregunta."
            )
            return

        if indice_actual >= len(preguntas):
            await message.channel.send(
                "🎉 ¡No hay más preguntas! Has completado todas.")
            return

        pregunta_actual = preguntas[indice_actual]["pregunta"]
        await message.channel.send(
            f"📢 **Pregunta {indice_actual + 1}/{len(preguntas)}:**\n{pregunta_actual}"
        )

    # Comando para responder (cambio de !responder a !r)
    elif contenido.startswith("!r "):
        if not preguntas:
            await message.channel.send("❌ No hay preguntas cargadas.")
            return

        if indice_actual >= len(preguntas):
            await message.channel.send(
                "❌ No hay pregunta activa. Usa `!p` primero.")
            return

        # Extraer la respuesta del usuario
        respuesta_usuario = message.content[len("!r "):].strip()

        if not respuesta_usuario:
            await message.channel.send(
                "❌ Debes proporcionar una respuesta. Ejemplo: `!r Tu respuesta aquí`"
            )
            return

        respuesta_oficial = preguntas[indice_actual]["respuesta"]

        # VALIDACIÓN MEJORADA: Verificar que la respuesta no sea absurda
        if not validar_respuesta_minima(respuesta_usuario):
            # SIEMPRE mostrar la respuesta correcta, incluso para respuestas inválidas
            mensaje_rechazo = f"❌ **{message.author.mention}** **(+0)** La respuesta '{respuesta_usuario}' no es válida (muy corta, sin sentido o absurda).\n\n**💡 Respuesta correcta:** {respuesta_oficial}"
            await enviar_mensaje_largo(message.channel, mensaje_rechazo)
            return

        # Prompt MEJORADO para evaluación más estricta
        prompt = f"""Eres un profesor estricto de Sistemas Operativos que evalúa según el libro de Stallings.

PREGUNTA: {preguntas[indice_actual]["pregunta"]}
RESPUESTA ESTUDIANTE: {respuesta_usuario}
RESPUESTA CORRECTA: {respuesta_oficial}

INSTRUCCIONES ESTRICTAS:
1. Compara DIRECTAMENTE la respuesta del estudiante con la respuesta correcta
2. Una respuesta es CORRECTA solo si:
   - Menciona los conceptos técnicos específicos de la respuesta correcta
   - Explica correctamente el mecanismo o proceso
   - Usa terminología precisa de Sistemas Operativos
3. Una respuesta es PARCIAL solo si:
   - Menciona algunos conceptos correctos pero incompletos
   - La dirección es correcta pero faltan detalles importantes
4. Una respuesta es INCORRECTA si:
   - No menciona los conceptos clave de la respuesta correcta
   - Contiene información técnicamente incorrecta
   - Es demasiado vaga o genérica
   - No demuestra comprensión del tema específico
   - Parece absurda o sin relación al tema

FORMATO OBLIGATORIO:
- Empezar con: CORRECTA / PARCIAL / INCORRECTA
- Explicar brevemente por qué (máximo 50 palabras)
- SIEMPRE terminar con: "Respuesta correcta: [respuesta completa]"

SÉ ESTRICTO. No des puntos por respuestas vagas, incorrectas o absurdas."""

        try:
            # Usando Groq con límite de tokens ajustado para respuestas más estrictas
            completion = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{
                    "role": "user",
                    "content": prompt
                }],
                max_tokens=300,
                temperature=0.0  # Temperatura 0 para máxima consistencia
            )

            resultado = completion.choices[0].message.content

            # Asegurar que siempre se incluya la respuesta correcta
            if "Respuesta correcta:" not in resultado:
                resultado += f"\n\n**💡 Respuesta correcta:** {respuesta_oficial}"

            # Actualizar puntajes basado en la evaluación
            if message.author.name not in puntajes:
                puntajes[message.author.name] = 0

            puntos_ganados = 0
            if resultado.upper().startswith("CORRECTA"):
                puntos_ganados = 2
                puntajes[message.author.name] += puntos_ganados
                emoji = "✅"
            elif resultado.upper().startswith("PARCIAL"):
                puntos_ganados = 1
                puntajes[message.author.name] += puntos_ganados
                emoji = "⚠️"
            else:  # INCORRECTA
                puntos_ganados = 0
                emoji = "❌"

            # Crear mensaje de respuesta más compacto
            puntos_texto = f" **(+{puntos_ganados})**" if puntos_ganados > 0 else " **(+0)**"
            mensaje_completo = f"{emoji} **{message.author.mention}**{puntos_texto}\n{resultado}"

            # Enviar mensaje (dividiéndolo si es necesario)
            await enviar_mensaje_largo(message.channel, mensaje_completo)

        except Exception as e:
            # En caso de error, al menos mostrar la respuesta correcta
            await message.channel.send(
                f"❌ Error al procesar la respuesta: {str(e)}\n\n**💡 Respuesta correcta:** {respuesta_oficial}"
            )

    # Comando para avanzar a la siguiente pregunta (solo admin/moderador)
    elif contenido.startswith("!siguiente"):
        if not message.author.guild_permissions.manage_messages:
            await message.channel.send(
                "❌ Solo moderadores pueden avanzar preguntas.")
            return

        indice_actual += 1
        if indice_actual >= len(preguntas):
            await message.channel.send(
                "🎉 ¡Cuestionario completado! Usa `!tantos` para ver resultados finales."
            )
        else:
            pregunta_actual = preguntas[indice_actual]["pregunta"]
            await message.channel.send(
                f"⏭️ **Pregunta {indice_actual + 1}/{len(preguntas)}:**\n{pregunta_actual}"
            )

    # Comando para ver puntajes
    elif contenido.startswith("!tantos"):
        if not puntajes:
            await message.channel.send("📊 No hay puntajes registrados aún.")
            return

        msg = "**🏆 Puntajes actuales:**\n"
        # Ordenar por puntaje descendente
        puntajes_ordenados = sorted(puntajes.items(),
                                    key=lambda x: x[1],
                                    reverse=True)

        for i, (user, score) in enumerate(puntajes_ordenados, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "📊"
            msg += f"{emoji} {user}: {score} puntos\n"

        await message.channel.send(msg)

    # Comando para reiniciar (solo admin/moderador)
    elif contenido.startswith("!reiniciar"):
        if not message.author.guild_permissions.manage_messages:
            await message.channel.send(
                "❌ Solo moderadores pueden reiniciar el cuestionario.")
            return

        indice_actual = 0
        puntajes.clear()
        await message.channel.send(
            "🔄 ¡Cuestionario reiniciado! Usa `!p` para empezar.")

    # Comando de ayuda
    elif contenido.startswith("!ayuda"):
        ayuda = """**💻 Comandos disponibles:**

**Para todos:**
`!p` - Muestra la primera pregunta (solo funciona al inicio)
`!r [tu respuesta]` - Responde a la pregunta actual
`!tantos` - Muestra los puntajes de todos los participantes
`!ayuda` - Muestra este mensaje de ayuda

**Para moderadores:**
`!siguiente` - Avanza a la siguiente pregunta (la muestra automáticamente)
`!reiniciar` - Reinicia el cuestionario desde el principio

**Sistema de puntos:**
✅ Correcta: +2 puntos
⚠️ Parcial: +1 punto
❌ Incorrecta: 0 puntos

**NOTA IMPORTANTE:**
- Las respuestas muy cortas, sin sentido o absurdas serán rechazadas automáticamente
- Se detectan respuestas como "jacaranda", "pizza", "qwerty", etc.
- La evaluación es estricta y requiere conceptos técnicos específicos
- Se compara directamente con la respuesta de cátedra
- SIEMPRE se muestra la respuesta correcta, incluso para respuestas inválidas

**Características del bot:**
- Evaluaciones estrictas basadas en Stallings
- Filtro avanzado contra respuestas absurdas y sin contenido
- Siempre muestra la respuesta de cátedra
- Feedback educativo preciso

**Modo de juego:**
1. El moderador usa `!p` para mostrar la primera pregunta
2. Varios usuarios pueden responder con `!r [respuesta]`
3. La IA evalúa de forma estricta y muestra la respuesta correcta
4. El moderador usa `!siguiente` para avanzar (muestra la pregunta automáticamente)"""

        await enviar_mensaje_largo(message.channel, ayuda)


# Función principal para iniciar todo
def main():
    """Función principal que inicia el servidor web y el bot de Discord"""
    # Iniciar servidor web en segundo plano
    web_thread = Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # Iniciar keep-alive
    keep_alive()
    
    print("🚀 Iniciando bot de Discord...")
    print("🌐 Servidor web iniciado para keep-alive")
    
    # Ejecutar el bot de Discord
    if not TOKEN_DISCORD:
        print("❌ Error: DISCORD_BOT_TOKEN no está configurado")
    elif not os.getenv("GROQ_API_KEY"):
        print("❌ Error: GROQ_API_KEY no está configurado")
    else:
        try:
            client.run(TOKEN_DISCORD)
        except discord.LoginFailure:
            print("❌ Error: Token de Discord inválido")
        except Exception as e:
            print(f"❌ Error al iniciar el bot: {e}")


# Ejecutar el bot
if __name__ == "__main__":
    main()