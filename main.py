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
            stabilite INTEGER DEFAULT 0,          -- Mental (-45 à +45)
            sursaut_dispo INTEGER DEFAULT 1,      -- Mécanique de Comeback (0 ou 1)
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
            PRIMARY KEY (user_id, nom)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- BIBLIOTHÈQUE DE SORTS (CONFIGURATION) ---
SKILLS_DB = {
    # --- MAGE (ESP) ---
    "zoltraak": {
        "nom": "Zoltraak",
        "base": 4, "coins": 3, "bonus": 3, "stat_type": "esp",
        "cout": 3, "cout_type": "mana", "desc": "Rayon de magie noire standard."
    },
    "aiguille": {
        "nom": "Aiguille Magique",
        "base": 2, "coins": 4, "bonus": 2, "stat_type": "esp",
        "cout": 6, "cout_type": "mana", "desc": "Projectile rapide et invisible."
    },
    "jilwer": {
        "nom": "Jilwer (Brume)",
        "base": 3, "coins": 4, "bonus": 2, "stat_type": "esp",
        "cout": 20, "cout_type": "mana", "desc": "Brouillard noir étouffant."
    },

    # --- GUERRIER (PHY) ---
    "frappe": {
        "nom": "Frappe Lourde",
        "base": 5, "coins": 2, "bonus": 4, "stat_type": "phy",
        "cout": 0, "cout_type": "tension", "desc": "Coup d'épée basique."
    },
    "fendoir": {
        "nom": "Fendoir Céleste",
        "base": 8, "coins": 1, "bonus": 10, "stat_type": "phy",
        "cout": 4, "cout_type": "tension", "desc": "Lame d'air à distance (Quitte ou Double)."
    },

    # --- PRÊTRE (FOI) ---
    "lance": {
        "nom": "Lance de la Déesse",
        "base": 4, "coins": 3, "bonus": 3, "stat_type": "foi",
        "cout": 25, "cout_type": "ferveur", "desc": "Rayon de lumière sacré."
    },
    "marteau": {
        "nom": "Marteau Spirituel",
        "base": 6, "coins": 2, "bonus": 6, "stat_type": "foi",
        "cout": 50, "cout_type": "ferveur", "desc": "Arme invoquée massive."
    }
}

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
        
        if not charger_db:
            self.niveau = 1
            self.points_stat = 0; self.points_comp = 0; self.points_attribut = 0
            self.init_stats_depart()
            self.recalculer_derives() 
            self.pv_actuel = self.pv_max
            self.mana = self.mana_max
            self.tension = 0; self.ferveur = 0; self.versets = self.versets_max
            
            self.stabilite = 0
            self.sursaut_dispo = 1 
            
            self.oral = 0; self.force_rp = 0; self.survie = 0
            self.histoire = 0; self.sciences = 0; self.medecine = 0
            self.religion = 0; self.discretion = 0
            
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
        if self.classe == "guerrier":
            self.pv_max = 55 + ((self.niveau - 1) * 8)
            self.mana_max = 0; self.versets_max = 0
        elif self.classe == "mage":
            self.pv_max = 35 + ((self.niveau - 1) * 4)
            self.mana_max = (self.int_stat * 8) + 10 
        elif self.classe == "pretre":
            self.pv_max = 45 + ((self.niveau - 1) * 6)
            self.versets_max = self.sag 

    def sauvegarder(self):
        conn = get_db_connection()
        skills_json = json.dumps(self.competences)
        conn.execute('''
            INSERT OR REPLACE INTO joueurs VALUES 
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (self.user_id, self.nom, self.classe, self.niveau,
              self.pv_actuel, self.pv_max, self.mana, self.mana_max,
              self.tension, self.ferveur, self.versets, 
              self.stabilite, self.sursaut_dispo,
              self.phy, self.const, self.agi,
              self.esp, self.int_stat, self.foi, self.sag,
              self.points_stat, self.points_comp, self.points_attribut, skills_json,
              self.oral, self.force_rp, self.survie, self.histoire, 
              self.sciences, self.medecine, self.religion, self.discretion))
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
    sorts = []
    for key, val in SKILLS_DB.items():
        if current.lower() in val['nom'].lower():
            sorts.append(app_commands.Choice(name=val['nom'], value=key))
    return sorts[:25]

# --- COMMANDES DE COMBAT ---

# 1. CLASH 
@bot.tree.command(name="clash", description="Défier une cible (Nécessite une Riposte)")
@app_commands.describe(sort="Votre technique", cible="L'adversaire", description="Action RP", sursaut="Activer le Sursaut ?")
@app_commands.autocomplete(sort=sort_autocomplete)
async def clash(interaction: discord.Interaction, sort: str, cible: discord.Member, description: str, sursaut: bool = False):
    p_attaquant = Personnage.charger(interaction.user.id)
    if not p_attaquant: return await interaction.response.send_message("❌ Pas de fiche perso.", ephemeral=True)

    if cible.id == interaction.user.id: return await interaction.response.send_message("❌ Cible invalide.", ephemeral=True)
    if cible.id in PENDING_CLASHES: return await interaction.response.send_message(f"❌ **{cible.display_name}** est déjà défié ! Utilisez `/attaque` pour une frappe unilatérale.", ephemeral=True)

    if sort not in SKILLS_DB: return await interaction.response.send_message("❌ Sort introuvable.", ephemeral=True)
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
    
    if sort not in SKILLS_DB: return await interaction.response.send_message("❌ Sort introuvable.", ephemeral=True)
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

    if sort not in SKILLS_DB: return await interaction.response.send_message("❌ Sort introuvable.", ephemeral=True)
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

    # CAS 2 : MITIGATION
    else:
        reduction_base = 0; reduction_extra = 0; msg_detail = ""

        if p.classe == "guerrier":
            reduction_base = p.const
            msg_detail = f"Base (CONST): -{reduction_base}"
            if ressource_spend > 0 and p.tension >= ressource_spend:
                p.tension -= ressource_spend
                reduction_extra = ressource_spend * 5
                msg_detail += f"\nTension (-{ressource_spend}): -{reduction_extra}"
        elif p.classe == "mage":
            if ressource_spend > 0 and p.mana >= ressource_spend:
                p.mana -= ressource_spend
                reduction_extra = ressource_spend * 2
                msg_detail = f"Barrière (-{ressource_spend} PM): -{reduction_extra}"
        elif p.classe == "pretre":
            if ressource_spend > 0 and p.ferveur >= ressource_spend:
                p.ferveur -= ressource_spend
                reduction_extra = ressource_spend * 3
                msg_detail = f"Aura (-{ressource_spend} Ferv.): -{reduction_extra}"

        total_reduc = reduction_base + reduction_extra
        degats_finaux = max(0, degats_subis - total_reduc)
        
        embed.add_field(name="Mitigation", value=f"Initiaux: **{degats_subis}**\nRéduction: **-{total_reduc}** ({msg_detail})", inline=False)
        embed.add_field(name="Dégâts Subis", value=f"💥 **{degats_finaux}**", inline=False)

    if degats_finaux > 0:
        p.pv_actuel -= degats_finaux
        p.stabilite = max(-45, p.stabilite - 5)
    
    p.sauvegarder()
    embed.add_field(name="État Final", value=f"PV: {p.pv_actuel}/{p.pv_max} | ST: {p.stabilite}", inline=False)
    await interaction.response.send_message(embed=embed)

# --- COMMANDES UTILITAIRES ---
@bot.tree.command(name="fiche", description="Voir votre fiche et vos points")
async def fiche(interaction: discord.Interaction, classe: str = None):
    if classe: 
        p = Personnage(interaction.user.id, interaction.user.display_name, classe)
        return await interaction.response.send_message("Perso créé.")
    p = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("Pas de fiche.", ephemeral=True)
    
    embed = discord.Embed(title=f"📜 {p.nom} (Niv {p.niveau})", color=0x3498db)
    stats_phys = f"PHY: {p.phy} | CONST: {p.const} | AGI: {p.agi}"
    stats_mag = f"ESP: {p.esp} | INT: {p.int_stat}"
    stats_div = f"FOI: {p.foi} | SAG: {p.sag}"
    embed.add_field(name="📊 Caractéristiques", value=f"{stats_phys}\n{stats_mag}\n{stats_div}", inline=False)
    
    combat_info = f"💚 PV: {p.pv_actuel}/{p.pv_max} | 🧠 ST: {p.stabilite}"
    if p.classe == "guerrier": combat_info += f" | 💢 Tension: {p.tension}"
    elif p.classe == "mage": combat_info += f" | 🔵 Mana: {p.mana}/{p.mana_max}"
    elif p.classe == "pretre": combat_info += f" | 🙏 Ferveur: {p.ferveur}"
    
    embed.add_field(name="⚔️ Combat", value=combat_info, inline=False)
    await interaction.response.send_message(embed=embed)

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

# --- COMMANDES GM ---
@bot.tree.command(name="gm_incarner", description="(GM) Créer ou changer de personnage")
@app_commands.describe(nom="Nom du PNJ", classe="Classe")
async def gm_incarner(interaction: discord.Interaction, nom: str, classe: str = "Guerrier"):
    user_id = interaction.user.id
    conn = get_db_connection()
    existe = conn.execute('SELECT * FROM joueurs WHERE user_id = ? AND nom = ?', (user_id, nom)).fetchone()
    conn.close()
    if existe:
        conn = get_db_connection()
        conn.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (user_id, nom))
        conn.commit()
        conn.close()
        p = Personnage.charger(user_id)
        await interaction.response.send_message(f"🎭 Vous incarnez **{p.nom}**.")
    else:
        p = Personnage(user_id, nom, classe)
        await interaction.response.send_message(f"👹 PNJ **{p.nom}** créé.")

# --- LANCEMENT ---
if __name__ == "__main__":
    webserver.keep_alive()
    if token:
        bot.run(token, log_handler=handler, log_level=logging.DEBUG)