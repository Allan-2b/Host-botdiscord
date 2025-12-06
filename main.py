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

# Commande test
@bot.tree.command(name="multiplication", description="Multiplie deux nombres")
async def multiplication(interaction: discord.Interaction, a: int, b: int):
    await interaction.response.send_message(f"Résultat : {a} x {b} = {a * b}")

#lancer de un ou plusieurs dès 
@bot.tree.command(name="roll", description="Lance x dés à n faces")
async def roll(interaction: discord.Interaction, faces: int, nombre_de_des: int = 1):
    resultats = [random.randint(1, faces) for _ in range(nombre_de_des)]
    total = sum(resultats)
    details = ", ".join(map(str, resultats))
    message = (f"🎲 **{nombre_de_des}d{faces}**➡️[{details}] **Total : {total}**")
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

