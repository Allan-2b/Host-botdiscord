import sqlite3
import discord
from discord.ext import commands
from discord import app_commands  
import logging 
from dotenv import load_dotenv
import os
import random
import json 
import webserver 

# --- CONFIGURATION INITIALE ---
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, owner_id=264667357631348749)

MY_GUILD_ID = discord.Object(id=1446818667655594006) 

# --- STOCKAGE TEMPORAIRE DES DUELS (Mémoire vive) ---
# Format : { id_defenseur : { 'attaquant_id': int, 'skill_a': Skill, 'sursaut_a': bool, 'desc_a': str, 'p_attaquant': Personnage } }
PENDING_CLASHES = {}

# --- BASE DE DONNÉES (SQLITE) ---
def get_db_connection():
    conn = sqlite3.connect('frieren_jdr.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER PRIMARY KEY,
            nom_perso_actif TEXT
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS joueurs (
            user_id INTEGER,
            nom TEXT, 
            classe TEXT, niveau INTEGER,
            pv_actuel INTEGER, pv_max INTEGER,
            mana INTEGER, mana_max INTEGER,
            tension INTEGER, ferveur INTEGER, versets INTEGER,
            stabilite INTEGER DEFAULT 0,
            sursaut_dispo INTEGER DEFAULT 1,
            phy INTEGER, const INTEGER, agi INTEGER,
            esp INTEGER, int_stat INTEGER, foi INTEGER, sag INTEGER,
            points_stat INTEGER DEFAULT 0,
            points_comp INTEGER DEFAULT 0,
            points_attribut INTEGER DEFAULT 0,
            competences TEXT DEFAULT '[]',
            oral INTEGER DEFAULT 0,
            force_rp INTEGER DEFAULT 0,
            survie INTEGER DEFAULT 0,
            histoire INTEGER DEFAULT 0,
            sciences INTEGER DEFAULT 0,
            medecine INTEGER DEFAULT 0,
            religion INTEGER DEFAULT 0,
            discretion INTEGER DEFAULT 0,
            -- NOUVEAUX CHAMPS --
            alias TEXT DEFAULT NULL,
            description TEXT DEFAULT 'Aucune description.',
            image_url TEXT DEFAULT NULL,
            PRIMARY KEY (user_id, nom)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- BIBLIOTHÈQUE DE SORTS (Mise à jour) ---
SKILLS_DB = {
    # --- MAGE ---
    "zoltraak": {
        "nom": "Zoltraak",
        "classes": ["mage"], "pallier": 1, "cout_achat": 1,
        "base": 4, "coins": 3, "bonus": 3, "stat_type": "esp",
        "cout": 3, "cout_type": "mana", "desc": "Rayon de magie noire standard.",
        "type": "actif",       # <--- NOUVEAU : actif ou passif
        "cat": "tronc"         # <--- NOUVEAU : tronc ou spe
    },
    "aiguille": {
        "nom": "Aiguille Magique",
        "classes": ["mage"], "pallier": 2, "cout_achat": 1,
        "base": 2, "coins": 4, "bonus": 2, "stat_type": "esp",
        "cout": 6, "cout_type": "mana", "desc": "Projectile rapide.",
        "type": "actif",
        "cat": "tronc"
    },
    # Exemple d'un Passif
    "regeneration": {
        "nom": "Aura de Mana",
        "classes": ["mage"], "pallier": 1, "cout_achat": 2,
        "base": 0, "coins": 0, "bonus": 0, "stat_type": "int_stat",
        "cout": 0, "cout_type": "mana", "desc": "Récupère 1 Mana par tour.",
        "type": "passif",      # C'est un passif
        "cat": "tronc"
    },
    # Exemple d'une compétence de Sous-classe (Spécialisation)
    "necromancie": {
        "nom": "Réanimation",
        "classes": ["mage"], "pallier": 3, "cout_achat": 3,
        "base": 0, "coins": 0, "bonus": 0, "stat_type": "esp",
        "cout": 20, "cout_type": "mana", "desc": "Relève un squelette.",
        "type": "actif",
        "cat": "spe"           # C'est une spé
    },

    # --- GUERRIER ---
    "frappe": {
        "nom": "Frappe Lourde",
        "classes": ["guerrier"], "pallier": 1, "cout_achat": 1,
        "base": 5, "coins": 2, "bonus": 4, "stat_type": "phy",
        "cout": 0, "cout_type": "tension", "desc": "Coup d'épée basique.",
        "type": "actif",
        "cat": "tronc"
    },
    "posture_fer": {
        "nom": "Posture de Fer",
        "classes": ["guerrier"], "pallier": 2, "cout_achat": 2,
        "base": 0, "coins": 0, "bonus": 0, "stat_type": "const",
        "cout": 0, "cout_type": "tension", "desc": "Réduit les dégâts de 2.",
        "type": "passif",
        "cat": "tronc"
    },

    # --- PRÊTRE ---
    "lumiere_divine": {
        "nom": "Lumière Divine",
        "classes": ["pretre"], "pallier": 1, "cout_achat": 1,
        "base": 3, "coins": 3, "bonus": 3, "stat_type": "foi",
        "cout": 10, "cout_type": "ferveur", "desc": "Rayon sacré.",
        "type": "actif",
        "cat": "tronc"
    }
}

















def get_points_investis_pallier(personnage, pallier_vise):
    """Calcule le nombre de points dépensés dans les sorts du pallier demandé."""
    total_points = 0
    for skill_key in personnage.competences:
        if skill_key in SKILLS_DB:
            data = SKILLS_DB[skill_key]
            # Si le sort appartient au pallier visé, on ajoute son coût
            if data['pallier'] == pallier_vise:
                total_points += data.get('cout_achat', 1)
    return total_points


# --- CLASSE SKILL (MOTEUR DE JEU) ---
class Skill:
    def __init__(self, nom, base, coin_bonus, coin_count, stat_bonus=0, stat_nom="Stat"):
        self.nom = nom
        self.base = base
        self.bonus = coin_bonus
        self.coins = coin_count
        self.stat_bonus = stat_bonus
        self.stat_nom = stat_nom 

    def roll(self, stabilite, est_inverse=False):
        """
        Lance les pièces en prenant en compte la stabilité et le sursaut.
        """
        chance = 50 + stabilite
        if chance > 95: chance = 95
        if chance < 5: chance = 5
        
        heads = 0
        details = []
        
        for _ in range(self.coins):
            jet = random.randint(1, 100)
            reussite = False
            

            if not est_inverse:
                if jet <= chance:
                    reussite = True
                    details.append("🟡") 
                else:
                    details.append("⚪") 
            
    
            else:
                if jet > chance: 
                    reussite = True
                    details.append("🧿") 
                else:
                    details.append("❌") 
            
            if reussite:
                heads += 1
        
        total = self.base + (self.bonus * heads) + self.stat_bonus
        return total, details, heads

# --- CLASSE PERSONNAGE (GESTION FICHE) ---
class Personnage:
    def __init__(self, user_id, nom, classe_nom, charger_db=False):
        self.user_id = user_id
        self.nom = nom
        self.classe = classe_nom.lower()
        self.competences = []
        
        # Initialisation des nouveaux champs par défaut
        self.alias = None
        self.description = "Aucune description."
        self.image_url = None

        if not charger_db:
            # ... (Le reste de l'init des stats reste identique) ...
            self.init_stats_depart()
            self.recalculer_derives() 
            # ...
            self.sauvegarder()

    def init_stats_depart(self):
        if self.classe == "guerrier":
            self.phy = 4; self.const = 3; self.agi = 1
            self.esp = 0; self.int_stat = 0; self.foi = 0; self.sag = 0
        elif self.classe == "mage":
            self.esp = 4; self.int_stat = 4; self.agi = 3
            self.phy = 0; self.const = 0; self.foi = 0; self.sag = 0
        elif self.classe == "pretre":
            self.foi = 4; self.sag = 3; self.agi = 2
            self.phy = 0; self.const = 0; self.esp = 0; self.int_stat = 0

    def recalculer_derives(self):
        self.mana_max = 0
        self.versets_max = 0
        if self.classe == "guerrier":
            self.pv_max = 55 + ((self.niveau - 1) * 8)
            
        elif self.classe == "mage":
            self.pv_max = 35 + ((self.niveau - 1) * 4)
            self.mana_max = (self.int_stat * 8) + 10 
            
        elif self.classe == "pretre":
            self.pv_max = 45 + ((self.niveau - 1) * 6)
            self.versets_max = self.sag 

    def sauvegarder(self):
        conn = get_db_connection()
        skills_json = json.dumps(self.competences)
        # Attention : On ajoute les 3 nouveaux champs à la fin de la requête SQL
        conn.execute('''
            INSERT OR REPLACE INTO joueurs VALUES 
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (self.user_id, self.nom, self.classe, self.niveau,
              self.pv_actuel, self.pv_max, self.mana, self.mana_max,
              self.tension, self.ferveur, self.versets, 
              self.stabilite, self.sursaut_dispo,
              self.phy, self.const, self.agi,
              self.esp, self.int_stat, self.foi, self.sag,
              self.points_stat, self.points_comp, self.points_attribut, skills_json,
              self.oral, self.force_rp, self.survie, self.histoire, 
              self.sciences, self.medecine, self.religion, self.discretion,
              # Nouveaux champs
              self.alias, self.description, self.image_url))
        conn.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (self.user_id, self.nom))
        conn.commit()
        conn.close()

    @staticmethod
    def charger(user_id):
        conn = get_db_connection()
        session = conn.execute('SELECT nom_perso_actif FROM sessions WHERE user_id = ?', (user_id,)).fetchone()    
        if not session:
            row = conn.execute('SELECT * FROM joueurs WHERE user_id = ? LIMIT 1', (user_id,)).fetchone()
        else:
            nom_actif = session['nom_perso_actif']
            row = conn.execute('SELECT * FROM joueurs WHERE user_id = ? AND nom = ?', (user_id, nom_actif)).fetchone()
        conn.close()
        if not row: return None 
        
        p = Personnage(user_id, row['nom'], row['classe'], charger_db=True)
        # On charge toutes les colonnes dynamiquement
        for col in row.keys():
            if col != 'competences': 
                setattr(p, col, row[col])
        try: p.competences = json.loads(row['competences'])
        except: p.competences = []
        return p


























# --- EVENTS ---
@bot.event
async def on_ready():
    print(f'Connecté en tant que {bot.user.name}')
    try:
        bot.tree.copy_global_to(guild=MY_GUILD_ID)
        await bot.tree.sync(guild=MY_GUILD_ID)
        print("✅ Commandes synchronisées !")
    except Exception as e:
        print(f"❌ Erreur sync: {e}")


# --- AUTOCOMPLETION ---
async def sort_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    
    # 1. On charge le personnage complet pour avoir ses compétences
    p = Personnage.charger(user_id)
    if not p:
        return []

    sorts_disponibles = []
    
    # 2. On ne parcourt que les compétences qu'il possède
    for skill_key in p.competences:
        if skill_key in SKILLS_DB:
            val = SKILLS_DB[skill_key]
            
            # Filtre de recherche textuelle (ce que le joueur tape)
            if current.lower() in val['nom'].lower():
                sorts_disponibles.append(app_commands.Choice(name=val['nom'], value=skill_key))
    
    return sorts_disponibles[:25]
















# --- COMMANDES DE COMBAT ---

# 1. CLASH 
@bot.tree.command(name="clash", description="Défier une cible (Nécessite une Riposte)")
@app_commands.describe(sort="Votre technique", cible="L'adversaire", description="Action RP", sursaut="Activer le Sursaut ?")
@app_commands.autocomplete(sort=sort_autocomplete)
async def clash(interaction: discord.Interaction, sort: str, cible: discord.Member, description: str, sursaut: bool = False):
    p_attaquant = Personnage.charger(interaction.user.id)
    if not p_attaquant: return await interaction.response.send_message("❌ Pas de fiche perso.", ephemeral=True)

    if p_attaquant.pv_actuel <= 0:
        return await interaction.response.send_message("💀 **Vous êtes K.O.** et ne pouvez pas agir !", ephemeral=True)

    if cible.id == interaction.user.id: return await interaction.response.send_message("❌ Cible invalide.", ephemeral=True)
    if cible.id in PENDING_CLASHES: return await interaction.response.send_message(f"❌ **{cible.display_name}** est déjà défié ! Utilisez `/attaque` pour une frappe unilatérale.", ephemeral=True)
    
    if sort not in SKILLS_DB: return await interaction.response.send_message("❌ Sort introuvable.", ephemeral=True)
    if sort not in p_attaquant.competences:
        return await interaction.response.send_message(f"❌ Vous n'avez pas appris la technique **{SKILLS_DB[sort]['nom']}**.", ephemeral=True)
    skill_data = SKILLS_DB[sort]
    
    # Coût
    cout = skill_data.get("cout", 0)
    cout_type = skill_data.get("cout_type", "mana")
    if cout > 0:
        valeur_actuelle = getattr(p_attaquant, cout_type, 0)
        if valeur_actuelle < cout: return await interaction.response.send_message(f"❌ Pas assez de **{cout_type}**.", ephemeral=True)
        setattr(p_attaquant, cout_type, valeur_actuelle - cout)
        p_attaquant.sauvegarder()

    # Sursaut
    if sursaut:
        if p_attaquant.sursaut_dispo == 1:
            p_attaquant.sursaut_dispo = 0
            p_attaquant.sauvegarder()
        else: return await interaction.response.send_message("❌ Sursaut déjà utilisé.", ephemeral=True)

    stat_nom = skill_data["stat_type"].upper()
    stat_valeur = getattr(p_attaquant, skill_data["stat_type"], 0)
    skill_obj = Skill(skill_data["nom"], skill_data["base"], skill_data["bonus"], skill_data["coins"], stat_bonus=stat_valeur, stat_nom=stat_nom)

    PENDING_CLASHES[cible.id] = {
        'attaquant_id': interaction.user.id,
        'skill_a': skill_obj,
        'sursaut_a': sursaut,
        'desc_a': description,
        'p_attaquant': p_attaquant
    }

    embed = discord.Embed(title="⚔️ CLASH INITIÉ !", description=f"**{p_attaquant.nom}** cible **{cible.display_name}** !\n\n*« {description} »*", color=0xE67E22)
    embed.add_field(name="En attente...", value=f"👉 **{cible.mention}**, répondez avec `/riposte` !", inline=False)
    await interaction.response.send_message(content=f"{cible.mention}", embed=embed)





# 2. RIPOSTE (Réponse)
@bot.tree.command(name="riposte", description="Répondre au défi")
@app_commands.describe(sort="Votre technique", description="Action RP", sursaut="Utiliser le Sursaut ?")
@app_commands.autocomplete(sort=sort_autocomplete)
async def riposte(interaction: discord.Interaction, sort: str, description: str, sursaut: bool = False):
    user_id = interaction.user.id
    if user_id not in PENDING_CLASHES: return await interaction.response.send_message("❌ Personne ne vous a défié.", ephemeral=True)
    
    clash_data = PENDING_CLASHES.pop(user_id)
    p_defenseur = Personnage.charger(user_id)
    p_attaquant = clash_data['p_attaquant']

    if p_defenseur.pv_actuel <= 0:
        return await interaction.response.send_message("💀 **Vous êtes K.O.** et ne pouvez pas agir !", ephemeral=True)
    
    if sort not in SKILLS_DB: return await interaction.response.send_message("❌ Sort introuvable.", ephemeral=True)
    if sort not in p_defenseur.competences:
        return await interaction.response.send_message(f"❌ Vous n'avez pas appris la technique **{SKILLS_DB[sort]['nom']}**.", ephemeral=True)
    skill_data_b = SKILLS_DB[sort]
    
    cout = skill_data_b.get("cout", 0)
    cout_type = skill_data_b.get("cout_type", "mana")
    if cout > 0:
        valeur_actuelle = getattr(p_defenseur, cout_type, 0)
        if valeur_actuelle < cout:
            PENDING_CLASHES[user_id] = clash_data 
            return await interaction.response.send_message(f"❌ Pas assez de **{cout_type}**.", ephemeral=True)
        setattr(p_defenseur, cout_type, valeur_actuelle - cout)

    if sursaut:
        if p_defenseur.sursaut_dispo == 1: p_defenseur.sursaut_dispo = 0
        else: 
            PENDING_CLASHES[user_id] = clash_data
            return await interaction.response.send_message("❌ Sursaut déjà utilisé.", ephemeral=True)

    stat_nom_b = skill_data_b["stat_type"].upper()
    stat_valeur_b = getattr(p_defenseur, skill_data_b["stat_type"], 0)
    skill_obj_b = Skill(skill_data_b["nom"], skill_data_b["base"], skill_data_b["bonus"], skill_data_b["coins"], stat_bonus=stat_valeur_b, stat_nom=stat_nom_b)
    skill_obj_a = clash_data['skill_a']

    # Lancer
    total_a, vis_a, heads_a = skill_obj_a.roll(p_attaquant.stabilite, est_inverse=clash_data['sursaut_a'])
    total_b, vis_b, heads_b = skill_obj_b.roll(p_defenseur.stabilite, est_inverse=sursaut)

    embed = discord.Embed(title="⚔️ RÉSULTAT DU CLASH", color=0x3498db)
    embed.add_field(name=f"🗣️ {p_attaquant.nom}", value=f"*« {clash_data['desc_a']} »*", inline=False)
    embed.add_field(name=f"🗣️ {p_defenseur.nom}", value=f"*« {description} »*", inline=False)
    embed.add_field(name="▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬", value="**IMPACT**", inline=False)

    calcul_a = f"Base {skill_obj_a.base} + ({heads_a}x{skill_obj_a.bonus}) + {skill_obj_a.stat_nom} {skill_obj_a.stat_bonus}"
    desc_a = f"**{skill_obj_a.nom}**\n{' '.join(vis_a)}\n`{calcul_a}`\n# 💥 Total : {total_a}"
    embed.add_field(name=f"👤 {p_attaquant.nom}", value=desc_a, inline=True)
    
    calcul_b = f"Base {skill_obj_b.base} + ({heads_b}x{skill_obj_b.bonus}) + {skill_obj_b.stat_nom} {skill_obj_b.stat_bonus}"
    desc_b = f"**{skill_obj_b.nom}**\n{' '.join(vis_b)}\n`{calcul_b}`\n# 🛡️ Total : {total_b}"
    embed.add_field(name=f"👤 {p_defenseur.nom}", value=desc_b, inline=True)

    if total_a > total_b:
        p_attaquant.stabilite = min(45, p_attaquant.stabilite + 5)
        p_defenseur.stabilite = max(-45, p_defenseur.stabilite - 5)
        if p_attaquant.classe == "guerrier": p_attaquant.tension += 1
        embed.add_field(name=f"🏆 VICTOIRE : {p_attaquant.nom}", value=f"**{p_defenseur.nom}** doit encaisser **{total_a}** dégâts !", inline=False)
        embed.color = 0x2ecc71
    elif total_b > total_a:
        p_defenseur.stabilite = min(45, p_defenseur.stabilite + 5)
        p_attaquant.stabilite = max(-45, p_attaquant.stabilite - 5)
        if p_defenseur.classe == "guerrier": p_defenseur.tension += 1
        embed.add_field(name=f"🏆 VICTOIRE : {p_defenseur.nom}", value=f"**{p_attaquant.nom}** doit encaisser **{total_b}** dégâts !", inline=False)
        embed.color = 0xe74c3c
    else:
        embed.add_field(name="⚖️ ÉGALITÉ", value="Parade parfaite. 0 Dégât.", inline=False)
        embed.color = 0x95a5a6

    p_attaquant.sauvegarder()
    p_defenseur.sauvegarder()
    await interaction.response.send_message(embed=embed)






# 3. ATTAQUE (Unilatérale)
@bot.tree.command(name="attaque", description="Attaque unilatérale (Pas de Clash)")
@app_commands.describe(sort="Votre technique", cible="L'adversaire", description="Action RP", sursaut="Utiliser le Sursaut ?")
@app_commands.autocomplete(sort=sort_autocomplete)
async def attaque(interaction: discord.Interaction, sort: str, cible: discord.Member, description: str, sursaut: bool = False):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche perso.", ephemeral=True)

    if p.pv_actuel <= 0:
        return await interaction.response.send_message("💀 **Vous êtes K.O.** et ne pouvez pas agir !", ephemeral=True)

    if sort not in SKILLS_DB: return await interaction.response.send_message("❌ Sort introuvable.", ephemeral=True)
    if sort not in p.competences:
        return await interaction.response.send_message(f"❌ Vous n'avez pas appris la technique **{SKILLS_DB[sort]['nom']}**.", ephemeral=True)
    skill_data = SKILLS_DB[sort]

    cout = skill_data.get("cout", 0)
    cout_type = skill_data.get("cout_type", "mana")
    if cout > 0:
        valeur_actuelle = getattr(p, cout_type, 0)
        if valeur_actuelle < cout: return await interaction.response.send_message(f"❌ Pas assez de **{cout_type}**.", ephemeral=True)
        setattr(p, cout_type, valeur_actuelle - cout)
        p.sauvegarder()

    if sursaut:
        if p.sursaut_dispo == 1:
            p.sursaut_dispo = 0
            p.sauvegarder()
        else: return await interaction.response.send_message("❌ Sursaut déjà utilisé.", ephemeral=True)

    stat_nom = skill_data["stat_type"].upper()
    stat_valeur = getattr(p, skill_data["stat_type"], 0)
    skill_obj = Skill(skill_data["nom"], skill_data["base"], skill_data["bonus"], skill_data["coins"], stat_bonus=stat_valeur, stat_nom=stat_nom)

    total, visuel, heads = skill_obj.roll(p.stabilite, est_inverse=sursaut)
    if p.classe == "guerrier": 
        p.tension += 1
        p.sauvegarder()

    embed = discord.Embed(title="⚔️ ATTAQUE UNILATÉRALE", color=0xE67E22)
    embed.add_field(name=f"🗣️ {p.nom}", value=f"*« {description} »*", inline=False)
    
    calcul = f"Base {skill_obj.base} + ({heads}x{skill_obj.bonus}) + {skill_obj.stat_nom} {skill_obj.stat_bonus}"
    desc_tech = f"**{skill_obj.nom}**\n{' '.join(visuel)}\n`{calcul}`"
    
    embed.add_field(name="Résultat", value=f"{desc_tech}\n# 💥 DÉGÂTS : {total}", inline=False)
    embed.add_field(name="⚠️ DÉFENSE REQUISE", value=f"👉 **{cible.mention}**, utilisez `/defense` contre **{total}** dégâts !", inline=False)

    await interaction.response.send_message(content=f"{cible.mention}", embed=embed)






# 4. DEFENSE (Dégâts)
@bot.tree.command(name="defense", description="Se défendre : Mitigation (Sûr) ou Esquive (Risqué)")
@app_commands.describe(type_def="Mitigation ou Esquive", degats_subis="Dégâts à encaisser", ressource_spend="Mana/Tension/Ferveur à dépenser", inversion="Sursaut (Esquive seulement)")
@app_commands.choices(type_def=[
    app_commands.Choice(name="🛡️ Mitigation (Dépense Ressource)", value="tank"),
    app_commands.Choice(name="🏃 Esquive (Risque x1.5 dégâts)", value="esquive")
])
async def defense(interaction: discord.Interaction, type_def: app_commands.Choice[str], degats_subis: int, ressource_spend: int = 0, inversion: bool = False):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("Pas de fiche.", ephemeral=True)

    if p.pv_actuel <= 0:
        return await interaction.response.send_message("💀 **Vous êtes K.O.** et ne pouvez pas agir !", ephemeral=True)

    embed = discord.Embed(title="🛡️ RÉSOLUTION DÉFENSIVE", color=0xF1C40F)
    degats_finaux = degats_subis
    
    # CAS 1 : ESQUIVE
    if type_def.value == "esquive":
        if inversion and p.stabilite > -30: return await interaction.response.send_message("❌ Sursaut impossible (Stabilité > -30).", ephemeral=True)

        base_esq = 2; bonus_esq = 5; coins_esq = p.agi
        skill_esq = Skill("Esquive", base_esq, bonus_esq, coins_esq, stat_bonus=0)
        total_esq, visuel, heads = skill_esq.roll(p.stabilite, est_inverse=inversion)
        
        embed.add_field(name="Tentative d'Esquive", value=f"Agilité ({p.agi} dés): {' '.join(visuel)}\nScore: **{total_esq}** vs Dégâts: **{degats_subis}**", inline=False)
        
        if total_esq >= degats_subis:
            degats_finaux = 0
            p.stabilite = min(45, p.stabilite + 10)
            embed.add_field(name="Résultat", value="💨 **ESQUIVE PARFAITE !**\nVous ne subissez aucun dégât.", inline=False)
        else:
            degats_finaux = int(degats_subis * 1.5)
            embed.add_field(name="Résultat", value=f"💥 **RÉCEPTION CRITIQUE !**\nL'esquive a échoué.\nDégâts multipliés par 1.5 : **{degats_finaux}** dégâts.", inline=False)

    # CAS 2 : MITIGATION (CORRIGÉ)
    else:
        reduction_base = 0
        reduction_extra = 0
        msg_detail = [] # On utilise une liste pour construire le message proprement

        # 1. Réduction Passive (Guerrier avec CONST)
        if p.classe == "guerrier":
            reduction_base = p.const
            msg_detail.append(f"🛡️ Base (Const): -{reduction_base}")
        
        # 2. Configuration selon la classe
        nom_ressource = ""
        stock_actuel = 0
        multiplicateur = 0 # Combien de dégâts réduits pour 1 point dépensé

        if p.classe == "guerrier":
            nom_ressource = "tension"
            stock_actuel = p.tension
            multiplicateur = 5
        elif p.classe == "mage":
            nom_ressource = "mana"
            stock_actuel = p.mana
            multiplicateur = 2
        elif p.classe == "pretre":
            nom_ressource = "ferveur"
            stock_actuel = p.ferveur
            multiplicateur = 3
        
        # 3. Logique de dépense (Intelligente)
        depense_reelle = 0
        if ressource_spend > 0:
            if stock_actuel >= ressource_spend:
                # On a assez, on dépense tout ce qui est demandé
                depense_reelle = ressource_spend
            else:
                # On n'a pas assez, on dépense TOUT ce qu'on a
                depense_reelle = stock_actuel
                if depense_reelle > 0:
                    msg_detail.append(f"⚠️ Stock insuffisant (Max utilisé: {depense_reelle})")
                else:
                    msg_detail.append(f"❌ Plus de {nom_ressource} !")

            # Application de la dépense
            if depense_reelle > 0:
                reduction_extra = depense_reelle * multiplicateur
                nouvelle_valeur = stock_actuel - depense_reelle
                setattr(p, nom_ressource, nouvelle_valeur) # Mise à jour de la stat
                msg_detail.append(f"🔥 {nom_ressource.capitalize()} (-{depense_reelle}): -{reduction_extra}")

        total_reduc = reduction_base + reduction_extra
        degats_finaux = max(0, degats_subis - total_reduc)
        
        # Construction du texte final
        desc_mitig = "\n".join(msg_detail) if msg_detail else "Aucune réduction active."
        
        embed.add_field(name="Mitigation (Tank)", value=f"Initiaux: **{degats_subis}**\n{desc_mitig}\nTotal Réduit: **-{total_reduc}**", inline=False)
        embed.add_field(name="Dégâts Subis", value=f"💥 **{degats_finaux}**", inline=False)

# --- FINALISATION ---
    msg_ko = ""
    if degats_finaux > 0:
        p.pv_actuel -= degats_finaux
        p.stabilite = max(-45, p.stabilite - 5)
        
        # --- NOUVEAU : DETECTION DU KO ---
        if p.pv_actuel <= 0:
            p.pv_actuel = 0
            msg_ko = "\n💀 **VOUS ÊTES K.O. !**\n*Vous ne pouvez plus attaquer ni lancer de sorts.*"
            # On reset les ressources au passage (optionnel)
            p.tension = 0
            p.ferveur = 0

    p.sauvegarder()
    
    etat_vital = f"💚 PV: {p.pv_actuel}/{p.pv_max} | 🧠 ST: {p.stabilite}"
    if p.classe == "guerrier": etat_vital += f" | 💢 Tension: {p.tension}"
    elif p.classe == "mage": etat_vital += f" | 🔵 Mana: {p.mana}"
    elif p.classe == "pretre": etat_vital += f" | 🙏 Ferveur: {p.ferveur}"

    embed.add_field(name="État Final", value=etat_vital + msg_ko, inline=False)
    
    # Changement de couleur si KO
    if msg_ko:
        embed.color = 0x000000 # Noir pour le KO
        
    await interaction.response.send_message(embed=embed)
    
    p.sauvegarder()
    
    # Affichage des barres de vie restantes
    etat_vital = f"💚 PV: {p.pv_actuel}/{p.pv_max} | 🧠 ST: {p.stabilite}"
    if p.classe == "guerrier": etat_vital += f" | 💢 Tension: {p.tension}"
    elif p.classe == "mage": etat_vital += f" | 🔵 Mana: {p.mana}"
    elif p.classe == "pretre": etat_vital += f" | 🙏 Ferveur: {p.ferveur}"

    embed.add_field(name="État Final", value=etat_vital, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="recitation", description="🙏 (Prêtre) Générer de la Ferveur par la prière")
@app_commands.describe(type_r="Intensité de la prière")
@app_commands.choices(type_r=[
    app_commands.Choice(name="🕯️ Simple (+15 Ferveur)", value="simple"),
    app_commands.Choice(name="📜 Complexe (+30 Ferveur)", value="complexe")
])
async def recitation(interaction: discord.Interaction, type_r: app_commands.Choice[str]):
    p = Personnage.charger(interaction.user.id)
    if not p: 
        return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    # 1. Vérification de la classe
    if p.classe != "pretre":
        return await interaction.response.send_message("🚫 Seul un **Prêtre** peut réciter des textes sacrés.", ephemeral=True)

    # 2. Application des effets
    gain = 0
    msg_regle = ""
    couleur = 0xF1C40F # Jaune/Or
    titre = ""

    if type_r.value == "simple":
        gain = 15
        titre = "🕯️ Récitation Simple"
        msg_regle = "✅ **Action Libre :** Vous POUVEZ lancer une attaque ou un sort après cette action."
    else:
        gain = 30
        titre = "📜 Récitation Complexe"
        msg_regle = "🛑 **Action Complète :** Vous NE POUVEZ PLUS attaquer ce tour-ci (Fin de tour)."

    # 3. Mise à jour du personnage
    p.ferveur += gain
    p.sauvegarder()

    # 4. Affichage du résultat
    embed = discord.Embed(title=titre, color=couleur)
    embed.add_field(name="Effet", value=f"La foi vous envahit.\n**+{gain} Ferveur**", inline=False)
    embed.add_field(name="Nouveau Total", value=f"🙏 **{p.ferveur}** Ferveur", inline=False)
    embed.add_field(name="Règle du tour", value=msg_regle, inline=False)

    await interaction.response.send_message(embed=embed)











# --- COMMANDES UTILITAIRES ---

@bot.tree.command(name="personnalisation", description="Modifier l'apparence et l'identité RP de votre personnage")
@app_commands.describe(alias="Surnom ou Titre (ex: Le Ténébreux)", description="Histoire ou physique (Max 1000 car.)", image_url="Lien direct vers une image (http...)")
async def personnalisation(interaction: discord.Interaction, alias: str = None, description: str = None, image_url: str = None):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    modifs = []
    
    if alias:
        p.alias = alias
        modifs.append(f"🔹 **Alias :** {alias}")
    
    if description:
        # On coupe si c'est trop long pour Discord
        if len(description) > 1000: description = description[:997] + "..."
        p.description = description
        modifs.append("🔹 **Description** mise à jour.")

    if image_url:
        # Vérification basique que c'est bien une URL
        if image_url.startswith("http"):
            p.image_url = image_url
            modifs.append("🔹 **Image** modifiée.")
        else:
            modifs.append("⚠️ **Image ignorée** (doit commencer par http).")

    if not modifs:
        return await interaction.response.send_message("❌ Aucune modification spécifiée.", ephemeral=True)

    p.sauvegarder()
    
    embed = discord.Embed(title="🎨 Profil Mis à Jour", description="\n".join(modifs), color=0x9b59b6)
    if p.image_url:
        embed.set_thumbnail(url=p.image_url)
    
    await interaction.response.send_message(embed=embed)








@bot.tree.command(name="fiche", description="Voir votre fiche complète")
async def fiche(interaction: discord.Interaction):
    p = Personnage.charger(interaction.user.id)
    if not p: 
        return await interaction.response.send_message("❌ Pas de fiche. Utilisez **/creation**.", ephemeral=True)
    
    # Gestion du titre avec Alias
    titre_perso = p.nom
    if p.alias:
        titre_perso = f"{p.nom} « {p.alias} »"

    embed = discord.Embed(title=f"📜 {titre_perso}", description=f"*{p.description}*", color=0x3498db)
    
    # Affichage de l'image si elle existe
    if p.image_url:
        embed.set_thumbnail(url=p.image_url)

    embed.set_author(name=f"Niveau {p.niveau} • {p.classe.capitalize()}", icon_url=interaction.user.display_avatar.url)
    
    # --- Bloc 1 : Stats ---
    stats_phys = f"**PHY**: {p.phy} | **CONST**: {p.const} | **AGI**: {p.agi}"
    stats_mag = f"**ESP**: {p.esp} | **INT**: {p.int_stat}"
    stats_div = f"**FOI**: {p.foi} | **SAG**: {p.sag}"
    embed.add_field(name="📊 Caractéristiques", value=f"{stats_phys}\n{stats_mag}\n{stats_div}", inline=False)
    
    # --- Bloc 2 : Attributs RP ---
    rp_row1 = f"🗣️ Oral: {p.oral} | 💪 Force: {p.force_rp} | 👻 Discrétion: {p.discretion}"
    rp_row2 = f"📜 Hist: {p.histoire} | ⚗️ Sci: {p.sciences} | 🏕️ Survie: {p.survie}"
    rp_row3 = f"💉 Méd: {p.medecine} | 🙏 Rel: {p.religion}"
    embed.add_field(name="🎭 Attributs (RP)", value=f"{rp_row1}\n{rp_row2}\n{rp_row3}", inline=False)

    # --- Bloc 3 : État Vital ---
    combat_info = f"💚 PV: {p.pv_actuel}/{p.pv_max} | 🧠 ST: {p.stabilite}"
    if p.classe == "guerrier": combat_info += f" | 💢 Tension: {p.tension}"
    elif p.classe == "mage": combat_info += f" | 🔵 Mana: {p.mana}/{p.mana_max}"
    elif p.classe == "pretre": combat_info += f" | 🙏 Ferveur: {p.ferveur}"
    embed.add_field(name="⚔️ État Actuel", value=combat_info, inline=False)

    # --- BLOC MODIFIÉ : COMPÉTENCES AVEC COÛT ---
    liste_tronc = []
    liste_spe = []
    liste_passifs = []

    for skill_key in p.competences:
        if skill_key in SKILLS_DB:
            data = SKILLS_DB[skill_key]
            
            # --- MODIFICATION ICI ---
            # On prépare le texte du coût (ex: " (3 Mana)")
            cout_str = ""
            if data.get('cout', 0) > 0:
                c_type = data.get('cout_type', 'mana').capitalize()
                cout_str = f" *({data['cout']} {c_type})*"
            
            nom_sort = f"🔹 {data['nom']} (P{data['pallier']}){cout_str}"
            # ------------------------

            if data.get('type') == 'passif':
                liste_passifs.append(f"🔸 {data['nom']}")
            elif data.get('cat') == 'spe':
                liste_spe.append(nom_sort)
            else:
                liste_tronc.append(nom_sort)

    if liste_tronc: embed.add_field(name="📘 Tronc Commun", value="\n".join(liste_tronc), inline=True)
    if liste_spe: embed.add_field(name="📕 Sous-Classe / Spé", value="\n".join(liste_spe), inline=True)
    if liste_passifs: embed.add_field(name="🛡️ Passifs", value="\n".join(liste_passifs), inline=False)

    if not (liste_tronc or liste_spe or liste_passifs):
        embed.add_field(name="Compétences", value="*Aucune technique apprise.*", inline=False)

    points_info = f"Disponibles -> Stats: {p.points_stat} | Attributs: {p.points_attribut} | Compétences: {p.points_comp}"
    embed.set_footer(text=points_info)


@bot.tree.command(name="creation", description="Créer un nouveau personnage avec un nom personnalisé")
@app_commands.describe(nom="Le nom de votre personnage", classe="Votre classe")
@app_commands.choices(classe=[
    app_commands.Choice(name="Guerrier", value="Guerrier"),
    app_commands.Choice(name="Mage", value="Mage"),
    app_commands.Choice(name="Prêtre", value="Pretre")
])
async def creation(interaction: discord.Interaction, nom: str, classe: app_commands.Choice[str]):
    user_id = interaction.user.id
    conn = get_db_connection()
    
    # 1. Vérifier si ce nom est déjà pris par ce joueur
    existe = conn.execute("SELECT 1 FROM joueurs WHERE user_id = ? AND nom = ?", (user_id, nom)).fetchone()
    conn.close()
    
    if existe:
        return await interaction.response.send_message(f"❌ Vous avez déjà un personnage nommé **{nom}**.", ephemeral=True)

    # 2. Création du personnage
    # La classe Personnage gère la sauvegarde en base de données automatiquement dans son __init__
    try:
        p = Personnage(user_id, nom, classe.value)

        skill_base = ""
        if p.classe == "guerrier": skill_base = "frappe"
        elif p.classe == "mage": skill_base = "zoltraak"
        else: skill_base = "lumiere_divine"
    
        if skill_base and skill_base in SKILLS_DB:
            p.competences.append(skill_base)
            p.sauvegarder()
        
        embed = discord.Embed(title="✨ Personnage Créé !", color=0x2ecc71)
        embed.add_field(name="Nom", value=p.nom, inline=True)
        embed.add_field(name="Classe", value=p.classe.capitalize(), inline=True)
        embed.set_footer(text="Utilisez /fiche pour voir vos stats.")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        print(f"Erreur création: {e}")
        await interaction.response.send_message("❌ Une erreur est survenue lors de la création.", ephemeral=True)




@bot.tree.command(name="fin_combat", description="Reset Tension, Ferveur, Stabilité et Sursaut")
async def fin_combat(interaction: discord.Interaction):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("Pas de fiche.", ephemeral=True)
    
    p.stabilite = 0
    p.sursaut_dispo = 1 
    msg = "⚖️ Stabilité à 0.\n🔄 Sursaut rechargé.\n"

    if p.classe == "guerrier":
        p.tension = 0
        msg += "💢 Tension à 0."
    elif p.classe == "pretre":
        p.ferveur = 0
        msg += "🙏 Ferveur à 0."
    
    p.sauvegarder()
    embed = discord.Embed(title="🏁 Fin de Combat", description=msg, color=0x95a5a6)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="repos", description="Récupération totale (PV, Mana, Versets)")
async def repos(interaction: discord.Interaction):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("Pas de fiche.", ephemeral=True)
    
    p.pv_actuel = p.pv_max
    p.stabilite = 0
    p.sursaut_dispo = 1
    
    if p.classe == "mage": p.mana = p.mana_max
    elif p.classe == "pretre": p.ferveur = 0; p.versets = p.versets_max
    elif p.classe == "guerrier": p.tension = 0
    
    p.sauvegarder()
    await interaction.response.send_message("💤 **Repos Long** : PV, Ressources et Mental restaurés.")


async def my_perso_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    conn = get_db_connection()
    # On cherche les persos de l'utilisateur qui correspondent à ce qu'il tape
    cursor = conn.execute("SELECT nom FROM joueurs WHERE user_id = ? AND nom LIKE ?", (user_id, f"%{current}%"))
    personnages = cursor.fetchall()
    conn.close()
    
    return [app_commands.Choice(name=p['nom'], value=p['nom']) for p in personnages][:25]

@bot.tree.command(name="mes_persos", description="Afficher la liste de tous vos personnages")
async def mes_persos(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = get_db_connection()
    
    # On récupère tous les persos de l'utilisateur
    rows = conn.execute("SELECT nom, classe, niveau, pv_actuel, pv_max FROM joueurs WHERE user_id = ?", (user_id,)).fetchall()
    
    # On vérifie quel est le personnage actif (session)
    session = conn.execute("SELECT nom_perso_actif FROM sessions WHERE user_id = ?", (user_id,)).fetchone()
    actif = session['nom_perso_actif'] if session else None
    
    conn.close()

    if not rows:
        return await interaction.response.send_message("❌ Vous n'avez aucun personnage enregistré.", ephemeral=True)

    embed = discord.Embed(title="📚 Vos Personnages", color=0x9b59b6)
    
    description = ""
    for row in rows:
        etat = "✅ Actif" if row['nom'] == actif else ""
        description += f"**{row['nom']}** (Niv {row['niveau']} {row['classe'].capitalize()})\n"
        description += f"└ *{row['pv_actuel']}/{row['pv_max']} PV* {etat}\n\n"
    
    embed.description = description
    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(name="delete_perso", description="⚠️ Supprimer DÉFINITIVEMENT un personnage")
@app_commands.describe(nom="Nom du personnage à supprimer")
@app_commands.autocomplete(nom=my_perso_autocomplete)
async def delete_perso(interaction: discord.Interaction, nom: str):
    user_id = interaction.user.id
    conn = get_db_connection()

    # Vérification que le perso existe et appartient bien à l'utilisateur
    check = conn.execute("SELECT 1 FROM joueurs WHERE user_id = ? AND nom = ?", (user_id, nom)).fetchone()
    
    if not check:
        conn.close()
        return await interaction.response.send_message(f"❌ Le personnage **{nom}** n'existe pas ou ne vous appartient pas.", ephemeral=True)

    try:
        # 1. Suppression de la table joueurs
        conn.execute("DELETE FROM joueurs WHERE user_id = ? AND nom = ?", (user_id, nom))
        
        # 2. Si c'était le perso actif, on nettoie la session
        session = conn.execute("SELECT nom_perso_actif FROM sessions WHERE user_id = ?", (user_id,)).fetchone()
        msg_extra = ""
        if session and session['nom_perso_actif'] == nom:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            msg_extra = "\n⚠️ C'était votre personnage actif, vous n'incarnez plus personne."

        conn.commit()
        await interaction.response.send_message(f"🗑️ Le personnage **{nom}** a été supprimé avec succès.{msg_extra}", ephemeral=True)
        
    except Exception as e:
        print(f"Erreur delete: {e}")
        await interaction.response.send_message("Une erreur est survenue lors de la suppression.", ephemeral=True)
    finally:
        conn.close()


@bot.tree.command(name="grimoire", description="📖 Consulter les détails d'une technique")
@app_commands.describe(nom="Nom de la technique")
async def grimoire(interaction: discord.Interaction, nom: str):
    skill_key = None
    for key, data in SKILLS_DB.items():
        if data['nom'].lower() == nom.lower():
            skill_key = key
            break
    if not skill_key and nom in SKILLS_DB:
        skill_key = nom 
    if not skill_key:
        return await interaction.response.send_message("❌ Technique introuvable.", ephemeral=True)
    s = SKILLS_DB[skill_key]
    embed = discord.Embed(title=f"📖 {s['nom']}", description=s['desc'], color=0x9b59b6)
    cout_txt = f"{s['cout']} {s['cout_type'].capitalize()}" if s['cout'] > 0 else "Aucun"
    stats_txt = f"Base: {s['base']} | Bonus: +{s['bonus']}/coin | Dés: {s['coins']} ({s['stat_type'].upper()})"
    embed.add_field(name="⚙️ Infos Techniques", value=f"**Type:** {s.get('type', 'Actif').capitalize()}\n**Pallier:** {s['pallier']}\n**Coût:** {cout_txt}", inline=True)
    embed.add_field(name="🎲 Dégâts / Effet", value=stats_txt, inline=False)
    req_txt = f"Classe: {', '.join(s['classes']).capitalize()}"
    if s.get('cat') == 'spe': req_txt += "\nSPÉCIALISATION (Sous-classe)"
    embed.add_field(name="🔒 Pré-requis", value=req_txt, inline=True)
    await interaction.response.send_message(embed=embed)

@grimoire.autocomplete('nom')
async def grimoire_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=v['nom'], value=k) for k, v in SKILLS_DB.items() if current.lower() in v['nom'].lower()][:25]





@bot.tree.command(name="hud", description="👀 Affichage compact de votre état vital")
async def hud(interaction: discord.Interaction):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    def draw_bar(actuel, max_val, length=10, color_full="█", color_empty="░"):
        if max_val == 0: return ""
        percent = actuel / max_val
        fill = int(percent * length)
        return f"[{color_full * fill}{color_empty * (length - fill)}]"
    barre_pv = draw_bar(p.pv_actuel, p.pv_max, 10, "🟩", "⬛")
    barre_res = ""
    txt_res = ""
    if p.classe == "mage":
        barre_res = draw_bar(p.mana, p.mana_max, 10, "🟦", "⬛")
        txt_res = f"Mana {p.mana}/{p.mana_max}"
    elif p.classe == "guerrier":
        barre_res = "💢" * p.tension
        txt_res = f"Tension {p.tension}"
    elif p.classe == "pretre":
        barre_res = "🙏" * (p.ferveur // 10) 
        txt_res = f"Ferveur {p.ferveur}"

    embed = discord.Embed(color=0x2c3e50)
    embed.set_author(name=f"État de {p.nom}", icon_url=interaction.user.display_avatar.url)
    embed.description = f"**PV** {p.pv_actuel}/{p.pv_max}\n`{barre_pv}`\n\n**{txt_res}**\n`{barre_res}`\n\n🧠 **Stabilité** : {p.stabilite}"
    
    await interaction.response.send_message(embed=embed)





@bot.tree.command(name="jet_attributs", description="🎲 Faire un test de compétence RP (Oral, Sciences, etc.)")
@app_commands.describe(attribut="L'attribut à tester", difficulte="Difficulté à battre (Défaut 50)")
@app_commands.choices(attribut=[
    app_commands.Choice(name="🗣️ Oral (Convaincre/Mentir)", value="oral"),
    app_commands.Choice(name="💪 Force RP (Soulever/Intimider)", value="force_rp"),
    app_commands.Choice(name="👻 Discrétion (Se cacher/Voler)", value="discretion"),
    app_commands.Choice(name="🏕️ Survie (Pistage/Nature)", value="survie"),
    app_commands.Choice(name="📜 Histoire (Savoir/Légendes)", value="histoire"),
    app_commands.Choice(name="⚗️ Sciences (Magie théorique/Ingénierie)", value="sciences"),
    app_commands.Choice(name="💉 Médecine (Soins/Anatomie)", value="medecine"),
    app_commands.Choice(name="🙏 Religion (Dieux/Démons)", value="religion")
])
async def jet_attributs(interaction: discord.Interaction, attribut: app_commands.Choice[str], difficulte: int = 50):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    # Récupération de la valeur (ex: 3)
    valeur_attr = getattr(p, attribut.value, 0)
    bonus = valeur_attr * 4
    lancer = random.randint(1, 100)
    total = lancer + bonus
    reussite = total >= difficulte
    couleur = 0x2ecc71 if reussite else 0xe74c3c
    titre_res = "SUCCÈS" if reussite else "ÉCHEC"
    if lancer >= 95: titre_res += " CRITIQUE !"
    if lancer <= 5: titre_res += " CRITIQUE..." # Échec critique naturel
    embed = discord.Embed(title=f"🎲 Test de {attribut.name}", color=couleur)
    embed.add_field(name="Joueur", value=p.nom, inline=True)
    embed.add_field(name="Calcul", value=f"Dé ({lancer}) + Bonus ({bonus})", inline=True)
    embed.add_field(name="Résultat", value=f"**{total}** / {difficulte} (Diff)", inline=False)
    embed.set_footer(text=titre_res)
    await interaction.response.send_message(embed=embed)

















# --- COMMANDES D'AMÉLIORATION ---

@bot.tree.command(name="ameliorer", description="Dépenser des points de caractéristiques")
@app_commands.describe(stat="La statistique à augmenter", point="Combien de points investir (défaut 1)")
@app_commands.choices(stat=[
    app_commands.Choice(name="💪 Physique (Force)", value="phy"),
    app_commands.Choice(name="🛡️ Constitution (PV)", value="const"),
    app_commands.Choice(name="💨 Agilité (Esquive/Vitesse)", value="agi"),
    app_commands.Choice(name="✨ Esprit (Magie)", value="esp"),
    app_commands.Choice(name="🧠 Intelligence (Mana)", value="int_stat"),
    app_commands.Choice(name="🙏 Foi (Miracles)", value="foi"),
    app_commands.Choice(name="🦉 Sagesse (Versets)", value="sag")
])
async def ameliorer(interaction: discord.Interaction, stat: app_commands.Choice[str], point: int = 1):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    # --- 1. DÉFINITION DES RESTRICTIONS ---
    ALLOWED_STATS = {
        "guerrier": ["phy", "const", "agi"],
        "mage":     ["esp", "int_stat", "agi"],
        "pretre":   ["foi", "sag", "agi"]
    }

    classe_joueur = p.classe.lower()
    stats_autorisees = ALLOWED_STATS.get(classe_joueur, [])

    # --- 2. VÉRIFICATION DE LA CLASSE ---
    if stat.value not in stats_autorisees:
        # Dictionnaire pour afficher les noms proprement dans le message d'erreur
        noms_propres = {
            "phy": "Physique", "const": "Constitution", "agi": "Agilité",
            "esp": "Esprit", "int_stat": "Intelligence",
            "foi": "Foi", "sag": "Sagesse"
        }
        # On crée une liste lisible (ex: "Physique, Constitution, Agilité")
        liste_lisible = ", ".join([noms_propres.get(s, s) for s in stats_autorisees])
        
        return await interaction.response.send_message(
            f"🚫 En tant que **{p.classe.capitalize()}**, tu ne peux améliorer que : **{liste_lisible}**.",
            ephemeral=True
        )

    # --- 3. LOGIQUE D'ACHAT (Identique à avant) ---
    if point < 1:
        return await interaction.response.send_message("❌ Nombre invalide.", ephemeral=True)

    if p.points_stat < point:
        return await interaction.response.send_message(f"❌ Pas assez de points ! (Disponibles : {p.points_stat})", ephemeral=True)

    # Application
    stat_code = stat.value
    valeur_actuelle = getattr(p, stat_code)
    setattr(p, stat_code, valeur_actuelle + point)
    
    p.points_stat -= point
    
    # Recalculer les dérivés (PV, Mana, etc.) car Const/Int/Sag peuvent changer
    p.recalculer_derives()
    p.sauvegarder()

    await interaction.response.send_message(f"✅ **{stat.name}** augmenté de +{point} ! (Nouveau score : {valeur_actuelle + point})\nPoints restants : {p.points_stat}")









@bot.tree.command(name="ameliorer_attribut", description="Dépenser des points d'Attributs (Compétences RP)")
@app_commands.describe(attribut="L'attribut RP à améliorer", point="Combien de points investir (défaut 1)")
@app_commands.choices(attribut=[
    app_commands.Choice(name="🗣️ Oral (Persuasion/Tromperie)", value="oral"),
    app_commands.Choice(name="💪 Force RP (Intimidation/Soulever)", value="force_rp"),
    app_commands.Choice(name="🏕️ Survie (Pistage/Nature)", value="survie"),
    app_commands.Choice(name="📜 Histoire (Savoir/Culture)", value="histoire"),
    app_commands.Choice(name="⚗️ Sciences (Ingénierie/Magie théorique)", value="sciences"),
    app_commands.Choice(name="💉 Médecine (Premiers secours)", value="medecine"),
    app_commands.Choice(name="🙏 Religion (Cultes/Démons)", value="religion"),
    app_commands.Choice(name="👻 Discrétion (Furtivité/Vol)", value="discretion")
])
async def ameliorer_attribut(interaction: discord.Interaction, attribut: app_commands.Choice[str], point: int = 1):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    if point < 1:
        return await interaction.response.send_message("❌ Nombre invalide.", ephemeral=True)

    if p.points_attribut < point:
        return await interaction.response.send_message(f"❌ Pas assez de points d'attributs ! (Disponibles : {p.points_attribut})", ephemeral=True)

    # Application
    attr_code = attribut.value
    valeur_actuelle = getattr(p, attr_code)
    
    # On ajoute les points
    setattr(p, attr_code, valeur_actuelle + point)
    
    # On retire du pool "points_attribut" (et non points_stat)
    p.points_attribut -= point
    
    p.sauvegarder()

    await interaction.response.send_message(f"✅ **{attribut.name}** augmenté de +{point} ! (Nouveau score : {valeur_actuelle + point})\nPoints d'attributs restants : {p.points_attribut}")







@bot.tree.command(name="apprendre", description="Apprendre une compétence (Vérifie Classe et Pallier)")
@app_commands.describe(competence="Compétence à apprendre")
@app_commands.choices(competence=[
    app_commands.Choice(name="Zoltraak (Mage - P1)", value="zoltraak"),
    app_commands.Choice(name="Aiguille Magique (Mage - P2)", value="aiguille"), # Ajouté pour tester P2
    app_commands.Choice(name="Frappe Lourde (Guerrier - P1)", value="frappe"),
    app_commands.Choice(name="Lance de la Déesse (Prêtre - P2)", value="lance")
])
async def apprendre(interaction: discord.Interaction, competence: app_commands.Choice[str]):
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    skill_code = competence.value
    
    # 1. Vérifier si le sort existe dans la DB
    if skill_code not in SKILLS_DB:
        return await interaction.response.send_message("❌ Compétence inconnue dans la base de données.", ephemeral=True)
        
    skill_data = SKILLS_DB[skill_code]
    skill_nom = skill_data['nom']
    cout_achat = skill_data.get('cout_achat', 1)
    pallier = skill_data['pallier']
    classes_autorisees = skill_data['classes'] # ex: ['mage']

    # --- CHECK 1 : VOIE (CLASSE) ---
    # On compare la classe du joueur (p.classe) avec la liste autorisée
    if p.classe not in classes_autorisees:
        return await interaction.response.send_message(
            f"🚫 **Voie Interdite** : Cette technique est réservée aux **{classes_autorisees[0].capitalize()}s** (Tu es {p.classe.capitalize()}).",
            ephemeral=True
        )

    # --- CHECK 2 : DÉJÀ APPRIS ---
    if skill_code in p.competences:
        return await interaction.response.send_message(f"⚠️ Vous connaissez déjà **{skill_nom}**.", ephemeral=True)

    # --- CHECK 3 : PALLIER (PRÉREQUIS) ---
    # Règle issue des sources[cite: 4, 5, 6, 7]:
    # P2 demande 3 pts en P1 | P3 demande 5 pts en P2 | P4 demande 7 pts en P3 | P5 demande 9 pts en P4
    
    if pallier > 1:
        pallier_precedent = pallier - 1
        # Formule : 3 pts pour P2, 5 pour P3, etc. => (pallier_vise * 2) - 1
        # P2 : (2*2)-1 = 3 requis. P3 : (3*2)-1 = 5 requis.
        points_requis = (pallier * 2) - 1
        
        points_actuels = get_points_investis_pallier(p, pallier_precedent)
        
        if points_actuels < points_requis:
            return await interaction.response.send_message(
                f"🔒 **Pallier {pallier} bloqué** !\n"
                f"Il faut avoir investi **{points_requis}** points dans le Pallier {pallier_precedent}.\n"
                f"Actuellement : {points_actuels}/{points_requis} points.",
                ephemeral=True
            )

    # --- CHECK 4 : POINTS DISPONIBLES ---
    if p.points_comp < cout_achat:
        return await interaction.response.send_message(
            f"❌ Pas assez de points de compétence (Coût: {cout_achat} | Avez: {p.points_comp}).",
            ephemeral=True
        )

    # --- APPLICATION ---
    p.points_comp -= cout_achat
    p.competences.append(skill_code)
    p.sauvegarder()

    await interaction.response.send_message(
        f"📖 **Apprentissage réussi !**\n"
        f"Vous maîtrisez maintenant **{skill_nom}** (Pallier {pallier}).\n"
        f"Points restants : {p.points_comp}"
    )












# --- COMMANDES GM ---


async def gm_perso_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    conn = get_db_connection()
    rows = conn.execute("SELECT nom FROM joueurs WHERE user_id = ? AND nom LIKE ?", (user_id, f"%{current}%")).fetchall()
    conn.close()
    return [app_commands.Choice(name=r['nom'], value=r['nom']) for r in rows][:25]


@bot.tree.command(name="gm_incarner", description="(GM) Prendre le contrôle d'un PNJ existant")
@app_commands.describe(nom="Nom exact du PNJ")
@app_commands.autocomplete(nom=gm_perso_autocomplete)
async def gm_incarner(interaction: discord.Interaction, nom: str):
    # Sécurité GM (Optionnel, tu peux décommenter si tu veux sécuriser)
    # if interaction.user.id != 264667357631348749: return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    user_id = interaction.user.id
    conn = get_db_connection()
    
    # On vérifie juste si le perso existe
    existe = conn.execute('SELECT 1 FROM joueurs WHERE user_id = ? AND nom = ?', (user_id, nom)).fetchone()
    
    if existe:
        # On met à jour la session
        conn.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (user_id, nom))
        conn.commit()
        conn.close()
        
        # On charge pour confirmer
        p = Personnage.charger(user_id)
        await interaction.response.send_message(f"🎭 Vous incarnez maintenant **{p.nom}** ({p.classe}).")
    else:
        conn.close()
        await interaction.response.send_message(f"❌ Le personnage **{nom}** n'existe pas.\nUtilisez `/gm_creer` pour le fabriquer.", ephemeral=True)

# 2. CRÉER UN PNJ (Séparé)
@bot.tree.command(name="gm_creer", description="(GM) Créer un nouveau PNJ à la volée")
@app_commands.describe(nom="Nom du PNJ", classe="Sa classe")
@app_commands.choices(classe=[
    app_commands.Choice(name="Guerrier", value="Guerrier"),
    app_commands.Choice(name="Mage", value="Mage"),
    app_commands.Choice(name="Prêtre", value="Pretre")
])
async def gm_creer(interaction: discord.Interaction, nom: str, classe: app_commands.Choice[str]):
    # if interaction.user.id != 264667357631348749: return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    user_id = interaction.user.id
    conn = get_db_connection()
    
    # Vérif doublon
    if conn.execute('SELECT 1 FROM joueurs WHERE user_id = ? AND nom = ?', (user_id, nom)).fetchone():
        conn.close()
        return await interaction.response.send_message(f"⚠️ **{nom}** existe déjà.", ephemeral=True)
    conn.close()

    # Création (La classe Personnage gère l'init DB)
    try:
        p = Personnage(user_id, nom, classe.value)
        # On force l'incarnation directe dessus
        conn = get_db_connection()
        conn.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (user_id, nom))
        conn.commit()
        conn.close()
        
        await interaction.response.send_message(f"👹 PNJ **{p.nom}** créé et incarné !")
    except Exception as e:
        await interaction.response.send_message(f"Erreur: {e}", ephemeral=True)


@bot.tree.command(name="gm_levelup", description="(GM) Faire monter un joueur de niveau")
@app_commands.describe(joueur="Le joueur à level up", niveaux="Nombre de niveaux (défaut 1)")
async def gm_levelup(interaction: discord.Interaction, joueur: discord.Member, niveaux: int = 1):
    # Sécurité : Vérifier si c'est bien le GM
    if interaction.user.id != 264667357631348749: 
        return await interaction.response.send_message("❌ Vous n'êtes pas le GM.", ephemeral=True)

    p = Personnage.charger(joueur.id)
    if not p:
        return await interaction.response.send_message(f"❌ **{joueur.display_name}** n'a pas de fiche.", ephemeral=True)

    # --- LOGIQUE DE LEVEL UP (Modifiée) ---
    ancien_niv = p.niveau
    anciens_pv = p.pv_max
    anciens_mana = p.mana_max
    
    # Règle : +1 partout par niveau
    gain_stats = 1 * niveaux
    gain_attributs = 1 * niveaux
    gain_comp = 1 * niveaux
    
    p.niveau += niveaux
    p.points_stat += gain_stats
    p.points_attribut += gain_attributs
    p.points_comp += gain_comp
    
    # Recalcul des PV/Mana max (si jamais les stats changeaient, ici c'est surtout pour les bases par niveau)
    p.recalculer_derives()
    
    # Soin complet
    p.pv_actuel = p.pv_max
    if p.classe == "mage": p.mana = p.mana_max
    elif p.classe == "pretre": p.versets = p.versets_max
    elif p.classe == "guerrier": p.tension = 0 

    p.sauvegarder()

    # --- AFFICHAGE ---
    embed = discord.Embed(title="🎉 LEVEL UP !", description=f"Félicitations {joueur.mention} !", color=0xF1C40F)
    embed.add_field(name="Niveau", value=f"{ancien_niv} ➔ **{p.niveau}**", inline=False)
    
    # Affichage des 3 types de points
    gains_txt = (
        f"💪 **Stats :** +{gain_stats}\n"
        f"🧠 **Attributs :** +{gain_attributs}\n"
        f"✨ **Compétences :** +{gain_comp}"
    )
    embed.add_field(name="Points Gagnés", value=gains_txt, inline=True)
    
    # Calcul des gains PV/Mana réels
    gain_pv_reel = p.pv_max - anciens_pv
    txt_evo = f"💚 PV Max : +{gain_pv_reel} (Total: {p.pv_max})"
    if p.mana_max > 0:
        gain_mana_reel = p.mana_max - anciens_mana
        txt_evo += f"\n🔵 Mana Max : +{gain_mana_reel} (Total: {p.mana_max})"
        
    embed.add_field(name="Évolution Vitale", value=txt_evo, inline=False)
    embed.set_footer(text="Utilise tes points via /ameliorer et /apprendre !")

    await interaction.response.send_message(content=f"{joueur.mention}", embed=embed)


# --- COMMANDES DE DON ---

@bot.tree.command(name="gm_give_points", description="(GM) Donner des points de compétence/stat/attribut")
@app_commands.describe(joueur="Le joueur cible", type_point="Type de points", montant="Quantité")
@app_commands.choices(type_point=[
    app_commands.Choice(name="💪 Points de Caractéristiques (Stats)", value="points_stat"),
    app_commands.Choice(name="✨ Points de Compétences (Sorts)", value="points_comp"),
    app_commands.Choice(name="🎭 Points d'Attributs (RP)", value="points_attribut")
])
async def gm_give_points(interaction: discord.Interaction, joueur: discord.Member, type_point: app_commands.Choice[str], montant: int):
    # Sécurité GM
    if interaction.user.id != 264667357631348749: 
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    p = Personnage.charger(joueur.id)
    if not p:
        return await interaction.response.send_message(f"❌ **{joueur.display_name}** n'a pas de fiche.", ephemeral=True)

    # Ajout des points
    attr_name = type_point.value
    actuel = getattr(p, attr_name)
    setattr(p, attr_name, actuel + montant)
    p.sauvegarder()

    embed = discord.Embed(title="🎁 Don de Points (GM)", color=0xF1C40F)
    embed.add_field(name="Joueur", value=joueur.mention, inline=True)
    embed.add_field(name="Type", value=type_point.name, inline=True)
    embed.add_field(name="Montant", value=f"+{montant} (Total: {actuel + montant})", inline=False)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="gm_give_spell", description="(GM) Forcer l'apprentissage d'un sort")
@app_commands.describe(joueur="Le joueur cible", sort="Le sort à donner")
@app_commands.autocomplete(sort=grimoire_autocomplete) # On réutilise l'autocomplétion existante
async def gm_give_spell(interaction: discord.Interaction, joueur: discord.Member, sort: str):
    # Sécurité GM
    if interaction.user.id != 264667357631348749: 
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    p = Personnage.charger(joueur.id)
    if not p:
        return await interaction.response.send_message(f"❌ **{joueur.display_name}** n'a pas de fiche.", ephemeral=True)

    # Recherche du sort (par clé ou par nom)
    skill_key = None
    if sort in SKILLS_DB:
        skill_key = sort
    else:
        # Essai de trouver par nom si l'admin a tapé le nom complet
        for key, val in SKILLS_DB.items():
            if val['nom'] == sort:
                skill_key = key
                break
    
    if not skill_key:
        return await interaction.response.send_message("❌ Ce sort n'existe pas dans la base.", ephemeral=True)

    # Vérification doublon
    if skill_key in p.competences:
        return await interaction.response.send_message(f"⚠️ {p.nom} connaît déjà **{SKILLS_DB[skill_key]['nom']}**.", ephemeral=True)

    # Ajout
    p.competences.append(skill_key)
    p.sauvegarder()

    embed = discord.Embed(title="📖 Don de Sort (GM)", description=f"**{p.nom}** a appris une nouvelle technique !", color=0x9b59b6)
    embed.add_field(name="Sort", value=f"{SKILLS_DB[skill_key]['nom']}", inline=True)
    
    await interaction.response.send_message(content=f"{joueur.mention}", embed=embed)












# --- LANCEMENT ---
if __name__ == "__main__":
    webserver.keep_alive()
    if token:
        bot.run(token, log_handler=handler, log_level=logging.DEBUG)