import sqlite3
import discord
from discord.ext import commands
import logging 
from dotenv import load_dotenv
import os
import random
from random import randint
import webserver

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, owner_id=264667357631348749)


MY_GUILD_ID = discord.Object(id=1446818667655594006) 

# Base de données
def get_db_connection():
    conn = sqlite3.connect('frieren_jdr.db')
    conn.row_factory = sqlite3.Row
    return conn

#démaragge 
@bot.event
async def on_ready():
    print(f'Connecté en tant que {bot.user.name} - {bot.user.id}')
    print('------')
    
    try:
        bot.tree.copy_global_to(guild=MY_GUILD_ID)
        synced = await bot.tree.sync(guild=MY_GUILD_ID)
        print(f"{len(synced)} commandes synchronisées sur le serveur de test !")
    except Exception as e:
        print(f"Erreur de sync : {e}")

# --- COMMANDES ---

#lancer de un ou plusieurs dès 
@bot.tree.command(name="roll", description="Lance des dés (format: 3d5, 1d20, d100)")
async def roll(interaction: discord.Interaction, formule: str):
    formule = formule.lower().replace(" ", "")
    try:
        if "d" not in formule:
            raise ValueError("Pas de 'd' trouvé")   
        parts = formule.split("d")
        if parts[0] == "":
            nombre_de_des = 1
        else:
            nombre_de_des = int(parts[0])    
        faces = int(parts[1])
    except ValueError:
        await interaction.response.send_message("❌ Format invalide ! Utilise le format **XdY** (ex: `3d5`, `1d20`).", ephemeral=True)
        return
    if faces < 2:
        await interaction.response.send_message("❌ Un dé doit avoir au moins 2 faces.", ephemeral=True)
        return
    if nombre_de_des < 1:
        await interaction.response.send_message("❌ Il faut au moins 1 dé.", ephemeral=True)
        return
    if nombre_de_des > 100:
        await interaction.response.send_message("❌ Max 100 dés à la fois.", ephemeral=True)
        return
    resultats = [random.randint(1, faces) for _ in range(nombre_de_des)]
    total = sum(resultats)
    details = ", ".join(map(str, resultats))
    if len(details) > 1900:
        details = "Trop de résultats..."
    message = f"🎲 **{formule}**➡️ [{details}] **Total : {total}**"
    await interaction.response.send_message(message)


# --- COMMANDES stop ---
@bot.command(name='stop')
@commands.is_owner() 
async def stop(ctx):
    await ctx.send("🛑 Arrêt du système...")
    print("Fermeture demandée.")
    await bot.close() 

# --- LANCEMENT ---
if __name__ == "__main__":
    webserver.keep_alive()
    if token:
        bot.run(token, log_handler=handler, log_level=logging.DEBUG)
    else:
        print("Erreur : Token introuvable.")

