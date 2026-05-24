import sqlite3
import discord
from discord.ext import commands
from discord import app_commands  
import logging 
from dotenv import load_dotenv
import os
import random
import json
import asyncio
import time
from collections import Counter
# import webserver  # Décommenter si hébergé sur Replit
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
# --- CONFIGURATION INITIALE ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------


load_dotenv()
token = os.getenv('DISCORD_TOKEN')
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.all()

# --- IDs des Game Masters (doit être défini AVANT la création du bot) ---
GM_IDS = [264667357631348749, 461067793677287434]

# --- Salons privés Pigeon Voyageur (joueur_id → salon_id) ---
PIGEON_CHANNELS = {
    762271064444895232:  1485319361307873300,
    302429969869701120:  1485319419608563814,
    265428087628365825:  1485319481470226462,
    477881115982430209:  1485319529218314321,
    465623001178832907:  1485319717563400343,
    505813139837943809:  1485319781195448471,
    # MJs — partagent le même salon de copie
    461067793677287434:  1485321781924597831,
    264667357631348749:  1485321781924597831,
}

def is_gm(user_id: int) -> bool:
    """Vérifie si un utilisateur est Game Master."""
    return user_id in GM_IDS

bot = commands.Bot(command_prefix="!", intents=intents, owner_id=GM_IDS[0])

MY_GUILD_ID = discord.Object(id=1446818667655594006)

# --- LOG DE COMBAT ---
# Mettre l'ID du canal où les actions de combat seront archivées.
# Mettre à None pour désactiver le log.
COMBAT_LOG_CHANNEL_ID = None  # Exemple : 1234567890123456789

async def log_combat(interaction: discord.Interaction, embed: discord.Embed):
    """Envoie une copie de l'embed dans le canal de log de combat (si configuré)."""
    if COMBAT_LOG_CHANNEL_ID is None:
        return
    try:
        canal = interaction.client.get_channel(COMBAT_LOG_CHANNEL_ID)
        if canal is None:
            canal = await interaction.client.fetch_channel(COMBAT_LOG_CHANNEL_ID)
        # Embed allégé pour le log : on clone et on ajoute l'auteur
        log_embed = embed.copy()
        log_embed.set_author(
            name=f"{interaction.user.display_name} — #{interaction.channel.name}",
            icon_url=interaction.user.display_avatar.url
        )
        log_embed.timestamp = discord.utils.utcnow()
        await canal.send(embed=log_embed)
    except Exception as e:
        print(f"[LOG COMBAT] Erreur envoi log : {e}")

PENDING_CLASHES = {}
LAST_ATTACKER = {}  # {defender_user_id: attacker_user_id} — pour Distorsion Permanente
COMBAT_STATS = {}   # {user_id: {"nom":"","degats_infliges":0,"degats_recus":0,"soins":0}}

def cs_get(user_id: int, nom: str = "") -> dict:
    if user_id not in COMBAT_STATS:
        COMBAT_STATS[user_id] = {"nom": nom, "degats_infliges": 0, "degats_recus": 0, "soins": 0}
    elif nom:
        COMBAT_STATS[user_id]["nom"] = nom
    return COMBAT_STATS[user_id]

def cs_add_infliges(uid, nom, v): cs_get(uid, nom)["degats_infliges"] += max(0, int(v))
def cs_add_recus(uid, nom, v):   cs_get(uid, nom)["degats_recus"]    += max(0, int(v))
def cs_add_soins(uid, nom, v):   cs_get(uid, nom)["soins"]           += max(0, int(v))

def get_db_connection():
    conn = sqlite3.connect('/data/frieren_jdr.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS sessions (user_id INTEGER PRIMARY KEY, nom_perso_actif TEXT)')
    
    conn.execute('''
        CREATE TABLE IF NOT EXISTS joueurs (
            user_id INTEGER, nom TEXT, classe TEXT, race TEXT DEFAULT 'Humain', niveau INTEGER,
            pv_actuel INTEGER, pv_max INTEGER, mana INTEGER, mana_max INTEGER,
            tension INTEGER, ferveur INTEGER, versets INTEGER,
            phy INTEGER, const INTEGER, agi INTEGER, esp INTEGER, int_stat INTEGER, foi INTEGER, sag INTEGER,
            points_stat INTEGER DEFAULT 0, points_comp INTEGER DEFAULT 0, points_attribut INTEGER DEFAULT 0,
            competences TEXT DEFAULT '[]',
            oral INTEGER DEFAULT 0, force_rp INTEGER DEFAULT 0, survie INTEGER DEFAULT 0,
            histoire INTEGER DEFAULT 0, sciences INTEGER DEFAULT 0, medecine INTEGER DEFAULT 0,
            religion INTEGER DEFAULT 0, discretion INTEGER DEFAULT 0,
            alias TEXT DEFAULT NULL, description TEXT DEFAULT 'Aucune description.', image_url TEXT DEFAULT NULL,
            mode_entrainement INTEGER DEFAULT 0, snapshot_entrainement TEXT DEFAULT NULL,
            sous_classes_unlocked TEXT DEFAULT '[]', effets TEXT DEFAULT '{}',
            acrobatie INTEGER DEFAULT 0, cooldowns TEXT DEFAULT '{}',
            festin INTEGER DEFAULT 0, charges_elementaires TEXT DEFAULT '[]',
            PRIMARY KEY (user_id, nom)
        )
    ''')

    conn.execute('CREATE TABLE IF NOT EXISTS config_sous_classes (nom TEXT PRIMARY KEY, classe_mere TEXT, description TEXT)')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS config_sorts (
            ref TEXT PRIMARY KEY, nom TEXT, classes TEXT, pallier INTEGER, 
            cout_achat INTEGER, base INTEGER, coins INTEGER, bonus INTEGER, 
            stat_type TEXT, cout INTEGER, cout_type TEXT, versets INTEGER DEFAULT 0, 
            cooldown INTEGER DEFAULT 0, desc TEXT, type TEXT, cat TEXT, 
            data_json TEXT DEFAULT '{}' 
        )
    ''')
    conn.execute('CREATE TABLE IF NOT EXISTS config_items (ref TEXT PRIMARY KEY, nom TEXT, slot TEXT, description TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS inventaire (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_ref TEXT, equipe INTEGER DEFAULT 0, FOREIGN KEY(item_ref) REFERENCES config_items(ref))')

    # ── NOUVEAU : Raretés, Sets, Étude ────────────────────────────────
    # config_items étendu (ALTER si colonnes manquantes)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS config_sets (
            set_ref TEXT PRIMARY KEY,
            nom TEXT,
            description TEXT,
            bonus_2 TEXT DEFAULT '{}',
            bonus_4 TEXT DEFAULT '{}'
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS config_set_items (
            set_ref TEXT,
            item_ref TEXT,
            PRIMARY KEY (set_ref, item_ref)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS etude_progress (
            user_id INTEGER,
            inv_id INTEGER,
            reussites INTEGER DEFAULT 0,
            derniere_tentative TEXT DEFAULT NULL,
            identifie INTEGER DEFAULT 0,
            sequence_en_cours TEXT DEFAULT NULL,
            PRIMARY KEY (user_id, inv_id)
        )
    ''')
    try: conn.execute("ALTER TABLE etude_progress ADD COLUMN sequence_en_cours TEXT DEFAULT NULL")
    except: pass
    # Nouvelles colonnes config_items
    try: conn.execute("ALTER TABLE config_items ADD COLUMN rarete TEXT DEFAULT 'commun'")
    except: pass
    try: conn.execute("ALTER TABLE config_items ADD COLUMN bonus_json TEXT DEFAULT '{}'")
    except: pass
    try: conn.execute("ALTER TABLE config_items ADD COLUMN points_limite INTEGER DEFAULT 5")
    except: pass
    try: conn.execute("ALTER TABLE config_items ADD COLUMN necessite_etude INTEGER DEFAULT 0")
    except: pass
    # inventaire : item identifié ?
    try: conn.execute("ALTER TABLE inventaire ADD COLUMN identifie INTEGER DEFAULT 1")
    except: pass

    try: conn.execute("ALTER TABLE joueurs ADD COLUMN race TEXT DEFAULT 'Humain'")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN effets TEXT DEFAULT '{}'")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN acrobatie INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE config_sorts ADD COLUMN cooldown INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN cooldowns TEXT DEFAULT '{}'")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE config_sorts ADD COLUMN data_json TEXT DEFAULT '{}'")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN monnaie INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN robustesse INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN festin INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN charges_elementaires TEXT DEFAULT '[]'")
    except sqlite3.OperationalError: pass

    # ── NOUVELLES COLONNES — Sous-classes V4 ──────────────────────
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN passe_active INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN parade_absorb INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN last_action_type TEXT DEFAULT 'autre'")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN fureur_tribale_used INTEGER DEFAULT 0")
    except: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN mana_bonus_racial INTEGER DEFAULT 0")
    except: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN bonus_base_item INTEGER DEFAULT 0")
    except: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN bonus_pieces_item INTEGER DEFAULT 0")
    except: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN mana_max_bonus_item INTEGER DEFAULT 0")
    except: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN pv_max_bonus_item INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN concentre INTEGER DEFAULT 1")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN serment_actif INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN serment_bonus INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN posture_active INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN designation_target_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN designation_stacks INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN sentence_target_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN sentence_targets TEXT DEFAULT '[]'")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN passe_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: conn.execute("ALTER TABLE joueurs ADD COLUMN badges TEXT DEFAULT '[]'")
    except sqlite3.OperationalError: pass

    conn.commit()
    conn.close()

SKILLS_DB = {}
RACES_DB = {
    "Elfe": {
        "vie": "700-1000 ans",
        "desc": "Êtres gracieux vivant en harmonie avec le mana.",
        "rp": "Avantage narratif sur l'Histoire et les entités anciennes.",
        "don": "+3 Histoire. Évo: Mana/Init/Religion."
    },
    "Humain": {
        "vie": "80-100 ans",
        "desc": "Ambitieux, inventifs et adaptables.",
        "rp": "Trouve toujours un contact ou une info en ville.",
        "don": "+2 Points de Stat. Évo: Coût Mana/PV/Point Comp."
    },
    "Nain": {
        "vie": "350-450 ans",
        "desc": "Maîtres artisans à la volonté de fer.",
        "rp": "Détecte passages secrets et architecture souterraine.",
        "don": "Réduction dégâts subis -1. Évo: Esprit/Force/Artisanat."
    },
    "Drakéide": {
        "vie": "150-200 ans",
        "desc": "Noblesse et fureur des dragons.",
        "rp": "Intimidation naturelle (animaux et faibles volontés).",
        "don": "Immunité Brûlure/Gel. Évo: +Dégâts.",
    },
    "Féral": {
        "vie": "70-90 ans",
        "desc": "Hybrides instinctifs et sens aiguisés.",
        "rp": "Prédit météo et dangers naturels.",
        "don": "Avantage sur les jets d'Agilité. Évo: Agi/Phy/Survie."
    },
    "Céleste": {
        "vie": "500-600 ans",
        "desc": "Touchés par la lumière divine.",
        "rp": "Discerne la sincérité et la noirceur de l'âme.",
        "don": "Soins +3. Évo: Mana/Tension/Verset."
    },
    "Vampire": {
        "vie": "Immortel",
        "desc": "Aristocrates de l'ombre.",
        "rp": "Persuasion accrue en tête-à-tête.",
        "don": "Vol de vie (+1PV sur dégâts). Mécanique de Sang.",
        "interdit": ["pretre"]
    }
}
def reload_data():
    global SKILLS_DB
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM config_sorts").fetchall()
    SKILLS_DB.clear()
    for r in rows:
        SKILLS_DB[r['ref']] = dict(r)
        try: SKILLS_DB[r['ref']]['classes'] = json.loads(r['classes'])
        except (json.JSONDecodeError, TypeError): SKILLS_DB[r['ref']]['classes'] = []
        
        # --- NOUVEAU : On s'assure que le champ data_json existe ---
        if 'data_json' not in SKILLS_DB[r['ref']] or not SKILLS_DB[r['ref']]['data_json']:
             SKILLS_DB[r['ref']]['data_json'] = "{}"

    conn.close()
    print(f"🔄 Données rechargées : {len(SKILLS_DB)} Sorts.")


def get_festin_stade(p) -> int:
    """Retourne le stade de la jauge de Festin (0-4)."""
    if not hasattr(p, 'festin'): return 0
    f = p.festin
    if "passif_sang_aieux" in p.competences and f >= 40: return 4
    if f >= 30: return 3
    if f >= 20: return 2
    if f >= 10: return 1
    return 0

def get_festin_max(p) -> int:
    """Retourne la valeur maximale de la jauge de Festin."""
    return 40 if "passif_sang_aieux" in p.competences else 39

def get_max_charges(p) -> int:
    """Retourne le nombre max de charges élémentaires."""
    return 4 if "passif_elem_avatar" in p.competences else 3

def get_resonance_dominant(p):
    """Retourne l'élément dominant des charges et son count, ou (None, 0)."""
    if not p.charges_elementaires: return None, 0
    c = Counter(p.charges_elementaires)
    dominant, count = c.most_common(1)[0]
    return dominant, count

def has_all_elements(p) -> bool:
    """Vérifie si les 4 éléments sont présents (Avatar des Éléments P5)."""
    return set(p.charges_elementaires) == {"feu", "glace", "foudre", "air"}

def get_bonus_resonance(p) -> dict:
    """
    Retourne les bonus de résonance actifs sous forme de dict.
    Si Avatar actif et 4 éléments présents → tous les bonus simultanément.
    """
    bonus = {}
    if not p.charges_elementaires: return bonus
    avatar_actif = "passif_elem_avatar" in p.competences and has_all_elements(p)
    
    bonus_sup = 0
    if "passif_elem_peau" in p.competences: bonus_sup += 1
    if "passif_elem_surcharge" in p.competences:
        c = Counter(p.charges_elementaires)
        dominant, count = c.most_common(1)[0]
        if count >= 3 and all(e == dominant for e in p.charges_elementaires[:count]): bonus_sup += 2
    if "passif_elem_tempetes" in p.competences: bonus_sup += 3

    if avatar_actif:
        bonus["feu"] = 3 + bonus_sup
        bonus["glace"] = 2 + bonus_sup
        bonus["foudre"] = 2 + bonus_sup
        bonus["air"] = 3 + bonus_sup
    else:
        dominant, _ = get_resonance_dominant(p)
        if dominant:
            if dominant == "feu": bonus["feu"] = 3 + bonus_sup
            elif dominant == "glace": bonus["glace"] = 2 + bonus_sup
            elif dominant == "foudre": bonus["foudre"] = 2 + bonus_sup
            elif dominant == "air": bonus["air"] = 3 + bonus_sup
    return bonus

# ═══════════════════════════════════════════════════════════════
# HELPERS — SOUS-CLASSES V4
# ═══════════════════════════════════════════════════════════════


def get_nb_alterations(cible: 'Personnage') -> int:
    """Retourne le nombre de types d'altérations d'état actives sur la cible."""
    alts = {"poison", "brulure", "hemorragie", "stun", "root", "gel", "corruption", "mutilation", "toxine"}
    return sum(1 for k in cible.effets if k in alts)

def get_lestage(cible: 'Personnage') -> int:
    """Retourne le nombre de stacks de Lestage sur la cible."""
    return cible.effets.get("lestage", {}).get("valeur", 0)

def ajouter_lestage(cible: 'Personnage', stacks: int, attaquant: 'Personnage' = None) -> str:
    """Ajoute des stacks de Lestage à une cible. Retourne un message résumé.
    attaquant : optionnel — si fourni, le seuil de Singularité est réduit à 4
                avec le passif [Avatar du Cosmos] (P5 Magie Gravitationnelle).
    """
    anciens = get_lestage(cible)
    nouveau = anciens + stacks
    cible.effets["lestage"] = {"duree": 9999, "valeur": nouveau}

    msgs = [f"⚖️ **Lestage** : {anciens} → {nouveau} stacks"]

    # Seuil de Singularité : 4 si Avatar du Cosmos actif, sinon 5
    seuil_sing = 4 if (attaquant and "passif_grav_avatar" in attaquant.competences) else 5

    # Seuil 1-2 : -1 Init / stack (narratif)
    if 1 <= nouveau <= 2:
        msgs.append(f"  ↳ Initiative -{nouveau} (lourdeur cosmique)")
    # Seuil 3 à (seuil_sing - 1) : Alourdie
    elif 3 <= nouveau < seuil_sing:
        msgs.append("  ↳ État **Alourdie** : Agilité ÷ 2")
    # Seuil atteint : Singularité
    elif nouveau >= seuil_sing:
        note_avatar = " *(Avatar du Cosmos : seuil 4)*" if seuil_sing == 4 else ""
        msgs.append(f"  ↳ 🌑 **SINGULARITÉ**{note_avatar} : Prochaine attaque ignore Armure+Rob + Enracinement auto !")
        cible.effets["singularite"] = {"duree": 9999, "valeur": 1}

    return "\n".join(msgs)

def consommer_singularite(cible: 'Personnage', attaquant: 'Personnage') -> tuple:
    """
    Consomme la Singularité si active.
    Retourne (ignore_armure: bool, degats_bonus: int, msg: str)
    """
    if "singularite" not in cible.effets:
        return False, 0, ""
    del cible.effets["singularite"]
    # Reset lestages
    cible.effets.pop("lestage", None)
    # Enracinement automatique (silencieux)
    cible.ajouter_effet("root", 1)
    degats_bonus = 0
    msg = "🌑 **Singularité déclenchée !** Armure et Robustesse ignorées !"
    # Passif Point de Rupture (P3) : +8 dégâts fixes
    if "passif_grav_rupture" in attaquant.competences:
        degats_bonus += 8
        msg += f"\n  ↳ +8 dégâts (Point de Rupture)"
    # Passif P5 : Singularité à 4 stacks
    if "passif_grav_avatar" in attaquant.competences:
        attaquant.mana = min(attaquant.mana_max, attaquant.mana + 10)
        msg += f"\n  ↳ +10 Mana (Avatar du Cosmos)"
    return True, degats_bonus, msg

def get_serment_bonus(p: 'Personnage') -> int:
    """Retourne le bonus de Base actuel du Serment du Sang."""
    if not p.serment_actif: return 0
    return p.serment_bonus

def calculer_serment(p: 'Personnage', degats_subis: int):
    """Serment du Sang — nouvelle règle :
    - S'active uniquement sous 40% PV.
    - +1 par tranche de 5 PV perdus (min +1).
    - Plafond : 8 normal | 10 avec Corps de Fer.
    - Sous 30% PV : plafond monte à 12 | 15 avec Corps de Fer.
    """
    if not p.serment_actif: return
    seuil_40 = p.pv_max * 0.4
    # Le Serment ne s'accumule que sous 40% PV
    if p.pv_actuel > seuil_40:
        return
    seuil_30 = p.pv_max * 0.3
    if p.pv_actuel <= seuil_30:
        max_actuel = 15 if "passif_nord_fer" in p.competences else 12
    else:
        max_actuel = 10 if "passif_nord_fer" in p.competences else 8
    gain = max(1, degats_subis // 5)
    p.serment_bonus = min(max_actuel, p.serment_bonus + gain)

def appliquer_fureur_tribale(p: 'Personnage', pv_avant: int, degats: int) -> str:
    """Vérifie et applique la Fureur Tribale (passage sous 50% PV). Retourne message."""
    if p.fureur_tribale_used: return ""
    seuil = p.pv_max // 2
    if pv_avant > seuil and (pv_avant - degats) <= seuil:
        p.tension += 2
        p.fureur_tribale_used = 1
        return "🔥 **Fureur Tribale** : +2 Tension (une seule fois ce combat) !"
    return ""

def appliquer_passe_trigger(p: 'Personnage') -> str:
    """Appelé lors de la réception de dégâts : déclenche le bonus Passe si actif."""
    if p.passe_active:
        p.passe_active = 0
        p.tension += 2
        return "⚔️ **Passe déclenchée** : +2 Tension !"
    return ""

def appliquer_parade_absorb(p: 'Personnage', degats: int) -> tuple:
    """Réduit les dégâts de parade_absorb si > 0. Retourne (degats_finaux, msg)."""
    if p.parade_absorb > 0:
        reduction = min(p.parade_absorb, degats)
        degats -= reduction
        p.parade_absorb = 0
        return degats, f"🛡️ **Parade Absolue** : -{reduction} dégâts absorbés !"
    return degats, ""

def appliquer_legere_inquisiteur(attaquant: 'Personnage', defenseur: 'Personnage', sort_data: dict) -> tuple:
    """Applique les bonus Sentence (Inquisiteur). Retourne (base_bonus, ignore_armure, msg)."""
    if defenseur.user_id not in attaquant.sentence_targets: return 0, False, ""
    # Déterminer si sort TC ou SC
    cat = sort_data.get("cat", "tronc")
    msgs = []
    base_bonus = 0
    ignore_armure = False
    if cat == "tronc":
        base_bonus = 3
        msgs.append("📜 **Sentence** : +3 Base (Tronc sur cible Condamnée)")
    else:
        ignore_armure = True
        msgs.append("📜 **Sentence** : Armure ignorée (Sort SC sur cible Condamnée)")
    # Passif La Balance du Confesseur (P4) : géré dans /sentence
    return base_bonus, ignore_armure, "\n".join(msgs)

def appliquer_designation(attaquant: 'Personnage', defenseur: 'Personnage', sort_data: dict) -> tuple:
    """Applique le bonus Désignation (Loge de l'Ombre) sur sort TC. Retourne (pieces_bonus, msg)."""
    if attaquant.designation_target_id != defenseur.user_id: return 0, ""
    if attaquant.designation_stacks <= 0: return 0, ""
    cat = sort_data.get("cat", "tronc")
    if cat != "tronc": return 0, ""
    attaquant.designation_stacks -= 1
    if attaquant.designation_stacks <= 0:
        attaquant.designation_target_id = 0
    # Passif Grand Régulateur (P5) géré séparément
    return 3, "🎯 **Désignation consommée** : +3 Pièces !"

def populate_spells():
    conn = get_db_connection()
    print("📚 Mise à jour du Grimoire (Boost de puissance appliqué)...")
    sorts = [
        # ==================== MAGE - TRONC COMMUN ====================
        # Base & P1 (+1 Base, +1 Pièce)
        ("zooltrak_novice", "Zooltrak Novice", '["mage"]', 1, 0, 5, 3, 2, "esp", 4, "mana", 0, 0, "Rayon de mana.", "actif", "tronc", "{}"),
        ("nebel_novice", "Nebel Novice", '["mage"]', 1, 1, 2, 4, 2, "esp", 5, "mana", 0, 2, "Nuage toxique.", "actif", "tronc", '{"seuil": 2, "status": {"poison": 2}}'),
        ("schild_novice", "Schild Novice (Bonus)", '["mage"]', 1, 1, 0, 2, 3, "esp", 5, "mana", 0, 2, "Barrière.", "defense", "tronc", '{"seuil": 1, "reduce_dmg_dynamic": true}'),
        ("funke_novice", "Funke Novice", '["mage"]', 1, 1, 3, 3, 2, "esp", 4, "mana", 0, 2, "Étincelle.", "actif", "tronc", '{"status": {"brulure": 1}}'),
        ("kernblitz", "Kernblitz", '["mage"]', 1, 1, 4, 3, 2, "esp", 5, "mana", 0, 2, "Foudre (Hâte).", "actif", "tronc", '{"seuil": 2, "self_status": {"hate": 1}}'),
        ("magia", "Magia (Bonus)", '["mage"]', 1, 1, 0, 2, 0, "esp", 4, "mana", 0, 2, "Détection.", "utilitaire", "tronc", '{"seuil": 2, "rp_effect": "Détecte le type de magie (Déesse/Démon)."}'),
        ("purgato", "Purgato (Bonus)", '["mage"]', 1, 1, 0, 0, 0, "esp", 3, "mana", 0, 2, "Nettoyage.", "utilitaire", "tronc", '{"rp_effect": "Nettoie la zone de 5m."}'),
        ("liber", "Liber (Bonus)", '["mage"]', 1, 1, 0, 0, 0, "esp", 3, "mana", 0, 2, "Analyse.", "utilitaire", "tronc", '{"rp_effect": "Indique l ancienneté (Blanc=neuf, Rouge=vieux)."}'),
        ("fessel", "Fessel", '["mage"]', 1, 1, 6, 3, 2, "esp", 5, "mana", 0, 2, "Enracinement.", "actif", "tronc", '{"seuil": 2, "status": {"root": 1}}'),
        ("ekko", "Ekko (Bonus)", '["mage"]', 1, 1, 0, 0, 0, "esp", 4, "mana", 0, 2, "Vision.", "utilitaire", "tronc", '{"rp_effect": "Vision des 5 dernières secondes de l objet."}'),
        ("siphon", "Siphon", '["mage"]', 1, 1, 3, 3, 2, "esp", 2, "mana", 0, 2, "Drain Mana.", "actif", "tronc", '{"seuil": 1, "restore_mana": 3}'),
        ("flash", "Flash (Bonus)", '["mage"]', 1, 1, 0, 1, 0, "esp", 7, "mana", 0, 2, "TP Esquive.", "defense", "tronc", '{"seuil": 1, "rp_effect": "+7 Esquive (Narratif/Bonus)."}'),

        # P2 (+2 Base, +1 Pièce)
        ("zooltrak", "Zooltrak", '["mage"]', 2, 2, 10, 3, 3, "esp", 8, "mana", 0, 0, "Rayon moyen.", "actif", "tronc", "{}"),
        ("schwer", "Schwer", '["mage"]', 2, 2, 6, 4, 2, "esp", 9, "mana", 0, 2, "Gravité.", "actif", "tronc", '{"seuil": 2, "status": {"stun": 1}}'),
        ("hagel", "Hagel", '["mage"]', 2, 2, 6, 6, 1, "esp", 8, "mana", 0, 2, "Grêle.", "actif", "tronc", '{"seuil": 3, "ricochet": true}'),
        ("eis", "Eis", '["mage"]', 2, 2, 8, 4, 2, "esp", 7, "mana", 0, 2, "Gel.", "actif", "tronc", '{"status": {"gel": 1}}'),
        ("hand", "Hand (Bonus)", '["mage"]', 2, 2, 0, 1, 0, "esp", 5, "mana", 0, 2, "Main.", "utilitaire", "tronc", '{"rp_effect": "Manipule objet 5kg/10m."}'),
        ("stimme", "Stimme (Bonus)", '["mage"]', 2, 2, 0, 2, 0, "esp", 3, "mana", 0, 2, "Voix.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Avantage sur jet Oral."}'),

        # P3 (+3 Base, +1 Pièce)
        ("schild_normal", "Schild (Bonus)", '["mage"]', 3, 3, 5, 3, 4, "esp", 10, "mana", 0, 2, "Bouclier Zone.", "defense", "tronc", '{"seuil": 2, "reduce_dmg_dynamic": true, "rp_effect": "Protège aussi un allié adjacent."}'),
        ("funke", "Funke", '["mage"]', 3, 3, 11, 3, 2, "esp", 12, "mana", 0, 2, "Grosse étincelle.", "actif", "tronc", '{"status": {"brulure": 3}}'),
        ("nebel", "Nebel", '["mage"]', 3, 3, 9, 4, 3, "esp", 12, "mana", 0, 3, "Brouillard.", "actif", "tronc", '{"status": {"poison": 3}}'),
        ("feder", "Feder (Bonus)", '["mage"]', 3, 3, 0, 1, 0, "esp", 5, "mana", 0, 2, "Poids plume.", "utilitaire", "tronc", "{}"),
        ("schloss", "Schloss (Bonus)", '["mage"]', 3, 3, 0, 2, 0, "esp", 6, "mana", 0, 2, "Serrure.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Ouvre/Ferme serrure magiquement."}'),
        ("fliegen", "Fliegen (Bonus)", '["mage"]', 3, 3, 0, 1, 0, "esp", 8, "mana", 0, 2, "Vol.", "utilitaire", "tronc", '{"rp_effect": "Vol 10min."}'),
        ("klinge", "Klinge", '["mage"]', 3, 3, 7, 5, 3, "esp", 11, "mana", 0, 2, "Lame vent.", "actif", "tronc", '{"seuil": 2, "status": {"hemorragie": 3}}'),
        ("golem", "Golem (Bonus)", '["mage"]', 3, 3, 3, 3, 0, "esp", 15, "mana", 0, 4, "Invocation.", "actif", "tronc", '{"seuil": 1, "summon": "golem", "rp_effect": "Golem 20 PV actif."}'),

        # P4 (+4 Base, +1 Pièce)
        ("zooltrak_avance", "Zooltrak Avancé", '["mage"]', 4, 4, 16, 3, 7, "esp", 18, "mana", 0, 0, "Perce-Défense.", "actif", "tronc", '{"ignore_armor": true}'),
        ("donner", "Donner", '["mage"]', 4, 4, 12, 5, 4, "esp", 16, "mana", 0, 2, "Tonnerre.", "actif", "tronc", '{"seuil": 3, "status": {"stun": 1}, "ricochet": true}'),
        ("vulkan", "Vulkan", '["mage"]', 4, 4, 14, 4, 6, "esp", 20, "mana", 0, 3, "Éruption.", "actif", "tronc", '{"seuil": 1, "status": {"brulure": 4}}'),
        ("teleport", "Teleport (Bonus)", '["mage"]', 4, 4, 0, 1, 0, "esp", 25, "mana", 0, 4, "Téléportation.", "utilitaire", "tronc", '{"rp_effect": "Voyage instantané ou Fuite auto."}'),
        ("spiegel", "Spiegel", '["mage"]', 4, 4, 4, 3, 0, "esp", 15, "mana", 0, 3, "Miroir.", "defense", "tronc", '{"seuil": 1, "rp_effect": "Annule la prochaine attaque (Clone)."}'),
        ("analyse", "Analyse (Bonus)", '["mage"]', 4, 4, 0, 2, 0, "esp", 12, "mana", 0, 0, "Scan.", "utilitaire", "tronc", '{"rp_effect": "Révèle PV, Faiblesses et Résistances."}'),

        # P5 (+5 Base, +1 Pièce)
        ("schild_avance_mage", "Schild Avancé (Bonus)", '["mage"]', 5, 5, 12, 2, 6, "esp", 22, "mana", 0, 2, "Forteresse.", "defense", "tronc", '{"seuil": 1, "reduce_dmg_dynamic": true, "reflect_dmg_percent": 50, "rp_effect": "Renvoie 50pourcent des dégâts."}'),
        ("funke_avance", "Funke Avancé", '["mage"]', 5, 5, 19, 3, 5, "esp", 24, "mana", 0, 2, "Orage.", "actif", "tronc", '{"status": {"brulure": 5}}'),
        ("nebel_avance", "Nebel Avancé", '["mage"]', 5, 5, 17, 4, 4, "esp", 23, "mana", 0, 2, "Nuage Gigantesque.", "actif", "tronc", '{"status": {"poison": 3}, "aoe": true}'),
        ("meteor", "Meteor", '["mage"]', 5, 5, 25, 4, 10, "esp", 40, "mana", 0, 3, "Météore.", "actif", "tronc", '{"seuil": 2, "aoe": true, "terrain_destruct": true}'),
        ("schwarzes_loch", "Schwarzes Loch", '["mage"]', 5, 5, 20, 6, 5, "esp", 30, "mana", 0, 4, "Trou Noir.", "actif", "tronc", '{"seuil": 4, "execute_flat": 30}'),
        ("jigoku", "Jigoku", '["mage"]', 5, 5, 17, 5, 6, "esp", 30, "mana", 0, 2, "Tempête Feu.", "actif", "tronc", '{"status": {"brulure": 4}, "status_cumul": true}'),
        ("judrajim", "Judrajim", '["mage"]', 5, 5, 25, 6, 5, "esp", 45, "mana", 0, 4, "Ruine.", "actif", "tronc", '{"status": {"stun": 1}, "ricochet": true}'),



        
        # ==================== GUERRIER - TRONC COMMUN ====================
        # PALLIER 1
        ("frappe_lourde_novice", "Frappe Lourde Novice", '["guerrier"]', 1, 0, 4, 3, 2, "phy", 0, "tension", 0, 0, "Un coup d'arme basique et efficace.", "actif", "tronc", '{"generate_tension": 1}'),
        ("schnitt_novice", "Schnitt Novice", '["guerrier"]', 1, 1, 4, 4, 1, "phy", 1, "tension", 0, 2, "Une entaille vicieuse visant une zone non protégée.", "actif", "tronc", '{"seuil": 1, "status": {"hemorragie": 2}}'),
        ("fegen_novice", "Fegen Novice", '["guerrier"]', 1, 1, 3, 4, 3, "phy", 1, "tension", 0, 2, "Un balayage bas visant les jambes pour faire chuter.", "actif", "tronc", '{"seuil": 2, "status": {"root": 1}}'),
        ("zorn_novice", "Zorn Novice", '["guerrier"]', 1, 1, 5, 4, 4, "phy", 1, "tension", 0, 2, "Une frappe alimentée par la colère.", "actif", "tronc", '{"self_damage": 5}'),
        ("hieb", "Hieb", '["guerrier"]', 1, 1, 5, 4, 1, "phy", 0, "tension", 0, 2, "Un coup d'arme brutal, parfait pour tester la garde adverse.", "actif", "tronc", '{"seuil": 1, "generate_tension": 1}'),
        ("stoss", "Stoss", '["guerrier"]', 1, 1, 6, 4, 2, "phy", 1, "tension", 0, 2, "Une frappe d'estoc directe et ultra-rapide conçue pour percer.", "actif", "tronc", '{"guaranteed_dmg": 5}'),
        ("atem", "Atem (Bonus)", '["guerrier"]', 1, 1, 0, 1, 0, "phy", 1, "tension", 0, 2, "Une technique de respiration pour ignorer la douleur.", "defense", "tronc", '{"seuil": 1, "reduce_dmg_flat": 4}'),
        ("instinkt", "Instinkt (Bonus)", '["guerrier"]', 1, 1, 0, 3, 0, "phy", 1, "tension", 0, 2, "Les sens s'aiguisent pour repérer le danger immédiat.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Détecte embuscade, piège ou ennemi caché."}'),
        ("blick", "Blick (Bonus)", '["guerrier"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 2, "Un simple regard noir.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Force un PNJ civil ou lâche à révéler une information sans avoir besoin de le frapper."}'),

        # PALLIER 2
        ("frappe_lourde", "Frappe Lourde Évoluée", '["guerrier"]', 2, 2, 6, 5, 3, "phy", 0, "tension", 0, 0, "Le coup de base du guerrier, affiné par l'expérience.", "actif", "tronc", '{"generate_tension": 1}'),
        ("ansturm", "Ansturm", '["guerrier"]', 2, 2, 7, 5, 2, "phy", 2, "tension", 0, 2, "Une charge où le guerrier se jette pour renverser l'ennemi.", "actif", "tronc", '{"seuil": 2, "status": {"stun": 1}}'),
        ("spalten", "Spalten", '["guerrier"]', 2, 2, 8, 4, 4, "phy", 2, "tension", 0, 3, "Un coup vertical dévastateur conçu pour fendre les boucliers et les armures.", "actif", "tronc", '{"guaranteed_dmg": 5, "status": {"hemorragie": 1}}'),
        ("wille", "Wille (Bonus)", '["guerrier"]', 2, 2, 0, 2, 0, "phy", 1, "tension", 0, 2, "Un effort mental pour rejeter une affliction.", "utilitaire", "tronc", '{"seuil": 1, "cleanse_self": true}'),
        ("wut", "Wut (Bonus)", '["guerrier"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 4, "Laisse la rage prendre le dessus pour ignorer la fatigue.", "utilitaire", "tronc", '{"seuil": 1, "generate_tension": 3, "self_damage": 10}'),
        ("gehor", "Gehör (Bonus)", '["guerrier"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 2, "Une concentration absolue sur les bruits environnants.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Permet d\'entendre à travers les murs épais ou de repérer des ennemis invisibles."}'),

        # PALLIER 3
        ("schnitt_normal", "Schnitt", '["guerrier"]', 3, 3, 6, 6, 2, "phy", 2, "tension", 0, 2, "L'entaille devient béante, tranchant profondément la chair.", "actif", "tronc", '{"seuil": 2, "status": {"hemorragie": 3}}'),
        ("fegen_normal", "Fegen", '["guerrier"]', 3, 3, 5, 5, 4, "phy", 2, "tension", 0, 2, "Un fauchage brisant les appuis de la cible.", "actif", "tronc", '{"seuil": 2, "status": {"root": 1}, "bonus_vs_status": "root", "bonus_val": 5}'),
        ("zorn_normal", "Zorn", '["guerrier"]', 3, 3, 8, 5, 4, "phy", 2, "tension", 0, 2, "Une attaque aveugle avec une force démesurée.", "actif", "tronc", '{"self_damage": 8}'),
        ("wirbelwind", "Wirbelwind", '["guerrier"]', 3, 3, 8, 6, 2, "phy", 2, "tension", 0, 2, "Une rotation meurtrière balayant tout autour du guerrier.", "actif", "tronc", '{"seuil": 2, "aoe": true}'),
        ("knochenbrecher", "Knochenbrecher", '["guerrier"]', 3, 3, 9, 6, 4, "phy", 2, "tension", 0, 3, "Une frappe écrasante visant à briser les os.", "actif", "tronc", '{"seuil": 3, "status": {"mutilation": 1}}'),
        ("schleifen", "Schleifen (Bonus)", '["guerrier"]', 3, 3, 0, 2, 0, "phy", 1, "tension", 0, 2, "Prend un instant pour aiguiser sa lame.", "utilitaire", "tronc", '{"seuil": 1, "self_status": {"dmg_boost": 5}}'),
        ("drohung", "Drohung (Bonus)", '["guerrier"]', 3, 3, 0, 2, 0, "phy", 1, "tension", 0, 2, "Une posture ou un cri de guerre si terrifiant qu'il paralyse.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Confère un Avantage majeur sur un jet d\'Intimidation de masse ou dissipe une émeute."}'),
        ("tragen", "Tragen (Bonus)", '["guerrier"]', 3, 3, 0, 1, 0, "phy", 1, "tension", 0, 2, "Déploie une force herculéenne momentanée.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Permet de soulever une charge impossible comme un rocher ou une herse."}'),

        # PALLIER 4
        ("frappe_lourde_avancee", "Frappe Lourde Avancée", '["guerrier"]', 4, 4, 8, 7, 4, "phy", 0, "tension", 0, 0, "La quintessence de la maîtrise martiale, alliant poids et précision.", "actif", "tronc", '{"generate_tension": 1}'),
        ("hinrichten", "Hinrichten", '["guerrier"]', 4, 4, 12, 7, 5, "phy", 3, "tension", 0, 3, "Le coup de grâce, réservé aux ennemis brisés.", "actif", "tronc", '{"seuil": 4, "execute_percent": 25}'),
        ("erdbeben", "Erdbeben", '["guerrier"]', 4, 4, 10, 7, 4, "phy", 3, "tension", 0, 3, "Frappe le sol avec une telle puissance que la terre se fracture.", "actif", "tronc", '{"seuil": 3, "aoe": true, "terrain_destruct": true}'),
        ("eiserner_wille", "Eiserner Wille (Bonus)", '["guerrier"]', 4, 4, 0, 2, 0, "phy", 2, "tension", 0, 4, "Une détermination d'acier qui repousse les intrusions mentales.", "utilitaire", "tronc", '{"seuil": 1, "cleanse_self": true, "rp_effect": "Purge instantanément tous les contrôles (Étourdissement, Enracinement, Sommeil, Gel) sur soi-même."}'),
        ("sprung", "Sprung (Bonus)", '["guerrier"]', 4, 4, 0, 2, 0, "phy", 1, "tension", 0, 2, "Un saut surhumain.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Permet de bondir par-dessus un ravin de 15 mètres ou d\'atteindre le sommet d\'un batiment."}'),
        ("uberleben", "Überleben (Bonus)", '["guerrier"]', 4, 4, 0, 2, 0, "phy", 0, "tension", 0, 2, "Un instinct de survie forgé dans les pires conditions.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Permet de survivre nu dans un blizzard, de digérer du poison naturel ou de résister à la soif."}'),

        # PALLIER 5
        ("schnitt_avance", "Schnitt Avancé", '["guerrier"]', 5, 5, 9, 8, 3, "phy", 3, "tension", 0, 2, "L'air lui-même semble trancher la chair (Stade 3).", "actif", "tronc", '{"seuil": 3, "status": {"hemorragie": 5}}'),
        ("fegen_avance", "Fegen Avancé", '["guerrier"]', 5, 5, 8, 8, 5, "phy", 3, "tension", 0, 2, "Une onde de choc au sol brisant les jambes (Stade 3).", "actif", "tronc", '{"seuil": 3, "status": {"root": 1}, "aoe": true}'),
        ("zorn_avance", "Zorn Avancé", '["guerrier"]', 5, 5, 12, 8, 6, "phy", 3, "tension", 0, 2, "La colère d'un dieu de la guerre (Stade 3).", "actif", "tronc", '{"self_damage": 12, "ignore_armor": true}'),
        ("kometenschlag", "Kometenschlag", '["guerrier"]', 5, 5, 16, 8, 6, "phy", 4, "tension", 0, 3, "Un saut prodigieux suivi d'un impact météoritique.", "actif", "tronc", '{"seuil": 4, "aoe": true, "terrain_destruct": true}'),
        ("verwustung", "Verwüstung", '["guerrier"]', 5, 5, 14, 8, 5, "phy", 3, "tension", 0, 3, "Un déluge ininterrompu de frappes d'une lourdeur effroyable.", "actif", "tronc", '{"seuil": 4, "ricochet": true}'),
        ("unsterblich", "Unsterblich (Bonus)", '["guerrier"]', 5, 5, 0, 1, 0, "phy", 4, "tension", 0, 6, "Le refus catégorique de mourir.", "defense", "tronc", '{"seuil": 1, "self_status": {"unsterblich": 9999}, "rp_effect": "Vous donne la marque de l’indomptable : Si une attaque doit vous mettre ko, vous restez à 1 PV."}'),
        ("aura", "Aura (Bonus)", '["guerrier"]', 5, 5, 0, 2, 0, "phy", 1, "tension", 0, 0, "Une présence si oppressante que l'air devient lourd.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Les ennemis de faible volonté fuient instantanément."}'),
        ("titanenblut", "Titanenblut (Bonus)", '["guerrier"]', 5, 5, 0, 2, 0, "phy", 3, "tension", 0, 4, "Le sang bout et les muscles se gonflent de manière inhumaine.", "utilitaire", "tronc", '{"seuil": 1, "self_status": {"titanenblut": 3}, "rp_effect": "Pendant 3 tours, vous gagnez 10pv par tour et toutes vos attaque gagne une pièce."}'),
        
        # ==================== PRETRE - TRONC COMMUN ====================
        # Base
        ("lumiere_divine", "Lumière Divine", '["pretre"]', 1, 0, 3, 4, 1, "foi", 10, "ferveur", 0, 0, "Rayon de lumière sacrée.", "actif", "tronc", "{}"),
        
        # PALLIER 1 (Coût: 1)
        ("heilung_novice", "Heilung Novice", '["pretre"]', 1, 1, 4, 3, 2, "foi", 15, "ferveur", 0, 2, "Soin divin léger qui referme les blessures.", "soin", "tronc", "{}"),
        ("bann_novice", "Bann Novice", '["pretre"]', 1, 1, 3, 2, 2, "foi", 12, "ferveur", 0, 2, "Fige partiellement la cible.", "actif", "tronc", '{"seuil": 1, "status": {"stun": 1}}'),
        ("schild_novice_pretre", "Schild Novice (Bonus)", '["pretre"]', 1, 1, 2, 2, 3, "foi", 15, "ferveur", 0, 2, "Barrière divine protectrice.", "defense", "tronc", '{"seuil": 1, "reduce_dmg_dynamic": true}'),
        ("urteil", "Urteil", '["pretre"]', 1, 1, 5, 2, 3, "foi", 10, "ferveur", 0, 0, "Un marteau de lumière tombe sur la cible.", "actif", "tronc", "{}"),
        ("heiliger_speer", "Heiliger Speer", '["pretre"]', 1, 1, 8, 3, 3, "foi", 15, "ferveur", 1, 3, "Lance de lumière perforante (Coûte 1 Verset).", "actif", "tronc", '{"ignore_armor": true}'),
        ("wahrheit", "Wahrheit (Bonus)", '["pretre"]', 1, 1, 0, 2, 0, "foi", 5, "ferveur", 0, 2, "Détecte les mensonges.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Avantage narratif pour discerner la vérité."}'),
        ("segnung", "Segnung (Bonus)", '["pretre"]', 1, 1, 0, 1, 0, "foi", 10, "ferveur", 0, 2, "Purifie les vivres.", "utilitaire", "tronc", '{"rp_effect": "Purifie l eau et la nourriture."}'),
        ("zuflucht", "Zuflucht (Bonus)", '["pretre"]', 1, 1, 0, 1, 0, "foi", 15, "ferveur", 2, 3, "Sanctuaire divin absolu (Coûte 2 Versets).", "defense", "tronc", '{"rp_effect": "Inciblable et invulnérable jusqu au prochain tour."}'),

        # PALLIER 2 (Coût: 2)
        ("lumiere_divine_2", "Lumière Divine Évoluée", '["pretre"]', 2, 2, 6, 4, 2, "foi", 15, "ferveur", 0, 0, "Le rayon gagne en intensité.", "actif", "tronc", "{}"),
        ("heilige_aura_novice", "Heilige Aura Novice", '["pretre"]', 2, 2, 6, 3, 3, "foi", 20, "ferveur", 0, 2, "Onde d énergie purificatrice.", "actif", "tronc", '{"seuil": 1, "aoe": true}'),
        ("lichtstrahl", "Lichtstrahl", '["pretre"]', 2, 2, 9, 4, 2, "foi", 15, "ferveur", 0, 2, "Rayon de lumière aveuglant.", "actif", "tronc", '{"seuil": 2, "status": {"brulure": 2}}'),
        ("zorn_gottes", "Zorn Gottes", '["pretre"]', 2, 2, 11, 4, 2, "foi", 25, "ferveur", 3, 3, "Éclair du ciel étourdissant (Coûte 3 Versets).", "actif", "tronc", '{"seuil": 2, "status": {"stun": 1}}'),
        ("vision", "Vision (Bonus)", '["pretre"]', 2, 2, 0, 2, 0, "foi", 10, "ferveur", 0, 2, "Vision véritable.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Permet de voir les entités invisibles ou illusions."}'),
        ("stimme_gottes", "Stimme Gottes (Bonus)", '["pretre"]', 2, 2, 0, 2, 0, "foi", 10, "ferveur", 0, 2, "Autorité divine.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Force un groupe de PNJ à cesser le combat."}'),
        ("wunder", "Wunder (Bonus)", '["pretre"]', 2, 2, 0, 2, 0, "foi", 20, "ferveur", 3, 4, "Miracle mineur (Coûte 3 Versets).", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Altère légèrement la réalité (réparer, ouvrir, etc.)."}'),

        # PALLIER 3 (Coût: 3)
        ("heilung_normal", "Heilung", '["pretre"]', 3, 3, 9, 4, 3, "foi", 25, "ferveur", 0, 2, "Soin purificateur plus puissant.", "soin", "tronc", '{"seuil": 1, "cleanse_target": true}'),
        ("bann_normal", "Bann", '["pretre"]', 3, 3, 7, 3, 3, "foi", 20, "ferveur", 0, 2, "Chaines sacrées brûlantes.", "actif", "tronc", '{"seuil": 1, "status": {"stun": 1, "brulure": 1}}'),
        ("schild_normal_pretre", "Schild (Bonus)", '["pretre"]', 3, 3, 5, 3, 4, "foi", 25, "ferveur", 0, 2, "Barrière de groupe protectrice.", "defense", "tronc", '{"seuil": 2, "reduce_dmg_dynamic": true}'),
        ("klingen", "Klingen", '["pretre"]', 3, 3, 11, 5, 2, "foi", 25, "ferveur", 0, 2, "Projectiles de lumière traqueurs.", "actif", "tronc", '{"seuil": 2, "ricochet": true}'),
        ("himmelsfeuer", "Himmelsfeuer", '["pretre"]', 3, 3, 20, 5, 4, "foi", 35, "ferveur", 6, 3, "Tempête de flammes sacrées (Coûte 6 Versets).", "actif", "tronc", '{"seuil": 3, "aoe": true, "status": {"brulure": 3}}'),
        ("exorzismus", "Exorzismus (Bonus)", '["pretre"]', 3, 3, 0, 2, 0, "foi", 15, "ferveur", 0, 2, "Contrôle mental divin.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Vous envoûtez l esprit d une personne pour un ordre non létal."}'),
        ("heiliger_boden", "Heiliger Boden (Bonus)", '["pretre"]', 3, 3, 0, 2, 0, "foi", 15, "ferveur", 0, 3, "Zone anti-affliction.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Dissipe les effets sur vous et vos alliés. (À retirer manuellement avec /retire_effet)"}'),
        ("erweckung", "Erweckung (Bonus)", '["pretre"]', 3, 3, 15, 3, 5, "foi", 30, "ferveur", 5, 4, "Donnez la force de combattre a un allié KO (Coûte 5 Versets).", "soin", "tronc", '{"seuil": 1, "rp_effect": "Réveille instantanément un allié tombé à 0 PV. (Ajustez les PV manuellement via /set_stat)"}'),

        # PALLIER 4 (Coût: 4)
        ("lumiere_divine_3", "Lumière Divine Avancée", '["pretre"]', 4, 4, 10, 5, 3, "foi", 25, "ferveur", 0, 0, "Pilier de lumière écrasant.", "actif", "tronc", "{}"),
        ("heilige_aura_normal", "Heilige Aura", '["pretre"]', 4, 4, 10, 4, 4, "foi", 30, "ferveur", 0, 2, "Explosion purificatrice totale.", "actif", "tronc", '{"seuil": 2, "aoe": true, "cleanse_self": true}'),
        ("licht_nova", "Licht Nova", '["pretre"]', 4, 4, 13, 5, 3, "foi", 25, "ferveur", 0, 2, "Onde de choc lumineuse.", "actif", "tronc", '{"seuil": 2, "aoe": true}'),
        ("judgement", "Judgement", '["pretre"]', 4, 4, 25, 5, 6, "foi", 40, "ferveur", 7, 4, "Épée sacrée géante (Coûte 7 Versets).", "actif", "tronc", '{"seuil": 3, "execute_percent": 20}'),
        ("glaubensprufung", "Glaubensprüfung (Bonus)", '["pretre"]', 4, 4, 0, 2, 0, "foi", 20, "ferveur", 0, 2, "Sonde l âme de la cible.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Dévoile alignement, péchés et peurs d un PNJ."}'),
        ("himmelswache", "Himmelswache (Bonus)", '["pretre"]', 4, 4, 0, 3, 0, "foi", 25, "ferveur", 0, 2, "Invoque un gardien spirituel.", "utilitaire", "tronc", '{"seuil": 2, "rp_effect": "Avatar d énergie montant la garde pendant 1h."}'),
        ("unantastbar", "Unantastbar (Bonus)", '["pretre"]', 4, 4, 0, 2, 0, "foi", 35, "ferveur", 6, 5, "Invulnérabilité divine (Coûte 6 Versets).", "defense", "tronc", '{"self_status": {"unsterblich": 1}}'),

        # PALLIER 5 (Coût: 5)
        ("heilung_avance", "Heilung Avancé", '["pretre"]', 5, 5, 16, 5, 4, "foi", 35, "ferveur", 0, 2, "Guérit toutes les blessures de la zone.", "soin", "tronc", '{"seuil": 2, "aoe": true, "cleanse_target": true}'),
        ("bann_avance", "Bann Avancé", '["pretre"]', 5, 5, 12, 5, 4, "foi", 30, "ferveur", 0, 2, "Fige totalement le champ de bataille.", "actif", "tronc", '{"seuil": 2, "aoe": true, "status": {"stun": 1}}'),
        ("schild_avance_pretre", "Schild Avancé (Bonus)", '["pretre"]', 5, 5, 12, 3, 6, "foi", 35, "ferveur", 0, 2, "Protection absolue de la déesse.", "defense", "tronc", '{"seuil": 1, "reduce_dmg_dynamic": true, "reflect_dmg_percent": 50}'),
        ("sonnensturm", "Sonnensturm", '["pretre"]', 5, 5, 18, 6, 4, "foi", 40, "ferveur", 0, 3, "Tempête de flammes solaires.", "actif", "tronc", '{"seuil": 3, "aoe": true, "status": {"brulure": 5}}'),
        ("mirai", "Mirai (Bonus)", '["pretre"]', 5, 5, 0, 1, 0, "foi", 70, "ferveur", 8, 5, "Maîtrise du temps (Coûte 8 Versets).", "soin", "tronc", '{"rp_effect": "Un allié choisi doit faire la commande /repos."}'),
        ("prophetie", "Prophetie (Bonus)", '["pretre"]', 5, 5, 0, 2, 0, "foi", 30, "ferveur", 0, 0, "Entrevoit les fils du destin.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Le MJ révèle un indice ou la faiblesse majeure d un boss."}'),
        ("wunder_gottes", "Wunder Gottes (Bonus)", '["pretre"]', 5, 5, 0, 2, 0, "foi", 60, "ferveur", 0, 0, "Miracle défiant la nature.", "utilitaire", "tronc", '{"seuil": 1, "rp_effect": "Modifie la réalité à grande échelle (montagnes, rivières...)."}'),
        ("wiederauferstehung", "Wiederauferstehung (Bonus)", '["pretre"]', 5, 5, 0, 2, 0, "foi", 80, "ferveur", 8, 11, "Le pouvoir ultime sur la mort (Coûte 8 Versets).", "soin", "tronc", '{"seuil": 1, "rp_effect": "Ramène à la vie un allié mort il y a une heure ou moins. (Restituer ses PV manuellement avec /set_stat)"}'),

    
        # ====================================================================================
        # MAGIE DU SANG — Sous-classe Mage 
        # ====================================================================================

        # --- PASSIFS ---
        ("passif_festin_stade1",  "[Festin Stade 1] (Passif)",   '["magie_sang"]', 1, 1, 0,0,0,"esp",0,"mana",0,0, "Tronc commun : +3 dégâts finaux (Stade 1+).", "passif", "spe", '{"passif": "festin_stade1"}'),
        ("passif_festin_stade2",  "[Festin Stade 2] (Passif)",   '["magie_sang"]', 2, 2, 0,0,0,"esp",0,"mana",0,0, "Tronc commun : +6 dégâts + Hémorragie auto (Stade 2+).", "passif", "spe", '{"passif": "festin_stade2"}'),
        ("passif_festin_stade3",  "[Festin Stade 3] (Passif)",   '["magie_sang"]', 3, 3, 0,0,0,"esp",0,"mana",0,0, "Sorts de sous-classe infligent leurs dégâts (Stade 3+).", "passif", "spe", '{"passif": "festin_stade3"}'),
        ("passif_sang_hote",      "[L'Hôte du Banquet] (Passif)",'["magie_sang"]', 4, 4, 0,0,0,"esp",0,"mana",0,0, "Commence chaque combat à 10 Festin.", "passif", "spe", '{"passif": "sang_hote"}'),
        ("passif_sang_aieux",     "[Le Sang de l'Aïeul] (Passif)",'["magie_sang"]',5, 5, 0,0,0,"esp",0,"mana",0,0, "La jauge de Festin monte jusqu'à 40 (Stade 4 accessible).", "passif", "spe", '{"passif": "sang_aieux"}'),

        # --- PALLIER 1 ---
        ("sang_ciseaux_novice",   "Ciseaux de Sang Novice",       '["magie_sang"]', 1, 1, 6, 3, 3, "esp", 6, "mana", 0, 2,  "Projets deux lames de sang tranchantes.", "actif", "spe",   '{"generate_festin": 4, "no_dmg_unless_stade3": true, "seuil": 1, "status": {"hemorragie": 2}}'),        ("sang_ombrelle_novice",  "Ombrelle Écarlate Novice (Bonus)", '["magie_sang"]', 1, 1, 0, 2, 3, "esp", 5, "mana", 0, 2, "Bouclier de sang cristallisé.", "defense", "spe", '{"generate_festin": 4, "seuil": 1, "reduce_dmg_flat": 5}'),        ("sang_siphon_novice",    "Siphon Aristocratique Novice", '["magie_sang"]', 1, 1, 5, 3, 3, "esp", 5, "mana", 0, 2,  "Aspire le sang de la cible pour se soigner.", "actif", "spe",  '{"generate_festin": 5, "no_dmg_unless_stade3": true, "seuil": 1, "lifesteal_flat": 4}'),        ("sang_degustation",      "Dégustation (Bonus)",          '["magie_sang"]', 1, 1, 0, 1, 0, "esp", 4, "mana", 0, 0,  "Analyse l'essence vitale d'une cible.", "utilitaire", "spe",  '{"generate_festin": 4, "rp_effect": "Révèle la race, les afflictions actives et les PV approximatifs de la cible."}'),
        ("sang_parfum",           "Parfum d'Hémoglobine (Bonus)", '["magie_sang"]', 1, 1, 0, 1, 0, "esp", 3, "mana", 0, 0,  "Perçoit le sang à distance.", "utilitaire", "spe",  '{"generate_festin": 4, "rp_effect": "Localise toute créature vivante dans un rayon de 30m pendant 1 tour."}'),

        # --- PALLIER 2 ---
        ("sang_broderie_novice",  "Broderie Macabre Novice",      '["magie_sang"]', 2, 2, 7, 4, 3, "esp", 8, "mana", 0, 2,  "Tisse des fils de sang pour ligoter l'ennemi.", "actif", "spe",   '{"generate_festin": 6, "no_dmg_unless_stade3": true, "seuil": 2, "status": {"root": 2}}'),        ("sang_baiser_novice",    "Baiser du Vampire Novice",     '["magie_sang"]', 2, 2, 0, 3, 4, "esp", 8, "mana", 0, 3,  "Morsure vampirique qui draine la vie.", "actif", "spe",    '{"generate_festin": 6, "no_dmg_unless_stade3": true, "seuil": 1, "lifesteal_flat": 6}'),        ("sang_tenue",            "Tenue de Soirée (Bonus)",      '["magie_sang"]', 2, 2, 0, 2, 0, "esp", 6, "mana", 0, 2,  "Illusion de noblesse vampirique.", "utilitaire", "spe",  '{"generate_festin": 5, "rp_effect": "Avantage sur les jets d\'Oral et de Discrétion pendant 1 scène."}'),
        ("sang_analyse_spe",      "Analyse Vampirique (Bonus)",   '["magie_sang"]', 2, 2, 0, 2, 0, "esp", 10, "mana", 0, 0, "Perçoit les faiblesses sanguines.", "utilitaire", "spe",  '{"generate_festin": 5, "rp_effect": "Révèle la faiblesse et la résistance principale de la cible."}'),
        ("sang_encre",            "Sang d'Encre (Bonus)",         '["magie_sang"]', 2, 2, 0, 2, 0, "esp", 6, "mana", 0, 2,  "Projette un nuage d'encre sanguine aveuglant.", "utilitaire", "spe",  '{"generate_festin": 5, "seuil": 1, "rp_effect": "Aveugle les ennemis dans un cône de 5m pendant 1 tour."}'),

        # --- PALLIER 3 ---
        ("sang_ciseaux",          "Ciseaux de Sang",              '["magie_sang"]', 3, 3, 11, 4, 4, "esp", 12, "mana", 0, 2,  "Lames de sang renforcées par le Festin.", "actif", "spe",   '{"generate_festin": 7, "no_dmg_unless_stade3": true, "seuil": 1, "status": {"hemorragie": 3}}'),        ("sang_ombrelle",         "Ombrelle Écarlate (Bonus)",    '["magie_sang"]', 3, 3, 0, 3, 4, "esp", 10, "mana", 0, 2,  "Bouclier de sang avancé avec contre-attaque.", "defense", "spe",  '{"generate_festin": 7, "seuil": 2, "reduce_dmg_flat": 10, "reflect_dmg_percent": 30}'),        ("sang_siphon",           "Siphon Aristocratique",        '["magie_sang"]', 3, 3, 10, 4, 4, "esp", 12, "mana", 0, 2,  "Drain puissant qui nourrit abondamment.", "actif", "spe",    '{"generate_festin": 8, "no_dmg_unless_stade3": true, "seuil": 1, "lifesteal_flat": 10}'),        ("sang_banquet",          "Règles du Banquet (Bonus)",    '["magie_sang"]', 3, 3, 0, 2, 0, "esp", 10, "mana", 0, 3,  "Impose les règles de l'aristocratie vampirique.", "utilitaire", "spe",  '{"generate_festin": 7, "rp_effect": "Force une cible humanoïde à respecter une règle de conduite pendant 1 scène."}'),
        ("sang_millesime",        "Millésime Écarlate (Bonus)",   '["magie_sang"]', 3, 3, 0, 2, 0, "esp", 8, "mana", 0, 2,  "Consomme du Festin pour soigner.", "soin", "spe",  '{"generate_festin": -5, "festin_heal": true}'),

        # --- PALLIER 4 ---
        ("sang_broderie",         "Broderie Macabre",             '["magie_sang"]', 4, 4, 15, 5, 4, "esp", 18, "mana", 0, 3,  "Les fils de sang transpercent et contorsionnent.", "actif", "spe",  '{"generate_festin": 8, "no_dmg_unless_stade3": true, "seuil": 2, "status": {"root": 2, "hemorragie": 2}}'),        ("sang_baiser",           "Baiser du Vampire",            '["magie_sang"]', 4, 4, 0, 4, 5, "esp", 16, "mana", 0, 3,  "Drain vampirique total : sang, mana et vitalité.", "actif", "spe",   '{"generate_festin": 9, "no_dmg_unless_stade3": true, "seuil": 2, "lifesteal_flat": 14, "restore_mana": 5}'),        ("sang_terreur",          "Aura de Terreur (Bonus)",      '["magie_sang"]', 4, 4, 0, 3, 0, "esp", 14, "mana", 0, 4,  "Rayonne une terreur aristocratique paralysante.", "utilitaire", "spe",  '{"generate_festin": 8, "seuil": 2, "rp_effect": "Applique la Peur à tous les ennemis humanoïdes dans 10m. Jet de résistance ou fuite."}'),
        ("sang_invitation",       "Invitation au Bal (Bonus)",    '["magie_sang"]', 4, 4, 0, 2, 0, "esp", 12, "mana", 0, 3,  "Attire irrésistiblement une cible vers soi.", "utilitaire", "spe",  '{"generate_festin": 7, "seuil": 1, "rp_effect": "Téléporte une cible consentante ou vaincue à 5m de soi."}'),
        ("sang_regard",           "Regard Hypnotique (Bonus)",    '["magie_sang"]', 4, 4, 0, 3, 0, "esp", 14, "mana", 0, 4,  "Plonge une cible dans une transe vampirique.", "utilitaire", "spe",  '{"generate_festin": 8, "seuil": 2, "rp_effect": "Contrôle une cible non-résistante pendant 1 tour (ordres simples)."}'),

        # --- PALLIER 5 ---
        ("sang_ciseaux_avance",   "Ciseaux de Sang Avancé",       '["magie_sang"]', 5, 5, 20, 4, 6, "esp", 24, "mana", 0, 3,  "La forme ultime : une volée de lames inévitables.", "actif", "spe",  '{"generate_festin": 10, "no_dmg_unless_stade3": true, "seuil": 1, "status": {"hemorragie": 4}, "aoe": true}'),        ("sang_ombrelle_avance",  "Ombrelle Écarlate Avancée (Bonus)",'["magie_sang"]',5, 5, 0, 3, 5, "esp", 22, "mana", 0, 3, "Forteresse de sang impénétrable.", "defense", "spe", '{"generate_festin": 10, "seuil": 2, "reduce_dmg_dynamic": true, "reflect_dmg_percent": 50}'),        ("sang_siphon_avance",    "Siphon Aristocratique Avancé", '["magie_sang"]', 5, 5, 17, 5, 5, "esp", 28, "mana", 0, 3,  "Drain total : vide la cible de son essence vitale.", "actif", "spe",   '{"generate_festin": 10, "no_dmg_unless_stade3": true, "seuil": 2, "lifesteal_flat": 20, "restore_mana": 10}'),        ("sang_carnaval",         "L'Heure du Carnaval (Bonus)",  '["magie_sang"]', 5, 5, 0, 3, 0, "esp", 20, "mana", 0, 5,  "Transformation en Seigneur Vampire : forme ultime.", "utilitaire", "spe",  '{"generate_festin": 10, "seuil": 2, "self_status": {"mode_sang": 3}, "rp_effect": "Transformation 3 tours : toutes les dépenses de Mana sont payées en PV, dégâts vampiriques doublés."}'),
        ("sang_miroir",           "Miroir de Sang (Bonus)",       '["magie_sang"]', 5, 5, 0, 2, 0, "esp", 18, "mana", 0, 4,  "Crée un double de sang qui absorbe une attaque.", "defense", "spe",  '{"generate_festin": 9, "seuil": 1, "rp_effect": "Annule la prochaine attaque reçue (Clone de sang)."}'),

        # ====================================================================================
        # MAGIE ÉLÉMENTAIRE — Sous-classe Mage
        # ====================================================================================

        # --- PASSIFS ---
        ("passif_elem_affinite",  "[Affinité Naturelle] (Passif)", '["magie_elementaire"]', 1, 1, 0,0,0,"esp",0,"mana",0,0, "Sorts élémentaires coûtent -1 Mana.", "passif", "spe", '{"passif": "elem_affinite"}'),
        ("passif_elem_peau",      "[Peau Élémentaire] (Passif)",   '["magie_elementaire"]', 2, 2, 0,0,0,"esp",0,"mana",0,0, "+1 à tous les bonus de Résonance.", "passif", "spe", '{"passif": "elem_peau"}'),
        ("passif_elem_surcharge", "[Surcharge Élémentaire] (Passif)",'["magie_elementaire"]',3, 3, 0,0,0,"esp",0,"mana",0,0, "Si 3 charges du même élément : -50% Mana sort élémentaire + +2 Résonance.", "passif", "spe", '{"passif": "elem_surcharge"}'),
        ("passif_elem_tempetes",  "[Maître des Tempêtes] (Passif)",'["magie_elementaire"]', 4, 4, 0,0,0,"esp",0,"mana",0,0, "+10PV +15Mana à chaque Décharge + +3 Résonance.", "passif", "spe", '{"passif": "elem_tempetes"}'),
        ("passif_elem_avatar",    "[Avatar des Éléments] (Passif)",'["magie_elementaire"]', 5, 5, 0,0,0,"esp",0,"mana",0,0, "Max charges →4 ; si 4 éléments différents = tous les bonus simultanément.", "passif", "spe", '{"passif": "elem_avatar"}'),

        # --- PALLIER 1 ---
        ("elem_flammes_novice",   "Jet de Flammes Novice",         '["magie_elementaire"]', 1, 1, 7, 3, 3, "esp", 5, "mana", 0, 2,  "Projette un jet de feu concentré.", "actif", "spe",  '{"generate_charge": "feu", "status": {"brulure": 1}}'),        ("elem_souffle_novice",   "Souffle Hivernal Novice (Bonus)",'["magie_elementaire"]', 1, 1, 0, 2, 3, "esp", 5, "mana", 0, 2,  "Souffle d'air glacé ralentissant.", "defense", "spe", '{"generate_charge": "glace", "seuil": 1, "status": {"root": 1}}'),        ("elem_etincelle_novice", "Étincelle Statique Novice",     '["magie_elementaire"]', 1, 1, 6, 3, 3, "esp", 4, "mana", 0, 2,  "Décharge électrostatique rapide.", "actif", "spe",  '{"generate_charge": "foudre", "seuil": 2, "self_status": {"hate": 1}}'),        ("elem_allumeur",         "Allume-Feu (Bonus)",            '["magie_elementaire"]', 1, 1, 0, 1, 0, "esp", 3, "mana", 0, 0,  "Maîtrise élémentaire basique.", "utilitaire", "spe", '{"generate_charge": "feu", "rp_effect": "Allume ou éteint des flammes dans un rayon de 5m."}'),
        ("elem_brise_novice",     "Brise Légère (Bonus)",          '["magie_elementaire"]', 1, 1, 0, 1, 0, "esp", 3, "mana", 0, 0,  "Courant d'air magique.", "utilitaire", "spe",  '{"generate_charge": "air", "rp_effect": "Crée un courant d\'air fort dans une direction. Éteint flammes, chasse gaz."}'),

        # --- PALLIER 2 ---
        ("elem_lance_glace_novice","Lance de Glace Novice",        '["magie_elementaire"]', 2, 2, 8, 4, 3, "esp", 7, "mana", 0, 2,  "Projette un pic de glace acéré.", "actif", "spe",  '{"generate_charge": "glace", "status": {"gel": 1}}'),        ("elem_bourrasque_novice","Bourrasque Novice (Bonus)",      '["magie_elementaire"]', 2, 2, 0, 3, 3, "esp", 6, "mana", 0, 2,  "Rafale de vent tranchante.", "actif", "spe",  '{"generate_charge": "air", "seuil": 2, "status": {"root": 1}}'),        ("elem_thermostat",       "Thermostat (Bonus)",            '["magie_elementaire"]', 2, 2, 0, 1, 0, "esp", 4, "mana", 0, 0,  "Régule la température ambiante.", "utilitaire", "spe",  '{"generate_charge": "feu", "rp_effect": "Chauffe ou refroidit une zone de 10m. Utile contre froid extrême/chaleur."}'),
        ("elem_appel_foudre",     "Appel de la Foudre (Bonus)",    '["magie_elementaire"]', 2, 2, 0, 2, 0, "esp", 6, "mana", 0, 2,  "Attire la foudre sur une cible métallique.", "utilitaire", "spe",  '{"generate_charge": "foudre", "seuil": 1, "rp_effect": "Cible portant métal subit désavantage sur ses jets ce tour."}'),
        ("elem_cristallisation",  "Cristallisation (Bonus)",       '["magie_elementaire"]', 2, 2, 0, 2, 0, "esp", 6, "mana", 0, 2,  "Fige un liquide ou une surface.", "utilitaire", "spe",  '{"generate_charge": "glace", "seuil": 1, "rp_effect": "Cristallise un liquide ou surface humide dans 3m. Crée terrain glissant."}'),

        # --- PALLIER 3 ---
        ("elem_flammes",          "Jet de Flammes",                '["magie_elementaire"]', 3, 3, 12, 3, 4, "esp", 12, "mana", 0, 2,  "Jet de flammes intense et dévastateur.", "actif", "spe",  '{"generate_charge": "feu", "status": {"brulure": 3}}'),        ("elem_lance_glace",      "Lance de Glace",                '["magie_elementaire"]', 3, 3, 11, 4, 4, "esp", 11, "mana", 0, 2,  "Lance de glace solide et perforante.", "actif", "spe",  '{"generate_charge": "glace", "seuil": 1, "status": {"gel": 1}, "guaranteed_dmg": 8}'),        ("elem_eclair",           "Éclair de Choc",                '["magie_elementaire"]', 3, 3, 10, 4, 3, "esp", 10, "mana", 0, 2,  "Éclair de foudre paralysant.", "actif", "spe",  '{"generate_charge": "foudre", "seuil": 2, "status": {"stun": 1}}'),        ("elem_vision_chaleur",   "Vision de Chaleur (Bonus)",     '["magie_elementaire"]', 3, 3, 0, 2, 0, "esp", 8, "mana", 0, 0,  "Vision thermique élémentaire.", "utilitaire", "spe",  '{"generate_charge": "feu", "rp_effect": "Vision thermique pendant 10min : détecte êtres vivants et pièges thermiques."}'),
        ("elem_mur_vent",         "Mur de Vent (Bonus)",           '["magie_elementaire"]', 3, 3, 0, 3, 4, "esp", 10, "mana", 0, 3,  "Crée un mur d'air protecteur.", "defense", "spe",  '{"generate_charge": "air", "seuil": 1, "reduce_dmg_flat": 8, "rp_effect": "Dévie projectiles et attaques à distance."}'),
        # --- PALLIER 4 ---
        ("elem_bourrasque",       "Bourrasque",                    '["magie_elementaire"]', 4, 4, 14, 5, 4, "esp", 16, "mana", 0, 2,  "Rafale déchaînée qui projette les ennemis.", "actif", "spe",  '{"generate_charge": "air", "seuil": 2, "status": {"stun": 1}, "aoe": true}'),        ("elem_supernova",        "Supernova",                     '["magie_elementaire"]', 4, 4, 18, 4, 6, "esp", 20, "mana", 0, 3,  "Explosion ardente consumant tout autour.", "actif", "spe",  '{"generate_charge": "feu", "seuil": 2, "status": {"brulure": 4}, "aoe": true}'),        ("elem_coeur_givre",      "Cœur de Givre (Bonus)",         '["magie_elementaire"]', 4, 4, 0, 3, 0, "esp", 14, "mana", 0, 3,  "Noyau de glace qui ralentit toute la zone.", "utilitaire", "spe",  '{"generate_charge": "glace", "seuil": 2, "rp_effect": "Réduit l\'initiative de tous les ennemis de -3 pendant 2 tours."}'),
        ("elem_transmutation",    "Transmutation Élémentaire (Bonus)",'["magie_elementaire"]',4, 4, 0, 2, 0, "esp", 12, "mana", 0, 3, "Convertit un élément en un autre.", "utilitaire", "spe",  '{"consume_charges": true, "rp_effect": "Échange le type de TOUTES vos charges actuelles contre un élément au choix."}'),
        ("elem_decharge",         "Décharge (Bonus)",              '["magie_elementaire"]', 4, 4, 0, 2, 0, "esp", 8, "mana", 0, 3,  "Libère toutes les charges pour doubler les pièces du prochain sort.", "utilitaire", "spe",  '{"consume_charges": true, "is_decharge": true, "self_status": {"decharge_active": 1}}'),

        # --- PALLIER 5 ---
        ("elem_tempete",          "Tempête Apocalyptique",         '["magie_elementaire"]', 5, 5, 22, 5, 7, "esp", 35, "mana", 0, 4,  "Déchaîne les 4 éléments simultanément.", "actif", "spe",  '{"generate_charge": "foudre", "generate_charge_2": "air", "seuil": 3, "aoe": true, "status": {"stun": 1}}'),        ("elem_zenith",           "Zénith Solaire (Bonus)",        '["magie_elementaire"]', 5, 5, 0, 3, 0, "esp", 30, "mana", 0, 5,  "Invoque le soleil pour brûler la zone.", "actif", "spe",  '{"generate_charge": "feu", "seuil": 2, "status": {"brulure": 5}, "aoe": true}'),
        ("elem_prison_cristal",   "Prison de Cristal",             '["magie_elementaire"]', 5, 5, 20, 5, 5, "esp", 32, "mana", 0, 4,  "Emprisonne la cible dans un cristal de glace massif.", "actif", "spe",  '{"generate_charge": "glace", "seuil": 3, "status": {"stun": 2}, "ignore_armor": true}'),        ("elem_vol",              "Vol Élémentaire (Bonus)",       '["magie_elementaire"]', 5, 5, 0, 2, 0, "esp", 20, "mana", 0, 0,  "Chevauche les courants élémentaires.", "utilitaire", "spe",  '{"generate_charge": "air", "rp_effect": "Vol libre pendant 30min sur courants d\'air. Vitesse doublée."}'),
        ("elem_eruption",         "Éruption Primordiale",          '["magie_elementaire"]', 5, 5, 27, 5, 9, "esp", 45, "mana", 0, 5,  "L'explosion élémentaire ultime.", "actif", "spe",  '{"generate_charge": "feu", "seuil": 3, "aoe": true, "status": {"brulure": 5}, "execute_percent": 15}'),
        # ====================================================================================
        # MAGIE GRAVITATIONNELLE — Sous-classe Mage
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_grav_masse",     "[Masse Initiale] (Passif)",     '["magie_gravitationnelle"]', 1, 1, 0,0,0,"esp",0,"mana",0,0, "Sorts TC sur cible 3+ Lestages infligent 1 Lestage bonus.", "passif", "spe", '{"passif": "grav_masse"}'),
        ("passif_grav_poids",     "[Poids Croissant] (Passif)",    '["magie_gravitationnelle"]', 2, 2, 0,0,0,"esp",0,"mana",0,0, "Vos sorts SC infligent +1 Lestage (doublé).", "passif", "spe", '{"passif": "grav_poids"}'),
        ("passif_grav_rupture",   "[Point de Rupture] (Passif)",   '["magie_gravitationnelle"]', 3, 3, 0,0,0,"esp",0,"mana",0,0, "Singularité → +8 dégâts fixes automatiques.", "passif", "spe", '{"passif": "grav_rupture"}'),
        ("passif_grav_distorsion","[Distorsion Permanente] (Passif)",'["magie_gravitationnelle"]', 4, 4, 0,0,0,"esp",0,"mana",0,0, "Tout ennemi qui vous attaque reçoit 1 Lestage.", "passif", "spe", '{"passif": "grav_distorsion"}'),
        ("passif_grav_avatar",    "[Avatar du Cosmos] (Passif)",   '["magie_gravitationnelle"]', 5, 5, 0,0,0,"esp",0,"mana",0,0, "Singularité à 4 stacks. +10 Mana après chaque Singularité.", "passif", "spe", '{"passif": "grav_avatar"}'),
        # P1
        ("grav_traction_novice",  "Traction Novice",               '["magie_gravitationnelle"]', 1, 1, 0, 3, 0, "esp", 4, "mana", 0, 2, "Filament de mana intensifiant la pesanteur locale.", "actif", "spe", '{"generate_lestage": 2, "seuil": 1}'),
        ("grav_onde_novice",      "Onde Répulsive Novice",         '["magie_gravitationnelle"]', 1, 1, 6, 3, 3, "esp", 5, "mana", 0, 2, "Inverse brutalement la pesanteur.", "actif", "spe", '{"generate_lestage": 1, "seuil": 2}'),        ("grav_pression_novice",  "Pression Gravitationnelle Novice",'["magie_gravitationnelle"]',1, 1, 0, 3, 0, "esp", 6, "mana", 0, 2, "Augmente la pesanteur autour des membres inférieurs.", "actif", "spe", '{"generate_lestage_cond": {"base": 0, "bonus_si_lestage": 1, "seuil_lestage": 2}, "status": {"root": 1}, "seuil": 2}'),
        ("grav_sens_vide",        "Sens du Vide (Bonus)",          '["magie_gravitationnelle"]', 1, 1, 0, 2, 0, "esp", 2, "mana", 0, 0, "Détecte masse anormale dans 30m.", "utilitaire", "spe", '{"rp_effect": "Détecte toute masse anormale dans 30m : passages secrets, métal, créatures lourdes."}'),
        ("grav_lenteur",          "Lenteur Spatiale (Bonus)",      '["magie_gravitationnelle"]', 1, 1, 0, 2, 0, "esp", 3, "mana", 0, 2, "Stoppe tout objet non-vivant en vol dans 5m.", "utilitaire", "spe", '{"rp_effect": "Stoppe/ralentit tout objet non-vivant en vol dans 5m (flèches, rochers)."}'),
        # P2
        ("grav_ecrasement_novice","Écrasement Orbital Novice",     '["magie_gravitationnelle"]', 2, 2, 7, 3, 4, "esp", 8, "mana", 0, 3, "La gravité plaque la cible au sol.", "actif", "spe", '{"generate_lestage": 2, "seuil": 2, "status_if_lestage_3": {"root": 1}}'),        ("grav_attraction_novice","Attraction Zonale Novice",      '["magie_gravitationnelle"]', 2, 2, 6, 4, 3, "esp", 9, "mana", 0, 3, "Puits de gravité aspirant les corps.", "actif", "spe", '{"generate_lestage": 1, "seuil": 2, "aoe": true}'),        ("grav_bouclier_novice",  "Bouclier Inertiel Novice",      '["magie_gravitationnelle"]', 2, 2, 0, 3, 0, "esp", 7, "mana", 0, 3, "Redirige la force d'un impact entrant.", "defense", "spe", '{"reduce_dmg_flat": 8, "seuil": 2, "lestage_sur_attaquant": 1}'),
        ("grav_levitation",       "Lévitation Contrôlée (Bonus)",  '["magie_gravitationnelle"]', 2, 2, 0, 1, 0, "esp", 7, "mana", 0, 2, "Vol à 10m de hauteur pendant 5min.", "utilitaire", "spe", '{"rp_effect": "Vous et 2 alliés flottez jusqu\'à 10m pendant 5min. Annule chutes."}'),
        ("grav_navigation",       "Navigation Céleste (Bonus)",    '["magie_gravitationnelle"]', 2, 2, 0, 2, 0, "esp", 5, "mana", 0, 0, "Position exacte même sans visibilité.", "utilitaire", "spe", '{"rp_effect": "Détermine position et heure exactes. Annule labyrinthe et désorientation magique."}'),
        # P3
        ("grav_traction_avance",  "Traction Avancée",              '["magie_gravitationnelle"]', 3, 3, 11, 4, 4, "esp", 13, "mana", 0, 2, "La masse d'un astre imaginaire s'abat.", "actif", "spe", '{"generate_lestage": 3, "seuil": 2}'),        ("grav_inversion",        "Champ d'Inversion",             '["magie_gravitationnelle"]', 3, 3, 9, 5, 3, "esp", 15, "mana", 0, 4, "Inverse la gravité d'une zone entière.", "actif", "spe", '{"generate_lestage": 1, "seuil": 3, "status": {"stun": 1}, "aoe": true}'),        ("grav_compression",      "Onde de Compression",           '["magie_gravitationnelle"]', 3, 3, 8, 4, 3, "esp", 11, "mana", 0, 3, "Compresse l'air autour de la cible.", "actif", "spe", '{"seuil": 2, "ignore_armor_si_alourdi": true, "status_si_alourdi": {"hemorragie": 1}}'),        ("grav_manteau",          "Manteau Stellaire (Bonus)",     '["magie_gravitationnelle"]', 3, 3, 0, 3, 0, "esp", 12, "mana", 0, 3, "Distorsion gravitationnelle créant une armure.", "defense", "spe", '{"reduce_dmg_flat": 8, "seuil": 2}'),
        ("grav_carto",            "Cartographie Cosmique (Bonus)", '["magie_gravitationnelle"]', 3, 3, 0, 3, 0, "esp", 8, "mana", 0, 2, "Révèle position de toute créature dans 100m.", "utilitaire", "spe", '{"rp_effect": "Révèle position de toute créature dans 100m. Ignore invisibles/illusoires."}'),
        # P4
        ("grav_compression_avance","Compression Gravitationnelle", '["magie_gravitationnelle"]', 4, 4, 15, 4, 6, "esp", 22, "mana", 0, 3, "Broie la cible par pesanteur concentrée.", "actif", "spe", '{"generate_lestage": 4, "seuil": 2, "bonus_si_singularite": 12}'),        ("grav_effondrement",     "Effondrement de Zone",          '["magie_gravitationnelle"]', 4, 4, 13, 5, 5, "esp", 20, "mana", 0, 4, "Convertit les Lestages en dégâts.", "actif", "spe", '{"consume_lestage_all": true, "dmg_per_lestage": 3, "seuil": 3, "aoe": true}'),        ("grav_pression_avance",  "Pression Gravitationnelle Avancée",'["magie_gravitationnelle"]',4, 4, 12, 4, 5, "esp", 18, "mana", 0, 3, "La pesanteur triple d'intensité.", "actif", "spe", '{"generate_lestage": 3, "seuil": 3, "double_rupture": true}'),        ("grav_saut",             "Saut Gravitationnel (Bonus)",   '["magie_gravitationnelle"]', 4, 4, 0, 3, 0, "esp", 18, "mana", 0, 4, "Téléportation vers tout point visible à 300m.", "utilitaire", "spe", '{"rp_effect": "Téléportation instantanée vers tout point visible à moins de 300m."}'),
        ("grav_contemplation",    "Contemplation du Néant (Bonus)",'["magie_gravitationnelle"]', 4, 4, 0, 4, 0, "esp", 25, "mana", 0, 0, "Méditation cosmique révélant un secret fondamental.", "utilitaire", "spe", '{"rp_effect": "Méditer 1h face au ciel nocturne. Le MJ révèle un secret fondamental de campagne."}'),
        # P5
        ("grav_stellaire",        "Effondrement Stellaire",        '["magie_gravitationnelle"]', 5, 5, 27, 6, 9, "esp", 45, "mana", 0, 5, "La puissance d'un astre mourant s'abat.", "actif", "spe", '{"generate_lestage": 5, "seuil": 4, "aoe": true, "check_singularite_all": true}'),        ("grav_non_retour",       "Point de Non-Retour",           '["magie_gravitationnelle"]', 5, 5, 20, 5, 8, "esp", 35, "mana", 0, 4, "Distorsion permanente dans la masse de la cible.", "actif", "spe", '{"reset_lestage_plus_2": true, "seuil": 3}'),        ("grav_bouclier_avance",  "Bouclier Inertiel Avancé",      '["magie_gravitationnelle"]', 5, 5, 0, 5, 0, "esp", 30, "mana", 0, 4, "Sphère gravitationnelle renvoyant les impacts.", "defense", "spe", '{"reduce_dmg_flat": 20, "seuil": 3, "lestage_sur_attaquant_multi": true}'),
        ("grav_dilation",         "Dilation Gravitationnelle (Bonus)",'["magie_gravitationnelle"]',5, 5, 0, 5, 0, "esp", 40, "mana", 0, 6, "Initiative traitée comme la plus haute ce tour.", "utilitaire", "spe", '{"rp_effect": "Ce tour : votre Initiative est traitée comme la plus élevée du combat."}'),
        ("grav_carto_avance",     "Cartographie Cosmique Avancée (Bonus)",'["magie_gravitationnelle"]',5, 5, 0, 3, 0, "esp", 20, "mana", 0, 3, "Révèle position de tout être dans 2km.", "utilitaire", "spe", '{"rp_effect": "Révèle position et déplacement de tout être vivant dans 2km."}'),

        # ====================================================================================
        # LOGE DE L'OMBRE — Sous-classe Mage
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_ombre_fantome",  "[Opération Fantôme] (Passif)", '["loge_ombre"]', 1, 1, 0,0,0,"esp",0,"mana",0,0, "+2 Discrétion, +2 Histoire. Sorts SC indétectables.", "passif", "spe", '{"passif": "ombre_fantome"}'),
        ("passif_ombre_prep",     "[Préparation Rapide] (Passif)",'["loge_ombre"]', 2, 2, 0,0,0,"esp",0,"mana",0,0, "Cooldown Marquage Silencieux -1 (min 1).", "passif", "spe", '{"passif": "ombre_prep"}'),
        ("passif_ombre_rens",     "[Renseignement Total] (Passif)",'["loge_ombre"]', 3, 3, 0,0,0,"esp",0,"mana",0,0, "Consommer Désignation révèle les PV actuels de la cible.", "passif", "spe", '{"passif": "ombre_rens"}'),
        ("passif_ombre_oeil",     "[L'Œil de la Confrérie] (Passif)",'["loge_ombre"]', 4, 4, 0,0,0,"esp",0,"mana",0,0, "Désignation persiste entre combats d'une même session.", "passif", "spe", '{"passif": "ombre_oeil"}'),
        ("passif_ombre_regulateur","[Le Grand Régulateur] (Passif)",'["loge_ombre"]', 5, 5, 0,0,0,"esp",0,"mana",0,0, "Kill sur cible Désignée : +15 Mana + nouvelle Désignation gratuite.", "passif", "spe", '{"passif": "ombre_regulateur"}'),
        # P1
        ("ombre_marquage_novice", "Marquage Silencieux",           '["loge_ombre"]', 1, 1, 5, 3, 2, "esp", 6, "mana", 0, 3, "Filament invisible liant le mage à sa proie.", "actif", "spe", '{"pose_designation": 1, "seuil": 1}'),        ("ombre_voile",           "Voile d'Ombre (Bonus)",         '["loge_ombre"]', 1, 1, 0, 2, 0, "esp", 5, "mana", 0, 2, "Invisibilité 10min.", "utilitaire", "spe", '{"rp_effect": "Invisibilité visuelle 10min (annulée si attaque ou cri)."}'),
        ("ombre_analyse",         "Analyse Comportementale (Bonus)",'["loge_ombre"]', 1, 1, 0, 2, 0, "esp", 3, "mana", 0, 0, "Révèle intentions immédiates d'une cible.", "utilitaire", "spe", '{"rp_effect": "Révèle intentions immédiates d\'une cible et si elle ment."}'),
        ("ombre_murmure",         "Murmure de Mana (Bonus)",       '["loge_ombre"]', 1, 1, 0, 2, 0, "esp", 3, "mana", 0, 2, "Écoute conversation à 50m ou intercepte message.", "utilitaire", "spe", '{"rp_effect": "Écoute toute conversation à 50m ou intercepte un message magique."}'),
        ("ombre_frappe_novice",   "Frappe dans l'Ombre Novice",    '["loge_ombre"]', 1, 1, 7, 3, 3, "esp", 7, "mana", 0, 2, "Sort basique amplifié par la préparation.", "actif", "spe", '{"seuil": 2, "bonus_si_designation": {"status": {"root": 1}}}'),        # P2
        ("ombre_filet_novice",    "Filet Invisible Novice",        '["loge_ombre"]', 2, 2, 7, 3, 3, "esp", 7, "mana", 0, 3, "Réseau de fils coupant les voies d'action.", "actif", "spe", '{"seuil": 2, "status": {"root": 1}, "ignore_rob_si_designation": true}'),        ("ombre_perturb_novice",  "Perturbation Neurale Novice (Bonus)",   '["loge_ombre"]', 2, 2, 0, 3, 0, "esp", 8, "mana", 0, 3, "Impulsion brouillant les pensées.", "utilitaire", "spe", '{"seuil": 2, "status": {"stun": 1}, "consomme_designation_bonus": true}'),
        ("ombre_marquage_avance", "Marquage Avancé",               '["loge_ombre"]', 2, 2, 6, 3, 3, "esp", 10, "mana", 0, 3, "Désignation gravée dans l'aura de la cible.", "actif", "spe", '{"pose_designation": 1, "seuil": 2, "bonus_si_deja_designee": 1}'),        ("ombre_grimage",         "Grimage Parfait (Bonus)",       '["loge_ombre"]', 2, 2, 0, 3, 0, "esp", 6, "mana", 0, 0, "Apparence parfaite d'un PNJ observé.", "utilitaire", "spe", '{"rp_effect": "Transforme apparence physique et vocale en PNJ observé. Dure jusqu\'à blessure."}'),
        ("ombre_scelle",          "Scellé de la Confrérie (Bonus)",'["loge_ombre"]', 2, 2, 0, 2, 0, "esp", 3, "mana", 0, 0, "Message lisible uniquement par le destinataire.", "utilitaire", "spe", '{"rp_effect": "Crée message scellé, lisible exclusivement par la personne désignée."}'),
        # P3
        ("ombre_marquage_profond","Marquage Profond",              '["loge_ombre"]', 3, 3, 5, 3, 3, "esp", 10, "mana", 0, 3, "Désignation persistante même après consommation.", "actif", "spe", '{"pose_designation": 2, "seuil": 2}'),        ("ombre_paralysie_novice","Paralysie Neurale Novice",      '["loge_ombre"]', 3, 3, 9, 4, 3, "esp", 12, "mana", 0, 3, "Paralyse le système nerveux supérieur.", "actif", "spe", '{"seuil": 2, "no_bonus_action_next_turn": true}'),        ("ombre_frappe_avance",   "Frappe dans l'Ombre Avancée",   '["loge_ombre"]', 3, 3, 9, 4, 4, "esp", 14, "mana", 0, 3, "Sort de zone masqué dans un nuage de mana.", "actif", "spe", '{"seuil": 2, "aoe": true, "double_dmg_si_designation": true}'),        ("ombre_effacement",      "Effacement de Mémoire (Bonus)", '["loge_ombre"]', 3, 3, 0, 3, 0, "esp", 10, "mana", 0, 2, "Efface 1h de mémoire d'un PNJ.", "utilitaire", "spe", '{"rp_effect": "Efface jusqu\'à 1h de mémoire d\'un PNJ ciblé. Ne fonctionne pas sur PJs."}'),
        ("ombre_reseau",          "Réseau Fantôme (Bonus)",        '["loge_ombre"]', 3, 3, 0, 4, 0, "esp", 15, "mana", 0, 3, "3 observateurs magiques invisibles dans une zone.", "utilitaire", "spe", '{"rp_effect": "Place 3 observateurs invisibles dans une zone. 2h de surveillance transmise par le MJ."}'),
        # P4
        ("ombre_sentence_letale", "Sentence Létale",               '["loge_ombre"]', 4, 4, 14, 4, 6, "esp", 20, "mana", 0, 3, "Dégâts massifs ignorant l'Armure. Requiert Désignation.", "actif", "spe", '{"requiert_designation": true, "ignore_armor": true, "seuil": 3}'),        ("ombre_champ_iso",       "Champ d'Isolation",             '["loge_ombre"]', 4, 4, 0, 4, 0, "esp", 18, "mana", 0, 4, "La cible ne peut cibler plusieurs ennemis ce tour.", "actif", "spe", '{"seuil": 3, "rp_effect": "La cible ne peut pas utiliser sorts de zone ce tour."}'),
        ("ombre_paralysie_avance","Paralysie Neurale Avancée",     '["loge_ombre"]', 4, 4, 11, 4, 4, "esp", 18, "mana", 0, 4, "Coupe les connexions motrices supérieures.", "actif", "spe", '{"seuil": 3, "status": {"stun": 2}, "ignore_rob_si_designation": true}'),        ("ombre_extraction",      "Extraction d'Information (Bonus)",'["loge_ombre"]', 4, 4, 0, 4, 0, "esp", 15, "mana", 0, 3, "Plonge dans les souvenirs d'une cible inconsciente.", "utilitaire", "spe", '{"rp_effect": "Accède aux souvenirs récents d\'une cible inconsciente. MJ révèle 3 infos."}'),
        ("ombre_poudre",          "Poudre d'Oubli (Bonus)",        '["loge_ombre"]', 4, 4, 0, 4, 0, "esp", 20, "mana", 0, 4, "6 PNJ oublient la Confrérie agir en 10min.", "utilitaire", "spe", '{"rp_effect": "Jusqu\'à 6 PNJ oublient avoir vu la Confrérie agir dans les 10 dernières minutes."}'),
        # P5
        ("ombre_execution",       "Exécution de l'Ombre",          '["loge_ombre"]', 5, 5, 22, 5, 7, "esp", 30, "mana", 0, 3, "La Confrérie a jugé. Dégâts massifs ignorant toute défense.", "actif", "spe", '{"requiert_designation": true, "ignore_armor": true, "ignore_rob": true, "seuil": 3, "execute_note": true}'),        ("ombre_sentence_avance", "Sentence Létale Avancée",       '["loge_ombre"]', 5, 5, 18, 5, 8, "esp", 35, "mana", 0, 3, "Le Grand Régulateur n'a pas besoin de deux balles.", "actif", "spe", '{"requiert_designation": true, "ignore_armor": true, "seuil": 3, "execute_percent_si_designation": 30}'),        ("ombre_marquage_fantome","Marquage Fantôme",               '["loge_ombre"]', 5, 5, 4, 3, 2, "esp", 12, "mana", 0, 2, "Pose Désignation après un kill.", "actif", "spe", '{"pose_designation": 1, "seuil": 1}'),        ("ombre_disparition",     "Disparition Totale (Bonus)",    '["loge_ombre"]', 5, 5, 0, 5, 0, "esp", 35, "mana", 0, 6, "Vous et votre groupe introuvables 24h.", "utilitaire", "spe", '{"rp_effect": "Vous et votre groupe êtes introuvables pendant 24h. Aucun sort de localisation."}'),
        ("ombre_manipulation",    "Manipulation Absolue (Bonus)",  '["loge_ombre"]', 5, 5, 0, 6, 0, "esp", 40, "mana", 0, 6, "Ordre post-hypnotique complexe sur un PNJ.", "utilitaire", "spe", '{"rp_effect": "Ordre post-hypnotique complexe déclenché par une condition précise sur un PNJ."}'),

        # ====================================================================================
        # ASSASSIN DE LA CONFRÉRIE — Sous-classe Guerrier
        # ====================================================================================
        # ── ASSASSIN DE LA CONFRÉRIE ─────────────────────────────────────
        # PASSIFS
        ("passif_assassin_lame",    "[Lame Infectée] (Passif)",        '["assassin_confrerie"]', 1, 1, 0,0,0,"phy",0,"tension",0,0, "25% de chance d'infliger Poison 1 ou Hémorragie 1 à chaque attaque (au choix).", "passif", "spe", '{"passif": "assassin_lame"}'),
        ("passif_assassin_neuro",   "[Neurotoxine] (Passif)",          '["assassin_confrerie"]', 2, 2, 0,0,0,"phy",0,"tension",0,0, "Cible sous Toxine : ne peut pas utiliser d'action Bonus ce tour.", "passif", "spe", '{"passif": "assassin_neuro"}'),
        ("passif_assassin_bourreau","[Bourreau des Ombres] (Passif)",  '["assassin_confrerie"]', 3, 3, 0,0,0,"phy",0,"tension",0,0, "Sort TC sur cible avec 3+ types d'altérations : coût en Tension réduit à 0.", "passif", "spe", '{"passif": "assassin_bourreau"}'),
        ("passif_assassin_heure",   "[L'Heure du Crime] (Passif)",     '["assassin_confrerie"]', 4, 4, 0,0,0,"phy",0,"tension",0,0, "Sorts TC ignorent Robustesse ET Armure de toute cible souffrant d'au moins 1 Poison.", "passif", "spe", '{"passif": "assassin_heure"}'),
        ("passif_assassin_ange",    "[L'Ange Noir] (Passif)",          '["assassin_confrerie"]', 5, 5, 0,0,0,"phy",0,"tension",0,0, "Tuer un ennemi avec 3+ altérations : +5 Tension et +15 PV.", "passif", "spe", '{"passif": "assassin_ange"}'),
        # PALLIER 1
        ("assassin_coup_vic_nov",   "Coup Vicieux Novice",             '["assassin_confrerie"]', 1, 1, 8, 3, 3, "phy", 1, "tension", 0, 0, "Frappe précise sur plaie ouverte. Ignore Armure si cible a Hémorragie.", "actif", "spe", '{"seuil": 2, "ignore_armor_si_hemo": true}'),        ("assassin_dague_nov",      "Dague Toxique Novice",            '["assassin_confrerie"]', 1, 1, 7, 3, 3, "phy", 1, "tension", 0, 1, "Lame empoisonnée. Inflige 1 Toxine (-1 Pièce ennemi prochain tour).", "actif", "spe", '{"seuil": 2, "status": {"toxine": 1}}'),        ("assassin_bombe_nov",      "Bombe Fumigène Novice (Bonus)",   '["assassin_confrerie"]', 1, 1, 0, 3, 3, "phy", 1, "tension", 0, 2, "Disparaît dans un nuage. Bouclier 9 + Furtif Assassin (+1 Pièce prochain sort).", "defense", "spe", '{"seuil": 1, "armure_base": 9, "self_status": {"furtif_assassin": 1}}'),        ("assassin_velours",        "Pas de Velours (Bonus)",          '["assassin_confrerie"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 0, "RP — Déplacement totalement silencieux.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Se déplacer ou s\'infiltrer sans produire le moindre son."}'),
        ("assassin_analyse",        "Analyse des Failles (Bonus)",     '["assassin_confrerie"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 1, "RP — Révèle la pire statistique de l\'ennemi.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Révèle immédiatement la pire statistique de l\'ennemi."}'),
        # PALLIER 2
        ("assassin_frappe_art_nov", "Frappe Artérielle Novice",        '["assassin_confrerie"]', 2, 2, 9, 3, 3, "phy", 2, "tension", 0, 2, "Vise les zones vitales. Inflige 2 Hémorragies.", "actif", "spe", '{"seuil": 2, "status": {"hemorragie": 2}}'),        ("assassin_couteaux_nov",   "Lancer de Couteaux Novice",       '["assassin_confrerie"]', 2, 2, 8, 4, 3, "phy", 2, "tension", 0, 1, "Projette des lames de précision. Touche 2 ennemis, 1 Poison chacun.", "actif", "spe", '{"seuil": 2, "status": {"poison": 1}, "ricochet": true}'),        ("assassin_fausse_id",      "Fausse Identité (Bonus)",         '["assassin_confrerie"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 0, "RP — Se déguiser parfaitement en un PNJ spécifique.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Se déguiser parfaitement en un PNJ spécifique."}'),
        ("assassin_crochet",        "Crochetage Expert (Bonus)",       '["assassin_confrerie"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 1, "RP — Ouvre toute serrure non-magique sans bruit.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Ouvre instantanément et sans bruit toute serrure, chaîne ou coffre non-magique."}'),
        ("assassin_somnifere",      "Somnifère Aérien (Bonus)",        '["assassin_confrerie"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 1, "RP — Endort un PNJ non-combattant 1 heure.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Endort instantanément un PNJ non-combattant pendant une heure."}'),
        # PALLIER 3
        ("assassin_coup_vic",       "Coup Vicieux",                    '["assassin_confrerie"]', 3, 3, 11, 3, 4, "phy", 3, "tension", 0, 0, "Déchire les chairs. 2 Hémorragies + Mutilation.", "actif", "spe", '{"seuil": 2, "status": {"hemorragie": 2, "mutilation": 1}}'),        ("assassin_dague",          "Dague Toxique",                   '["assassin_confrerie"]', 3, 3, 9, 4, 4, "phy", 3, "tension", 0, 1, "Venin concentré. 2 Toxines + Silence (magie impossible ce tour).", "actif", "spe", '{"seuil": 3, "status": {"toxine": 2}, "silence_cible": true}'),        ("assassin_bombe",          "Bombe Fumigène (Bonus)",          '["assassin_confrerie"]', 3, 3, 0, 4, 4, "phy", 2, "tension", 0, 2, "Bouclier 13 + toute l\'équipe devient Furtive pour le prochain tour.", "defense", "spe", '{"seuil": 2, "armure_base": 13, "self_status": {"furtif_assassin": 1}, "aoe_furtif_assassin": true}'),        ("assassin_voix",           "Voix de l'Ombre (Bonus)",        '["assassin_confrerie"]', 3, 3, 0, 3, 0, "phy", 0, "tension", 0, 1, "RP — Imite parfaitement la voix d\'un PNJ entendu.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Imite à la perfection la voix d\'un PNJ entendu au moins une fois."}'),
        ("assassin_poison_pers",    "Poison Persistant (Bonus)",       '["assassin_confrerie"]', 3, 3, 0, 3, 0, "phy", 0, "tension", 0, 1, "RP — Empoisonne un plat indétectablement.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Empoisonne indétectablement un plat ou une boisson (mortel pour un PNJ mineur après quelques heures)."}'),
        # PALLIER 4
        ("assassin_frappe_art",     "Frappe Artérielle",               '["assassin_confrerie"]', 4, 4, 13, 4, 4, "phy", 4, "tension", 0, 2, "Hémorragie inarrêtable. 3 Hémorragies + 5 PV perdus à chaque action.", "actif", "spe", '{"seuil": 3, "status": {"hemorragie": 3}, "dmg_par_action": 5}'),        ("assassin_couteaux",       "Lancer de Couteaux",              '["assassin_confrerie"]', 4, 4, 11, 5, 4, "phy", 4, "tension", 0, 1, "Zone. 1 Poison + 1 Toxine à tous les ennemis.", "actif", "spe", '{"seuil": 3, "status": {"poison": 1, "toxine": 1}, "aoe": true}'),        ("assassin_marque_peur",    "Marque de Peur (Bonus)",          '["assassin_confrerie"]', 4, 4, 0, 3, 0, "phy", 0, "tension", 0, 1, "RP — Symbole gravé : quiconque le voit obéit aux menaces.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Gravez un symbole. Quiconque le voit obéit à vos menaces sans combattre."}'),
        ("assassin_poudre_amn",     "Poudre d'Amnésie (Bonus)",       '["assassin_confrerie"]', 4, 4, 0, 3, 0, "phy", 0, "tension", 0, 1, "RP — Efface 10 minutes de mémoire d\'un PNJ.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Efface les 10 dernières minutes de mémoire d\'un PNJ."}'),
        ("assassin_langage",        "Langage Silencieux (Bonus)",      '["assassin_confrerie"]', 4, 4, 0, 3, 0, "phy", 0, "tension", 0, 1, "RP — Communication par signes imperceptibles.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Communique par signes ou messages codés imperceptibles aux non-initiés."}'),
        # PALLIER 5
        ("assassin_coup_vic_av",    "Coup Vicieux Avancé",             '["assassin_confrerie"]', 5, 5, 18, 4, 5, "phy", 5, "tension", 0, 0, "Exécution chirurgicale. Exécute si cible < 20% PV après l\'attaque.", "actif", "spe", '{"seuil": 3, "execute_sous_20pct": true}'),        ("assassin_dague_av",       "Dague Toxique Avancée",           '["assassin_confrerie"]', 5, 5, 15, 5, 5, "phy", 5, "tension", 0, 1, "Toxine du Cauchemar. Inflige 4 Toxines.", "actif", "spe", '{"seuil": 4, "status": {"toxine": 4}}'),        ("assassin_bombe_av",       "Bombe Fumigène Avancée (Bonus)",  '["assassin_confrerie"]', 5, 5, 0, 5, 5, "phy", 4, "tension", 0, 3, "Invulnérabilité à toute l\'équipe ce tour.", "defense", "spe", '{"seuil": 3, "self_status": {"invulnerable": 1}, "aoe_invulnerable": true}'),        ("assassin_ecoute",         "Écoute Ténébreuse (Bonus)",       '["assassin_confrerie"]', 5, 5, 0, 4, 0, "phy", 0, "tension", 0, 2, "RP — Entend à travers les murs via les ombres.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Entend parfaitement à travers les murs en utilisant les ombres comme catalyseur."}'),
        ("assassin_contrat",        "Contrat Absolu (Bonus)",          '["assassin_confrerie"]', 5, 5, 0, 6, 0, "phy", 0, "tension", 0, 5, "RP Ultime — Fait assassiner un PNJ mineur à distance en 24h.", "utilitaire", "spe", '{"seuil": 4, "rp_effect": "Fait assassiner un PNJ mineur ou non-combattant à distance dans les 24h sans laisser de trace."}'),
        # ====================================================================================
        # ÉCOLE DE L'ESTOC — Sous-classe Guerrier
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_estoc_lecture",  "[Lecture de Garde] (Passif)",   '["ecole_estoc"]', 1, 1, 0,0,0,"phy",0,"tension",0,0, "+1 Initiative. Déclare cible APRÈS les autres même initiative.", "passif", "spe", '{"passif": "estoc_lecture"}'),
        ("passif_estoc_contretemps","[Contre-Temps] (Passif)",     '["ecole_estoc"]', 2, 2, 0,0,0,"phy",0,"tension",0,0, "+1 Tension à chaque Clash gagné.", "passif", "spe", '{"passif": "estoc_contretemps"}'),
        ("passif_estoc_discipline","[Discipline du Salon] (Passif)",'["ecole_estoc"]', 3, 3, 0,0,0,"phy",0,"tension",0,0, "Dernière action était une Passe + Estoc ce tour : +1 Tension bonus.", "passif", "spe", '{"passif": "estoc_discipline"}'),
        ("passif_estoc_memoire",  "[Mémoire du Corps] (Passif)",   '["ecole_estoc"]', 4, 4, 0,0,0,"phy",0,"tension",0,0, "Bonus Estoc s'étend au tour précédent si dernière action était Passe.", "passif", "spe", '{"passif": "estoc_memoire"}'),
        ("passif_estoc_maitre",   "[Art de l'Estoc Maîtrisé] (Passif)",'["ecole_estoc"]',5, 5, 0,0,0,"phy",0,"tension",0,0, "Chaque Passe jouée réduit coût prochain sort de 1 (max -3).", "passif", "spe", '{"passif": "estoc_maitre"}'),
        # P1 — Passes ⚔️ et Estocs 🎯
        ("estoc_quarte_novice",   "Quarte Novice (Passe ⚔️)",      '["ecole_estoc"]', 1, 1, 6, 3, 3, "phy", 1, "tension", 0, 2, "Dévie la lame adverse. Pose passe_active.", "actif", "spe", '{"pose_passe": true, "seuil": 2}'),        ("estoc_direct_novice",   "Estoc Direct Novice (Estoc 🎯)",'["ecole_estoc"]', 1, 1, 7, 0, 1, "phy", 1, "tension", 0, 0, "Botte rectiligne 5 dégâts fixes. Si Passe : 0 Tension + Base 8.", "actif", "spe", '{"degats_fixes": 5, "bonus_si_passe": {"base_override": 8, "cout_zero": true}}'),        ("estoc_feinte",          "Feinte Légère (Bonus)",          '["ecole_estoc"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 2, "Révèle la cible déclarée d'un PNJ.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Combat : révèle cible déclarée d\'un PNJ ce tour."}'),
        ("estoc_prestance",       "Prestance du Cercle (Bonus)",    '["ecole_estoc"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 2, "Avantage en contexte aristocratique.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Dans contexte noble : Avantage automatique sur premier jet d\'Oral ou Force RP."}'),
        ("estoc_mesure",          "Prise de Mesure (Bonus)",        '["ecole_estoc"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 3, "Révèle compétence la plus utilisée par l'ennemi.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Combat : révèle compétence la plus utilisée par ennemi depuis début combat."}'),
        # P2
        ("estoc_sixte",           "Sixte Filée (Passe ⚔️)",        '["ecole_estoc"]', 2, 2, 7, 4, 3, "phy", 1, "tension", 0, 2, "Déviation en arc retournant l'élan adverse.", "actif", "spe", '{"pose_passe": true, "seuil": 2, "status_si_clash_gagne": {"stun": 1}}'),        ("estoc_botte_novice",    "Botte Secrète Novice (Estoc 🎯)",'["ecole_estoc"]', 2, 2, 9, 4, 3, "phy", 2, "tension", 0, 2, "Exploite l'angle mort révélé par la déviation.", "actif", "spe", '{"seuil": 2, "status": {"hemorragie": 1}, "bonus_si_passe": {"cout_zero": true, "coins_bonus": 1}}'),        ("estoc_desarme",         "Désarmement Partiel",            '["ecole_estoc"]', 2, 2, 0, 3, 0, "phy", 1, "tension", 0, 3, "Tord le poignet avec précision d'horloger.", "actif", "spe", '{"seuil": 2, "rp_effect": "Prochaine attaque de la cible perd 2 Pièces ce tour."}'),
        ("estoc_salut",           "Salut du Duelliste (Bonus)",     '["ecole_estoc"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 0, "Instaure conditions d'un duel propre.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Défie officiellement un adversaire. PNJ acceptant ne reçoit pas aide de ses alliés."}'),
        ("estoc_analyse",         "Analyse de Combat (Bonus)",      '["ecole_estoc"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 2, "Mémorise patterns adverses.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Prochaine Passe ce combat gagne +1 Pièce supplémentaire."}'),
        # P3
        ("estoc_tierce",          "Tierce Croisée (Passe ⚔️)",     '["ecole_estoc"]', 3, 3, 8, 5, 3, "phy", 2, "tension", 0, 2, "Parade croisée absorbant l'impact.", "actif", "spe", '{"pose_passe": true, "seuil": 2, "status_si_clash_gagne": {"root": 1}}'),        ("estoc_lunge_novice",    "Lunge Novice (Estoc 🎯)",        '["ecole_estoc"]', 3, 3, 10, 4, 4, "phy", 2, "tension", 0, 2, "Fente explosive couvrant distance impossible.", "actif", "spe", '{"seuil": 2, "status": {"hemorragie": 2}, "bonus_si_passe": {"cout_zero": true, "coins_bonus": 1}}'),        ("estoc_riposte",         "Riposte Foudroyante",            '["ecole_estoc"]', 3, 3, 9, 4, 4, "phy", 2, "tension", 0, 3, "Convertit la Tension récupérée en frappe.", "actif", "spe", '{"seuil": 2, "bonus_si_passe_ce_tour": {"base_bonus": 2}}'),        ("estoc_honneur",         "Code d'Honneur (Bonus)",         '["ecole_estoc"]', 3, 3, 0, 2, 0, "phy", 0, "tension", 0, 0, "Contrat moral inviolable.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Dans négociation avec règles de conduite claires : interlocuteur contraint moralement."}'),
        ("estoc_repute",          "Réputation du Cercle (Bonus)",   '["ecole_estoc"]', 3, 3, 0, 2, 0, "phy", 0, "tension", 0, 0, "Accès automatique haute société.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Accès automatique salons, banquets, audiences nobles sans jet de compétence."}'),
        # P4
        ("estoc_parade_absolue",  "Parade Absolue (Passe ⚔️)",     '["ecole_estoc"]', 4, 4, 10, 5, 4, "phy", 2, "tension", 0, 3, "Parade parfaite. passe_active + parade_absorb 5.", "actif", "spe", '{"pose_passe": true, "pose_parade_absorb": 5, "seuil": 3}'),        ("estoc_botte_avance",    "Botte Secrète Avancée (Estoc 🎯)",'["ecole_estoc"]', 4, 4, 12, 5, 5, "phy", 3, "tension", 0, 2, "La botte parfaite — visible trop tard.", "actif", "spe", '{"seuil": 3, "status": {"hemorragie": 3}, "bonus_si_passe": {"cout_zero": true, "coins_bonus": 1}}'),        ("estoc_desarme_total",   "Désarmement Total",              '["ecole_estoc"]', 4, 4, 7, 4, 3, "phy", 2, "tension", 0, 4, "La lame vole à dix mètres.", "actif", "spe", '{"seuil": 3, "rp_effect": "La cible ne peut pas utiliser de sort offensif son prochain tour."}'),        ("estoc_lunge_avance",    "Lunge Avancée (Estoc 🎯)",       '["ecole_estoc"]', 4, 4, 13, 5, 5, "phy", 3, "tension", 0, 3, "Fente si rapide que personne ne la voit.", "actif", "spe", '{"seuil": 3, "status": {"hemorragie": 3}, "ignore_rob": true, "bonus_si_passe": {"cout_zero": true, "coins_bonus": 1}}'),        ("estoc_defi",            "Défi Officiel (Bonus)",          '["ecole_estoc"]', 4, 4, 0, 2, 0, "phy", 0, "tension", 0, 0, "Cartel signé du sceau du Cercle.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Défi formel à tout personnage de rang équivalent ou supérieur. Refus = perte de réputation."}'),
        # P5
        ("estoc_passe_royale",    "Passe Royale (Passe ⚔️)",       '["ecole_estoc"]', 5, 5, 12, 6, 5, "phy", 3, "tension", 0, 4, "L'arme adverse revient frapper son propriétaire.", "actif", "spe", '{"pose_passe": true, "seuil": 4, "retour_degats_si_marge_3": true}'),        ("estoc_final",           "Estoc Final (Estoc 🎯)",         '["ecole_estoc"]', 5, 5, 16, 7, 6, "phy", 4, "tension", 0, 3, "Le coup que Maître Valère ne peut décrire.", "actif", "spe", '{"seuil": 4, "status": {"hemorragie": 4}, "execute_percent": 30, "bonus_si_passe": {"cout_zero": true, "coins_bonus": 1}}'),        ("estoc_riposte_maitre",  "Riposte du Maître (Passe ⚔️)",  '["ecole_estoc"]', 5, 5, 14, 6, 5, "phy", 3, "tension", 0, 3, "Contre-attaque simultanée à la parade.", "actif", "spe", '{"pose_passe": true, "seuil": 3, "status_si_clash_gagne": {"stun": 1, "hemorragie": 2}}'),        ("estoc_legende",         "Légende du Cercle (Bonus)",      '["ecole_estoc"]', 5, 5, 0, 4, 0, "phy", 0, "tension", 0, 4, "Ennemi inférieur se rend avant le combat.", "utilitaire", "spe", '{"seuil": 3, "rp_effect": "Ennemi non-boss de niveau inférieur refuse de combattre et se rend ou fuit."}'),
        ("estoc_honneur_cercle",  "Honneur du Cercle (Bonus)",      '["ecole_estoc"]', 5, 5, 0, 3, 0, "phy", 0, "tension", 0, 0, "Audience auprès de n'importe quelle figure.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Audience auprès de toute figure aristocratique, politique ou militaire sans jet."}'),

        # ====================================================================================
        # CLAN DU NORD — Sous-classe Guerrier
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_nord_peau",      "[Peau de Pierre] (Passif)",     '["clan_nord"]', 1, 1, 0,0,0,"phy",0,"tension",0,0, "+2 Robustesse permanente.", "passif", "spe", '{"passif": "nord_peau", "rob_bonus": 2}'),
        ("passif_nord_machoire",  "[Mâchoire de Fer] (Passif)",    '["clan_nord"]', 2, 2, 0,0,0,"phy",0,"tension",0,0, "Poison/Brûlure n'appliquent dégâts que tous les 2 tours.", "passif", "spe", '{"passif": "nord_machoire"}'),
        ("passif_nord_fureur",    "[Fureur Tribale] (Passif)",     '["clan_nord"]', 3, 3, 0,0,0,"phy",0,"tension",0,0, "Passage sous 50% PV : +2 Tension immédiatement (une seule fois par combat).", "passif", "spe", '{"passif": "nord_fureur"}'),
        ("passif_nord_fer",       "[Corps de Fer] (Passif)",       '["clan_nord"]', 4, 4, 0,0,0,"phy",0,"tension",0,0, "Serment max +10 (40% PV) / +15 sous 30% PV.", "passif", "spe", '{"passif": "nord_fer"}'),
        ("passif_nord_indestructible","[L'Indestructible] (Passif)",'["clan_nord"]', 5, 5, 0,0,0,"phy",0,"tension",0,0, "+5 PV au Serment. Une survie à 1 PV par combat.", "passif", "spe", '{"passif": "nord_indestructible"}'),
        # P1
        ("nord_coup_tete_novice", "Coup de Tête Novice",           '["clan_nord"]', 1, 1, 6, 3, 3, "phy", 1, "tension", 0, 2, "Impact frontal surprenant.", "actif", "spe", '{"seuil": 2, "status": {"stun": 1}, "bonus_si_serment_degats": {"tension_bonus": 1}}'),        ("nord_rugissement_novice","Rugissement Novice",           '["clan_nord"]', 1, 1, 5, 3, 2, "phy", 1, "tension", 0, 2, "Cri de guerre vacillant la résolution.", "actif", "spe", '{"seuil": 2, "status": {"hemorragie": 2}}'),        ("nord_briseur_novice",   "Briseur d'Os Novice",           '["clan_nord"]', 1, 1, 6, 3, 3, "phy", 1, "tension", 0, 2, "Vise les articulations pour affaiblir.", "actif", "spe", '{"seuil": 2, "rp_effect": "Réduit Base prochaine attaque cible de 3. Dure 1 tour."}'),        ("nord_cracher",          "Cracher le Sang (Bonus)",       '["clan_nord"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 2, "Retire 1 stack Poison ou Brûlure.", "utilitaire", "spe", '{"seuil": 1, "cleanse_self_dot": 1, "rp_effect": "Retire 1 stack Poison ou Brûlure. Intimide PNJ qui vous a vu blessé."}'),
        ("nord_resistance",       "Résistance Tribale (Bonus)",    '["clan_nord"]', 1, 1, 0, 1, 0, "phy", 0, "tension", 0, 0, "Immunité froid, faim, épuisement.", "utilitaire", "spe", '{"rp_effect": "Immunisé aux malus environnementaux : froid extrême, faim, épuisement ordinaire."}'),
        # P2
        ("nord_charge_novice",    "Charge Brutale Novice",         '["clan_nord"]', 2, 2, 8, 4, 3, "phy", 2, "tension", 0, 2, "Charge pleine vitesse renversant tout.", "actif", "spe", '{"seuil": 2, "status": {"root": 1}}'),        ("nord_masse_novice",     "Coup de Masse Novice",          '["clan_nord"]', 2, 2, 9, 0, 1, "phy", 2, "tension", 0, 3, "7 dégâts fixes. Si Serment +4 bonus : Étourdissement.", "actif", "spe", '{"degats_fixes": 7, "stun_si_serment_bonus_4": true}'),        ("nord_rugissement_avance","Rugissement Avancé",           '["clan_nord"]', 2, 2, 7, 4, 3, "phy", 2, "tension", 0, 3, "Cri brisant la volonté de combattre.", "actif", "spe", '{"seuil": 2, "status": {"hemorragie": 3}, "apply_serment_bonus": true}'),        ("nord_histoire",         "Histoire du Nord (Bonus)",      '["clan_nord"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 0, "Avantage Intimidation terres du nord.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Avantage jets d\'Intimidation dans terres du nord ou face guerriers qui reconnaissent les marques."}'),
        ("nord_marque",           "Marque du Survivant (Bonus)",   '["clan_nord"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 0, "Créatures sauvages ne vous attaquent pas d'abord.", "utilitaire", "spe", '{"rp_effect": "Créature sauvage/guerrier tribal reconnaît votre marque et n\'attaque pas en premier."}'),
        # P3
        ("nord_coup_tete_avance", "Coup de Tête Avancé",           '["clan_nord"]', 3, 3, 8, 5, 3, "phy", 2, "tension", 0, 2, "Impact si violent que le sol tremble.", "actif", "spe", '{"seuil": 2, "status": {"stun": 1, "hemorragie": 1}}'),        ("nord_dechainnement_novice","Déchaînement Novice",        '["clan_nord"]', 3, 3, 11, 5, 4, "phy", 3, "tension", 0, 3, "Rafale de coups. Touche 2ème cible à moitié.", "actif", "spe", '{"seuil": 3, "aoe_reduit": true}'),        ("nord_briseur_avance",   "Briseur d'Os Avancé",           '["clan_nord"]', 3, 3, 9, 4, 4, "phy", 2, "tension", 0, 3, "Fracasse l'épaule, bras inutilisable.", "actif", "spe", '{"seuil": 3, "rp_effect": "Cible ne peut pas utiliser sort offensif prochain tour.", "status_si_serment": {"hemorragie": 2}}'),        ("nord_chant",            "Chant de Guerre (Bonus)",       '["clan_nord"]', 3, 3, 0, 3, 0, "phy", 1, "tension", 0, 3, "PNJ de faible volonté hésitent à agir.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Tous PNJ de faible volonté hésitent à agir ce tour."}'),
        ("nord_legende",          "Légende de la Tribu (Bonus)",   '["clan_nord"]', 3, 3, 0, 3, 0, "phy", 0, "tension", 0, 0, "Accès ressources tribales en terres sauvages.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "En terres sauvages : accès abri, vivres, escorte + Avantage jets de Force RP face guerriers."}'),
        # P4
        ("nord_charge_avance",    "Charge Dévastatrice",           '["clan_nord"]', 4, 4, 12, 6, 4, "phy", 3, "tension", 0, 3, "Charge de titan fracassant armures.", "actif", "spe", '{"seuil": 3, "status": {"stun": 1}, "ignore_armor": true}'),        ("nord_masse_avance",     "Coup de Masse Avancé",          '["clan_nord"]', 4, 4, 13, 0, 1, "phy", 3, "tension", 0, 3, "11 dégâts fixes. Enracinement.", "actif", "spe", '{"degats_fixes": 11, "status": {"root": 1}}'),        ("nord_dechainnement_avance","Déchaînement Avancé",        '["clan_nord"]', 4, 4, 13, 6, 5, "phy", 3, "tension", 0, 4, "Si kill : relancer sur nouvelle cible sans Tension.", "actif", "spe", '{"seuil": 3, "kill_relancer": true}'),        ("nord_survivant",        "Récit du Survivant (Bonus)",    '["clan_nord"]', 4, 4, 0, 2, 0, "phy", 0, "tension", 0, 0, "Cicatrices donnent Avantage négociation.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Mercenaires/soldats accordent respect sans jet. Avantage négociation ou commandement."}'),
        ("nord_sang_tribu",       "Sang de la Tribu (Bonus)",      '["clan_nord"]', 4, 4, 0, 4, 0, "phy", 2, "tension", 0, 6, "1d4 guerriers de la Tribu en renfort 24h.", "utilitaire", "spe", '{"seuil": 3, "rp_effect": "Dans les 24h, 1d4 guerriers de la Tribu arrivent en renfort (zone de présence tribale requise)."}'),
        # P5
        ("nord_dechainnement_total","Déchaînement Total",          '["clan_nord"]', 5, 5, 16, 7, 6, "phy", 4, "tension", 0, 4, "Rage d'une vie libérée en un instant. Zone.", "actif", "spe", '{"seuil": 4, "status": {"stun": 1}, "aoe": true}'),        ("nord_masse_final",      "Coup de Masse Final",           '["clan_nord"]', 5, 5, 17, 0, 1, "phy", 4, "tension", 0, 4, "15 dégâts fixes. Ignore Armure. Si Serment <30% : Stun + 4 Hémos.", "actif", "spe", '{"degats_fixes": 15, "ignore_armor": true, "bonus_si_serment_30pct": {"status": {"stun": 1, "hemorragie": 4}}}'),        ("nord_briseur_final",    "Briseur d'Os Final",            '["clan_nord"]', 5, 5, 13, 6, 5, "phy", 3, "tension", 0, 3, "Corps de l'ennemi cède entièrement.", "actif", "spe", '{"seuil": 4, "ignore_rob": true, "status": {"hemorragie": 4}, "rp_effect": "Cible ne peut pas utiliser sort offensif pendant 2 tours."}'),        ("nord_terreur",          "Terreur de la Steppe (Bonus)",  '["clan_nord"]', 5, 5, 0, 3, 0, "phy", 0, "tension", 0, 0, "Présence décourage confrontation.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "PNJ doivent réussir jet de Volonté pour oser vous attaquer en premier."}'),
        ("nord_memoire",          "Mémoire Ancestrale (Bonus)",    '["clan_nord"]', 5, 5, 0, 4, 0, "phy", 2, "tension", 0, 5, "Savoir ancestral de la Tribu.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "MJ révèle technique martiale oubliée, info tactique sur ennemi, ou localisation lieu sacré."}'),

        # ====================================================================================
        # LÉGION DE FER — Sous-classe Guerrier
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_legion_rempart", "[Rempart Vivant] (Passif)",     '["legion_fer"]', 1, 1, 0,0,0,"phy",0,"tension",0,0, "+4 PV Max permanents, +1 Robustesse.", "passif", "spe", '{"passif": "legion_rempart", "pv_bonus": 4, "rob_bonus": 1}'),
        ("passif_legion_endurance","[Endurance d'Acier] (Passif)", '["legion_fer"]', 2, 2, 0,0,0,"phy",0,"tension",0,0, "En Posture : Brûlure/Poison actifs seulement si valeur >3.", "passif", "spe", '{"passif": "legion_endurance"}'),
        ("passif_legion_muraille","[Muraille de Chair] (Passif)",  '["legion_fer"]', 3, 3, 0,0,0,"phy",0,"tension",0,0, "En Posture : seuil KO à -10 PV.", "passif", "spe", '{"passif": "legion_muraille"}'),
        ("passif_legion_implacable","[L'Implacable] (Passif)",     '["legion_fer"]', 4, 4, 0,0,0,"phy",0,"tension",0,0, "Malus Base en Posture réduit à -1.", "passif", "spe", '{"passif": "legion_implacable"}'),
        ("passif_legion_rempart_final","[Le Dernier Rempart] (Passif)",'["legion_fer"]',5, 5, 0,0,0,"phy",0,"tension",0,0, "Une fois/combat, <20% PV : Posture auto 2 tours + +3 Tension.", "passif", "spe", '{"passif": "legion_rempart_final"}'),
        # P1
        ("legion_frappe_bouclier_novice","Frappe Bouclier Novice", '["legion_fer"]', 1, 1, 8, 3, 4, "phy", 1, "tension", 0, 2, "Percute du plat du bouclier. En Posture : 0 Tension.", "actif", "spe", '{"seuil": 2, "status": {"root": 1}, "cout_zero_si_posture": true}'),        ("legion_ancrage_novice", "Ancrage Défensif Novice",       '["legion_fer"]', 1, 1, 8, 3, 4, "phy", 1, "tension", 0, 2, "Creuse ses appuis, refuse toute progression.", "actif", "spe", '{"seuil": 2, "status": {"root": 1}, "base_bonus_si_posture": 3}'),        ("legion_tenir",          "Tenir la Ligne (Bonus)",        '["legion_fer"]', 1, 1, 0, 2, 0, "phy", 1, "tension", 0, 2, "Annule effets de déplacement forcé ce tour.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Ce tour : tous effets déplacement forcé annulés. PNJ ordinaire ne peut vous déplacer."}'),
        ("legion_presence",       "Présence de Garde (Bonus)",     '["legion_fer"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 0, "Stature calme foules et crédibilise autorité.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Stature de légionnaire calme foules ordinaires et donne crédibilité à autorité invoquée."}'),
        ("legion_rapport",        "Rapport de Situation (Bonus)",  '["legion_fer"]', 1, 1, 0, 2, 0, "phy", 0, "tension", 0, 0, "Analyse menace : nombre, positions, niveau.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "MJ révèle nombre d\'ennemis, positions générales et niveau de menace."}'),
        # P2
        ("legion_charge_novice",  "Charge Défensive Novice",       '["legion_fer"]', 2, 2, 10, 4, 4, "phy", 2, "tension", 0, 2, "Pas en avant décidé. En Posture : +2 Base.", "actif", "spe", '{"seuil": 2, "status": {"stun": 1}, "base_bonus_si_posture": 3}'),        ("legion_rempart_novice", "Rempart de Corps Novice",       '["legion_fer"]', 2, 2, 0, 3, 0, "phy", 2, "tension", 0, 3, "Armure 10. En Posture : Armure 15.", "defense", "spe", '{"reduce_dmg_flat": 10, "seuil": 2, "armure_si_posture": 15}'),
        ("legion_frappe_novice",  "Frappe de Bouclier Novice",     '["legion_fer"]', 2, 2, 10, 4, 4, "phy", 2, "tension", 0, 2, "Bouclier en arme de percussion. En Posture : 0 Tension + 1 Pièce.", "actif", "spe", '{"seuil": 2, "status": {"stun": 1}, "cout_zero_si_posture": true, "coins_bonus_si_posture": 1}'),        ("legion_protocole",      "Protocole de Protection (Bonus)",'["legion_fer"]', 2, 2, 0, 3, 0, "phy", 0, "tension", 0, 2, "Évacuation 20 civils sans jet.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Organise évacuation jusqu\'à 20 civils sans jet. Avantage Survie milieu urbain."}'),
        ("legion_evaluation",     "Évaluation Tactique (Bonus)",   '["legion_fer"]', 2, 2, 0, 2, 0, "phy", 0, "tension", 0, 2, "Révèle si ennemi sous 50% PV.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "MJ confirme si ennemi est sous 50% PV. Identifie cible prioritaire."}'),
        # P3
        ("legion_frappe_avance",  "Frappe Bouclier Avancée",       '["legion_fer"]', 3, 3, 12, 5, 4, "phy", 2, "tension", 0, 2, "Bouclier en arme de brisement. En Posture : 0 Tension.", "actif", "spe", '{"seuil": 3, "status": {"stun": 1, "root": 1}, "cout_zero_si_posture": true}'),        ("legion_zone_novice",    "Zone de Contrôle Novice",       '["legion_fer"]', 3, 3, 13, 4, 5, "phy", 2, "tension", 0, 3, "Emprise écrasante. Enracinement zone.", "actif", "spe", '{"seuil": 2, "status": {"root": 1}, "aoe_reduit": true}'),        ("legion_rempart_avance", "Rempart de Corps Avancé",       '["legion_fer"]', 3, 3, 0, 4, 0, "phy", 3, "tension", 0, 3, "Armure 18 / Posture 24. Rebond 4 dmg si bloqué.", "defense", "spe", '{"reduce_dmg_flat": 18, "seuil": 2, "armure_si_posture": 24, "rebond_si_bloque": 4}'),
        ("legion_autorite",       "Autorité de la Légion (Bonus)", '["legion_fer"]', 3, 3, 0, 3, 0, "phy", 0, "tension", 0, 0, "Ordres suivis par gardes sans question.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Dans cité civilisée : ordres suivis sans question par gardes. Accès prisons et ressources militaires."}'),
        ("legion_reseau",         "Réseau de la Garde (Bonus)",    '["legion_fer"]', 3, 3, 0, 2, 0, "phy", 0, "tension", 0, 0, "Contact Légion dans chaque ville.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Dans toute ville, contact Légion fournissant informations, abri discret ou escorte armée."}'),
        # P4
        ("legion_bastion_novice", "Bastion Novice",                '["legion_fer"]', 4, 4, 0, 4, 0, "phy", 3, "tension", 0, 4, "Armure 20 pendant 2 tours. En Posture : -5 dmg fixes.", "defense", "spe", '{"reduce_dmg_flat": 20, "seuil": 2, "duree_armure": 2, "reduction_bonus_si_posture": 5}'),
        ("legion_zone_avance",    "Zone de Contrôle Avancée",      '["legion_fer"]', 4, 4, 15, 5, 6, "phy", 3, "tension", 0, 4, "Contrôle absolu. Enracinement + Stun en Posture.", "actif", "spe", '{"seuil": 3, "status": {"root": 1}, "status_si_posture": {"stun": 1}, "aoe": true}'),        ("legion_frappe_bouclier_avance","Frappe de Bouclier Avancée",'["legion_fer"]',4, 4, 14, 5, 5, "phy", 3, "tension", 0, 3, "Désarticule l'épaule. En Posture : 0 Tension.", "actif", "spe", '{"seuil": 3, "status": {"stun": 1}, "rp_effect": "Cible ne peut pas utiliser sort offensif prochain tour.", "cout_zero_si_posture": true}'),        ("legion_presence_rempart","Présence du Rempart (Bonus)",  '["legion_fer"]', 4, 4, 0, 3, 0, "phy", 0, "tension", 0, 0, "Accès ressources locales dans villes protégées.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Dans ville/village protégé : accès logement, nourriture, info, soins. Coopération totale."}'),
        ("legion_serment",        "Serment de la Légion (Bonus)",  '["legion_fer"]', 4, 4, 0, 5, 0, "phy", 3, "tension", 0, 6, "2 légionnaires d'élite en renfort 24h.", "utilitaire", "spe", '{"seuil": 3, "rp_effect": "Dans les 24h, 2 légionnaires d\'élite arrivent en renfort (villes sous autorité civile uniquement)."}'),
        # P5
        ("legion_zone_absolue",   "Zone de Contrôle Absolue",      '["legion_fer"]', 5, 5, 18, 7, 6, "phy", 4, "tension", 0, 4, "Zone. Enracinement. En Posture : Stun aussi.", "actif", "spe", '{"seuil": 4, "status": {"root": 1}, "status_si_posture": {"stun": 1}, "aoe": true}'),        ("legion_bastion_avance", "Bastion Avancé",                '["legion_fer"]', 5, 5, 0, 5, 0, "phy", 4, "tension", 0, 5, "Armure 30 pendant 2 tours. -8 dmg fixes (Posture -3 supp).", "defense", "spe", '{"reduce_dmg_flat": 30, "seuil": 3, "duree_armure": 2, "reduction_fixe": 8, "reduction_bonus_si_posture": 3}'),
        ("legion_frappe_finale",  "Frappe de Bouclier Finale",     '["legion_fer"]', 5, 5, 18, 6, 7, "phy", 4, "tension", 0, 3, "Jugement divin. En Posture : 0 Tension + ignore Armure.", "actif", "spe", '{"seuil": 3, "status": {"root": 1, "stun": 1}, "cout_zero_si_posture": true, "ignore_armor_si_posture": true}'),        ("legion_memoire",        "Mémoire du Capitaine Oryk (Bonus)",'["legion_fer"]',5, 5, 0, 3, 0, "phy", 0, "tension", 0, 0, "Trêve à toute faction neutre.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Invoquer Légion pour demander trêve à faction neutre/civilisée. Refus = scandale politique."}'),
        ("legion_honneur",        "Honneur de la Légion (Bonus)",  '["legion_fer"]', 5, 5, 0, 4, 0, "phy", 2, "tension", 0, 5, "Invoquer Légion pour arrêter un conflit.", "utilitaire", "spe", '{"seuil": 3, "rp_effect": "Invoquer Légion de Fer pour arrêter conflit, obtenir reddition ou forcer coopération faction entière."}'),

        # ====================================================================================
        # MOINE DU LOTUS — Sous-classe Prêtre
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_lotus_discipline","[Discipline du Corps] (Passif)",'["moine_lotus"]', 1, 1, 0,0,0,"foi",0,"ferveur",0,0, "+5 PV Max, +1 Agi pour Initiative uniquement.", "passif", "spe", '{"passif": "lotus_discipline", "pv_bonus": 5}'),
        ("passif_lotus_souffle",  "[Maîtrise du Souffle] (Passif)",'["moine_lotus"]', 2, 2, 0,0,0,"foi",0,"ferveur",0,0, "En début de tour Concentré : +3 Ferveur.", "passif", "spe", '{"passif": "lotus_souffle"}'),
        ("passif_lotus_corps",    "[Corps-Temple] (Passif)",       '["moine_lotus"]', 3, 3, 0,0,0,"foi",0,"ferveur",0,0, "Immunisé au Poison. Brûlure = moitié dégâts.", "passif", "spe", '{"passif": "lotus_corps"}'),
        ("passif_lotus_harmonie", "[Harmonie Parfaite] (Passif)",  '["moine_lotus"]', 4, 4, 0,0,0,"foi",0,"ferveur",0,0, "Une fois/combat : dépenser 30 Ferveur pour retrouver Concentré.", "passif", "spe", '{"passif": "lotus_harmonie"}'),
        ("passif_lotus_eveil",    "[L'Éveil du Moine] (Passif)",   '["moine_lotus"]', 5, 5, 0,0,0,"foi",0,"ferveur",0,0, "Ne peut plus devenir Perturbé. +2 Base permanent tous sorts.", "passif", "spe", '{"passif": "lotus_eveil"}'),
        # P1
        ("lotus_frappe_novice",   "Frappe du Lotus Novice",        '["moine_lotus"]', 1, 1, 6, 3, 3, "foi", 8, "ferveur", 0, 2, "Coup au centre de l'énergie vitale.", "actif", "spe", '{"seuil": 2, "status_si_concentre": {"hemorragie": 1}}'),        ("lotus_infusion_novice", "Infusion Vitale Novice",        '["moine_lotus"]', 1, 1, 6, 3, 3, "foi", 12, "ferveur", 0, 2, "Soin 8 PV. Concentré : +5 PV. Perturbé : moitié.", "soin", "spe", '{"seuil": 2, "soin_base": 8, "concentre_bonus": 5}'),        ("lotus_posture_novice",  "Posture du Lotus Novice",       '["moine_lotus"]', 1, 1, 0, 3, 0, "foi", 10, "ferveur", 0, 3, "Armure 6. Concentré : 9. Perturbé : 10.", "defense", "spe", '{"seuil": 1, "armure_concentre": 9, "armure_perturbe": 10, "armure_base": 6}'),
        ("lotus_herbo",           "Herboristerie Sacrée (Bonus)",  '["moine_lotus"]', 1, 1, 0, 2, 0, "foi", 5, "ferveur", 0, 0, "Identifie, prépare, détecte toute herbe.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Identifie/prépare/détecte toute herbe. Crée remède ou antidote pour maladie/poison ordinaire."}'),
        ("lotus_meditation",      "Méditation Active (Bonus)",     '["moine_lotus"]', 1, 1, 0, 1, 0, "foi", 5, "ferveur", 0, 0, "+20 Ferveur sur prochain /meditation.", "utilitaire", "spe", '{"rp_effect": "En méditant 10min hors combat : +20 Ferveur lors du prochain /meditation."}'),
        # P2
        ("lotus_paume_novice",    "Paume du Vide Novice",          '["moine_lotus"]', 2, 2, 7, 3, 4, "foi", 15, "ferveur", 0, 3, "Désactive soins cible ce tour. Concentré : Enracinement.", "actif", "spe", '{"seuil": 2, "no_soin_next_turn": true, "status_si_concentre": {"root": 1}}'),        ("lotus_transfert_novice","Transfert de Flux Novice",      '["moine_lotus"]', 2, 2, 7, 3, 3, "foi", 18, "ferveur", 0, 3, "Soin 12 PV allié, perd 4 PV. Concentré : +5/−2.", "soin", "spe", '{"seuil": 2, "soin_base": 12, "concentre_bonus": 5, "self_dmg": 4, "self_dmg_concentre": 2}'),        ("lotus_frappe_eveil_novice","Frappe d'Éveil Novice",      '["moine_lotus"]', 2, 2, 8, 4, 3, "foi", 12, "ferveur", 0, 2, "Dégâts physiques. Perturbé : ignore Rob. Concentré : +5 Ferveur.", "actif", "spe", '{"seuil": 2, "ignore_rob_si_perturbe": true, "ferveur_si_concentre": 5}'),        ("lotus_enseignement",    "Enseignement du Lotus (Bonus)", '["moine_lotus"]', 2, 2, 0, 2, 0, "foi", 8, "ferveur", 0, 0, "Expert corps, poisons, arts martiaux.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Expert niveau sur corps humain, poisons, arts martiaux, spiritualité. Avantage Médecine/Religion/Sciences."}'),
        ("lotus_voie",            "Voie du Moine (Bonus)",         '["moine_lotus"]', 2, 2, 0, 0, 0, "foi", 0, "ferveur", 0, 0, "Reconnu initié du Temple du Lotus.", "utilitaire", "spe", '{"rp_effect": "Dans toute communauté religieuse : accueil en frère, accès remèdes, informations, abri du Temple."}'),
        # P3
        ("lotus_frappe_avance",   "Frappe du Lotus Avancée",       '["moine_lotus"]', 3, 3, 10, 4, 4, "foi", 20, "ferveur", 0, 2, "Flux vital retourné. Concentré : -5 Ferveur cible. Perturbé : +4 Base.", "actif", "spe", '{"seuil": 3, "status": {"hemorragie": 2}, "ferveur_cible_si_concentre": -5, "ignore_armor_si_perturbe": true}'),        ("lotus_sceau_novice",    "Sceau du Lotus Novice",         '["moine_lotus"]', 3, 3, 8, 3, 4, "foi", 22, "ferveur", 1, 3, "Soin 14 PV + dissipe 1 négatif. Concentré : +5.", "soin", "spe", '{"seuil": 2, "soin_base": 14, "concentre_bonus": 5, "cleanse_target": true}'),        ("lotus_paume_avance",    "Paume du Vide Avancée",         '["moine_lotus"]', 3, 3, 10, 4, 4, "foi", 22, "ferveur", 0, 3, "Stun. Concentré : no regen adversaire. Perturbé : +4 Base.", "actif", "spe", '{"seuil": 3, "status": {"stun": 1}, "no_regen_si_concentre": true, "status_si_perturbe": {"root": 1}}'),        ("lotus_perception",      "Perception du Flux (Bonus)",    '["moine_lotus"]', 3, 3, 0, 3, 0, "foi", 10, "ferveur", 0, 2, "État de santé réel de tous dans 15m.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Identifie état de santé réel de tous êtres vivants dans 15m (blessures cachées, maladies, poisons)."}'),
        ("lotus_ancrage",         "Ancrage Mental (Bonus)",        '["moine_lotus"]', 3, 3, 0, 2, 0, "foi", 8, "ferveur", 0, 2, "Dissipe 1 effet contrôle mental.", "utilitaire", "spe", '{"seuil": 1, "cleanse_self": true, "rp_effect": "Dissipe 1 effet contrôle mental/peur. Immunisé intimidation/manipulation ordinaire."}'),
        # P4
        ("lotus_sceau_avance",    "Sceau du Lotus Avancé",         '["moine_lotus"]', 4, 4, 12, 4, 5, "foi", 30, "ferveur", 2, 3, "Soin 22 PV + dissipe tous négatifs. Concentré : +5.", "soin", "spe", '{"seuil": 3, "soin_base": 22, "concentre_bonus": 5, "cleanse_target": true, "cleanse_all": true}'),        ("lotus_frappe_eveil_avance","Frappe de l'Éveil Avancée",  '["moine_lotus"]', 4, 4, 14, 5, 5, "foi", 28, "ferveur", 0, 3, "Stun. Concentré : no regen. Perturbé : +4 Base + ignore Armure+Rob.", "actif", "spe", '{"seuil": 3, "status": {"stun": 1}, "no_regen_si_concentre": true, "ignore_armor_rob_si_perturbe": true}'),        ("lotus_transfert_total_novice","Transfert Total Novice",  '["moine_lotus"]', 4, 4, 10, 4, 5, "foi", 35, "ferveur", 2, 4, "Soin 25 PV allié, perd 8 PV. Concentré : +5.", "soin", "spe", '{"seuil": 3, "soin_base": 25, "concentre_bonus": 5, "self_dmg": 8}'),        ("lotus_secret",          "Secret du Monastère (Bonus)",   '["moine_lotus"]', 4, 4, 0, 3, 0, "foi", 15, "ferveur", 1, 2, "Connaissance interdite du Temple.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Temple révèle connaissance interdite : org secrète, poison rare, technique oubliée ou maladie incurable."}'),
        ("lotus_herbo_cimes",     "Herboristerie des Cimes (Bonus)",'["moine_lotus"]', 4, 4, 0, 2, 0, "foi", 10, "ferveur", 0, 4, "Décoction soignant 15 PV hors combat.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Prépare décoction en 10min : soigne 15 PV hors combat, dissipe Poison ou stabilise KO. Stockable."}'),
        # P5
        ("lotus_frappe_finale",   "Frappe de l'Éveil Finale",      '["moine_lotus"]', 5, 5, 16, 5, 6, "foi", 40, "ferveur", 0, 3, "Dégâts massifs. 3 Hémos. Ignore Armure. Rob cible -3.", "actif", "spe", '{"seuil": 4, "status": {"hemorragie": 3}, "ignore_armor": true, "reduce_rob_cible": 3}'),        ("lotus_transfert_final", "Transfert Total Avancé",        '["moine_lotus"]', 5, 5, 20, 4, 6, "foi", 50, "ferveur", 4, 4, "Soin 40 PV allié + dissipe tous négatifs, perd 15 PV.", "soin", "spe", '{"seuil": 3, "soin_base": 40, "concentre_bonus": 5, "self_dmg": 15, "cleanse_target": true, "cleanse_all": true}'),        ("lotus_sceau_final",     "Sceau du Lotus Final",          '["moine_lotus"]', 5, 5, 14, 5, 6, "foi", 45, "ferveur", 3, 4, "Soin 35 PV + dissipe tous + Armure 15 1 tour.", "soin", "spe", '{"seuil": 4, "soin_base": 35, "cleanse_target": true, "cleanse_all": true, "self_status": {"armure": 15}}'),        ("lotus_noir",            "Lotus Noir (Bonus)",            '["moine_lotus"]', 5, 5, 0, 4, 0, "foi", 35, "ferveur", 3, 6, "Purification profonde d'un traumatisme.", "utilitaire", "spe", '{"seuil": 3, "rp_effect": "Cible consentante affronte pires regrets. Dissipe effets mentaux permanents, malédictions ou compétences bloquées."}'),
        ("lotus_detachement",     "Détachement du Moine (Bonus)",  '["moine_lotus"]', 5, 5, 0, 3, 0, "foi", 20, "ferveur", 2, 4, "Résistance mentale absolue 1 scène.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Résistance mentale absolue pendant 1 scène. Aucune manipulation ou magie mentale."}'),

        # ====================================================================================
        # ORDRE HOSPITALIER — Sous-classe Prêtre
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_hosp_aura",      "[Aura de Sacrifice] (Passif)", '["ordre_hospitalier"]', 1, 1, 0,0,0,"foi",0,"ferveur",0,0, "Chaque attaque sur un allié : 3 dégâts transférés à l'Hospitalier.", "passif", "spe", '{"passif": "hosp_aura"}'),
        ("hosp_aura_sacrifice",   "Aura de Sacrifice (Bonus)",    '["ordre_hospitalier"]', 1, 1, 0, 0, 0, "foi", 5, "ferveur", 0, 0, "Active ou désactive l'Aura de Sacrifice.", "utilitaire", "spe", '{"toggle_aura": true}'),
        ("passif_hosp_resilience","[Résilience Sacrée] (Passif)", '["ordre_hospitalier"]', 2, 2, 0,0,0,"foi",0,"ferveur",0,0, "+2 Robustesse permanente.", "passif", "spe", '{"passif": "hosp_resilience"}'),
        ("passif_hosp_intercession","[Intercession] (Passif)",  '["ordre_hospitalier"]', 3, 3, 0,0,0,"foi",0,"ferveur",0,0, "Une fois par combat, absorbe totalité d'une attaque alliée (aucun dégât pour l'allié).", "passif", "spe", '{"passif": "hosp_intercession"}'),
        ("passif_hosp_martyr",    "[Martyr Vivant] (Passif)",    '["ordre_hospitalier"]', 4, 4, 0,0,0,"foi",0,"ferveur",0,0, "Sous 25% PV : Aura transfère 6 dégâts au lieu de 3.", "passif", "spe", '{"passif": "hosp_martyr"}'),
        ("passif_hosp_redemption","[Rédemption] (Passif)",       '["ordre_hospitalier"]', 5, 5, 0,0,0,"foi",0,"ferveur",0,0, "Mort de l'Hospitalier soigne tous les alliés de 20 PV.", "passif", "spe", '{"passif": "hosp_redemption"}'),
        # --- ACTIFS ---
        ("hosp_imposition",       "Imposition des Mains",        '["ordre_hospitalier"]', 1, 1, 10, 3, 3, "foi", 15, "ferveur", 0, 2, "Soin ciblé. L'Hospitalier subit 2 dégâts.", "soin", "spe", '{"seuil": 1, "soin_cible": 10, "self_dmg": 2}'),        ("hosp_bouclier_sacre",   "Bouclier Sacré",               '["ordre_hospitalier"]', 2, 2, 8, 3, 3, "foi", 20, "ferveur", 0, 3, "Pose état Armure 3 sur un allié.", "soin", "spe", '{"seuil": 2, "self_status": {"armure": 3}, "cible_allie": true}'),        ("hosp_purification",     "Purification Sacrificielle",  '["ordre_hospitalier"]', 3, 3, 11, 4, 4, "foi", 25, "ferveur", 0, 3, "Dissipe toutes les altérations d'un allié. L'Hospitalier en absorbe la moitié.", "soin", "spe", '{"seuil": 2, "cleanse_cible_allie": true, "self_dmg_half_alts": true}'),        ("hosp_sanctuaire",       "Sanctuaire",                  '["ordre_hospitalier"]', 4, 4, 14, 5, 5, "foi", 35, "ferveur", 0, 4, "Zone de protection : tous les alliés ignorent prochains 5 dégâts.", "soin", "spe", '{"seuil": 3, "armure_allie_aoe": 5}'),        ("hosp_sacrifice_absolu",  "Sacrifice Absolu",            '["ordre_hospitalier"]', 5, 5, 0, 6, 0, "foi", 50, "ferveur", 0, 6, "L'Hospitalier tombe à 1 PV. Tous les alliés régénèrent 40% de leurs PV max.", "soin", "spe", '{"seuil": 4, "sacrifice_absolu": true}'),

        # ====================================================================================
        # ORACLE — Sous-classe Prêtre
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_oracle_transe",  "[Transe Mineure] (Passif)",     '["oracle"]', 1, 1, 0,0,0,"foi",0,"ferveur",0,0, "+2 Sagesse, +2 Religion. Présages RP 70% fiables.", "passif", "spe", '{"passif": "oracle_transe"}'),
        ("passif_oracle_futur",   "[Voix du Futur] (Passif)",      '["oracle"]', 2, 2, 0,0,0,"foi",0,"ferveur",0,0, "Présage exact → +20 Ferveur (au lieu de +15).", "passif", "spe", '{"passif": "oracle_futur"}'),
        ("passif_oracle_memoire", "[Mémoire des Fils] (Passif)",   '["oracle"]', 3, 3, 0,0,0,"foi",0,"ferveur",0,0, "2 Présages par tour. Si les 2 exacts : +35 Ferveur.", "passif", "spe", '{"passif": "oracle_memoire"}'),
        ("passif_oracle_tisserand","[Tisserand du Destin] (Passif)",'["oracle"]', 4, 4, 0,0,0,"foi",0,"ferveur",0,0, "Exact : +25 Ferveur. Partiel : +12. Présage exact = effets seuil mini garantis.", "passif", "spe", '{"passif": "oracle_tisserand"}'),
        ("passif_oracle_inevitable","[La Voix de l'Inévitable] (Passif)",'["oracle"]',5, 5, 0,0,0,"foi",0,"ferveur",0,0, "Exact : +30 Ferveur. Effets statut sans seuil si Présage exact sur cible.", "passif", "spe", '{"passif": "oracle_inevitable"}'),
        # P1
        ("oracle_entrave_novice", "Entrave du Destin Novice",      '["oracle"]', 1, 1, 5, 3, 3, "foi", 10, "ferveur", 0, 2, "Freine le mouvement d'un être.", "actif", "spe", '{"seuil": 2, "status": {"root": 1}}'),        ("oracle_touche_novice",  "Touche du Destin Novice (Bonus)", '["oracle"]', 1, 1, 0, 3, 0, "foi", 12, "ferveur", 0, 3, "Réduit Base prochain sort cible de Foi÷2.", "utilitaire", "spe", '{"seuil": 2, "reduce_base_cible": "foi_half", "bonus_si_presage_exact": {"reduce_bonus_pieces": 2}}'),
        ("oracle_vision",         "Vision du Prochain Pas (Bonus)",'["oracle"]', 1, 1, 0, 2, 0, "foi", 8, "ferveur", 0, 2, "Une fois/combat : Présage auto exact.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Une fois/combat : Présage de ce tour compte comme exact automatiquement."}'),
        ("oracle_proba",          "Lecture des Probabilités (Bonus)",'["oracle"]', 1, 1, 0, 2, 0, "foi", 5, "ferveur", 0, 0, "Probabilités favorables/défavorables/neutres.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Avant action risquée : MJ indique probabilités (favorables/défavorables/neutres)."}'),
        ("oracle_encens",         "Encens Oraculaire (Bonus)",     '["oracle"]', 1, 1, 0, 1, 0, "foi", 5, "ferveur", 0, 0, "Prochain Présage RP 90% fiable.", "utilitaire", "spe", '{"rp_effect": "En brûlant 10min encens hors combat : prochain Présage RP fiable à 90%."}'),
        # P2
        ("oracle_deviation_novice","Déviation de Trajectoire Novice",'["oracle"]', 2, 2, 0, 3, 0, "foi", 18, "ferveur", 0, 3, "Réduit prochaine attaque ciblant allié de (Foi).", "defense", "spe", '{"seuil": 2, "protect_allie_foi": true}'),
        ("oracle_frappe_premo_novice","Frappe Prémonitoire Novice",'["oracle"]', 2, 2, 8, 3, 4, "foi", 15, "ferveur", 0, 2, "Dégâts sacrés. Présage exact : +3 Base.", "actif", "spe", '{"seuil": 2, "base_bonus_si_presage": 3}'),        ("oracle_entrave_avance", "Entrave du Destin Avancée",     '["oracle"]', 2, 2, 7, 4, 3, "foi", 16, "ferveur", 0, 2, "Dégâts sacrés. Enracinement + Étourdissement.", "actif", "spe", '{"seuil": 2, "status": {"root": 1, "stun": 1}}'),        ("oracle_bassin",         "Bassin des Reflets (Bonus)",    '["oracle"]', 2, 2, 0, 2, 0, "foi", 12, "ferveur", 0, 2, "1 info sur personne/lieu/événement passé.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Dans surface réfléchissante : MJ révèle 1 info sur personne, lieu ou événement passé lié à cet endroit."}'),
        ("oracle_intervention",   "Intervention Providentielle (Bonus)",'["oracle"]',2, 2, 0, 2, 0, "foi", 10, "ferveur", 0, 0, "Évite accident ou catastrophe imminente.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Intervenez physiquement pour éviter accident/catastrophe imminente (MJ valide)."}'),
        # P3
        ("oracle_inversion_novice","Inversion de Probabilité Novice",'["oracle"]', 3, 3, 0, 3, 0, "foi", 20, "ferveur", 2, 3, "Prochain jet cible : toutes pièces Pile.", "actif", "spe", '{"seuil": 2, "force_pile_next": true}'),
        ("oracle_frappe_premo_avance","Frappe Prémonitoire Avancée",'["oracle"]', 3, 3, 10, 4, 4, "foi", 22, "ferveur", 0, 2, "Dégâts sacrés. Présage exact : +5 Base + ignore Rob.", "actif", "spe", '{"seuil": 3, "base_bonus_si_presage": 5, "ignore_rob_si_presage": true}'),        ("oracle_touche_avance",  "Touche du Destin Avancée (Bonus)", '["oracle"]', 3, 3, 0, 4, 0, "foi", 22, "ferveur", 0, 3, "Stun. Présage exact : cible no regen ce tour.", "utilitaire", "spe", '{"seuil": 3, "status": {"stun": 1}, "no_regen_si_presage": true}'),
        ("oracle_carto",          "Cartographie du Destin (Bonus)",'["oracle"]', 3, 3, 0, 3, 0, "foi", 15, "ferveur", 0, 2, "Conséquences probables d'une décision.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "MJ révèle conséquences probables d\'une décision majeure (orienté, pas certain)."}'),
        ("oracle_reseau",         "Réseau de l'Ordre (Bonus)",     '["oracle"]', 3, 3, 0, 2, 0, "foi", 10, "ferveur", 0, 0, "Renseignements sur personne publique ou organisation.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "L\'Ordre fournit renseignements sur toute personne publique, org ou rumeur majeure en quelques heures."}'),
        # P4
        ("oracle_deviation_totale","Déviation Totale",             '["oracle"]', 4, 4, 0, 4, 0, "foi", 30, "ferveur", 3, 4, "Annule prochaine attaque sur allié. Dégâts à 0.", "defense", "spe", '{"seuil": 3, "annule_attaque_allie": true}'),
        ("oracle_inversion_avance","Inversion de Probabilité Avancée",'["oracle"]',4, 4, 0, 5, 0, "foi", 28, "ferveur", 3, 4, "Zone : tous ennemis pièces Pile ce tour.", "actif", "spe", '{"seuil": 3, "force_pile_zone": true, "aoe": true}'),
        ("oracle_frappe_noeud",   "Frappe du Nœud",                '["oracle"]', 4, 4, 13, 5, 5, "foi", 30, "ferveur", 0, 3, "Ignore Rob. Présage exact : +5 Base + Stun.", "actif", "spe", '{"seuil": 3, "ignore_rob": true, "base_bonus_si_presage": 5, "status_si_presage": {"stun": 1}}'),        ("oracle_entrevision",    "Entrevision (Bonus)",           '["oracle"]', 4, 4, 0, 4, 0, "foi", 25, "ferveur", 2, 3, "Scène passée ou future (6h max) liée à objet.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "MJ révèle scène du passé ou futur proche (6h max) liée à personne ou objet. Véridique mais métaphorique."}'),
        ("oracle_synchro",        "Synchronisation Cosmique (Bonus)",'["oracle"]', 4, 4, 0, 3, 0, "foi", 20, "ferveur", 1, 3, "Contact mental 10min avec l'Ordre.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Contact mental 10min avec l\'Ordre. Transmission/réception infos, visions, alertes en temps réel."}'),
        # P5
        ("oracle_noeud_destin",   "Nœud du Destin",                '["oracle"]', 5, 5, 17, 5, 7, "foi", 45, "ferveur", 5, 4, "Dégâts massifs ignorant toute défense. Stun 2 tours.", "actif", "spe", '{"seuil": 4, "ignore_armor": true, "ignore_rob": true, "status": {"stun": 2}}'),        ("oracle_deviation_absolue","Déviation Absolue",           '["oracle"]', 5, 5, 0, 5, 0, "foi", 40, "ferveur", 4, 5, "Redirige attaque ciblant allié vers un ennemi.", "defense", "spe", '{"seuil": 4, "redirection_attaque": true}'),
        ("oracle_frappe_noeud_avance","Frappe du Nœud Avancée",    '["oracle"]', 5, 5, 16, 6, 6, "foi", 40, "ferveur", 0, 3, "Ignore toute défense. Présage exact <30% PV : Exécution.", "actif", "spe", '{"seuil": 4, "ignore_armor": true, "ignore_rob": true, "execute_percent_si_presage": 30}'),        ("oracle_prophetie",      "Prophétie de l'Ordre (Bonus)",  '["oracle"]', 5, 5, 0, 4, 0, "foi", 60, "ferveur", 6, 6, "Prophétie publique se réalisant dans la session.", "utilitaire", "spe", '{"seuil": 3, "rp_effect": "Prononcez prophétie publique. MJ garantit réalisation dans cette session ou la suivante."}'),
        ("oracle_eternite",       "Regard de l'Éternité (Bonus)",  '["oracle"]', 5, 5, 0, 4, 0, "foi", 40, "ferveur", 3, 4, "Communique avec esprit d'un défunt non résolu.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Communique brièvement (5min) avec esprit défunt dont mort non résolue."}'),

        # ====================================================================================
        # INQUISITEUR DE LA CONFRÉRIE — Sous-classe Prêtre
        # ====================================================================================
        # --- PASSIFS ---
        ("passif_inq_yeux",       "[Yeux du Confesseur] (Passif)", '["inquisiteur"]', 1, 1, 0,0,0,"foi",0,"ferveur",0,0, "+2 Religion, +2 Discrétion. Immunisé illusions P1-P2.", "passif", "spe", '{"passif": "inq_yeux"}'),
        ("passif_inq_dossier",    "[Dossier Vivant] (Passif)",     '["inquisiteur"]', 2, 2, 0,0,0,"foi",0,"ferveur",0,0, "Impossible d'être trompé par infos contradictoires sur cible Condamnée.", "passif", "spe", '{"passif": "inq_dossier"}'),
        ("passif_inq_permanente", "[Inquisition Permanente] (Passif)",'["inquisiteur"]',3, 3, 0,0,0,"foi",0,"ferveur",0,0, "2 Sentences simultanées.", "passif", "spe", '{"passif": "inq_permanente"}'),
        ("passif_inq_balance",    "[La Balance du Confesseur] (Passif)",'["inquisiteur"]',4, 4, 0,0,0,"foi",0,"ferveur",0,0, "+15 Ferveur à chaque nouvelle Sentence.", "passif", "spe", '{"passif": "inq_balance"}'),
        ("passif_inq_grand",      "[Grand Inquisiteur] (Passif)",  '["inquisiteur"]', 5, 5, 0,0,0,"foi",0,"ferveur",0,0, "3 Sentences simultanées. Kill Condamné : +20 Ferveur +1 Verset.", "passif", "spe", '{"passif": "inq_grand"}'),
        # P1
        ("inq_jugement_novice",   "Jugement Novice",               '["inquisiteur"]', 1, 1, 7, 3, 3, "foi", 12, "ferveur", 0, 2, "Dégâts sacrés. Si Condamnée : +3 Base + 1 Brûlure.", "actif", "spe", '{"seuil": 2, "bonus_si_condamne": {"base_bonus": 3, "status": {"brulure": 1}}}'),        ("inq_frappe_novice",     "Frappe d'Inquisition Novice",   '["inquisiteur"]', 1, 1, 6, 3, 3, "foi", 10, "ferveur", 0, 2, "Dégâts sacrés. Si Condamnée : Enracinement.", "actif", "spe", '{"seuil": 2, "status_si_condamne": {"root": 1}}'),        ("inq_aveu",              "Aveu Forcé (Bonus)",            '["inquisiteur"]', 1, 1, 0, 2, 0, "foi", 8, "ferveur", 0, 2, "Force PNJ à répondre véridiquement.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Force PNJ à répondre véridiquement à 1 question. Pas PJs ni Foi égale/sup."}'),
        ("inq_detection",         "Détection des Hérésies (Bonus)",'["inquisiteur"]', 1, 1, 0, 2, 0, "foi", 5, "ferveur", 0, 0, "Détecte corruption, trahison, mensonge.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "En observant quelqu\'un en conversation, détecte s\'il vous cache quelque chose d\'important."}'),
        ("inq_sceau",             "Sceau d'Anathème (Bonus)",      '["inquisiteur"]', 1, 1, 0, 2, 0, "foi", 5, "ferveur", 0, 2, "Marque invisible reconnaissable par la Confrérie.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Appose marque invisible sur cible. Tout membre Confrérie sait qu\'elle est Condamnée."}'),
        # P2
        ("inq_chatiment_novice",  "Châtiment Novice",              '["inquisiteur"]', 2, 2, 8, 4, 3, "foi", 18, "ferveur", 0, 2, "Dégâts sacrés. Si Condamnée : Étourdissement.", "actif", "spe", '{"seuil": 2, "status_si_condamne": {"stun": 1}}'),        ("inq_purif",             "Purification Forcée",           '["inquisiteur"]', 2, 2, 0, 3, 0, "foi", 15, "ferveur", 0, 3, "Dissipe tous effets actifs. Si Condamnée : no buff reste combat.", "actif", "spe", '{"seuil": 2, "cleanse_target": true, "cleanse_all": true, "no_buff_si_condamne": true}'),
        ("inq_frappe_avance",     "Frappe d'Inquisition Avancée",  '["inquisiteur"]', 2, 2, 9, 4, 4, "foi", 16, "ferveur", 0, 2, "Dégâts sacrés. Si Condamnée : Stun + 2 Brûlures.", "actif", "spe", '{"seuil": 2, "status_si_condamne": {"stun": 1, "brulure": 2}}'),        ("inq_archives",          "Archives de la Confrérie (Bonus)",'["inquisiteur"]',2, 2, 0, 2, 0, "foi", 10, "ferveur", 0, 0, "Passé, affiliations, crimes, faiblesses d'une personne.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Réseau Bureau Secret : passé, affiliations, crimes, faiblesses d\'une personne ou org en quelques heures."}'),
        ("inq_interrogatoire",    "Interrogatoire Expert (Bonus)", '["inquisiteur"]', 2, 2, 0, 3, 0, "foi", 8, "ferveur", 0, 2, "Extrait 3 informations vraies d'un PNJ.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Lors d\'interrogatoire : extrait 3 informations vraies d\'un PNJ (sans violence si Foi > résistance morale)."}'),
        # P3
        ("inq_jugement_avance",   "Jugement Avancé",               '["inquisiteur"]', 3, 3, 11, 4, 4, "foi", 25, "ferveur", 0, 2, "Dégâts sacrés. Si Condamnée : 3 Brûlures + Stun.", "actif", "spe", '{"seuil": 3, "status_si_condamne": {"brulure": 3, "stun": 1}}'),        ("inq_contre_esp_novice", "Contre-Espionnage Novice",      '["inquisiteur"]', 3, 3, 0, 3, 0, "foi", 20, "ferveur", 0, 3, "Révèle invisibles/déguisés dans 50m.", "actif", "spe", '{"seuil": 2, "cleanse_furtif": true, "rp_effect": "Révèle toute personne invisible/déguisée/en filature dans 50m."}'),
        ("inq_chatiment_avance",  "Châtiment Avancé",              '["inquisiteur"]', 3, 3, 10, 4, 4, "foi", 22, "ferveur", 0, 2, "Dégâts sacrés. Si Condamnée : Stun 2 tours + ignore Rob.", "actif", "spe", '{"seuil": 3, "status_si_condamne": {"stun": 2}, "ignore_rob_si_condamne": true}'),        ("inq_verite",            "Vérité Absolue (Bonus)",        '["inquisiteur"]', 3, 3, 0, 3, 0, "foi", 20, "ferveur", 2, 3, "Zone 10m où aucun mensonge possible.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Crée zone 10m où aucun mensonge possible pendant 10min. MJ valide réponses."}'),
        ("inq_mandat",            "Mandat de la Confrérie (Bonus)",'["inquisiteur"]', 3, 3, 0, 2, 0, "foi", 15, "ferveur", 0, 0, "Assistance immédiate Confrérie dans zone agents.", "utilitaire", "spe", '{"seuil": 1, "rp_effect": "Dans lieu Confrérie présente : surveillance, protection discrète, accès zone sécurisée."}'),
        # P4
        ("inq_chatiment_divin",   "Châtiment Divin",               '["inquisiteur"]', 4, 4, 13, 5, 5, "foi", 32, "ferveur", 0, 3, "Dégâts sacrés massifs. Si Condamnée : Stun 2 tours + ignore Armure.", "actif", "spe", '{"seuil": 3, "ignore_armor_si_condamne": true, "status_si_condamne": {"stun": 2}}'),        ("inq_purif_totale",      "Purification Totale",           '["inquisiteur"]', 4, 4, 0, 4, 0, "foi", 25, "ferveur", 2, 4, "Dissipe TOUT. Si Condamnée : no buff reste combat + résistances.", "actif", "spe", '{"seuil": 3, "cleanse_target": true, "cleanse_all": true, "no_buff_si_condamne": true}'),
        ("inq_contre_esp_avance", "Contre-Espionnage Avancé",      '["inquisiteur"]', 4, 4, 10, 4, 4, "foi", 25, "ferveur", 0, 3, "Révèle et Condamne automatiquement ennemis Furtifs.", "actif", "spe", '{"seuil": 3, "condamne_furtifs": true, "aoe": true}'),        ("inq_effacement",        "Effacement de Dossier (Bonus)", '["inquisiteur"]', 4, 4, 0, 3, 0, "foi", 20, "ferveur", 2, 3, "Efface identité d'une personne dans une ville.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Efface existence administrative, sociale et criminelle d\'une personne dans une ville. Ne peut cibler PJs."}'),
        ("inq_reseau",            "Réseau d'Inquisition (Bonus)",  '["inquisiteur"]', 4, 4, 0, 4, 0, "foi", 25, "ferveur", 2, 4, "Surveillance totale d'une cible 48h.", "utilitaire", "spe", '{"seuil": 2, "rp_effect": "Cible sous surveillance totale 48h. MJ informe de chaque mouvement important."}'),
        # P5
        ("inq_jugement_final",    "Jugement Final",                '["inquisiteur"]', 5, 5, 20, 6, 7, "foi", 50, "ferveur", 6, 5, "Dégâts sacrés massifs. Condamnée <20% PV : Exécution.", "actif", "spe", '{"seuil": 4, "execute_percent_si_condamne": 20}'),        ("inq_contre_esp_total",  "Contre-Espionnage Total",       '["inquisiteur"]', 5, 5, 14, 5, 5, "foi", 35, "ferveur", 0, 3, "Zone : dissipe tous Furtifs/illusions. Tous révélés = Condamnés.", "actif", "spe", '{"seuil": 3, "cleanse_furtif": true, "condamne_tous_reveles": true, "aoe": true}'),        ("inq_chatiment_absolu",  "Châtiment Absolu",              '["inquisiteur"]', 5, 5, 16, 6, 6, "foi", 40, "ferveur", 0, 4, "Ignore toute défense. Condamnée : Stun 2 tours + 5 Brûlures.", "actif", "spe", '{"seuil": 4, "ignore_armor": true, "ignore_rob": true, "status_si_condamne": {"stun": 2, "brulure": 5}}'),        ("inq_confession",        "Confession Finale (Bonus)",     '["inquisiteur"]', 5, 5, 0, 6, 0, "foi", 70, "ferveur", 8, 6, "Question absolue — l'univers répond véridiquement.", "utilitaire", "spe", '{"seuil": 4, "rp_effect": "Posez question absolue sur mystère, org ou personne. MJ répond véridiquement et complètement."}'),
        ("inq_disparition",       "Disparition Administrative (Bonus)",'["inquisiteur"]',5, 5, 0, 5, 0, "foi", 40, "ferveur", 4, 6, "Fait disparaître un PNJ de la circulation 24h.", "utilitaire", "spe", '{"seuil": 3, "rp_effect": "PNJ disparaît de la circulation sans trace en 24h. Ne peut cibler PJs."}'),

        
    ]




    for s in sorts:
        try:
            # Correction : Ajout de la colonne data_json et d'un 17ème point d'interrogation (?)
            conn.execute('''
                INSERT OR REPLACE INTO config_sorts 
                (ref, nom, classes, pallier, cout_achat, base, coins, bonus, stat_type, cout, cout_type, versets, cooldown, desc, type, cat, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', s)
        except Exception as e:
            print(f"❌ Erreur sur {s[1]}: {e}")


    conn.commit()
    conn.close()
    print("✅ Sorts P1 Mage & Guerrier importés avec succès.")


def get_points_investis_pallier(personnage, pallier_vise):
    """Calcule le nombre de points dépensés dans les sorts du pallier demandé."""
    total_points = 0
    for skill_key in personnage.competences:
        if skill_key in SKILLS_DB:
            data = SKILLS_DB[skill_key]
            if data['pallier'] == pallier_vise:
                total_points += data.get('cout_achat', 1)
    return total_points

class Skill:
    def __init__(self, nom, base, coin_bonus, coin_count, stat_bonus=0, stat_nom="Stat"):
        self.nom = nom
        self.base = base
        self.bonus = coin_bonus
        self.coins = coin_count
        self.stat_bonus = stat_bonus
        self.stat_nom = stat_nom 

    def roll(self, bonus_niveau=0, force_pile=False):
        """Lance les pièces. Chance fixe de 50%. force_pile=True : toutes pièces réussies."""
        chance = 50 
        heads = 0
        details = []
        
        if self.coins <= 0:
            return self.base + self.stat_bonus + bonus_niveau, ["(Aucun jet)"], 0
            
        for _ in range(self.coins):
            if force_pile:
                heads += 1
                details.append("🟡🔮")
            else:
                jet = random.randint(1, 100)
                if jet <= chance:
                    heads += 1
                    details.append("🟡") 
                else:
                    details.append("⚪") 
        
        total = self.base + (self.bonus * heads) + self.stat_bonus + bonus_niveau
        return total, details, heads

class Personnage:
    def __init__(self, user_id, nom, classe_nom, race="Humain", charger_db=False):
        self.user_id = user_id
        self.nom = nom
        self.classe = classe_nom.lower()
        self.race = race
        self.competences = []
        self.sous_classes_unlocked = []
        
        self.niveau = 1
        self.pv_actuel = 10; self.pv_max = 10
        self.mana = 0; self.mana_max = 0
        self.versets_max = 0
        self.tension = 0; self.ferveur = 0; self.versets = 0
        
        # Stats
        self.phy = 0; self.const = 0; self.agi = 0
        self.esp = 0; self.int_stat = 0; self.foi = 0; self.sag = 0
        self.points_stat = 0; self.points_comp = 0; self.points_attribut = 0

        self.alias = None; self.description = "Aucune description."; self.image_url = None
        self.oral = 0; self.force_rp = 0; self.survie = 0
        self.histoire = 0; self.sciences = 0; self.medecine = 0
        self.religion = 0; self.discretion = 0
        self.acrobatie = 0
        self.mode_entrainement = 0; self.snapshot_entrainement = None
        self.monnaie = 0
        self.robustesse = 0
        self.festin = 0
        self.charges_elementaires = []
        # ── Sous-classes V4 ──
        self.passe_active = 0
        self.parade_absorb = 0
        self.last_action_type = "autre"
        self.fureur_tribale_used = 0
        self.concentre = 1
        self.serment_actif = 0
        self.serment_bonus = 0
        self.mana_bonus_racial = 0
        self.bonus_base_item = 0
        self.bonus_pieces_item = 0
        self.mana_max_bonus_item = 0
        self.pv_max_bonus_item = 0
        self.posture_active = 0
        self.designation_target_id = 0
        self.designation_stacks = 0
        self.sentence_target_id = 0
        self.sentence_targets = []  # Liste des cibles Condamnées (P3: max 2, P5: max 3)
        self.passe_count = 0        # Nb de Passes jouées ce tour (Art de l'Estoc Maîtrisé P5)
        self.badges = []            # Titres et récompenses RP accordés par le MJ
        # ── Flags temporaires (non persistés en DB) ──
        self._ignore_armor = False
        self._ignore_rob   = False
        self._sentence_ignore_armure = False
      
        self.cooldowns = {}
        self.equipement = []
        self.effets = {}

        if not charger_db:
            self.init_stats_depart()
            self.appliquer_bonus_race()
            self.recalculer_derives()
            self.pv_actuel = self.pv_max 
            if self.classe == "mage": self.mana = self.mana_max
            self.sauvegarder()

    def init_stats_depart(self):
        if self.classe == "guerrier": self.phy = 4; self.const = 3; self.agi = 1
        elif self.classe == "mage": self.esp = 4; self.int_stat = 4; self.agi = 3
        elif self.classe == "pretre": self.foi = 4; self.sag = 3; self.agi = 2

    def appliquer_bonus_race(self):
        if self.race == "Humain": self.points_stat += 2
        elif self.race == "Elfe": self.esp += 1; self.int_stat += 1
        elif self.race == "Nain": self.const += 1; self.phy += 1
        elif self.race == "Féral": self.agi += 1
        elif self.race == "Céleste" and self.classe == "guerrier": self.tension = 1

    def recalculer_derives(self):
        self.mana_max = 0
        self.versets_max = 0
        if self.classe == "guerrier":
            bonus_humain = (self.niveau // 3) * 2 if self.race == "Humain" else 0
            self.pv_max = 55 + ((self.niveau - 1) * 8) + getattr(self, 'pv_max_bonus_item', 0) + bonus_humain
        elif self.classe == "mage":
            self.pv_max = 35 + ((self.niveau - 1) * 4) + getattr(self, 'pv_max_bonus_item', 0)
            self.mana_max = (self.int_stat * 8) + 10 + getattr(self, 'mana_bonus_racial', 0) + getattr(self, 'mana_max_bonus_item', 0) 
        elif self.classe == "pretre":
            self.pv_max = 45 + ((self.niveau - 1) * 6) + getattr(self, 'pv_max_bonus_item', 0)
            self.versets_max = self.sag 
        if self.race == "Féral":
            self.pv_max -= 5
        # Passifs V4 permanents
        if "passif_legion_rempart" in self.competences:
            self.pv_max += 4
        if "passif_lotus_discipline" in self.competences:
            self.pv_max += 5

    def get_bonus_niveau(self):
        return self.niveau // 5
    
    def sauvegarder(self):
        conn = get_db_connection()
        skills_json = json.dumps(self.competences)
        sous_classes_json = json.dumps(self.sous_classes_unlocked)
        effets_json = json.dumps(self.effets)
        cooldowns_json = json.dumps(self.cooldowns)
        charges_json = json.dumps(self.charges_elementaires)

        conn.execute('''
            INSERT OR REPLACE INTO joueurs 
            (user_id, nom, classe, race, niveau, pv_actuel, pv_max, mana, mana_max,
             tension, ferveur, versets,
             phy, const, agi, esp, int_stat, foi, sag,
             points_stat, points_comp, points_attribut, competences,
             oral, force_rp, survie, histoire, sciences, medecine, religion, discretion, acrobatie,
             alias, description, image_url, 
             mode_entrainement, snapshot_entrainement, sous_classes_unlocked, effets, cooldowns, monnaie, robustesse,
             festin, charges_elementaires,
             passe_active, parade_absorb, last_action_type, fureur_tribale_used,
             concentre, serment_actif, serment_bonus, posture_active,
             designation_target_id, designation_stacks, sentence_target_id, sentence_targets, passe_count, badges, mana_bonus_racial,
             bonus_base_item, bonus_pieces_item, mana_max_bonus_item, pv_max_bonus_item)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) 
        ''', (self.user_id, self.nom, self.classe, self.race, self.niveau,
              self.pv_actuel, self.pv_max, self.mana, self.mana_max,
              self.tension, self.ferveur, self.versets, 
              self.phy, self.const, self.agi,
              self.esp, self.int_stat, self.foi, self.sag,
              self.points_stat, self.points_comp, self.points_attribut, skills_json,
              self.oral, self.force_rp, self.survie, self.histoire, 
              self.sciences, self.medecine, self.religion, self.discretion, self.acrobatie,
              self.alias, self.description, self.image_url, 
              self.mode_entrainement, self.snapshot_entrainement, sous_classes_json, effets_json, cooldowns_json,
              self.monnaie, self.robustesse, self.festin, charges_json,
              self.passe_active, self.parade_absorb, self.last_action_type, self.fureur_tribale_used,
              self.concentre, self.serment_actif, self.serment_bonus, self.posture_active,
              self.designation_target_id, self.designation_stacks, self.sentence_target_id, json.dumps(self.sentence_targets), self.passe_count,
              json.dumps(self.badges), getattr(self, 'mana_bonus_racial', 0),
              getattr(self, 'bonus_base_item', 0), getattr(self, 'bonus_pieces_item', 0),
              getattr(self, 'mana_max_bonus_item', 0), getattr(self, 'pv_max_bonus_item', 0)))
        
        # Ne mettre à jour la session que si ce personnage est déjà le personnage actif
        # Évite d'écraser la session du MJ quand il sauvegarde un PNJ/monstre en combat
        session_row = conn.execute('SELECT nom_perso_actif FROM sessions WHERE user_id = ?', (self.user_id,)).fetchone()
        if session_row is None:
            # Pas encore de session : on en crée une
            conn.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (self.user_id, self.nom))
        # Si une session existe déjà, on ne la touche pas — le MJ reste sur son perso actif
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
        
        race_db = row['race'] if row['race'] else "Humain"
        p = Personnage(user_id, row['nom'], row['classe'], race=race_db, charger_db=True)
        
        colonnes_a_ignorer = ['competences', 'sous_classes_unlocked', 'race', 'effets', 'groupe', 'stabilite', 'sursaut_dispo','familier', 'familier_dispo', 'charges_elementaires']
        
        for col in row.keys():
            if col not in colonnes_a_ignorer:
                setattr(p, col, row[col])
        
        try: p.competences = json.loads(row['competences'])
        except (json.JSONDecodeError, TypeError): p.competences = []
        try: p.sous_classes_unlocked = json.loads(row['sous_classes_unlocked'])
        except (json.JSONDecodeError, TypeError): p.sous_classes_unlocked = []
        try: p.effets = json.loads(row['effets'])
        except (json.JSONDecodeError, TypeError): p.effets = {}
        try: p.cooldowns = json.loads(row['cooldowns'])
        except (json.JSONDecodeError, TypeError): p.cooldowns = {}
        p.monnaie = row['monnaie'] if 'monnaie' in row.keys() else 0
        p.robustesse = row['robustesse'] if 'robustesse' in row.keys() else 0
        p.festin = row['festin'] if 'festin' in row.keys() else 0
        try: p.charges_elementaires = json.loads(row['charges_elementaires']) if 'charges_elementaires' in row.keys() else []
        except (json.JSONDecodeError, TypeError): p.charges_elementaires = []
        # ── Sous-classes V4 ──
        p.passe_active = row['passe_active'] if 'passe_active' in row.keys() else 0
        p.parade_absorb = row['parade_absorb'] if 'parade_absorb' in row.keys() else 0
        p.last_action_type = row['last_action_type'] if 'last_action_type' in row.keys() else 'autre'
        p.fureur_tribale_used = row['fureur_tribale_used'] if 'fureur_tribale_used' in row.keys() else 0
        p.concentre = row['concentre'] if 'concentre' in row.keys() else 1
        p.serment_actif = row['serment_actif'] if 'serment_actif' in row.keys() else 0
        p.serment_bonus = row['serment_bonus'] if 'serment_bonus' in row.keys() else 0
        p.mana_bonus_racial = row['mana_bonus_racial'] if 'mana_bonus_racial' in row.keys() else 0
        p.bonus_base_item = row['bonus_base_item'] if 'bonus_base_item' in row.keys() else 0
        p.bonus_pieces_item = row['bonus_pieces_item'] if 'bonus_pieces_item' in row.keys() else 0
        p.mana_max_bonus_item = row['mana_max_bonus_item'] if 'mana_max_bonus_item' in row.keys() else 0
        p.pv_max_bonus_item = row['pv_max_bonus_item'] if 'pv_max_bonus_item' in row.keys() else 0
        p.posture_active = row['posture_active'] if 'posture_active' in row.keys() else 0
        p.designation_target_id = row['designation_target_id'] if 'designation_target_id' in row.keys() else 0
        p.designation_stacks = row['designation_stacks'] if 'designation_stacks' in row.keys() else 0
        p.sentence_target_id = row['sentence_target_id'] if 'sentence_target_id' in row.keys() else 0
        try:
            p.sentence_targets = json.loads(row['sentence_targets']) if 'sentence_targets' in row.keys() and row['sentence_targets'] else ([p.sentence_target_id] if p.sentence_target_id else [])
        except (json.JSONDecodeError, TypeError):
            p.sentence_targets = [p.sentence_target_id] if p.sentence_target_id else []
        p.passe_count = row['passe_count'] if 'passe_count' in row.keys() else 0
        try: p.badges = json.loads(row['badges']) if 'badges' in row.keys() and row['badges'] else []
        except (json.JSONDecodeError, TypeError): p.badges = []

        p.charger_equipement()
        return p

    @staticmethod
    def charger_par_nom(user_id, nom: str):
        """Charge un personnage précis d'un joueur sans toucher à sa session active."""
        conn = get_db_connection()
        row = conn.execute('SELECT * FROM joueurs WHERE user_id = ? AND nom = ?', (user_id, nom)).fetchone()
        conn.close()
        if not row: return None
        # On réutilise la logique complète de charger() en faisant une petite astuce :
        # On force temporairement la session dans l'objet sans l'écrire en DB.
        race_db = row['race'] if row['race'] else "Humain"
        p = Personnage(user_id, row['nom'], row['classe'], race=race_db, charger_db=True)
        colonnes_a_ignorer = ['competences', 'sous_classes_unlocked', 'race', 'effets', 'groupe', 'stabilite', 'sursaut_dispo','familier', 'familier_dispo', 'charges_elementaires']
        for col in row.keys():
            if col not in colonnes_a_ignorer:
                setattr(p, col, row[col])
        try: p.competences = json.loads(row['competences'])
        except (json.JSONDecodeError, TypeError): p.competences = []
        try: p.sous_classes_unlocked = json.loads(row['sous_classes_unlocked'])
        except (json.JSONDecodeError, TypeError): p.sous_classes_unlocked = []
        try: p.effets = json.loads(row['effets'])
        except (json.JSONDecodeError, TypeError): p.effets = {}
        try: p.cooldowns = json.loads(row['cooldowns'])
        except (json.JSONDecodeError, TypeError): p.cooldowns = {}
        p.monnaie = row['monnaie'] if 'monnaie' in row.keys() else 0
        p.robustesse = row['robustesse'] if 'robustesse' in row.keys() else 0
        p.festin = row['festin'] if 'festin' in row.keys() else 0
        try: p.charges_elementaires = json.loads(row['charges_elementaires']) if 'charges_elementaires' in row.keys() else []
        except (json.JSONDecodeError, TypeError): p.charges_elementaires = []
        p.passe_active = row['passe_active'] if 'passe_active' in row.keys() else 0
        p.parade_absorb = row['parade_absorb'] if 'parade_absorb' in row.keys() else 0
        p.last_action_type = row['last_action_type'] if 'last_action_type' in row.keys() else 'autre'
        p.fureur_tribale_used = row['fureur_tribale_used'] if 'fureur_tribale_used' in row.keys() else 0
        p.concentre = row['concentre'] if 'concentre' in row.keys() else 1
        p.serment_actif = row['serment_actif'] if 'serment_actif' in row.keys() else 0
        p.serment_bonus = row['serment_bonus'] if 'serment_bonus' in row.keys() else 0
        p.mana_bonus_racial = row['mana_bonus_racial'] if 'mana_bonus_racial' in row.keys() else 0
        p.bonus_base_item = row['bonus_base_item'] if 'bonus_base_item' in row.keys() else 0
        p.bonus_pieces_item = row['bonus_pieces_item'] if 'bonus_pieces_item' in row.keys() else 0
        p.mana_max_bonus_item = row['mana_max_bonus_item'] if 'mana_max_bonus_item' in row.keys() else 0
        p.pv_max_bonus_item = row['pv_max_bonus_item'] if 'pv_max_bonus_item' in row.keys() else 0
        p.posture_active = row['posture_active'] if 'posture_active' in row.keys() else 0
        p.designation_target_id = row['designation_target_id'] if 'designation_target_id' in row.keys() else 0
        p.designation_stacks = row['designation_stacks'] if 'designation_stacks' in row.keys() else 0
        p.sentence_target_id = row['sentence_target_id'] if 'sentence_target_id' in row.keys() else 0
        try:
            p.sentence_targets = json.loads(row['sentence_targets']) if 'sentence_targets' in row.keys() and row['sentence_targets'] else ([p.sentence_target_id] if p.sentence_target_id else [])
        except (json.JSONDecodeError, TypeError):
            p.sentence_targets = [p.sentence_target_id] if p.sentence_target_id else []
        p.passe_count = row['passe_count'] if 'passe_count' in row.keys() else 0
        try: p.badges = json.loads(row['badges']) if 'badges' in row.keys() and row['badges'] else []
        except (json.JSONDecodeError, TypeError): p.badges = []
        p.charger_equipement()
        return p

    def ajouter_effet(self, code, duree, puissance=None):
        if self.race == "Drakéide" and code in ["brulure", "gel"]:
            return

        effets_cumulables = ["hemorragie", "brulure"]
        
        if puissance is None:
            puissance = duree

        if code in self.effets:
            self.effets[code]["duree"] += duree
            if code in effets_cumulables:
                self.effets[code]["valeur"] += puissance
            else:
                self.effets[code]["valeur"] = max(self.effets[code]["valeur"], puissance)
        else:
            self.effets[code] = {"duree": duree, "valeur": puissance}
            # Le stun ne prend effet qu'au tour SUIVANT celui où il est appliqué.
            if code == "stun":
                self.effets[code]["nouveau"] = True
        
        if code == "brulure":
             self.effets[code]["valeur"] = self.effets[code]["duree"]
            

    def charger_equipement(self):
        conn = get_db_connection()
        rows = conn.execute('''
            SELECT c.nom, c.slot, c.description, c.bonus_json, i.item_ref, i.identifie
            FROM inventaire i
            JOIN config_items c ON i.item_ref = c.ref
            WHERE i.user_id = ? AND i.equipe = 1
        ''', (self.user_id,)).fetchall()
        self.equipement = [dict(row) for row in rows]

        # Reset bonuses items
        self.bonus_base_item = 0
        self.bonus_pieces_item = 0
        self.mana_max_bonus_item = 0
        self.pv_max_bonus_item = 0

        BONUS_MAP = {
            "pv_max": "pv_max_bonus_item",
            "mana_max": "mana_max_bonus_item",
            "bonus_base_item": "bonus_base_item",
            "bonus_pieces_item": "bonus_pieces_item",
        }

        # Appliquer bonus_json des items identifiés
        for row in rows:
            if not row['identifie']: continue
            try:
                bj = json.loads(row['bonus_json'] or '{}')
                for key, val in bj.items():
                    attr = BONUS_MAP.get(key, key)
                    if hasattr(self, attr):
                        setattr(self, attr, getattr(self, attr, 0) + val)
            except Exception:
                pass

        # Appliquer bonus de sets
        refs_equipes = {row['item_ref'] for row in rows if row['identifie']}
        tous_sets = conn.execute("SELECT * FROM config_sets").fetchall()
        for s in tous_sets:
            items_set = conn.execute("SELECT item_ref FROM config_set_items WHERE set_ref=?",
                                     (s['set_ref'],)).fetchall()
            refs_set = [r['item_ref'] for r in items_set]
            count = sum(1 for r in refs_set if r in refs_equipes)
            for pieces, bonus_col in [(2, 'bonus_2'), (4, 'bonus_4')]:
                if count >= pieces:
                    try:
                        bj = json.loads(s[bonus_col] or '{}')
                        for key, val in bj.items():
                            attr = BONUS_MAP.get(key, key)
                            if hasattr(self, attr):
                                setattr(self, attr, getattr(self, attr, 0) + val)
                    except Exception:
                        pass
        conn.close()


    def verifier_evolution_race(self, niveaux_gagnes):
        """Appelé par le GM lors du Level Up. Retourne les messages d'évolution."""
        ancien_niv = self.niveau - niveaux_gagnes
        messages = []
        for i in range(ancien_niv + 1, self.niveau + 1):
            if i % 3 == 0:
                res = self.appliquer_pallier_race(i)
                if res: messages.append(res)
        return "\n".join(messages)

    def appliquer_pallier_race(self, niveau_palier=None):
        """Les bonus tous les 3 niveaux"""
        niv_affiche = niveau_palier if niveau_palier is not None else self.niveau
        msg = f"🧬 **Évolution Raciale ({self.race}) au niveau {niv_affiche} !**"
        
        if self.race == "Elfe":
            if self.classe == "mage": self.mana_bonus_racial = getattr(self, 'mana_bonus_racial', 0) + 3
            elif self.classe == "guerrier": self.acrobatie += 1; self.religion += 1; msg += " 🌿 +1 Acrobatie (Initiative), +1 Religion !"
            elif self.classe == "pretre": self.medecine += 1; self.religion += 1

        elif self.race == "Humain":
            if self.classe == "mage": pass 
            elif self.classe == "guerrier": self.pv_max += 2; self.pv_actuel += 2
            elif self.classe == "pretre": self.points_comp += 1

        elif self.race == "Nain":
            if self.classe == "mage": self.esp += 1
            elif self.classe == "guerrier": self.const += 1; self.phy += 1
            elif self.classe == "pretre": self.const += 1

        elif self.race == "Drakéide":
            # +1 aux dégâts de base (bonus_base_item) à chaque pallier
            self.bonus_base_item = getattr(self, 'bonus_base_item', 0) + 1
            msg += " 🐲 +1 Dégâts de base (bonus permanent) !"

        elif self.race == "Féral":
            if self.classe == "mage":
                self.agi += 1
                self.acrobatie += 1      
            elif self.classe == "guerrier":
                self.phy += 1
                self.acrobatie += 1     
            elif self.classe == "pretre":
                self.agi += 1     
                self.acrobatie += 1     

        elif self.race == "Céleste":
            if self.classe == "mage": self.mana_bonus_racial = getattr(self, 'mana_bonus_racial', 0) + 2
            elif self.classe == "guerrier": self.tension += 1; msg += " ✨ +1 Tension (bonus de départ permanent) !"
            elif self.classe == "pretre": self.versets_max += 1; self.versets += 1

        elif self.race == "Vampire":
            if self.classe == "mage": self.mana_bonus_racial = getattr(self, 'mana_bonus_racial', 0) + 4; msg += " 🧛 +4 Mana Max !"
            elif self.classe == "guerrier": self.pv_max += 3; self.pv_actuel += 3; msg += " 🧛 +3 PV Max (Régénération vampirique) !"
            elif self.classe == "pretre": self.pv_max += 2; self.pv_actuel += 2; self.mana_bonus_racial = getattr(self, 'mana_bonus_racial', 0) + 2; msg += " 🧛 +2 PV Max, +2 Mana Max !"

        self.recalculer_derives()
        return msg
    

    def get_robustesse(self):
        """Calcule la robustesse totale (Base + Items + Passifs + Résonance Glace)"""
        rob = self.robustesse
        if self.classe in ["guerrier", "monstre"]:
            rob += self.const
        if self.race == "Nain":
            rob += 1 + (self.niveau // 5)
        # Passifs V4 permanents
        if "passif_nord_peau" in self.competences:
            rob += 2
        if "passif_legion_rempart" in self.competences:
            rob += 1
        if "passif_hosp_resilience" in self.competences:
            rob += 2
        # Résonance Glace (Magie Élémentaire)
        if "magie_elementaire" in self.sous_classes_unlocked and self.classe == "mage":
            bonus_res = get_bonus_resonance(self)
            if "glace" in bonus_res:
                rob += bonus_res["glace"]
        return rob

#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
# --- EVENTS ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------


@bot.event
async def on_ready():
    init_db()           
    populate_spells() 
    reload_data()       
    print(f'Connecté en tant que {bot.user.name}')
    try:
        bot.tree.copy_global_to(guild=MY_GUILD_ID)
        await bot.tree.sync(guild=MY_GUILD_ID)
        print("✅ Commandes synchronisées !")
    except Exception as e:
        print(f"❌ Erreur sync: {e}")

#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
# --- AUTOCOMPLETION ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------

# --- AUTOCOMPLETION ---

async def perso_cible_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete listant tous les personnages actifs (sessions) — retourne user_id en value."""
    conn = get_db_connection()
    # On joint sessions + joueurs pour avoir nom, classe, niveau du perso actif de chaque joueur
    rows = conn.execute("""
        SELECT j.user_id, j.nom, j.classe, j.niveau
        FROM sessions s
        JOIN joueurs j ON j.user_id = s.user_id AND j.nom = s.nom_perso_actif
        WHERE j.user_id != ? AND (j.nom LIKE ? OR j.classe LIKE ?)
        LIMIT 25
    """, (interaction.user.id, f"%{current}%", f"%{current}%")).fetchall()
    conn.close()
    choices = []
    for r in rows:
        label = f"{r['nom']} (Niv {r['niveau']} {r['classe'].capitalize()})"
        choices.append(app_commands.Choice(name=label, value=str(r['user_id'])))
    return choices

async def spe_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db_connection()
    rows = conn.execute("SELECT nom FROM config_sous_classes WHERE nom LIKE ?", (f"%{current}%",)).fetchall()
    conn.close()
    return [app_commands.Choice(name=r['nom'].capitalize(), value=r['nom']) for r in rows][:25]

async def sort_offensif_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    is_gm_user = is_gm(user_id)
    nom_override = getattr(interaction.namespace, 'personnage', None)
    p = Personnage.charger_par_nom(user_id, nom_override) if nom_override else Personnage.charger(user_id)
    if not p and not is_gm_user: return []
    choix = []
    for key, val in SKILLS_DB.items():
        if val.get('type') != 'actif': continue
        if not is_gm_user and val.get('cat') == 'monstre' and (not p or key not in p.competences): continue
        if not is_gm_user and val.get('cat') != 'monstre' and p and key not in p.competences: continue
        if current.lower() in val['nom'].lower():
            nom_aff = f"👹 {val['nom']}" if val.get('cat')=='monstre' else val['nom']
            choix.append(app_commands.Choice(name=nom_aff, value=key))
    return choix[:25]


async def action_bonus_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    nom_override = getattr(interaction.namespace, 'personnage', None)
    p = Personnage.charger_par_nom(user_id, nom_override) if nom_override else Personnage.charger(user_id)
    
    # Si le joueur n'a pas de fiche, on ne propose rien
    if not p: return []
    
    choix = []
    for key, val in SKILLS_DB.items():
        # Filtre 1 : sorts bonus = "(BONUS)" dans le nom OU type utilitaire avec cat monstre (freestyle bonus)
        is_bonus_nom = "(BONUS)" in val['nom'].upper()
        is_freestyle_bonus = val.get('cat') == 'monstre' and val.get('type') == 'utilitaire'
        if not is_bonus_nom and not is_freestyle_bonus: continue
        
        # Filtre 2 : On ne montre QUE les sorts que le personnage possède
        if key not in p.competences: continue
        
        if current.lower() in val['nom'].lower():
            choix.append(app_commands.Choice(name=f"⚡ {val['nom']}", value=key))
            
    return choix[:25]

async def sort_soin_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    is_gm_user = is_gm(user_id)
    nom_override = getattr(interaction.namespace, 'personnage', None)
    p = Personnage.charger_par_nom(user_id, nom_override) if nom_override else Personnage.charger(user_id)
    if not p and not is_gm_user: return []
    # Pour les MJs sans override : compétences de toutes leurs fiches
    if is_gm_user and not nom_override:
        conn = get_db_connection()
        toutes_fiches = conn.execute("SELECT competences FROM joueurs WHERE user_id = ?", (user_id,)).fetchall()
        conn.close()
        toutes_comps = set()
        for fiche in toutes_fiches:
            try: toutes_comps.update(json.loads(fiche['competences']))
            except (json.JSONDecodeError, TypeError): pass
        if p: toutes_comps.update(p.competences)
    elif p:
        toutes_comps = set(p.competences)
    else:
        toutes_comps = set()
    choix = []
    for key, val in SKILLS_DB.items():
        if val.get('type') != 'soin': continue
        if key not in toutes_comps: continue
        if current.lower() in val['nom'].lower():
            choix.append(app_commands.Choice(name=val['nom'], value=key))
    return choix[:25]

async def classe_autocomplete(interaction: discord.Interaction, current: str):
    classes_base = ["Guerrier", "Mage", "Pretre", "Monstre"]
    return [app_commands.Choice(name=c, value=c) for c in classes_base if current.lower() in c.lower()]

async def stat_autocomplete(interaction: discord.Interaction, current: str):
    stats = {"phy": "Physique", "esp": "Esprit", "agi": "Agilité", "foi": "Foi", "int_stat": "Intelligence", "sag": "Sagesse", "const": "Constitution"}
    return [app_commands.Choice(name=nom, value=code) for code, nom in stats.items() if current.lower() in nom.lower()]

async def tour_noms_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete pour /tour : liste tous les personnages de tous les joueurs en session.
    Inclut toutes les fiches (pas seulement la fiche active) pour permettre au MJ d'ajouter ses PNJ.
    Retourne la valeur sous la forme 'user_id:nom' pour que /tour puisse charger le bon perso."""
    conn = get_db_connection()
    # On récupère tous les joueurs ayant une session active, puis TOUTES leurs fiches
    rows = conn.execute("""
        SELECT DISTINCT j.user_id, j.nom, j.classe, j.niveau
        FROM joueurs j
        WHERE j.user_id IN (SELECT user_id FROM sessions)
        AND (j.nom LIKE ? OR j.classe LIKE ?)
        ORDER BY j.user_id, j.nom
        LIMIT 25
    """, (f"%{current}%", f"%{current}%")).fetchall()
    conn.close()
    return [
        app_commands.Choice(
            name=f"{r['nom']} (Niv {r['niveau']} {r['classe'].capitalize()})",
            value=f"{r['user_id']}:{r['nom']}"
        )
        for r in rows
    ][:25]

async def joueur_perso_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete listant toutes les fiches du joueur (pour les commandes de combat multi-perso MJ)."""
    user_id = interaction.user.id
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT nom, classe, niveau FROM joueurs WHERE user_id = ? AND nom LIKE ? ORDER BY nom",
        (user_id, f"%{current}%")
    ).fetchall()
    conn.close()
    return [
        app_commands.Choice(name=f"{r['nom']} (Niv {r['niveau']} {r['classe'].capitalize()})", value=r['nom'])
        for r in rows
    ][:25]

async def cible_fiche_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete cible : liste TOUTES les fiches de tous les joueurs en session.
    Retourne 'user_id:nom' pour permettre au MJ de cibler n'importe quelle fiche."""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT DISTINCT j.user_id, j.nom, j.classe, j.niveau
        FROM joueurs j
        WHERE j.user_id IN (SELECT user_id FROM sessions)
        AND (j.nom LIKE ? OR j.classe LIKE ?)
        ORDER BY j.nom
        LIMIT 25
    """, (f"%{current}%", f"%{current}%")).fetchall()
    conn.close()
    return [
        app_commands.Choice(
            name=f"{r['nom']} (Niv {r['niveau']} {r['classe'].capitalize()})",
            value=f"{r['user_id']}:{r['nom']}"
        )
        for r in rows
    ][:25]

def parse_cibles_sec(cibles_str: str):
    """Parse les cibles secondaires : 'user_id:nom' séparés par espaces/virgules.
    Supporte aussi les @mentions Discord. Retourne une liste de Personnage."""
    import re
    tokens = [t.strip() for t in cibles_str.replace(",", " ").split() if t.strip()]
    result = []
    for token in tokens:
        p_sec = None
        if ":" in token:
            p_sec = parse_cible_arg(token)
        else:
            m = re.match(r"<@!?(\d+)>", token)
            if m:
                p_sec = Personnage.charger(int(m.group(1)))
        if p_sec:
            result.append(p_sec)
    return result

def appliquer_statuts_aoe(persos_sec, data_sort, heads=0):
    """Applique les statuts du sort immédiatement sur les fiches secondaires.
    Vérifie le seuil du sort. Les dégâts restent à défendre via /defense."""
    icones_s = {"poison":"☠️","brulure":"🔥","gel":"❄️","stun":"💫",
                "root":"🌳","hemorragie":"🩸","mutilation":"🦴"}
    seuil = data_sort.get("seuil", 0)
    lignes = []
    # Vérifier le seuil — si pas atteint, aucun effet appliqué
    if seuil > 0 and heads < seuil:
        return [f"*Seuil {seuil} non atteint ({heads} 🟡) — Effets zone annulés.*"]
    for p_sec in persos_sec:
        appliques = []
        for effet, valeur in data_sort.get("status", {}).items():
            p_sec.ajouter_effet(effet, valeur)
            appliques.append(f"{icones_s.get(effet,'✨')} {effet.capitalize()} ({valeur})")
        p_sec.sauvegarder()
        if appliques:
            lignes.append(f"**{p_sec.nom}** : {', '.join(appliques)}")
    return lignes

def parse_cible_arg(arg: str):
    """Parse un argument cible de la forme 'user_id:nom' ou 'user_id'.
    Retourne (user_id: int, nom: str | None). Charge le Personnage correspondant."""
    if arg and ':' in arg:
        parts = arg.split(':', 1)
        try:
            uid = int(parts[0])
            nom = parts[1]
            return Personnage.charger_par_nom(uid, nom)
        except (ValueError, IndexError):
            return None
    elif arg:
        try:
            return Personnage.charger(int(arg))
        except ValueError:
            return None
    return None

def resolve_sort_ref(sort: str) -> str:
    """Résout une ref de sort : accepte la ref directe OU le nom affiché (mobile).
    Retourne la ref normalisée si trouvée, sinon la valeur originale."""
    # Normaliser d'abord
    sort_clean = sort.strip().lower()
    # 1. Chercher par ref directe
    if sort_clean in SKILLS_DB:
        return sort_clean
    # 2. Chercher par nom (cas mobile où l'autocomplétion envoie le nom)
    for key, val in SKILLS_DB.items():
        if val['nom'].lower() == sort_clean:
            return key
        # Sans les préfixes emoji (⚡, 👹, etc.)
        nom_clean = val['nom'].lower().strip()
        if nom_clean == sort_clean:
            return key
    return sort_clean  # Retourne tel quel si non trouvé






#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#---------------------------------------------------------------------------
# --- COMMANDES DE COMBAT ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------

def traiter_effets_json(data_json: str, attaquant: Personnage, defenseur: Personnage, degats_actuels: int, heads: int = 0):
    msg = []
    
    if not data_json or data_json == "{}": return degats_actuels, ""
    try: data = json.loads(data_json)
    except (json.JSONDecodeError, ValueError): return degats_actuels, ""

    # --- 1. VÉRIFICATION DU SEUIL ---
    seuil_requis = data.get("seuil", 0)
    if seuil_requis > 0:
        if heads < seuil_requis:
            return degats_actuels, f"*Seuil {seuil_requis} non atteint ({heads} 🟡). Effet annulé.*"
        else: msg.append(f"✅ **Seuil {seuil_requis} atteint !**")

    degats_finaux = degats_actuels

    # --- CONSOMMATION BONUS DÉGÂTS (Schleifen) ---
    if "dmg_boost" in attaquant.effets:
        bonus = attaquant.effets["dmg_boost"]["valeur"]
        degats_finaux += bonus
        del attaquant.effets["dmg_boost"]
        msg.append(f"**BONUS DE DEGATS** : +{bonus} Dégâts !")

    # --- 2. EFFETS RP ---
    if data.get("rp_effect"): msg.append(f"📜 **Info RP** : {data.get('rp_effect')}")

    # --- 3. RESSOURCES ---
    if "generate_tension" in data and attaquant.classe == "guerrier":
        attaquant.tension += data["generate_tension"]
        msg.append(f"💢 **Tension** : +{data['generate_tension']}")
    if "restore_mana" in data and attaquant.classe == "mage":
        attaquant.mana = min(attaquant.mana_max, attaquant.mana + data["restore_mana"])
        msg.append(f"🔵 **Mana** : +{data['restore_mana']}")

    # --- 4. AUTO-BUFFS ---
    for effet, valeur in data.get("self_status", {}).items():
        attaquant.ajouter_effet(effet, valeur)
        if effet == "hate": msg.append("⚡ **Hâte** : +2 Pièces au prochain tour !")
        elif effet == "dmg_boost": msg.append(f"**buff** : +{valeur} Dégâts à la prochaine attaque !")
        else: msg.append(f"**{effet.capitalize()}** (Sur soi) appliqué !")

    # --- 5. CLEANSE ---
    negatifs = ["poison", "brulure", "gel", "stun", "hemorragie", "root"]
    if data.get("cleanse_self"):
        retire = [e for e in negatifs if e in attaquant.effets]
        for e in retire: del attaquant.effets[e]
        if retire: msg.append(f"✨ **Purification** : {', '.join(retire)} retiré(s).")
    # Cracher le Sang : retire 1 stack de Poison ou Brûlure uniquement
    if data.get("cleanse_self_dot"):
        dots = ["poison", "brulure"]
        retire_dot = []
        for dot in dots:
            if dot in attaquant.effets:
                attaquant.effets[dot]["valeur"] = max(0, attaquant.effets[dot]["valeur"] - 1)
                if attaquant.effets[dot]["valeur"] <= 0:
                    del attaquant.effets[dot]
                    retire_dot.append(f"{dot.capitalize()} retiré")
                else:
                    retire_dot.append(f"{dot.capitalize()} réduit (−1 stack)")
        if retire_dot:
            msg.append(f"🩸 **Cracher le Sang** : {', '.join(retire_dot)} !")
        else:
            msg.append("🩸 **Cracher le Sang** : Aucun Poison ou Brûlure actif.")
    if data.get("cleanse_target"):
        retire = [e for e in negatifs if e in defenseur.effets]
        for e in retire: del defenseur.effets[e]
        if retire: msg.append(f"✨ **Cible Purifiée** : {', '.join(retire)} retiré(s).")

    # --- 6. VOL DE VIE ---
    if data.get("lifesteal_flat", 0) > 0:
        cond = data.get("lifesteal_condition")
        if not cond or cond in defenseur.effets:
            attaquant.pv_actuel = min(attaquant.pv_max, attaquant.pv_actuel + data.get("lifesteal_flat", 0))
            msg.append(f"🩸 **Drain** : +{data['lifesteal_flat']} PV récupérés.")
        else: msg.append(f"❌ **Drain échoué** : Cible non affectée par {cond}.")

    # --- 7. APPLICATION STATUS ---
    icones = {
        "poison": "☠️", "brulure": "🔥", "gel": "❄️", "stun": "💫", 
        "root": "🌳", "hemorragie": "🩸", "defi": "📢",
        "mutilation": "🦴", "titanenblut": "🩸", "unsterblich": "🛡️"
    }
    for effet, valeur in data.get("status", {}).items():
        defenseur.ajouter_effet(effet, valeur)
        msg.append(f"{icones.get(effet, '✨')} **{effet.capitalize()}** ({valeur}) appliqué !")

    # --- 8. BONUS & BOUCLIERS ---
    if "bonus_vs_status" in data and data["bonus_vs_status"] in defenseur.effets:
        degats_finaux += data.get("bonus_val", 0)
        msg.append(f"🎯 **Opportunisme** : +{data.get('bonus_val')} Dégâts !")

    if data.get("reduce_dmg_dynamic"):
        attaquant.ajouter_effet("bouclier", 1, degats_finaux)
        msg.append(f"🛡️ **Bouclier Actif** : Absorbera {degats_finaux} dégâts.")
    elif data.get("reduce_dmg_flat", 0) > 0:
        attaquant.ajouter_effet("bouclier", 1, data["reduce_dmg_flat"])
        msg.append(f"🛡️ **Protection** : -{data['reduce_dmg_flat']} dégâts.")
    elif "armure_base" in data:
        # Posture du Lotus : armure conditionnelle selon état Concentré/Perturbé
        attaquant.effets["posture_lotus_active"] = {
            "duree": 1, "valeur": 1,
            "armure_base": data["armure_base"],
            "armure_concentre": data.get("armure_concentre", data["armure_base"]),
            "armure_perturbe": data.get("armure_perturbe", data["armure_base"])
        }
        if attaquant.concentre:
            val_aff = data.get("armure_concentre", data["armure_base"])
            label = "Concentré"
        else:
            val_aff = data.get("armure_perturbe", data["armure_base"])
            label = "Perturbé"
        msg.append(f"🌸 **Posture du Lotus ({label})** : -{val_aff} dégâts au prochain impact !")

    # ==========================================
    # --- 9. NOUVEAUTÉS : SANG & GUERRIER ---
    # ==========================================
    
    # Dégâts sur soi-même (Zorn, Wut)
    if "self_damage" in data:
        attaquant.pv_actuel -= data["self_damage"]
        msg.append(f"**Contrecoup** : L'attaquant perd {data['self_damage']} PV.")

    # Statut conditionnel (Hémostase Novice/Normale)
    if "conditional_status" in data:
        cond = data["conditional_status"]
        c_etat = cond["condition"]
        c_min = cond["min_stacks"]
        c_effet = cond["effect"]
        if c_etat in defenseur.effets and defenseur.effets[c_etat].get("valeur", 0) >= c_min:
            defenseur.ajouter_effet(c_effet, 1)
            msg.append(f"**Condition Remplie ({c_min}+ {c_etat})** : {c_effet.capitalize()} appliqué !")

    # Multiplication de statut (Bain Rouge)
    if "multiply_status" in data:
        m_etat = data["multiply_status"]["status"]
        m_facteur = data["multiply_status"]["factor"]
        if m_etat in defenseur.effets:
            defenseur.effets[m_etat]["valeur"] *= m_facteur
            msg.append(f"**Prolifération** : {m_etat.capitalize()} multiplié par {m_facteur} !")

    # Consommer des stacks pour des dégâts (Hémostase Avancée)
    if "consume_status" in data and "dmg_per_stack" in data:
        c_etat = data["consume_status"]
        if c_etat in defenseur.effets:
            stacks = defenseur.effets[c_etat].get("valeur", 0)
            degats_bonus = stacks * data["dmg_per_stack"]
            degats_finaux += degats_bonus
            del defenseur.effets[c_etat]
            msg.append(f"**Explosion de {c_etat}** ({stacks} stacks) : +{degats_bonus} Dégâts !")

    # ==========================================

    # --- 10. SYSTÈME D'EXÉCUTION (INSTA-KILL) ---
    if "execute_percent" in data:
        seuil_pv = int(defenseur.pv_max * (data["execute_percent"] / 100))
        if defenseur.pv_actuel <= seuil_pv:
            degats_finaux += 9999 
            msg.append(f" **EXÉCUTION** : Cible sous les {data['execute_percent']}% PV !")
            
    if "execute_flat" in data:
        if defenseur.pv_actuel <= data["execute_flat"]:
            degats_finaux += 9999
            msg.append(f"**EXÉCUTION** : Cible sous les {data['execute_flat']} PV.")

    if data.get("aoe"): msg.append("💥 **Zone** : Touche tous les ennemis")
    if data.get("ricochet"): msg.append("🔁 **Ricochet** : Touche une 2ème cible")

    # --- IGNORE ARMOR / IGNORE ROB (flags transmis via attributs temporaires) ---
    if data.get("ignore_armor"):
        attaquant._ignore_armor = True
        attaquant._ignore_rob   = True
        msg.append("🗡️ **Perce-Armure** : Ignore l'Armure ET la Robustesse !")
    elif data.get("ignore_rob"):
        attaquant._ignore_rob = True
        msg.append("🗡️ **Perce-Rob** : Ignore la Robustesse !")

    # Mise à Mort (Assassin P5) : ignore armure + rob si cible a 3+ altérations
    if data.get("ignore_armor_si_3alt") and defenseur and get_nb_alterations(defenseur) >= 3:
        attaquant._ignore_armor = True
        attaquant._ignore_rob   = True
        msg.append("🗡️ **Mise à Mort** : 3+ altérations — Armure et Robustesse ignorées !")
    elif data.get("ignore_armor_si_3alt") and defenseur:
        msg.append(f"⚠️ **Mise à Mort** : {get_nb_alterations(defenseur)} altération(s) (seuil 3 requis pour percer).")
    if data.get("ignore_rob_si_3alt") and defenseur and get_nb_alterations(defenseur) >= 3:
        attaquant._ignore_rob = True  # déjà posé ci-dessus si ignore_armor aussi, mais sécurité

    # Conditionnels contextuels
    if data.get("ignore_armor_si_alourdi") and get_lestage(defenseur) >= 3:
        attaquant._ignore_armor = True
        attaquant._ignore_rob   = True
        msg.append("⚖️ **Alourdie** : Armure + Robustesse ignorées !")
    if data.get("ignore_rob_si_designation") and attaquant.designation_target_id == defenseur.user_id:
        attaquant._ignore_rob = True
        msg.append("🎯 **Désignation** : Robustesse ignorée !")
    if data.get("ignore_rob_si_perturbe") and not attaquant.concentre:
        attaquant._ignore_rob = True
        msg.append("🔥 **Perturbé** : Robustesse ignorée !")
    if data.get("ignore_armor_rob_si_perturbe") and not attaquant.concentre:
        attaquant._ignore_armor = True
        attaquant._ignore_rob   = True
        msg.append("🔥 **Perturbé** : Armure + Robustesse ignorées !")
    if data.get("ignore_armor_si_perturbe") and not attaquant.concentre:
        attaquant._ignore_armor = True
        msg.append("🔥 **Perturbé** : Armure ignorée !")
    if data.get("ignore_armor_si_posture") and attaquant.posture_active:
        attaquant._ignore_armor = True
        msg.append("🛡️ **Posture** : Armure ignorée !")
    if data.get("ignore_rob_si_presage") and attaquant.effets.get("_presage_exact"):
        attaquant._ignore_rob = True
        attaquant.effets.pop("_presage_exact", None)
        msg.append("🔮 **Présage exact consommé** : Robustesse ignorée !")
    if data.get("ignore_armor_si_condamne") and defenseur and defenseur.user_id in attaquant.sentence_targets:
        attaquant._ignore_armor = True
        msg.append("📜 **Sentence** : Armure ignorée !")
    if data.get("ignore_rob_si_condamne") and defenseur and defenseur.user_id in attaquant.sentence_targets:
        attaquant._ignore_rob = True
        msg.append("📜 **Sentence** : Robustesse ignorée !")


    # --- MÉCANIQUE DÉGÂTS GARANTIS (Stoss) ---
    if "guaranteed_dmg" in data:
        guaranteed = data["guaranteed_dmg"]
        if degats_finaux < guaranteed:
            degats_finaux = guaranteed
            msg.append(f"⚖️ **Dégâts Garantis** : {guaranteed} dégâts minimum infligés.")
    
    if data.get("cleanse_aoe"):
        retire = [e for e in negatifs if e in attaquant.effets]
        for e in retire: del attaquant.effets[e]
        retire_def = [e for e in negatifs if e in defenseur.effets]
        for e in retire_def: del defenseur.effets[e]
        msg.append("✨ **Zone Purifiée** : Tous les malus de la zone sont dissipés.")

    # ==========================================
    # --- MÉCANIQUE FESTIN (Magie du Sang) ---
    # ==========================================
    if "generate_festin" in data and attaquant.classe == "mage":
        gain = data["generate_festin"]
        if gain > 0:
            festin_max = get_festin_max(attaquant)
            attaquant.festin = min(festin_max, attaquant.festin + gain)
            stade = get_festin_stade(attaquant)
            stade_txt = f"▶ Stade {stade}" if stade > 0 else ""
            msg.append(f"🩸 **Festin** : +{gain} ({attaquant.festin}) {stade_txt}")
        elif gain < 0:
            attaquant.festin = max(0, attaquant.festin + gain)
            msg.append(f"🩸 **Festin** consommé : {attaquant.festin} restant.")

    # Sorts de sous-classe sans dégâts tant que Stade 3 non atteint
    if data.get("no_dmg_unless_stade3") and get_festin_stade(attaquant) < 3:
        degats_finaux = 0
        msg.append(f"*🩸 Stade {get_festin_stade(attaquant)} insuffisant — Aucun dégât (Stade 3 requis pour infliger des dégâts).*")

    # Soin basé sur le Festin (Millésime Écarlate)
    if data.get("festin_heal") and attaquant.classe == "mage":
        stade = get_festin_stade(attaquant)
        soin_festin = stade * 6  # 0/6/12/18/24 selon stade
        if soin_festin > 0:
            attaquant.pv_actuel = min(attaquant.pv_max, attaquant.pv_actuel + soin_festin)
            msg.append(f"🩸 **Millésime Écarlate** : +{soin_festin} PV (Stade {stade}).")

    # ==========================================
    # --- MÉCANIQUE CHARGES ÉLÉMENTAIRES ---
    # ==========================================
    if "generate_charge" in data and attaquant.classe == "mage":
        element = data["generate_charge"]
        max_ch = get_max_charges(attaquant)
        if len(attaquant.charges_elementaires) >= max_ch:
            attaquant.charges_elementaires.pop(0)
        attaquant.charges_elementaires.append(element)
        c_txt = " ".join([{"feu":"🔥","glace":"❄️","foudre":"⚡","air":"💨"}.get(e,e) for e in attaquant.charges_elementaires])
        msg.append(f"✨ **Charge {element.capitalize()}** acquise ! [{c_txt}]")

    # 2ème charge générée (Tempête Apocalyptique)
    if "generate_charge_2" in data and attaquant.classe == "mage":
        element2 = data["generate_charge_2"]
        max_ch = get_max_charges(attaquant)
        if len(attaquant.charges_elementaires) >= max_ch:
            attaquant.charges_elementaires.pop(0)
        attaquant.charges_elementaires.append(element2)

    # Consommation des charges (Décharge / Transmutation)
    if data.get("consume_charges") and attaquant.charges_elementaires:
        nb = len(attaquant.charges_elementaires)
        is_decharge = data.get("is_decharge", False)
        if is_decharge:
            # Décharge : doublement des pièces du prochain sort TC + passif Tempêtes
            if "passif_elem_tempetes" in attaquant.competences:
                attaquant.pv_actuel = min(attaquant.pv_max, attaquant.pv_actuel + 10)
                attaquant.mana = min(attaquant.mana_max, attaquant.mana + 15)
                msg.append(f"🌪️ **Décharge** : {nb} charges libérées ! Pièces doublées + +10PV +15Mana (Maître des Tempêtes).")
            else:
                msg.append(f"🌪️ **Décharge** : {nb} charges libérées ! Le prochain sort TC double ses Pièces.")
        else:
            # Transmutation : le MJ / joueur choisit le nouvel élément RP
            msg.append(f"✨ **Transmutation** : {nb} charges converties. Choisissez le nouvel élément (RP).")
        attaquant.charges_elementaires.clear()

    # ═══════════════════════════════════════════════════════════════
    # NOUVELLES MÉCANIQUES — SOUS-CLASSES V4
    # ═══════════════════════════════════════════════════════════════

    # -- LESTAGE GRAVITATIONNEL --
    if "generate_lestage" in data:
        stacks = data["generate_lestage"]
        # Passif Poids Croissant (P2) : +1 lestage sur tous les sorts SC
        if "passif_grav_poids" in attaquant.competences:
            stacks += 1
        lestage_msg = ajouter_lestage(defenseur, stacks, attaquant)
        msg.append(lestage_msg)

    # Lestage conditionnel (bonus si cible a déjà N lestages)
    if "generate_lestage_cond" in data:
        cond_data = data["generate_lestage_cond"]
        seuil_l = cond_data.get("seuil_lestage", 2)
        bonus_l = cond_data.get("bonus_si_lestage", 0)
        if get_lestage(defenseur) >= seuil_l:
            lestage_msg = ajouter_lestage(defenseur, bonus_l, attaquant)
            msg.append(lestage_msg)

    # Consommer tous les Lestages pour dégâts (Effondrement de Zone)
    if data.get("consume_lestage_all"):
        stacks_l = get_lestage(defenseur)
        if stacks_l > 0:
            dmg_bonus_l = stacks_l * data.get("dmg_per_lestage", 3)
            degats_finaux += dmg_bonus_l
            defenseur.effets.pop("lestage", None)
            defenseur.effets.pop("singularite", None)
            msg.append(f"⚖️ **Effondrement** : {stacks_l} Lestages → +{dmg_bonus_l} dégâts !")

    # Reset + réapplication lestages (Point de Non-Retour P5)
    if data.get("reset_lestage_plus_2"):
        anciens_l = get_lestage(defenseur)
        nouveaux_l = anciens_l + 2
        defenseur.effets.pop("lestage", None)
        defenseur.effets.pop("singularite", None)
        dmg_fixe_l = anciens_l * 3
        degats_finaux += dmg_fixe_l
        lestage_msg = ajouter_lestage(defenseur, nouveaux_l, attaquant)
        msg.append(f"🌑 **Point de Non-Retour** : {anciens_l} retiré(s) + {nouveaux_l} réinfligé(s), +{dmg_fixe_l} dégâts fixes !\n{lestage_msg}")

    # Ignore Armure si cible Alourdie (3+ lestages)
    if data.get("ignore_armor_si_alourdi") and get_lestage(defenseur) >= 3:
        msg.append("⚖️ **Alourdie** : Armure ignorée !")
        # Marqué pour la résolution de la commande /attaque

    # Status si Alourdie
    if "status_si_alourdi" in data and get_lestage(defenseur) >= 3:
        for eff_code, eff_val in data["status_si_alourdi"].items():
            defenseur.ajouter_effet(eff_code, eff_val)
            msg.append(f"⚖️ **Alourdie** → {eff_code.capitalize()} ({eff_val})")

    # Status si cible a 3+ Lestages AVANT ce sort (status_if_lestage_3)
    if "status_if_lestage_3" in data and defenseur and get_lestage(defenseur) >= 3:
        for eff_code, eff_val in data["status_if_lestage_3"].items():
            defenseur.ajouter_effet(eff_code, eff_val)
            msg.append(f"⚖️ **3+ Lestages** → {eff_code.capitalize()} ({eff_val}) !")

    # Bonus dégâts si Singularité déclenchée par ce sort (Compression Grav P4)
    if data.get("bonus_si_singularite") and get_lestage(defenseur) >= 5:
        bonus_sing = data["bonus_si_singularite"]
        degats_finaux += bonus_sing
        msg.append(f"🌑 **Singularité bonus** : +{bonus_sing} dégâts fixes !")

    # Lestage sur attaquant via bouclier (Bouclier Inertiel Novice/Avancé)
    # Dans le contexte /defense, l'attaquant EST le joueur qui se défend, la cible EST son agresseur.
    # On applique le lestage sur la cible (l'agresseur) directement.
    if data.get("lestage_sur_attaquant") and defenseur:
        lestage_msg_bci = ajouter_lestage(defenseur, data["lestage_sur_attaquant"], attaquant)
        msg.append(f"⚖️ **Bouclier Inertiel** : L'agresseur reçoit {data['lestage_sur_attaquant']} Lestage(s) !\n{lestage_msg_bci}")

    # Bouclier Inertiel Avancé : chaque attaque reçue donne 1 Lestage (flag posé pour 2 tours)
    if data.get("lestage_sur_attaquant_multi"):
        attaquant.ajouter_effet("bouclier_inertiel_actif", 2, 1)
        msg.append("⚖️ **Bouclier Inertiel Avancé** : Chaque attaquant reçoit 1 Lestage pendant 2 tours !")

    # -- DÉSIGNATION (LOGE DE L'OMBRE) --
    if "pose_designation" in data:
        nb_stacks_d = data["pose_designation"]
        attaquant.designation_target_id = defenseur.user_id
        attaquant.designation_stacks = nb_stacks_d
        label_d = "double" if nb_stacks_d >= 2 else "simple"
        msg.append(f"🎯 **Désignation ({label_d})** posée sur {getattr(defenseur, 'nom', 'cible')} !")

    # -- POSE PASSE (ÉCOLE DE L'ESTOC) --
    if data.get("pose_passe"):
        attaquant.passe_active = 1
        attaquant.last_action_type = "passe"
        # Art de l'Estoc Maîtrisé (P5) : compteur de Passes pour réduction coût prochain sort
        if "passif_estoc_maitre" in attaquant.competences:
            attaquant.passe_count = min(getattr(attaquant, "passe_count", 0) + 1, 3)
        msg.append("⚔️ **Passe active** : Si vous êtes attaqué, +2 Tension auto !")

    # -- POSE PARADE ABSORB --
    if "pose_parade_absorb" in data:
        attaquant.parade_absorb = data["pose_parade_absorb"]
        msg.append(f"🛡️ **Parade Absolue** : -{data['pose_parade_absorb']} dégâts absorbés si Clash perdu !")

    # -- DÉGÂTS FIXES (Estoc Direct, Coup de Masse) --
    if "degats_fixes" in data:
        degats_finaux = data["degats_fixes"]
        msg.append(f"⚔️ **Dégâts Fixes** : {degats_finaux} (précision garantie).")

    # -- BONUS SORTS GUERRIER SI SERMENT (le bonus ne se consomme pas) --
    if data.get("apply_serment_bonus") and attaquant.serment_actif:
        bonus_s = get_serment_bonus(attaquant)
        if bonus_s > 0:
            degats_finaux += bonus_s
            msg.append(f"🩸 **Serment du Sang** : +{bonus_s} Base !")

    # -- SENTENCE (INQUISITEUR) -- bonus statut + dégâts conditionnels
    if defenseur and defenseur.user_id in attaquant.sentence_targets:
        if "status_si_condamne" in data:
            for eff_code, eff_val in data["status_si_condamne"].items():
                defenseur.ajouter_effet(eff_code, eff_val)
                msg.append(f"📜 **Sentence** → {eff_code.capitalize()} ({eff_val})")
        if "bonus_si_condamne" in data:
            b = data["bonus_si_condamne"]
            if "base_bonus" in b:
                degats_finaux += b["base_bonus"]
                msg.append(f"📜 **Sentence** : +{b['base_bonus']} Base (cible Condamnée)")
            if "status" in b:
                for ec, ev in b["status"].items():
                    defenseur.ajouter_effet(ec, ev)
        if "execute_percent_si_condamne" in data:
            seuil_exec = int(defenseur.pv_max * data["execute_percent_si_condamne"] / 100)
            if defenseur.pv_actuel <= seuil_exec:
                degats_finaux += 9999
                msg.append(f"📜⚔️ **EXÉCUTION INQUISITORIALE** : Cible Condamnée sous {data['execute_percent_si_condamne']}% PV !")

    # -- ORACLE : bonus si présage exact — consommé à l'usage --
    presage_exact = bool(attaquant.effets.get("_presage_exact"))
    sort_utilise_presage = any(k in data for k in [
        "base_bonus_si_presage", "status_si_presage", "execute_percent_si_presage",
        "ignore_rob_si_presage", "no_regen_si_presage"
    ])
    if presage_exact and sort_utilise_presage:
        # Consommer le flag dès qu'un sort Oracle l'exploite
        attaquant.effets.pop("_presage_exact", None)
        msg.append("🔮 **Prédiction exacte consommée !**")
    if presage_exact:
        if "base_bonus_si_presage" in data:
            bp = data["base_bonus_si_presage"]
            degats_finaux += bp
            msg.append(f"🔮 **Présage exact** : +{bp} Base !")
        if "status_si_presage" in data:
            for eff_code, eff_val in data["status_si_presage"].items():
                defenseur.ajouter_effet(eff_code, eff_val)
                msg.append(f"🔮 **Présage exact** → {eff_code.capitalize()} ({eff_val})")
        if "execute_percent_si_presage" in data and defenseur:
            seuil_p = int(defenseur.pv_max * data["execute_percent_si_presage"] / 100)
            if defenseur.pv_actuel <= seuil_p:
                degats_finaux += 9999
                msg.append(f"🔮⚔️ **EXÉCUTION PROPHÉTIQUE** : Présage exact + cible sous {data['execute_percent_si_presage']}% PV !")

    # -- DÉSIGNATION : exécution si cible désignée --
    if "execute_percent_si_designation" in data and defenseur and attaquant.designation_target_id == defenseur.user_id:
        seuil_d = int(defenseur.pv_max * data["execute_percent_si_designation"] / 100)
        if defenseur.pv_actuel <= seuil_d:
            degats_finaux += 9999
            msg.append(f"🎯⚔️ **EXÉCUTION DE L'OMBRE** : Cible Désignée sous {data['execute_percent_si_designation']}% PV !")

    # -- MOINE : ferveur si Concentré --
    if data.get("ferveur_si_concentre") and attaquant.concentre:
        gain_ferv = data["ferveur_si_concentre"]
        attaquant.ferveur = getattr(attaquant, "ferveur", 0) + gain_ferv
        msg.append(f"🌸 **Concentré** : +{gain_ferv} Ferveur !")

    # -- MOINE : drain ferveur cible si Concentré --
    if "ferveur_cible_si_concentre" in data and attaquant.concentre and defenseur:
        drain_ferv = data["ferveur_cible_si_concentre"]  # valeur négative = drain
        defenseur.ferveur = max(0, getattr(defenseur, "ferveur", 0) + drain_ferv)
        if drain_ferv < 0:
            msg.append(f"🌸 **Concentré** : {abs(drain_ferv)} Ferveur drainée de la cible !")

    # -- MOINE : no_regen si Concentré (empêche regen PV/ressource ce tour) --
    if data.get("no_regen_si_concentre") and attaquant.concentre and defenseur:
        defenseur.ajouter_effet("no_regen", 1, 1)
        msg.append("🌸 **Concentré** : La cible ne peut pas régénérer ce tour !")

    # -- LÉGION : base_bonus_si_posture (Ancrage Défensif Novice) --
    if "base_bonus_si_posture" in data and attaquant.posture_active:
        bonus_bp = data["base_bonus_si_posture"]
        degats_finaux += bonus_bp
        msg.append(f"🛡️ **Posture** : +{bonus_bp} Base (Ancrage Défensif) !")

    # -- LÉGION : armure bonus si Posture active --
    if "armure_si_posture" in data and attaquant.posture_active:
        bonus_arm = data["armure_si_posture"]
        attaquant.ajouter_effet("bouclier", 1, bonus_arm)
        msg.append(f"🛡️ **Posture** : Armure {bonus_arm} (au lieu de {data.get('reduce_dmg_flat', 0)}) !")

    # -- LÉGION : durée armure multi-tours (Bastion) --
    if "duree_armure" in data and data.get("reduce_dmg_flat", 0) > 0:
        duree_arm = data["duree_armure"]
        val_arm = data["armure_si_posture"] if ("armure_si_posture" in data and attaquant.posture_active) else data["reduce_dmg_flat"]
        # Override le bouclier posé par reduce_dmg_flat avec la bonne durée
        attaquant.ajouter_effet("bouclier", duree_arm, val_arm)
        msg.append(f"🛡️ **Bastion** : Armure {val_arm} pendant {duree_arm} tours !")

    # -- LÉGION : réduction fixe bonus en Posture (Bastion Novice/Avancé) --
    if "reduction_bonus_si_posture" in data and attaquant.posture_active:
        red_pos = data["reduction_bonus_si_posture"]
        # Pose un bouclier fixe supplémentaire
        attaquant.ajouter_effet("reduction_fixe_posture", 1, red_pos)
        msg.append(f"🛡️ **Posture Défensive** : -{red_pos} dégâts supplémentaires !")

    # -- LÉGION : réduction fixe générale (Bastion Avancé) --
    if "reduction_fixe" in data and "reduction_bonus_si_posture" not in data:
        attaquant.ajouter_effet("reduction_fixe_posture", 1, data["reduction_fixe"])
        msg.append(f"🛡️ **Bastion** : -{data['reduction_fixe']} dégâts (fixe) !")

    # -- LÉGION : status_si_posture (Zone de Contrôle Avancée P4) --
    if "status_si_posture" in data and attaquant.posture_active and defenseur:
        for eff_code, eff_val in data["status_si_posture"].items():
            defenseur.ajouter_effet(eff_code, eff_val)
            msg.append(f"🛡️ **Posture** → {eff_code.capitalize()} ({eff_val}) supplémentaire !")

    # -- LÉGION : cout_zero_si_posture (Frappe de Bouclier Finale) — narratif uniquement --
    if data.get("cout_zero_si_posture") and attaquant.posture_active:
        msg.append("🛡️ **Posture** : Coût en Tension annulé !")

    # -- LÉGION : rebond_si_bloque (Rempart de Corps Avancé) --
    # Pose un flag pour que /defense applique 4 dégâts en retour si des dégâts sont bloqués
    if "rebond_si_bloque" in data:
        attaquant.ajouter_effet("rebond_actif", 1, data["rebond_si_bloque"])
        msg.append(f"🛡️ **Rempart** : Tout dégât bloqué renvoie {data['rebond_si_bloque']} dégâts en retour !")

    # -- CLAN DU NORD : bonus si Serment + cible <30% PV --
    if "bonus_si_serment_30pct" in data and attaquant.serment_actif and defenseur:
        seuil_s = int(defenseur.pv_max * 0.30)
        if defenseur.pv_actuel <= seuil_s:
            b_s = data["bonus_si_serment_30pct"]
            if "status" in b_s:
                for ec, ev in b_s["status"].items():
                    defenseur.ajouter_effet(ec, ev)
                    msg.append(f"🩸 **Serment + <30% PV** → {ec.capitalize()} ({ev}) !")

    # -- LOTUS : réduction Robustesse de la cible (Frappe de l'Éveil Finale) --
    if "reduce_rob_cible" in data and defenseur:
        red_rob = data["reduce_rob_cible"]
        defenseur.robustesse = max(0, getattr(defenseur, "robustesse", 0) - red_rob)
        defenseur.sauvegarder()
        msg.append(f"🌸 **Frappe de l'Éveil** : Robustesse de la cible réduite de {red_rob} !")

    # -- MOINE : status si Concentré (Frappe du Lotus Novice, Paume du Vide Novice) --
    if "status_si_concentre" in data and attaquant.concentre and defenseur:
        for eff_code, eff_val in data["status_si_concentre"].items():
            defenseur.ajouter_effet(eff_code, eff_val)
            msg.append(f"🌸 **Concentré** → {eff_code.capitalize()} ({eff_val}) !")

    # -- MOINE : status_si_perturbe (Paume du Vide Avancée P3) --
    if "status_si_perturbe" in data and not attaquant.concentre and defenseur:
        for eff_code, eff_val in data["status_si_perturbe"].items():
            defenseur.ajouter_effet(eff_code, eff_val)
            msg.append(f"🔥 **Perturbé** → {eff_code.capitalize()} ({eff_val}) supplémentaire !")

    # -- MOINE : no_soin_next_turn (Paume du Vide) — pose flag sur la cible --
    if data.get("no_soin_next_turn") and defenseur:
        defenseur.ajouter_effet("no_soin", 1, 1)
        msg.append("🌸 **Paume du Vide** : La cible ne peut pas être soignée ce tour !")

    # -- ASSASSIN : double_dot_si_poison (Venin Avancé P3) --
    if data.get("double_dot_si_poison") and defenseur and "poison" in defenseur.effets:
        defenseur.effets["poison"]["valeur"] *= 2
        msg.append(f"☠️ **Venin Avancé** : Poison doublé ! (×2 puissance)")

    # -- LOGE DE L'OMBRE : no_bonus_action_next_turn (Paralysie Neurale) --
    if data.get("no_bonus_action_next_turn") and defenseur:
        defenseur.ajouter_effet("no_bonus_action", 1, 1)
        msg.append("🎯 **Paralysie Neurale** : La cible ne peut pas utiliser d'Action Bonus son prochain tour !")

    # -- LOGE DE L'OMBRE : requiert_designation (Sentence Létale, Exécution) --
    if data.get("requiert_designation") and defenseur:
        if attaquant.designation_target_id != defenseur.user_id:
            msg.append("⚠️ Ce sort **requiert une Désignation active** sur la cible. Aucun effet spécial.")

    # -- LOGE DE L'OMBRE : double_dmg_si_designation (Frappe dans l'Ombre Avancée) --
    if data.get("double_dmg_si_designation") and defenseur and attaquant.designation_target_id == defenseur.user_id:
        degats_finaux *= 2
        msg.append("🎯 **Désignation** : Dégâts doublés !")

    # -- LOGE : consomme_designation_bonus (Perturbation Neurale) --
    if data.get("consomme_designation_bonus") and defenseur and attaquant.designation_target_id == defenseur.user_id:
        attaquant.designation_stacks -= 1
        if attaquant.designation_stacks <= 0:
            attaquant.designation_target_id = 0
        degats_finaux += 4
        msg.append("🎯 **Désignation consommée** : +4 Dégâts (Perturbation Neurale) !")

    # -- LOGE : bonus_si_designation (Frappe dans l'Ombre Novice) — status conditionnel --
    if "bonus_si_designation" in data and defenseur and attaquant.designation_target_id == defenseur.user_id:
        for eff_code, eff_val in data["bonus_si_designation"].get("status", {}).items():
            defenseur.ajouter_effet(eff_code, eff_val)
            msg.append(f"🎯 **Désigné** → {eff_code.capitalize()} ({eff_val}) !")

    # -- CLAN DU NORD : kill_relancer (Déchaînement Avancé P4) --
    # Si ce sort tue la cible (PV → 0), le joueur peut relancer immédiatement sans coût en Tension.
    # On pose un flag sur l'attaquant pour que l'embed l'annonce.
    if data.get("kill_relancer") and defenseur:
        if defenseur.pv_actuel <= 0:
            attaquant.effets["_kill_relancer_dispo"] = {"duree": 1, "valeur": 1}
            msg.append(f"🩸⚡ **Déchaînement** : {getattr(defenseur, 'nom', 'cible')} est à terre ! Vous pouvez immédiatement relancer ce sort sur une nouvelle cible sans coût en Tension !")

    # -- CLAN DU NORD : bonus_si_serment_degats (Coup de Tête Novice) --
    if "bonus_si_serment_degats" in data and attaquant.serment_actif:
        b_sd = data["bonus_si_serment_degats"]
        if "tension_bonus" in b_sd:
            attaquant.tension += b_sd["tension_bonus"]
            msg.append(f"🩸 **Serment** : +{b_sd['tension_bonus']} Tension !")

    # -- CLAN DU NORD : stun_si_serment_bonus_4 (Coup de Masse Novice) --
    if data.get("stun_si_serment_bonus_4") and attaquant.serment_actif and defenseur:
        if attaquant.serment_bonus >= 4:
            defenseur.ajouter_effet("stun", 1)
            msg.append("🩸 **Serment +4** : Étourdissement !")

    # -- ORACLE : reduce_base_cible (Touche du Destin Novice P1) --
    if data.get("reduce_base_cible") and defenseur:
        reduction_b = attaquant.foi // 2
        defenseur.ajouter_effet("malus_base", 1, reduction_b)
        msg_red = f"🔮 **Touche du Destin** : -{reduction_b} Base sur le prochain sort de {getattr(defenseur, 'nom', 'cible')} !"
        # bonus_si_presage_exact : si présage exact ce tour → réduit aussi les Bonus Pièces de 2
        if "bonus_si_presage_exact" in data and attaquant.effets.get("_presage_exact"):
            bonus_pce = data["bonus_si_presage_exact"].get("reduce_bonus_pieces", 2)
            defenseur.ajouter_effet("malus_bonus_pieces", 1, bonus_pce)
            msg_red += f"\n🔮 **Présage exact** : -{bonus_pce} Bonus Pièces en plus !"
        msg.append(msg_red)

    # -- ORACLE : force_pile_next (Inversion de Probabilité Novice) --
    if data.get("force_pile_next") and defenseur:
        defenseur.ajouter_effet("force_pile", 1, 1)
        msg.append("🔮 **Inversion** : Prochain jet de la cible = toutes pièces Pile !")

    # -- ORACLE : protect_allie_foi (Déviation de Trajectoire Novice P2) --
    # Pose un bouclier sur la CIBLE (l'allié désigné à protéger).
    # Le sort est de type defense/action_bonus ; defenseur = la cible choisie.
    if data.get("protect_allie_foi") and defenseur:
        val_prot = attaquant.foi
        defenseur.ajouter_effet("bouclier", 1, val_prot)
        msg.append(f"🔮 **Déviation** : Bouclier {val_prot} posé sur {getattr(defenseur, 'nom', 'allié')} (= Foi de {getattr(attaquant, 'nom', 'lanceur')}) !")

    # -- ORACLE : force_pile_zone (Inversion de Probabilité Avancée) --
    if data.get("force_pile_zone") and defenseur:
        defenseur.ajouter_effet("force_pile", 2, 1)
        msg.append("🔮 **Inversion de Zone** : Tous les jets de la cible = Pile ce tour !")

    # -- ORACLE : no_regen_si_presage (Touche du Destin Avancée) --
    if data.get("no_regen_si_presage") and attaquant.effets.get("_presage_exact") and defenseur:
        defenseur.ajouter_effet("no_regen", 1, 1)
        msg.append("🔮 **Présage exact** : La cible ne peut pas régénérer ce tour !")

    # -- INQUISITEUR : no_buff_si_condamne (Purification Forcée/Totale) --
    if data.get("no_buff_si_condamne") and defenseur and defenseur.user_id in attaquant.sentence_targets:
        defenseur.ajouter_effet("no_buff", 999, 1)
        msg.append("📜 **Condamnée** : La cible ne peut plus recevoir de buffs pour le reste du combat !")

    # -- ÉCOLE DE L'ESTOC : bonus_si_passe_ce_tour (Riposte Foudroyante) --
    if "bonus_si_passe_ce_tour" in data and attaquant.passe_active:
        b_pct = data["bonus_si_passe_ce_tour"].get("base_bonus", 0)
        if b_pct:
            degats_finaux += b_pct
            msg.append(f"⚔️ **Passe active** : +{b_pct} Base (Riposte) !")

    # -- CONSUME_CHARGES : différencier Décharge (is_decharge) de Transmutation --
    # La distinction est gérée par is_decharge flag + self_status decharge_active déjà posé.

    # -- ORACLE : annule_attaque_allie (Déviation Totale P4) --
    if data.get("annule_attaque_allie") and defenseur:
        defenseur.ajouter_effet("deviation_totale", 1, 1)
        msg.append(f"🔮 **Déviation Totale** : La prochaine attaque sur {getattr(defenseur, 'nom', 'allié')} est annulée (dégâts → 0) !")

    # -- ORACLE : redirection_attaque (Déviation Absolue P5) --
    if data.get("redirection_attaque") and defenseur:
        # Pose un flag sur l'allié : la prochaine attaque le ciblant est redirigée vers un ennemi (MJ gère)
        defenseur.ajouter_effet("redirection_active", 1, 1)
        msg.append(f"🔮 **Déviation Absolue** : Prochaine attaque sur {getattr(defenseur, 'nom', 'allié')} redirigée vers un ennemi (MJ désigne la nouvelle cible) !")

    # ─────────────────────────────────────────────────────────────────────────────
    # HANDLERS MANQUANTS — Sous-classes V4
    # ─────────────────────────────────────────────────────────────────────────────

    # -- ÉCOLE DE L'ESTOC : status_si_clash_gagne (Sixte Filée, Tierce Croisée, Riposte du Maître) --
    # Ce flag est stocké pour être appliqué par /riposte si le vainqueur est attaquant.
    # On le pose dans effets de l'attaquant comme flag temporaire que /riposte lira.
    if "status_si_clash_gagne" in data:
        attaquant.effets["_status_si_clash_gagne"] = {"duree": 1, "valeur": json.dumps(data["status_si_clash_gagne"])}
        msg.append("⚔️ **Passe** : Statut conditionnel posé (Clash gagné requis).")

    # -- ÉCOLE DE L'ESTOC : retour_degats_si_marge_3 (Passe Royale P5) --
    # Le retour de dégâts se fait dans /riposte si l'attaquant gagne avec marge ≥ 3 pièces.
    if data.get("retour_degats_si_marge_3"):
        attaquant.effets["_retour_marge_3"] = {"duree": 1, "valeur": 1}
        msg.append("⚔️ **Passe Royale** : Si vous gagnez le Clash avec 3+ pièces de marge, l'ennemi subit aussi vos dégâts !")

    # -- MAGIE GRAVITATIONNELLE : double_rupture (Pression Gravitationnelle Avancée P4) --
    # Si la cible était déjà en Singularité avant ce sort, le passif Point de Rupture s'applique deux fois.
    if data.get("double_rupture") and defenseur:
        if "passif_grav_rupture" in attaquant.competences and "singularite" in defenseur.effets:
            degats_finaux += 8  # deuxième application du passif
            msg.append("🌑 **Double Rupture** : Point de Rupture appliqué deux fois ! +8 dégâts fixes supplémentaires.")

    # -- MAGIE GRAVITATIONNELLE : check_singularite_all (Effondrement Stellaire P5) --
    # Vérifie et déclenche immédiatement la Singularité sur chaque cible touchée (AoE).
    # En combat solo (cible unique), on consomme la singularité ici.
    if data.get("check_singularite_all") and defenseur:
        ignore_sing, bonus_sing, msg_sing = consommer_singularite(defenseur, attaquant)
        if ignore_sing:
            degats_finaux += bonus_sing
            attaquant._ignore_armor = True
            attaquant._ignore_rob = True
            msg.append(f"🌑 **Singularité (Stellaire)** déclenchée sur {getattr(defenseur, 'nom', 'cible')} !\n{msg_sing}")

    # -- LOGE DE L'OMBRE : bonus_si_deja_designee (Marquage Avancé P2) --
    # +1 pièce supplémentaire si la cible était déjà désignée avant ce sort.
    if "bonus_si_deja_designee" in data and defenseur and attaquant.designation_target_id == defenseur.user_id:
        msg.append(f"🎯 **Déjà Désignée** : +{data['bonus_si_deja_designee']} Pièce(s) bonus (déjà marquée) !")
        # Note : ce bonus est narratif ici — les pièces sont fixées avant le roll.
        # Il faut l'appliquer avant le roll dans /attaque. On stocke un flag.
        attaquant.effets["_bonus_marquage_avance"] = {"duree": 1, "valeur": data["bonus_si_deja_designee"]}

    # -- ÉCOLE DE L'ESTOC : base_override (Estoc Direct si Passe active) --
    if "bonus_si_passe" in data and attaquant.passe_active:
        override = data["bonus_si_passe"].get("base_override")
        if override is not None:
            degats_finaux = override + attaquant.phy  # base_override remplace la Base entière
            msg.append(f"⚔️ **Estoc Direct (Passe)** : Base remplacée par {override} → {degats_finaux} dégâts fixes !")

    # -- GÉNÉRAL : self_dmg (auto-dégât du lanceur, ex: Imposition des Mains) --
    # Géré ici pour les sorts non-Moine qui ont un self_dmg.
    if "self_dmg" in data and attaquant and not (
        "moine_lotus" in getattr(attaquant, "sous_classes_unlocked", [])
        and "soin_base" in data
    ):
        dmg_self = data["self_dmg"]
        if dmg_self > 0 and attaquant.pv_actuel > dmg_self:
            attaquant.pv_actuel -= dmg_self
            msg.append(f"💔 **Contrecoup** : {attaquant.nom} subit {dmg_self} dégâts.")
        elif dmg_self > 0:
            msg.append("⚠️ **Contrecoup** : PV insuffisants pour payer le coût en PV.")

    # -- ORDRE HOSPITALIER : soin_cible (Imposition des Mains) --
    # Soin fixe supplémentaire sur la cible, en plus du jet normal.
    if "soin_cible" in data and defenseur:
        soin_bonus = data["soin_cible"]
        defenseur.pv_actuel = min(defenseur.pv_max, defenseur.pv_actuel + soin_bonus)
        msg.append(f"💚 **Imposition des Mains** : +{soin_bonus} PV sur {getattr(defenseur, 'nom', 'cible')} !")

    # -- ORDRE HOSPITALIER : cleanse_cible_allie + self_dmg_half_alts (Purification Sacrificielle) --
    if data.get("cleanse_cible_allie") and defenseur:
        negatifs_p = ["poison", "brulure", "gel", "stun", "hemorragie", "root", "corruption"]
        retirees = [e for e in negatifs_p if e in defenseur.effets]
        for e in retirees:
            del defenseur.effets[e]
        if retirees:
            msg.append(f"✨ **Purification** : {', '.join(retirees)} retiré(s) de {getattr(defenseur, 'nom', 'cible')}.")
        if data.get("self_dmg_half_alts") and retirees:
            nb_alts = len(retirees)
            dmg_self_p = nb_alts // 2
            if dmg_self_p > 0 and attaquant.pv_actuel > dmg_self_p:
                attaquant.pv_actuel -= dmg_self_p
                msg.append(f"💔 **Purification Sacrificielle** : L'Hospitalier absorbe {dmg_self_p} altérations (-{dmg_self_p} PV).")

    # -- ORDRE HOSPITALIER : armure_allie_aoe (Sanctuaire P4) --
    # Pose un état Armure 5 sur la cible (et narrativement sur toute l'équipe via AoE).
    if "armure_allie_aoe" in data and defenseur:
        val_arm = data["armure_allie_aoe"]
        defenseur.ajouter_effet("bouclier", 1, val_arm)
        msg.append(f"🛡️ **Sanctuaire** : Armure {val_arm} posée sur {getattr(defenseur, 'nom', 'la zone')} (annoncez aux autres alliés) !")

    # -- ORDRE HOSPITALIER : sacrifice_absolu (Sacrifice Absolu P5) --
    if data.get("sacrifice_absolu") and attaquant:
        attaquant.pv_actuel = 1
        # Soin de 40% des PV max sur tous les alliés (MJ notifié — le bot ne peut pas cibler toute l'équipe auto)
        msg.append(f"✨ **SACRIFICE ABSOLU** : {attaquant.nom} tombe à 1 PV ! Tous les alliés régénèrent **40% de leurs PV max** (annoncez le soin — chaque allié utilise /defense ou /gm_effet).")

    # -- INQUISITEUR : cleanse_furtif (Contre-Espionnage Novice P3 / Total P5) --
    # Révèle les personnes invisibles/déguisées. Retire les effets de furtivité sur la cible.
    if data.get("cleanse_furtif") and defenseur:
        furtifs = [e for e in ["invisible", "furtif", "voile", "camouflage", "grimage"] if e in defenseur.effets]
        for e in furtifs:
            del defenseur.effets[e]
        msg_furtif = f"📜🔍 **Contre-Espionnage** : {getattr(defenseur, 'nom', 'cible')} révélé(e) !"
        if furtifs:
            msg_furtif += f" (effets retirés : {', '.join(furtifs)})"
        else:
            msg_furtif += " (aucun effet de furtivité actif — MJ peut révéler PNJ cachés dans la zone)"
        msg.append(msg_furtif)

    # -- INQUISITEUR : condamne_furtifs (Contre-Espionnage Avancé P4) --
    # Révèle ET condamne automatiquement les ennemis furtifs dans la zone.
    if data.get("condamne_furtifs") and attaquant and defenseur:
        # Retire furtivité
        furtifs_c = [e for e in ["invisible", "furtif", "voile", "camouflage", "grimage"] if e in defenseur.effets]
        for e in furtifs_c:
            del defenseur.effets[e]
        # Condamne automatiquement
        if defenseur.user_id not in attaquant.sentence_targets:
            attaquant.sentence_targets.append(defenseur.user_id)
            attaquant.sentence_target_id = defenseur.user_id
        msg.append(f"📜⚔️ **Contre-Espionnage Avancé** : {getattr(defenseur, 'nom', 'cible')} révélé(e) et automatiquement Condamné(e) !")

    # -- INQUISITEUR : condamne_tous_reveles (Contre-Espionnage Total P5) --
    if data.get("condamne_tous_reveles") and attaquant:
        if defenseur and defenseur.user_id not in attaquant.sentence_targets:
            attaquant.sentence_targets.append(defenseur.user_id)
            attaquant.sentence_target_id = defenseur.user_id
            msg.append(f"📜⚔️ **Contre-Espionnage Total** : {getattr(defenseur, 'nom', 'cible')} est automatiquement Condamné(e) !")

    # --- ORDRE HOSPITALIER : toggle_aura (Aura de Sacrifice) ---
    if data.get("toggle_aura") and attaquant:
        if "aura_active" in attaquant.effets:
            del attaquant.effets["aura_active"]
            msg.append("✨ **Aura de Sacrifice** désactivée.")
        else:
            attaquant.effets["aura_active"] = {"duree": 9999, "valeur": attaquant.user_id}
            msg.append("✨ **Aura de Sacrifice** activée ! Vous absorbez 3 dégâts (ou 6 sous 25% PV) pour chaque allié protégé.")

    return degats_finaux, "\n".join(msg)


def verifier_cooldown(personnage: Personnage, sort_ref: str):
    """Vérifie si un sort est actuellement en temps de recharge."""
    if sort_ref in personnage.cooldowns:
        tours_restants = personnage.cooldowns[sort_ref]
        nom_sort = SKILLS_DB.get(sort_ref, {'nom': sort_ref}).get('nom', sort_ref)
        return False, f"⏳ **{nom_sort}** est en recharge pour encore {tours_restants} tour(s)."
    return True, ""

def appliquer_cooldown(personnage: Personnage, sort_ref: str):
    """Applique le cooldown d'un sort après son utilisation."""
    if sort_ref in SKILLS_DB:
        cd = SKILLS_DB[sort_ref].get('cooldown', 0)
        if cd > 0:
            personnage.cooldowns[sort_ref] = cd

def maj_etat_moine(p: 'Personnage', skill_data: dict, visuel: list) -> str:
    """Gère les transitions d'état Concentré/Perturbé du Moine du Lotus.
    - 2 sorts Tronc Commun consécutifs  → Perturbé  (si Concentré, sans Éveil P5)
    - 2 sorts Sous-Classe consécutifs   → Concentré (si Perturbé)
    Retourne un message de transition (vide si aucun changement).
    """
    if "moine_lotus" not in p.sous_classes_unlocked:
        return ""

    prev_action = p.last_action_type
    action_type = "TC" if skill_data.get("cat") == "tronc" else "spe"
    p.last_action_type = action_type
    msg = ""

    if "passif_lotus_eveil" not in p.competences:
        # Concentré + 2 TC consécutives → Perturbé
        if p.concentre and action_type == "TC" and prev_action == "TC":
            p.concentre = 0
            visuel.append("🔥(Perturbé!)")
            msg = "\n🔥 **Perturbé !** Le flux est rompu."

    # Perturbé + 2 sorts Sous-Classe consécutifs → Concentré
    if not p.concentre and action_type == "spe" and prev_action == "spe":
        p.concentre = 1
        visuel.append("🌸(Concentré!)")
        msg = "\n🌸 **Concentré !** L'équilibre est restauré."

    return msg

def is_stun_actif(p) -> bool:
    """Retourne True si le stun bloque les actions (flag nouveau=False = tour suivant l'application)."""
    if "stun" not in p.effets:
        return False
    return not p.effets["stun"].get("nouveau", False)

@bot.tree.command(name="action_bonus", description="⚡ Action rapide (Buff personnel, Soin, Drain)")
@app_commands.describe(sort="La compétence à utiliser", description="Description RP", cible="[Optionnel] Ennemi via @mention", cible_fiche="[Optionnel] Ennemi via nom de fiche (prioritaire sur @)", personnage="[Optionnel] Votre personnage (si vous jouez plusieurs fiches)")
@app_commands.autocomplete(sort=action_bonus_autocomplete, personnage=joueur_perso_autocomplete, cible_fiche=cible_fiche_autocomplete)
async def action_bonus(interaction: discord.Interaction, sort: str, description: str, cible: discord.Member = None, cible_fiche: str = None, personnage: str = None):
    await interaction.response.defer() 

    p: Personnage = Personnage.charger_par_nom(interaction.user.id, personnage) if personnage else Personnage.charger(interaction.user.id)
    # cible_fiche (autocomplete fiche) prioritaire sur le @ Discord
    if cible_fiche:
        p_cible = parse_cible_arg(cible_fiche)
    elif cible:
        p_cible = Personnage.charger(cible.id)
    else:
        p_cible = p

    if not p: return await interaction.followup.send("❌ Pas de fiche.", ephemeral=True)
    if (cible_fiche or cible) and not p_cible: return await interaction.followup.send("❌ La cible n'a pas de fiche de personnage.", ephemeral=True)
    if p.pv_actuel <= 0: return await interaction.followup.send("💀 K.O.", ephemeral=True)

    if is_stun_actif(p): return await interaction.followup.send("💫 **Étourdi !** Impossible d'agir.", ephemeral=True)
    if "gel" in p.effets: return await interaction.followup.send("❄️ **Gelé !** Impossible d'agir.", ephemeral=True)
    if "no_bonus_action" in p.effets:
        return await interaction.followup.send("🎯 **Paralysie Neurale** : Vous ne pouvez pas utiliser d'Action Bonus ce tour !", ephemeral=True)
    if "toxine" in p.effets:
        return await interaction.followup.send("🧪 **Neurotoxine** : La Toxine vous empêche d'utiliser une Action Bonus ce tour !", ephemeral=True)

    sort = resolve_sort_ref(sort)
    if sort not in SKILLS_DB: return await interaction.followup.send("❌ Sort introuvable.", ephemeral=True)
    skill_data = SKILLS_DB[sort]

    dispo, msg_err = verifier_cooldown(p, sort)
    if not dispo: return await interaction.followup.send(msg_err, ephemeral=True)

    if "(BONUS)" not in skill_data['nom'].upper():
        return await interaction.followup.send("❌ Ce sort n'est pas une **Action Bonus**.", ephemeral=True)

    cout = skill_data.get("cout", 0); cout_type = skill_data.get("cout_type", "mana")
    reduc_humain = p.niveau // 3
    if p.race == "Humain" and p.classe == "mage" and reduc_humain > 0: 
        cout = max(int(skill_data.get("cout", 0) / 2), cout - reduc_humain)
    
    cout_paye_en_pv = False
    cout_msg = ""
    if cout > 0:
        valeur_actuelle = getattr(p, cout_type, 0)
        if "mode_sang" in p.effets and p.race == "Vampire" and p.classe == "mage" and p.pv_actuel > cout:
            p.pv_actuel -= cout; cout_paye_en_pv = True
            cout_msg += f" (-{cout} PV 🩸)"
        elif valeur_actuelle >= cout: 
            setattr(p, cout_type, valeur_actuelle - cout)
            ico = "🔵" if cout_type == "mana" else "🔴" if cout_type == "tension" else "🟨"
            cout_msg += f" (-{cout} {cout_type.capitalize()} {ico})"
        elif p.race == "Vampire" and p.classe == "mage" and p.pv_actuel > cout:
            p.pv_actuel -= cout; cout_paye_en_pv = True
            cout_msg += f" (-{cout} PV 🩸)"
        else: return await interaction.followup.send(f"❌ Pas assez de **{cout_type}**.", ephemeral=True)
        
    cout_versets = skill_data.get("versets", 0)
    if cout_versets > 0:
        if p.versets < cout_versets: return await interaction.followup.send(f"❌ **Foi insuffisante !**", ephemeral=True)
        p.versets -= cout_versets
        cout_msg += f" (-{cout_versets} Verset(s) 📜)"

    stat_nom = skill_data["stat_type"].upper()
    stat_valeur = getattr(p, skill_data["stat_type"], 0)
    if p.classe == "guerrier": stat_valeur = p.phy; stat_nom = "PHY"
    elif p.classe == "mage": stat_valeur = p.esp; stat_nom = "ESP"
    elif p.classe == "pretre": stat_valeur = p.foi; stat_nom = "FOI"

    skill_obj = Skill(skill_data["nom"], skill_data["base"] + getattr(p, 'bonus_base_item', 0), skill_data["bonus"], skill_data["coins"] + getattr(p, 'bonus_pieces_item', 0), stat_bonus=stat_valeur, stat_nom=stat_nom)

    if "hate" in p.effets:
        skill_obj.coins += 2
        cout_msg += " ⚡(Hâte)"
        del p.effets["hate"] 

    if "titanenblut" in p.effets:
        skill_obj.coins += 1
        cout_msg += " 🩸(Titan)"

    if "toxine" in p.effets:
        stacks_toxine = p.effets["toxine"].get("valeur", 1)
        skill_obj.coins = max(1, skill_obj.coins - stacks_toxine)
        cout_msg += f" 🧪(-{stacks_toxine}🪙)"

    if "furtif_assassin" in p.effets:
        skill_obj.coins += 1
        del p.effets["furtif_assassin"]
        cout_msg += " 🌑(+1🪙 Furtif)"

    fp_ab = bool(p.effets.get("force_pile"))
    if fp_ab:
        del p.effets["force_pile"]
    total, visuel, heads = skill_obj.roll(bonus_niveau=p.get_bonus_niveau(), force_pile=fp_ab)
    if fp_ab: visuel.append("🔮(Toutes Pile !)")

    if skill_obj.coins > skill_data["coins"]: visuel.append("⚡(+2 Pièces)")
    # Poison non appliqué sur Action Bonus (exemption volontaire)

    json_data = skill_data.get('data_json', '{}')

    # --- DÉSIGNATION (Loge de l'Ombre) — appliquée AVANT le seuil/traiter ---
    msg_designation_pre = ""
    if "loge_ombre" in p.sous_classes_unlocked and p_cible and p.designation_target_id == p_cible.user_id:
        pieces_bonus_d_pre, msg_designation_pre = appliquer_designation(p, p_cible, skill_data)
        if pieces_bonus_d_pre > 0:
            skill_obj.coins += pieces_bonus_d_pre
            total, visuel, heads = skill_obj.roll(bonus_niveau=bonus_niv)
            visuel.append(f"🎯+{pieces_bonus_d_pre}(Désig)")

    total, msg_effets_spe = traiter_effets_json(json_data, p, p_cible, total, heads=heads)

    # Masse Initiale (Magie Gravitationnelle P1) : sorts TC → +1 Lestage si cible ≥ 3 Lestages
    if "passif_grav_masse" in p.competences and skill_data.get("cat") == "tronc":
        if get_lestage(p_cible) >= 3:
            ajouter_lestage(p_cible, 1, p)
            msg_effets_spe = (msg_effets_spe or "") + "\n⚫ **Masse Initiale** : +1 Lestage bonus (cible portait ≥ 3 Lestages) !"
    
    if msg_effets_spe: visuel.append(f"\n{msg_effets_spe}")

    # --- Moine du Lotus : +4 Base si Perturbé | +2 Base si Éveil P5 (tous sorts offensifs) ---
    if "moine_lotus" in p.sous_classes_unlocked and skill_data.get('type') != 'soin':
        if "passif_lotus_eveil" in p.competences:
            total += 2
            visuel.append("+2(Éveil)")
        elif not p.concentre:
            total += 4
            visuel.append("🔥+4(Perturbé)")

    # --- Légion de Fer : -3 Base en Posture (-1 si Implacable P4) ---
    if "legion_fer" in p.sous_classes_unlocked and p.posture_active:
        malus_pos = 1 if "passif_legion_implacable" in p.competences else 3
        total -= malus_pos
        visuel.append(f"🛡️(-{malus_pos} Posture)")

    msg_effet = ""
    if skill_data.get('type') == 'soin':
        if p.race == "Céleste": total += 3
        p.pv_actuel = min(p.pv_max, p.pv_actuel + total)
        msg_effet = f"\n💚 **Soin :** +{total} PV"
    elif not skill_data.get("reduce_dmg_dynamic"):
        if p.race == "Drakéide" and p.niveau >= 3:
            total += (p.niveau // 3)
            visuel.append("🐲")
        
        if "mutilation" in p.effets:
            total = int(total * 0.75)
            visuel.append("(-25% Mutilé)")
            
        msg_effet = f"\n💥 **Puissance :** {total}"
    
    appliquer_cooldown(p, sort)
    
    msg_moine_ab = maj_etat_moine(p, skill_data, visuel)
    if p_cible and p_cible.user_id != p.user_id:
        p_cible.sauvegarder()
    p.sauvegarder()
    
    nom_cible_txt = f" ➔ **{p_cible.nom}**" if (cible_fiche or cible) else ""
    embed = discord.Embed(title="⚡ ACTION BONUS", color=0x00FFFF)
    embed.description = f"**{p.nom}**{nom_cible_txt} : *« {description} »*"
    
    calcul_txt = f"Base {skill_obj.base} + ({heads}x{skill_obj.bonus}) + {stat_nom}"
    if cout_paye_en_pv: calcul_txt += " (PV🩸)"
    
    embed.add_field(name=f"Technique : {skill_obj.nom}", value=f"*{skill_data['desc']}*{cout_msg}\n{' '.join(visuel)}\n`{calcul_txt}`{msg_effet}{msg_moine_ab}", inline=False)
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="appliquer", description="Appliquer un effet (X automatique basé sur la durée)")
@app_commands.describe(cible="[Optionnel] Cible via @", cible_fiche="[Optionnel] Cible via nom de fiche (prioritaire)", effet="Type d'effet", duree="Nombre de tours")
@app_commands.autocomplete(cible_fiche=cible_fiche_autocomplete)
@app_commands.choices(effet=[
    app_commands.Choice(name="🔥 Brûlure (X Dégâts / X Tours)", value="brulure"),
    app_commands.Choice(name="☠️ Poison (Malus)", value="poison"),
    app_commands.Choice(name="🩸 Hémorragie (X Punition)", value="hemorragie"),
    app_commands.Choice(name="❄️ Gel", value="gel"),
    app_commands.Choice(name="💫 Étourdissement", value="stun"),
    app_commands.Choice(name="🌳 Enracinement", value="root"),
    app_commands.Choice(name="🌑 Corruption", value="corruption"),
    app_commands.Choice(name="⚡ Hâte", value="hate"),
    app_commands.Choice(name="🛡️ Armure (Bloque X dégâts / -1 Charge)", value="armure"),
])
async def appliquer(interaction: discord.Interaction, effet: app_commands.Choice[str], duree: int, cible: discord.Member = None, cible_fiche: str = None):
    if cible_fiche:
        p_cible = parse_cible_arg(cible_fiche)
    elif cible:
        p_cible = Personnage.charger(cible.id)
    else:
        return await interaction.response.send_message("❌ Précisez une cible (@ ou nom de fiche).", ephemeral=True)
    if not p_cible: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    # On ne passe plus de 3ème argument pour laisser l'auto-calcul (puissance = duree)
    p_cible.ajouter_effet(effet.value, duree) 
    p_cible.sauvegarder()

    n_duree = p_cible.effets[effet.value]["duree"]
    n_valeur = p_cible.effets[effet.value]["valeur"]

    embed = discord.Embed(title="✨ Statut Mis à Jour", color=0x9b59b6)
    embed.description = f"**{effet.name}** sur **{p_cible.nom}**.\n⌛ Durée : **{n_duree}** | 💥 Puissance (X) : **{n_valeur}**"
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="tour", description="🔄 Début de tour : HUD + Gestion des Effets + Initiative")
@app_commands.describe(
    perso1="Personnage supplémentaire 1",
    perso2="Personnage supplémentaire 2",
    perso3="Personnage supplémentaire 3",
    perso4="Personnage supplémentaire 4",
    perso5="Personnage supplémentaire 5",
    perso6="Personnage supplémentaire 6",
    perso7="Personnage supplémentaire 7",
    perso8="Personnage supplémentaire 8",
    perso9="Personnage supplémentaire 9",
)
@app_commands.autocomplete(
    perso1=tour_noms_autocomplete, perso2=tour_noms_autocomplete, perso3=tour_noms_autocomplete,
    perso4=tour_noms_autocomplete, perso5=tour_noms_autocomplete, perso6=tour_noms_autocomplete,
    perso7=tour_noms_autocomplete, perso8=tour_noms_autocomplete, perso9=tour_noms_autocomplete,
)
async def tour(interaction: discord.Interaction,
               perso1: str = None, perso2: str = None, perso3: str = None,
               perso4: str = None, perso5: str = None, perso6: str = None,
               perso7: str = None, perso8: str = None, perso9: str = None):
    
    # 1. On defer car le chargement et la sauvegarde de 10 fiches peut prendre quelques secondes
    await interaction.response.defer()

    # --- 2. CHARGEMENT DE TOUS LES PERSONNAGES ---
    persos_a_traiter = []
    
    p_main = Personnage.charger(interaction.user.id)
    if not p_main: 
        return await interaction.followup.send("❌ Pas de fiche.", ephemeral=True)
    persos_a_traiter.append(p_main)

    perso_noms_args = [a for a in [perso1, perso2, perso3, perso4, perso5, perso6, perso7, perso8, perso9] if a]
    for arg in perso_noms_args:
        p_extra = None
        if ":" in arg:
            parts = arg.split(":", 1)
            try:
                p_extra = Personnage.charger_par_nom(int(parts[0]), parts[1])
            except (ValueError, IndexError):
                pass
        else:
            conn = get_db_connection()
            row = conn.execute("""
                SELECT j.user_id FROM sessions s
                JOIN joueurs j ON j.user_id = s.user_id AND j.nom = s.nom_perso_actif
                WHERE j.nom = ? LIMIT 1
            """, (arg,)).fetchone()
            conn.close()
            if row:
                p_extra = Personnage.charger(row['user_id'])
        
        if p_extra:
            persos_a_traiter.append(p_extra)

    entrees_init = []

    # --- 3. TRAITEMENT DE CHAQUE PERSONNAGE ---
    for p in persos_a_traiter:
        rapport_effets = []
        msg_cd_refresh = []
        cds_a_retirer = []
        
        # Indicateurs d'état pour le tour
        skip_turn = False 
        agi_effective = p.agi 
        malus_poison_val = 0
        pv_perdus_total = 0
        effets_a_supprimer = []

        # Reset passe_count
        if p.passe_count != 0:
            p.passe_count = 0
        
        # --- GESTION DES COOLDOWNS ---
        if p.cooldowns:
            for sort_ref in list(p.cooldowns.keys()):
                p.cooldowns[sort_ref] -= 1
                if p.cooldowns[sort_ref] <= 0:
                    cds_a_retirer.append(sort_ref)
                    nom_sort = SKILLS_DB.get(sort_ref, {'nom': sort_ref})['nom']
                    msg_cd_refresh.append(f"🔄 **{nom_sort}** est disponible !")
        
        for ref in cds_a_retirer:
            del p.cooldowns[ref]
            
        if msg_cd_refresh:
            rapport_effets.append("\n".join(msg_cd_refresh))

        # --- GESTION DES EFFETS ---
        CONFIG_EFFETS = {
            "brulure": "🔥", "poison": "☠️", "hemorragie": "🩸",
            "gel": "❄️", "stun": "💫", "root": "🌳",
            "hate": "⚡", "corruption": "🌑", "toxine": "🧪", "silence": "🤫", "furtif_assassin": "🌑"
        }

        if p.effets:
            if "passif_lotus_corps" in p.competences:
                if "poison" in p.effets:
                    del p.effets["poison"]
                    rapport_effets.append("🌸 **Corps-Temple** : Immunité au Poison !")
                if "brulure" in p.effets:
                    p.effets["brulure"]["valeur"] = max(1, p.effets["brulure"]["valeur"] // 2)
                    rapport_effets.append("🌸 **Corps-Temple** : Brûlure divisée par 2.")

            # On utilise list() pour éviter les erreurs si on modifie le dict pendant la boucle
            for code, data in list(p.effets.items()):
                ico = CONFIG_EFFETS.get(code, "❓")
                if code in ["brulure", "hemorragie"]: 
                    data["valeur"] = data["duree"]
                valeur = data.get("valeur", 0)
                
                if code == "brulure":
                    degats = valeur
                    if "passif_legion_endurance" in p.competences and p.posture_active and degats <= 3:
                        rapport_effets.append(f"{ico} **Brûlure** : 🛡️ Endurance d'Acier — ignorée (≤ 3 en Posture).")
                    elif "passif_nord_machoire" in p.competences and data.get("duree", 0) % 2 == 0:
                        rapport_effets.append(f"{ico} **Brûlure** : 🦷 Mâchoire de Fer — tour de pause.")
                    else:
                        pv_perdus_total += degats
                        rapport_effets.append(f"{ico} **Brûlure** : -{degats} PV")

                elif code == "poison":
                    malus_poison_val = (5 + p.niveau) // 5
                    if "passif_legion_endurance" in p.competences and p.posture_active and malus_poison_val <= 3:
                        rapport_effets.append(f"{ico} **Poison** : 🛡️ Endurance d'Acier — ignoré.")
                    elif "passif_nord_machoire" in p.competences and data.get("duree", 0) % 2 == 0:
                        rapport_effets.append(f"{ico} **Poison** : 🦷 Mâchoire de Fer — tour de pause.")
                    else:
                        rapport_effets.append(f"{ico} **Poison** : Malus -{malus_poison_val} aux jets.")

                elif code == "hemorragie":
                    degats_debut = max(1, valeur // 2) 
                    pv_perdus_total += degats_debut
                    rapport_effets.append(f"🩸 **Hémorragie** : -{degats_debut} PV. (Attention: -{valeur} PV à chaque attaque !)")

                elif code == "corruption":
                    drain = 2 
                    perte_msg = ""
                    if p.classe == "mage" and p.mana > 0:
                        perte = min(p.mana, drain); p.mana -= perte; perte_msg = f"-{perte} Mana"
                    elif p.classe == "guerrier" and p.tension > 0:
                        perte = min(p.tension, drain); p.tension -= perte; perte_msg = f"-{perte} Tension"
                    elif p.classe == "pretre" and p.ferveur > 0:
                        perte = min(p.ferveur, drain); p.ferveur -= perte; perte_msg = f"-{perte} Ferveur"
                    
                    msg_corr = f"{ico} **Corruption** : {perte_msg}" if perte_msg else f"{ico} **Corruption** : Ressources drainées."
                    rapport_effets.append(msg_corr)

                elif code == "toxine":
                    # Toxine : réduit les Pièces de l'ennemi de -1 ce tour (géré à l'attaque via effets)
                    stacks = data.get("valeur", 1)
                    rapport_effets.append(f"🧪 **Toxine** ({stacks} stack(s)) : -{stacks} Pièce(s) sur votre prochain sort !")

                elif code == "silence":
                    rapport_effets.append("🤫 **Silence** : Magie impossible ce tour !")

                elif code == "furtif_assassin":
                    rapport_effets.append("🌑 **Furtif** : +1 Pièce sur votre prochain sort de la Confrérie !")

                elif code == "root":
                     agi_effective = 0 
                     rapport_effets.append(f"{ico} **Enraciné** : Agilité réduite à 0.")

                elif code in ["stun", "gel"]:
                    if code == "stun" and data.get("nouveau"):
                        # Premier tour : annonce seulement, NE PAS décrémenter
                        data.pop("nouveau")
                        rapport_effets.append(f"{ico} **Étourdi** : Bloqué au **prochain tour** !")
                        continue  # skip la décrémentation de ce tour
                    else:
                        skip_turn = True
                        nom_etat = "Gelé" if code == "gel" else "Étourdi"
                        detail = "(Défense possible)" if code == "gel" else "(Aucune défense)"
                        rapport_effets.append(f"{ico} **{nom_etat}** : Tour passé {detail} !")
                
                elif code == "hate":
                    rapport_effets.append(f"{ico} **Hâte** : +2 Pièces.")

                elif code == "malus_base":
                    malus_b_val = data.get("valeur", 0)
                    rapport_effets.append(f"🔮 **Touche du Destin** : -{malus_b_val} Base !")
                elif code == "malus_bonus_pieces":
                    malus_bp_val = data.get("valeur", 0)
                    rapport_effets.append(f"🔮 **Présage exact** : -{malus_bp_val} Bonus Pièces !")
                elif code == "no_soin":
                    rapport_effets.append("🌸 **Paume du Vide** : Impossible d'être soigné ce tour.")
                elif code == "no_bonus_action":
                    rapport_effets.append("🎯 **Paralysie Neurale** : Action Bonus bloquée ce tour.")
                elif code == "force_pile":
                    rapport_effets.append("🔮 **Inversion** : Votre prochain jet de dés = Pile !")
                elif code == "no_buff":
                    rapport_effets.append("📜 **Condamné(e)** : Aucun soin ni buff possible.")
                elif code == "titanenblut":
                    p.pv_actuel = min(p.pv_max, p.pv_actuel + 10)
                    rapport_effets.append(f"🩸 **Sang de Titan** : Régénération +10 PV.")

                # Décrémentation de la durée
                p.effets[code]["duree"] -= 1
                if p.effets[code]["duree"] <= 0:
                    effets_a_supprimer.append(code)

            # Nettoyage
            for code in effets_a_supprimer:
                if code in p.effets:
                    del p.effets[code]
                    rapport_effets.append(f"✨ L'effet **{code.capitalize()}** s'est dissipé.")

            # Application des dégâts totaux du tour
            if pv_perdus_total > 0:
                p.pv_actuel -= pv_perdus_total
                if p.pv_actuel <= 0:
                    if "unsterblich" in p.effets:
                        p.pv_actuel = 1
                        del p.effets["unsterblich"]
                        rapport_effets.append("La mort vous refuse. Vous survivez à 1 PV !")
                    else:
                        p.pv_actuel = 0
                if p.classe == "guerrier": p.tension += 1 

        # --- GESTION DES PASSIFS DE CLASSE ---
        if "ordre_hospitalier" in p.sous_classes_unlocked and "aura_active" in p.effets and p.pv_actuel > 0:
            cout_aura = 3
            if p.ferveur >= cout_aura:
                p.ferveur -= cout_aura
                rapport_effets.append(f"✨ **Aura de Sacrifice** active (-{cout_aura} Ferveur entretien).")
                if "passif_hosp_resilience" in p.competences and p.pv_actuel <= 1:
                    del p.effets["aura_active"]
                    rapport_effets.append("✨ **Foi Inébranlable** : Aura coupée (1 PV).")
            else:
                del p.effets["aura_active"]
                rapport_effets.append("✨ **Aura de Sacrifice** : Ferveur insuffisante — Aura désactivée !")

        if p.classe == "pretre" and p.pv_actuel > 0:
            gain_passif = 5
            p.ferveur += gain_passif
            rapport_effets.append(f"🙏 **Prière Constante** : +{gain_passif} Ferveur.")

        if "passif_sang_hote" in p.competences and p.classe == "mage" and p.festin == 0:
            p.festin = 10
            rapport_effets.append("🩸 **L'Hôte du Banquet** : Jauge de Festin initialisée à 10.")

        if "passif_lotus_souffle" in p.competences and p.concentre and p.pv_actuel > 0:
            p.ferveur += 3
            rapport_effets.append("🌸 **Souffle du Lotus** : +3 Ferveur (Concentré).")

        if "posture_forcee" in p.effets:
            p.effets["posture_forcee"]["duree"] -= 1
            if p.effets["posture_forcee"]["duree"] <= 0:
                del p.effets["posture_forcee"]
                p.posture_active = 0
                rapport_effets.append("🛡️ **Posture Forcée** expirée.")

        # --- HUD SPÉCIFIQUE & ÉTATS ACTIFS (HUD V4) ---
        hud_v4 = ""
        if "magie_sang" in p.sous_classes_unlocked and p.classe == "mage":
            stade = get_festin_stade(p)
            festin_max = get_festin_max(p)
            stade_label = f"Stade {stade}" if stade > 0 else "Stade 0"
            hud_v4 += f"\n🩸 **Festin [{stade_label}]** : {p.festin}/{festin_max}"
            
        if "magie_elementaire" in p.sous_classes_unlocked and p.classe == "mage":
            icones_elem = {"feu":"🔥","glace":"❄️","foudre":"⚡","air":"💨"}
            ch_txt = " ".join([icones_elem.get(e, e) for e in p.charges_elementaires]) if p.charges_elementaires else "*Aucune*"
            hud_v4 += f"\n✨ **Charges Élémentaires** : {ch_txt}"

        if "legion_fer" in p.sous_classes_unlocked:
            hud_v4 += f"\n🛡️ **Posture ACTIVE**" if p.posture_active else "\n⚔️ Posture inactive"
        if "clan_nord" in p.sous_classes_unlocked and p.serment_actif:
            hud_v4 += f"\n🩸 **Serment actif** (+{p.serment_bonus})"
        if "moine_lotus" in p.sous_classes_unlocked:
            hud_v4 += f"\n🌸 **Concentré**" if p.concentre else "\n🔥 **Perturbé** (+4 Dégâts)"
        
        lestage_perso = get_lestage(p)
        if lestage_perso > 0: hud_v4 += f"\n⚖️ **Lestages** : {lestage_perso}"
        if p.designation_stacks > 0: hud_v4 += f"\n🎯 **Désignation** ({p.designation_stacks} stack(s))"
        if p.sentence_targets: hud_v4 += f"\n📜 **Sentence** prononcée"
        if p.passe_active: hud_v4 += f"\n⚔️ **Passe active !**"

        # --- INITIATIVE ---
        d1 = random.randint(1, 20)
        if "hate" in p.effets or p.race == "Féral":
            d2 = random.randint(1, 20)
            d_retenu = max(d1, d2)
            visuel_de = f"[{d1}, **{d2}**]" if d2 > d1 else f"[**{d1}**, {d2}]"
            d1 = d_retenu
        else:
            visuel_de = f"{d1}"

        score_init = d1 + agi_effective - malus_poison_val
        detail_init = f"Dé {visuel_de} + Agi {agi_effective}"

        if "magie_elementaire" in p.sous_classes_unlocked and p.classe == "mage":
            bonus_res_init = get_bonus_resonance(p)
            if "foudre" in bonus_res_init:
                score_init += bonus_res_init["foudre"]
                detail_init += f" + {bonus_res_init['foudre']} (⚡Rés)"
        
        if malus_poison_val > 0: detail_init += f" - {malus_poison_val} (Psn)"
        if p.race == "Elfe" and p.classe == "guerrier":
            bonus = (p.niveau // 3) * 2
            score_init += bonus; detail_init += f" + {bonus} (Elfe)"

        # SAUVEGARDE DU PERSONNAGE
        p.sauvegarder()

        entrees_init.append((p, score_init, detail_init, skip_turn, rapport_effets, hud_v4))

    # --- 4. CONSTRUCTION DU TABLEAU D'INITIATIVE ---
    entrees_init.sort(key=lambda x: x[1])

    def build_bar(actuel, max_val, longueur=8, c_full="█", c_empty="░"):
        if max_val <= 0: return c_empty * longueur
        pct = max(0.0, min(1.0, actuel / max_val))
        fill = round(pct * longueur)
        return c_full * fill + c_empty * (longueur - fill)

    embeds_joueurs = []
    for rang, (px, sc, det, sk, rapports, h_v4) in enumerate(entrees_init, 1):
        stun_ico = "💫 " if sk else ""
        couleur_px = 0xe74c3c if sk else 0x2ecc71

        bar_pv = build_bar(px.pv_actuel, px.pv_max, 8, "🟩", "⬛")

        if px.classe == "mage":
            bar_res = build_bar(px.mana, px.mana_max, 8, "🟦", "⬛"); label_res = "Mana"
        elif px.classe == "guerrier":
            bar_res = build_bar(min(px.tension, 10), 10, 8, "🔴", "⬛"); label_res = "Tension"
        elif px.classe == "pretre":
            bar_res = build_bar(px.ferveur, 100, 8, "🟨", "⬛"); label_res = "Ferveur"
        else:
            bar_res = "—"; label_res = "Res"

        icones_effets = {
            "brulure": "🔥", "poison": "☠️", "hemorragie": "🩸",
            "gel": "❄️", "stun": "💫", "root": "🌳", "hate": "⚡", "corruption": "🌑"
        }
        effets_actifs = " ".join(icones_effets[e] for e in px.effets if e in icones_effets)

        contenu = f"`PV  ` {bar_pv}\n`{label_res[:3]:<3} ` {bar_res}"
        
        if h_v4:
            contenu += f"\n{h_v4}"
        if effets_actifs:
            contenu += f"\n\n**Effets :** {effets_actifs}"
        if rapports:
            contenu += f"\n\n📝 **Journal :**\n" + "\n".join(rapports)
        if sk:
            contenu += "\n\n**🚫 Tour passé**"

        em = discord.Embed(
            title=f"{rang}. {stun_ico}{px.nom}  —  Init **{sc}**",
            description=contenu,
            color=couleur_px
        )
        if px.image_url:
            em.set_thumbnail(url=px.image_url)
        em.set_footer(text=f"{det}")
        embeds_joueurs.append(em)

    header = discord.Embed(
        title="📋 Ordre du Tour (croissant)",
        color=0x2ecc71
    )
    header.set_footer(text="À vous ! (/attaque, /clash...)")

    all_embeds = [header] + embeds_joueurs

    await log_combat(interaction, header)
    
    # On utilise followup.send car on a utilisé defer() au début
    await interaction.followup.send(embeds=all_embeds)


# 1. SOIN
@bot.tree.command(name="soigner", description="🙏 Soigner une cible")
@app_commands.describe(sort="Le sort de soin", cible="Le joueur à soigner (tapez pour chercher)", personnage="[Optionnel] Votre personnage (si vous jouez plusieurs fiches)")
@app_commands.autocomplete(sort=sort_soin_autocomplete, personnage=joueur_perso_autocomplete, cible=cible_fiche_autocomplete)
async def soigner(interaction: discord.Interaction, sort: str, cible: str, personnage: str = None):
    p: Personnage = Personnage.charger_par_nom(interaction.user.id, personnage) if personnage else Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    dispo, msg_err = verifier_cooldown(p, sort)
    if not dispo:
        return await interaction.response.send_message(msg_err, ephemeral=True)
    # Vérif État Soigneur
    if is_stun_actif(p) or "gel" in p.effets:
        return await interaction.response.send_message("❌ Vous êtes hors d'état d'agir (Stun/Gel).", ephemeral=True)
    p_cible = parse_cible_arg(cible) if cible else p
    if not p_cible: return await interaction.response.send_message("❌ Cible invalide.", ephemeral=True)
    sort = resolve_sort_ref(sort)
    if sort not in SKILLS_DB: return await interaction.response.send_message("❌ Sort introuvable.", ephemeral=True)
    
    skill_data = SKILLS_DB[sort]
    if skill_data.get('type') != 'soin':
        return await interaction.response.send_message(f"🚫 Pas un sort de soin.", ephemeral=True)

    # --- BLOCAGES : no_soin (Paume du Vide) et no_buff (Purification Inquisiteur) ---
    if "no_soin" in p_cible.effets:
        return await interaction.response.send_message(
            f"🌸 **Soin impossible** : {p_cible.nom} est sous l'effet de la **Paume du Vide** et ne peut pas être soigné ce tour.",
            ephemeral=True
        )
    if "no_buff" in p_cible.effets:
        return await interaction.response.send_message(
            f"📜 **Soin impossible** : {p_cible.nom} est **Condamné(e)** et ne peut plus recevoir de soins ou buffs pour le reste du combat.",
            ephemeral=True
        )

    # Coûts (Code existant inchangé pour la brièveté, mais à garder)
    cout = skill_data.get("cout", 0); cout_type = skill_data.get("cout_type", "mana")
    cout_paye_en_pv = False
    if cout > 0:
        valeur_actuelle = getattr(p, cout_type, 0)
        
        if "mode_sang" in p.effets and p.race == "Vampire" and p.classe == "mage" and p.pv_actuel > cout:
            p.pv_actuel -= cout
            cout_paye_en_pv = True
            
        elif valeur_actuelle >= cout:
            setattr(p, cout_type, valeur_actuelle - cout)
            
        elif p.race == "Vampire" and p.classe == "mage" and p.pv_actuel > cout:
            p.pv_actuel -= cout
            cout_paye_en_pv = True
            
        else:
            return await interaction.response.send_message(f"❌ Pas assez de **{cout_type}**.", ephemeral=True)
        
    
    # --- DEBUT AJOUT VERSETS ---
    cout_versets = skill_data.get("versets", 0)
    if cout_versets > 0:
        if p.versets < cout_versets:
            return await interaction.response.send_message(f"❌ **Foi insuffisante !**\nCe miracle nécessite **{cout_versets} Versets** (Vous en avez {p.versets}).", ephemeral=True)
        p.versets -= cout_versets

    # Jet de soin
    stat_nom = skill_data["stat_type"].upper()
    stat_valeur = getattr(p, skill_data["stat_type"], 0)
    skill_obj = Skill(skill_data["nom"], skill_data["base"], skill_data["bonus"], skill_data["coins"], stat_bonus=stat_valeur, stat_nom=stat_nom)
    total_soin, visuel, heads = skill_obj.roll(bonus_niveau=p.get_bonus_niveau())
    json_data = skill_data.get('data_json', '{}')
    total, msg_effets_spe = traiter_effets_json(json_data, p, p_cible, total_soin, heads=heads)
    # --- MOINE DU LOTUS : soin_base (fixe) + concentre_bonus + self_dmg ---
    data_j = json.loads(skill_data.get("data_json", "{}"))
    msg_lotus_soin = ""
    if "moine_lotus" in p.sous_classes_unlocked and "soin_base" in data_j:
        soin_fixe = data_j["soin_base"]
        total_soin = soin_fixe  # Override : soin fixe, pas dé
        visuel_base = [f"💚{soin_fixe}(fixe)"]
        # Bonus Concentré
        if p.concentre and "concentre_bonus" in data_j:
            bonus_c = data_j["concentre_bonus"]
            total_soin += bonus_c
            visuel_base.append(f"🌸+{bonus_c}(Concentré)")
        # Malus Perturbé : moitié (si pas Concentré)
        elif not p.concentre:
            total_soin = total_soin // 2
            visuel_base.append("🔥÷2(Perturbé)")
        visuel = visuel_base
        # Auto-dégât soigneur (self_dmg)
        dmg_self = data_j.get("self_dmg", 0)
        if p.concentre and "self_dmg_concentre" in data_j:
            dmg_self = data_j["self_dmg_concentre"]
        if dmg_self > 0 and p.pv_actuel > dmg_self:
            p.pv_actuel -= dmg_self
            msg_lotus_soin = f"\n🌸 **Transfert** : -{dmg_self} PV au soigneur."
        elif dmg_self > 0:
            msg_lotus_soin = "\n⚠️ PV insuffisants pour le Transfert."


    # Bonus Céleste (Soigneur)
    if p.race == "Céleste":
        total_soin += 3
        visuel.append("✨(+3 Don)")
        
    # NOUVEAU : Bonus Céleste (Cible)
    if p_cible.race == "Céleste" and p.user_id != p_cible.user_id:
        total_soin += 3
        visuel.append("👼(+3 Reçu)")

    # --- EFFET CORRUPTION (PESTE) ---
    msg_peste = ""
    # Si la cible est corrompue et que le soigneur ne l'est pas encore
    if "corruption" in p_cible.effets and "corruption" not in p.effets:
        p.ajouter_effet("corruption", 3, 1) # Durée 3, Puissance 1
        msg_peste = "\n☣️ **CONTAGION :** La corruption infecte le soigneur !"
        
    anciens_pv = p_cible.pv_actuel
    soin_reel = min(p_cible.pv_max - p_cible.pv_actuel, total_soin)
    p_cible.pv_actuel = min(p_cible.pv_max, p_cible.pv_actuel + total_soin)
    cs_add_soins(p.user_id, p.nom, soin_reel)
    cs_get(p_cible.user_id, p_cible.nom)  # init cible dans les stats
    appliquer_cooldown(p, sort)
    p.sauvegarder()
    p_cible.sauvegarder()

    embed = discord.Embed(title="✨ SOIN DIVIN", color=0x2ecc71)
    embed.add_field(name=f"🙏 {p.nom} ➔ {p_cible.nom}", value=f"**{skill_obj.nom}**\n*{skill_data['desc']}*", inline=False)
    embed.add_field(name="Résultat", value=f"{' '.join(visuel)}\n# 💚 +{total_soin} PV{msg_peste}{msg_lotus_soin}", inline=False)
    embed.add_field(name="État", value=f"{anciens_pv} ➔ **{p_cible.pv_actuel}** / {p_cible.pv_max} PV", inline=False)
    await log_combat(interaction, embed)
    await interaction.response.send_message(content=f"<@{p_cible.user_id}>", embed=embed)

# 2. CLASH
@bot.tree.command(name="clash", description="un adversaire vous attaque et vous l'attaquez en retour")
@app_commands.describe(
    sort="Votre technique", cible="L'adversaire (tapez pour chercher)",
    description="Action RP", personnage="[Optionnel] Votre personnage (si vous jouez plusieurs fiches)",
    cible_sec1="Cible de zone 1 (optionnel)", cible_sec2="Cible de zone 2 (optionnel)", cible_sec3="Cible de zone 3 (optionnel)",
    bonus_base="[Optionnel] Bonus fixe sur la Base (buff, circonstance MJ…)",
    bonus_pieces="[Optionnel] Pièces bonus supplémentaires"
)
@app_commands.autocomplete(sort=sort_offensif_autocomplete, personnage=joueur_perso_autocomplete, cible=cible_fiche_autocomplete,
    cible_sec1=cible_fiche_autocomplete, cible_sec2=cible_fiche_autocomplete, cible_sec3=cible_fiche_autocomplete)
async def clash(interaction: discord.Interaction, sort: str, cible: str, description: str, personnage: str = None,
                cible_sec1: str = None, cible_sec2: str = None, cible_sec3: str = None,
                bonus_base: int = 0, bonus_pieces: int = 0):
    await interaction.response.defer()
    cibles_secondaires = " ".join(s for s in [cible_sec1, cible_sec2, cible_sec3] if s) or None
    p_attaquant = Personnage.charger_par_nom(interaction.user.id, personnage) if personnage else Personnage.charger(interaction.user.id)
    if not p_attaquant: return await interaction.followup.send("❌ Pas de fiche.", ephemeral=True)
    if p_attaquant.pv_actuel <= 0: return await interaction.followup.send("💀 K.O.", ephemeral=True)

    # --- VÉRIFICATION ÉTATS BLOQUANTS ---
    if is_stun_actif(p_attaquant): return await interaction.followup.send("💫 **Étourdi !** Impossible de lancer un clash.", ephemeral=True)
    if "gel" in p_attaquant.effets: return await interaction.followup.send("❄️ **Gelé !** Impossible de bouger.", ephemeral=True)

    # Résolution de la cible depuis "user_id:nom"
    p_cible_clash = parse_cible_arg(cible)
    if not p_cible_clash: return await interaction.followup.send("❌ Cible introuvable.", ephemeral=True)
    cible_user_id = p_cible_clash.user_id

    # Blocage auto-ciblage — sauf pour un GM qui joue deux fiches distinctes
    if cible_user_id == interaction.user.id:
        if not (is_gm(interaction.user.id) and personnage):
            return await interaction.followup.send("❌ Cible invalide.", ephemeral=True)
    if cible_user_id in PENDING_CLASHES: return await interaction.followup.send(f"❌ Déjà défié.", ephemeral=True)

    sort = resolve_sort_ref(sort)
    if sort not in SKILLS_DB: return await interaction.followup.send("❌ Sort introuvable.", ephemeral=True)
    skill_data = SKILLS_DB[sort]

    dispo, msg_err = verifier_cooldown(p_attaquant, sort)
    if not dispo:
        return await interaction.followup.send(msg_err, ephemeral=True)

    if skill_data.get('type') == 'soin': return await interaction.followup.send(f"🚫 C'est un soin.", ephemeral=True)

    # --- BLOCAGE ACTIONS BONUS ---
    if "(BONUS)" in skill_data['nom'].upper() or "(BONUS)" in sort.upper():
        return await interaction.followup.send("❌ Impossible de **Clash** avec une Action Bonus.\nUtilisez `/action_bonus` ou choisissez une vraie attaque.", ephemeral=True)
    
    # --- GESTION COÛT & RACES ---
    cout = skill_data.get("cout", 0)
    cout_type = skill_data.get("cout_type", "mana")
    reduc_humain = p_attaquant.niveau // 3
    if p_attaquant.race == "Humain" and p_attaquant.classe == "mage" and reduc_humain > 0:
        cout = max(int(skill_data.get("cout", 0) / 2), cout - reduc_humain)

    cout_msg = ""
    if cout > 0:
        val = getattr(p_attaquant, cout_type, 0)
        
        # 1. Mode Sang
        if "mode_sang" in p_attaquant.effets and p_attaquant.race == "Vampire" and p_attaquant.classe == "mage" and p_attaquant.pv_actuel > cout:
            p_attaquant.pv_actuel -= cout
            cout_msg = " (PV🩸)"
        
        # 2. Ressource Standard
        elif val >= cout:
            setattr(p_attaquant, cout_type, val - cout)
            
        # 3. Secours Vampire
        elif p_attaquant.race == "Vampire" and p_attaquant.classe == "mage" and p_attaquant.pv_actuel > cout:
            p_attaquant.pv_actuel -= cout
            cout_msg = " (PV🩸)"
            
        # 4. Échec
        else:
            return await interaction.followup.send(f"❌ Pas assez de {cout_type}.", ephemeral=True)
        
    # --- DEBUT AJOUT VERSETS ---
    cout_versets = skill_data.get("versets", 0)
    if cout_versets > 0:
        if p_attaquant.versets < cout_versets:
            return await interaction.followup.send(f"❌ **Foi insuffisante !**\nCe miracle nécessite **{cout_versets} Versets** (Vous en avez {p_attaquant.versets}).", ephemeral=True)
        p_attaquant.versets -= cout_versets
    
# --- Calcul de l'Hémorragie (Dégâts = X) ---
    msg_hemo = ""
    if "hemorragie" in p_attaquant.effets:
        val_hemo = p_attaquant.effets["hemorragie"].get("valeur", 0)
        p_attaquant.pv_actuel -= val_hemo
        msg_hemo = f"\n🩸 **Hémorragie** : L'effort ouvre vos plaies (-{val_hemo} PV)."
    
    appliquer_cooldown(p_attaquant, sort)
    maj_etat_moine(p_attaquant, skill_data, [])
    p_attaquant.sauvegarder()

    # Préparation objet Skill
    stat_valeur = 0; stat_nom = "STAT"
    # Si Enraciné, Agilité = 0 pour le calcul
    if "root" in p_attaquant.effets and skill_data["stat_type"] == "agi":
        stat_valeur = 0
        stat_nom = "AGI(0)"
    else:
        if p_attaquant.classe == "guerrier": stat_valeur = p_attaquant.phy; stat_nom = "PHY"
        elif p_attaquant.classe == "mage": stat_valeur = p_attaquant.esp; stat_nom = "ESP"
        elif p_attaquant.classe == "pretre": stat_valeur = p_attaquant.foi; stat_nom = "FOI"
        else: stat_nom = skill_data["stat_type"].upper(); stat_valeur = getattr(p_attaquant, skill_data["stat_type"], 0)

    skill_obj = Skill(skill_data["nom"], skill_data["base"] + getattr(p_attaquant, 'bonus_base_item', 0), skill_data["bonus"], skill_data["coins"] + getattr(p_attaquant, 'bonus_pieces_item', 0), stat_bonus=stat_valeur, stat_nom=stat_nom)
    # --- malus_base / malus_bonus_pieces (Briseur d'Os, Touche du Destin) ---
    _malus_b_clash = p_attaquant.effets.pop("malus_base", None)
    if _malus_b_clash:
        skill_obj.base = max(0, skill_obj.base - _malus_b_clash["valeur"])
    _malus_bp_clash = p_attaquant.effets.pop("malus_bonus_pieces", None)
    if _malus_bp_clash:
        skill_obj.bonus = max(0, skill_obj.bonus - _malus_bp_clash["valeur"])

    # --- BONUS MANUELS (paramètres optionnels) ---
    msg_bonus_manuel_clash = ""
    if bonus_base != 0:
        skill_obj.base = max(0, skill_obj.base + bonus_base)
        signe = "+" if bonus_base > 0 else ""
        msg_bonus_manuel_clash += f"\n✨ **Bonus Base** : {signe}{bonus_base}"
    if bonus_pieces != 0:
        skill_obj.coins = max(1, skill_obj.coins + bonus_pieces)
        signe = "+" if bonus_pieces > 0 else ""
        msg_bonus_manuel_clash += f"\n✨ **Bonus Pièces** : {signe}{bonus_pieces}"

    if "hate" in p_attaquant.effets:
        skill_obj.coins += 2
        cout_msg += " ⚡(Hâte)"
        del p_attaquant.effets["hate"]

    if "titanenblut" in p_attaquant.effets:
        skill_obj.coins += 1
        cout_msg += "(Titaneblut)"

    if "toxine" in p_attaquant.effets:
        stacks_toxine = p_attaquant.effets["toxine"].get("valeur", 1)
        skill_obj.coins = max(1, skill_obj.coins - stacks_toxine)
        cout_msg += f" 🧪(-{stacks_toxine}🪙 Toxine)"

    if "furtif_assassin" in p_attaquant.effets:
        skill_obj.coins += 1
        del p_attaquant.effets["furtif_assassin"]
        cout_msg += " 🌑(+1🪙 Furtif)"

    # --- LOGE DE L'OMBRE : bonus_si_deja_designee (Marquage Avancé P2) ---
    _flag_ma_clash = p_attaquant.effets.pop("_bonus_marquage_avance", None)
    if _flag_ma_clash:
        skill_obj.coins += _flag_ma_clash.get("valeur", 1)

    # --- DÉSIGNATION (Loge de l'Ombre) — appliquée AVANT le clash ---
    if "loge_ombre" in p_attaquant.sous_classes_unlocked and p_cible_clash and p_attaquant.designation_target_id == p_cible_clash.user_id:
        pieces_bonus_d_clash, _ = appliquer_designation(p_attaquant, p_cible_clash, skill_data)
        if pieces_bonus_d_clash > 0:
            skill_obj.coins += pieces_bonus_d_clash
            msg_bonus_manuel_clash += f"\n🎯 **Désignation** : +{pieces_bonus_d_clash} Pièces !"

    PENDING_CLASHES[cible_user_id] = {
        'attaquant_id': interaction.user.id,
        'skill_a': skill_obj,
        'desc_a': description,
        'p_attaquant': p_attaquant,
        'cibles_sec_a': cibles_secondaires,
        'ref_a': sort,
        'sort_data_a': skill_data
    }

    embed = discord.Embed(title="⚔️ CLASH INITIÉ !", description=f"**{p_attaquant.nom}** provoque **{p_cible_clash.nom}** !", color=0xE67E22)
    embed.add_field(name="Technique", value=f"⚡ **{skill_obj.nom}**\n*{skill_data['desc']}*{cout_msg}{msg_hemo}{msg_bonus_manuel_clash}", inline=False)
    embed.add_field(name="Action", value=f"*« {description} »*", inline=False)
    embed.add_field(name="En attente...", value=f"👉 **{p_cible_clash.nom}** (<@{cible_user_id}>), répondez avec `/riposte` !", inline=False)

    await log_combat(interaction, embed)
    await interaction.followup.send(content=f"<@{cible_user_id}>", embed=embed)

# 3. RIPOSTE (Modifié avec Races & Calculs Dégâts)
@bot.tree.command(name="riposte", description="Répondre à la commande /clash d'un adversaire")
@app_commands.describe(
    sort="Votre technique", description="Action RP", personnage="[Optionnel] Votre personnage (si vous jouez plusieurs fiches)",
    cible_sec1="Cible de zone 1 (optionnel)", cible_sec2="Cible de zone 2 (optionnel)", cible_sec3="Cible de zone 3 (optionnel)",
    bonus_base="[Optionnel] Bonus fixe sur la Base (buff, circonstance MJ…)",
    bonus_pieces="[Optionnel] Pièces bonus supplémentaires"
)
@app_commands.autocomplete(sort=sort_offensif_autocomplete, personnage=joueur_perso_autocomplete,
    cible_sec1=cible_fiche_autocomplete, cible_sec2=cible_fiche_autocomplete, cible_sec3=cible_fiche_autocomplete)
async def riposte(interaction: discord.Interaction, sort: str, description: str, personnage: str = None,
                  cible_sec1: str = None, cible_sec2: str = None, cible_sec3: str = None,
                  bonus_base: int = 0, bonus_pieces: int = 0):
    cibles_secondaires = " ".join(s for s in [cible_sec1, cible_sec2, cible_sec3] if s) or None
    await interaction.response.defer()
    user_id = interaction.user.id

    # Charger la fiche défenseur selon le paramètre personnage
    p_defenseur: Personnage = Personnage.charger_par_nom(user_id, personnage) if personnage else Personnage.charger(user_id)
    if not p_defenseur:
        return await interaction.followup.send("❌ Fiche introuvable.", ephemeral=True)

    # Chercher le clash en attente : d'abord par user_id direct, puis par user_id:nom_fiche
    clash_data = None
    if user_id in PENDING_CLASHES:
        clash_data = PENDING_CLASHES.pop(user_id)
    else:
        return await interaction.followup.send("❌ Personne ne vous a défié.", ephemeral=True)

    p_attaquant: Personnage = clash_data['p_attaquant']
    skill_a_org: Skill = clash_data['skill_a']

    # --- VÉRIFICATIONS DÉFENSEUR ---
    if p_defenseur.pv_actuel <= 0: return await interaction.followup.send("💀 K.O.", ephemeral=True)
    if is_stun_actif(p_defenseur): return await interaction.followup.send("💫 **Étourdi !** Impossible de riposter.", ephemeral=True)
    
    sort = resolve_sort_ref(sort)
    if sort not in SKILLS_DB: 
        PENDING_CLASHES[user_id] = clash_data 
        return await interaction.followup.send("❌ Sort introuvable.", ephemeral=True)
    skill_data_b = SKILLS_DB[sort]
    if skill_data_b.get('type') == 'soin': return await interaction.followup.send(f"🚫 Impossible avec un soin.", ephemeral=True)

    # --- BLOCAGE ACTIONS BONUS ---
    if "(BONUS)" in skill_data_b['nom'].upper() or "(BONUS)" in sort.upper():
        return await interaction.followup.send("❌ Impossible de **Riposter** avec une Action Bonus.\nUtilisez une compétence offensive ou défensive (MIX).", ephemeral=True)

    # --- VÉRIFICATION COOLDOWN DÉFENSEUR ---
    dispo_rip, msg_err_rip = verifier_cooldown(p_defenseur, sort)
    if not dispo_rip:
        PENDING_CLASHES[user_id] = clash_data  # On remet le clash en attente
        return await interaction.followup.send(msg_err_rip, ephemeral=True)

    # --- COÛT DÉFENSEUR ---
    cout = skill_data_b.get("cout", 0); cout_type = skill_data_b.get("cout_type", "mana")
    reduc_humain = p_defenseur.niveau // 3
    if p_defenseur.race == "Humain" and p_defenseur.classe == "mage" and reduc_humain > 0: 
        cout = max(int(skill_data_b.get("cout", 0) / 2), cout - reduc_humain)
    
    if cout > 0:
        val = getattr(p_defenseur, cout_type, 0)
        
        # 1. Mode Sang
        if "mode_sang" in p_defenseur.effets and p_defenseur.race == "Vampire" and p_defenseur.classe == "mage" and p_defenseur.pv_actuel > cout:
            p_defenseur.pv_actuel -= cout
            
        # 2. Ressource Standard
        elif val >= cout:
            setattr(p_defenseur, cout_type, val - cout)
            
        # 3. Secours Vampire
        elif p_defenseur.race == "Vampire" and p_defenseur.classe == "mage" and p_defenseur.pv_actuel > cout:
            p_defenseur.pv_actuel -= cout
            
        # 4. Échec
        else:
            PENDING_CLASHES[user_id] = clash_data 
            return await interaction.followup.send(f"❌ Pas assez de {cout_type}.", ephemeral=True)
        

    cout_versets = skill_data_b.get("versets", 0)
    if cout_versets > 0:
        if p_defenseur.versets < cout_versets:
            PENDING_CLASHES[user_id] = clash_data # On remet le clash en attente si ça rate
            return await interaction.followup.send(f"❌ **Foi insuffisante !**\nCe miracle nécessite **{cout_versets} Versets** (Vous en avez {p_defenseur.versets}).", ephemeral=True)
        p_defenseur.versets -= cout_versets

    # --- Calcul de l'Hémorragie (Dégâts = X) ---
    msg_hemo = ""
    if "hemorragie" in p_defenseur.effets:
        val_hemo = p_defenseur.effets["hemorragie"].get("valeur", 0)
        p_defenseur.pv_actuel -= val_hemo
        # On sauvegarde les PV immédiatement pour éviter les bugs si le bot crash
        p_defenseur.sauvegarder() 
        msg_hemo = f"\n🩸 **Hémorragie** : La riposte aggrave vos blessures (-{val_hemo} PV)."

    # --- PRÉPARATION SKILL B ---
    stat_b = 0; nom_stat_b = "STAT"
    # Gestion Root
    if "root" in p_defenseur.effets and skill_data_b["stat_type"] == "agi":
        stat_b = 0; nom_stat_b = "AGI(0)"
    else:
        if p_defenseur.classe == "guerrier": stat_b = p_defenseur.phy; nom_stat_b = "PHY"
        elif p_defenseur.classe == "mage": stat_b = p_defenseur.esp; nom_stat_b = "ESP"
        elif p_defenseur.classe == "pretre": stat_b = p_defenseur.foi; nom_stat_b = "FOI"
        else: nom_stat_b = skill_data_b["stat_type"].upper(); stat_b = getattr(p_defenseur, skill_data_b["stat_type"], 0)

    skill_b_org = Skill(skill_data_b["nom"], skill_data_b["base"] + getattr(p_defenseur, 'bonus_base_item', 0), skill_data_b["bonus"], skill_data_b["coins"] + getattr(p_defenseur, 'bonus_pieces_item', 0), stat_bonus=stat_b, stat_nom=nom_stat_b)

    # --- ORACLE : malus_base (Touche du Destin) — réduit la Base de ce sort ---
    _malus_b_rip = p_defenseur.effets.pop("malus_base", None)
    if _malus_b_rip:
        skill_b_org.base = max(0, skill_b_org.base - _malus_b_rip["valeur"])
    _malus_bp_rip = p_defenseur.effets.pop("malus_bonus_pieces", None)
    if _malus_bp_rip:
        skill_b_org.bonus = max(0, skill_b_org.bonus - _malus_bp_rip["valeur"])

    # --- BONUS MANUELS (paramètres optionnels) ---
    msg_bonus_manuel_rip = ""
    if bonus_base != 0:
        skill_b_org.base = max(0, skill_b_org.base + bonus_base)
        signe = "+" if bonus_base > 0 else ""
        msg_bonus_manuel_rip += f"\n✨ **Bonus Base** : {signe}{bonus_base}"
    if bonus_pieces != 0:
        skill_b_org.coins = max(1, skill_b_org.coins + bonus_pieces)
        signe = "+" if bonus_pieces > 0 else ""
        msg_bonus_manuel_rip += f"\n✨ **Bonus Pièces** : {signe}{bonus_pieces}"

    if "hate" in p_defenseur.effets:
        skill_b_org.coins += 2
        await interaction.followup.send(f"⚡ **{p_defenseur.nom}** utilise sa vitesse surnaturelle (+2 Pièces) !", ephemeral=True)
        del p_defenseur.effets["hate"]

    if "titanenblut" in p_defenseur.effets:
        skill_b_org.coins += 1

    # --- DÉSIGNATION (Loge de l'Ombre) — appliquée sur le défenseur (riposteur) ---
    if "loge_ombre" in p_defenseur.sous_classes_unlocked and p_attaquant and p_defenseur.designation_target_id == p_attaquant.user_id:
        pieces_bonus_d_rip, _ = appliquer_designation(p_defenseur, p_attaquant, skill_data_b)
        if pieces_bonus_d_rip > 0:
            skill_b_org.coins += pieces_bonus_d_rip
            msg_bonus_manuel_rip += f"\n🎯 **Désignation** : +{pieces_bonus_d_rip} Pièces !"

    await interaction.followup.send(f"⚔️ **Le Clash commence !**\n🔴 **{p_attaquant.nom}** vs 🔵 **{p_defenseur.nom}**{msg_hemo}{msg_bonus_manuel_rip}")

# --- CALCUL DES MALUS ET BONUS ---
    # Poison : (5 + lvl) // 5
    malus_a = (5 + p_attaquant.niveau) // 5 if "poison" in p_attaquant.effets else 0 # <-- MODIFIÉ ICI
    malus_b = (5 + p_defenseur.niveau) // 5 if "poison" in p_defenseur.effets else 0 # <-- MODIFIÉ ICI
    
    # Hâte : Avantage (on le gère dans la boucle en lançant 2 fois)
    hate_a = "hate" in p_attaquant.effets
    hate_b = "hate" in p_defenseur.effets
    
    # Suppression Hâte après usage
    if hate_a: del p_attaquant.effets["hate"]
    if hate_b: del p_defenseur.effets["hate"]

    # --- Force Pile (Oracle) : vérifier avant le clash ---
    fp_a = bool(p_attaquant.effets.get("force_pile"))
    fp_b = bool(p_defenseur.effets.get("force_pile"))
    if fp_a: del p_attaquant.effets["force_pile"]
    if fp_b: del p_defenseur.effets["force_pile"]

    coins_a = skill_a_org.coins; coins_b = skill_b_org.coins
    tour_clash = 1
    
    # Bonus niveau (Overwhelm)
    bonus_lvl_a = p_attaquant.get_bonus_niveau()
    bonus_lvl_b = p_defenseur.get_bonus_niveau()

    # --- BOUCLE DE DUEL ---
    while coins_a > 0 and coins_b > 0:
        await asyncio.sleep(3) 
        def lancer_clash(skill, bonus_lvl, malus_poison, a_hate, force_pile=False):
            tot, vis, h = skill.roll(bonus_niveau=bonus_lvl, force_pile=force_pile)
            if force_pile: vis.append("🔮(Toutes Pile!)")
            if a_hate:
                tot2, vis2, h2 = skill.roll(bonus_niveau=bonus_lvl)
                if tot2 > tot: tot, vis, h = tot2, vis2, h2
                vis.append("⚡")
            if malus_poison > 0:
                tot -= malus_poison
                vis.append("☠️")
            return tot, vis, h

        # Création skills temporaires pour le round
        tmp_a = Skill(skill_a_org.nom, skill_a_org.base, skill_a_org.bonus, coins_a, skill_a_org.stat_bonus, stat_nom=getattr(skill_a_org, 'stat_nom', ''))
        tmp_b = Skill(skill_b_org.nom, skill_b_org.base, skill_b_org.bonus, coins_b, skill_b_org.stat_bonus, stat_nom=getattr(skill_b_org, 'stat_nom', ''))

        # Lancer
        # Lancer
        tot_a, vis_a, heads_a = lancer_clash(tmp_a, bonus_lvl_a, malus_a, hate_a, force_pile=fp_a)
        tot_b, vis_b, heads_b = lancer_clash(tmp_b, bonus_lvl_b, malus_b, hate_b, force_pile=fp_b)

        # --- Moine du Lotus : +4 Base si Perturbé | +2 Base si Éveil P5 ---
        if "moine_lotus" in p_attaquant.sous_classes_unlocked:
            if "passif_lotus_eveil" in p_attaquant.competences:
                tot_a += 2; vis_a.append("+2(Éveil)")
            elif not p_attaquant.concentre:
                tot_a += 4; vis_a.append("🔥+4(Perturbé)")
        if "moine_lotus" in p_defenseur.sous_classes_unlocked:
            if "passif_lotus_eveil" in p_defenseur.competences:
                tot_b += 2; vis_b.append("+2(Éveil)")
            elif not p_defenseur.concentre:
                tot_b += 4; vis_b.append("🔥+4(Perturbé)")

        # --- Légion de Fer : -3 Base en Posture (-1 si Implacable P4) ---
        if "legion_fer" in p_attaquant.sous_classes_unlocked and p_attaquant.posture_active:
            malus_p = 1 if "passif_legion_implacable" in p_attaquant.competences else 3
            tot_a -= malus_p; vis_a.append(f"🛡️(-{malus_p} Posture)")
        if "legion_fer" in p_defenseur.sous_classes_unlocked and p_defenseur.posture_active:
            malus_p = 1 if "passif_legion_implacable" in p_defenseur.competences else 3
            tot_b -= malus_p; vis_b.append(f"🛡️(-{malus_p} Posture)")

        # --- Drakéide : +1 dégât par palier de 3 niveaux ---
        drake_a = p_attaquant.niveau // 3
        if p_attaquant.race == "Drakéide" and drake_a > 0:
            tot_a += drake_a; vis_a.append(f"🐲+{drake_a}(Drakéide)")
        drake_b = p_defenseur.niveau // 3
        if p_defenseur.race == "Drakéide" and drake_b > 0:
            tot_b += drake_b; vis_b.append(f"🐲+{drake_b}(Drakéide)")
        fp_a = False; fp_b = False  # Ne s'applique qu'au premier round
        
        # Résonance Divine supprimée — Ferveur gagnée uniquement via Prière Constante (+5/tour)

        # Comparaison
        resultat_txt = ""; color_embed = 0x3498db
        if tot_a > tot_b:
            coins_b -= 1
            resultat_txt = f"💥 **{p_attaquant.nom}** touche !"
            color_embed = 0xe74c3c
            # Contre-Temps (École de l'Estoc P2) : +1 Tension si round gagné
            if "passif_estoc_contretemps" in p_attaquant.competences:
                p_attaquant.tension = min(p_attaquant.tension + 1, 20)
                resultat_txt += " ⚡+1T"
        elif tot_b > tot_a:
            coins_a -= 1
            resultat_txt = f"💥 **{p_defenseur.nom}** contre !"
            color_embed = 0x2ecc71
            # Contre-Temps (École de l'Estoc P2) : +1 Tension si round gagné
            if "passif_estoc_contretemps" in p_defenseur.competences:
                p_defenseur.tension = min(p_defenseur.tension + 1, 20)
                resultat_txt += " ⚡+1T" 
        else:
            resultat_txt = "⚖️ **Égalité !**"
            color_embed = 0x95a5a6 

        vis_a_str = ' '.join(vis_a) if vis_a else "⚪"
        vis_b_str = ' '.join(vis_b) if vis_b else "⚪"

        embed_round = discord.Embed(title=f"🔄 Round {tour_clash}", color=color_embed)
        embed_round.add_field(name=f"🔴 {p_attaquant.nom}", value=f"**{tot_a}** `{vis_a_str}`", inline=True)
        embed_round.add_field(name=f"🔵 {p_defenseur.nom}", value=f"**{tot_b}** `{vis_b_str}`", inline=True)
        embed_round.set_footer(text=resultat_txt)
        
        try: await interaction.followup.send(embed=embed_round)
        except discord.HTTPException: pass
        tour_clash += 1
        if tour_clash > 15: break

    # --- RÉSOLUTION FINALE ---
    vainqueur = None; perdant = None; pieces_restantes = 0; skill_vainqueur = None; bonus_v = 0
    if coins_a > 0 and coins_b <= 0:
        vainqueur = p_attaquant; perdant = p_defenseur
        pieces_restantes = coins_a; skill_vainqueur = skill_a_org; bonus_v = bonus_lvl_a
    elif coins_b > 0 and coins_a <= 0:
        vainqueur = p_defenseur; perdant = p_attaquant
        pieces_restantes = coins_b; skill_vainqueur = skill_b_org; bonus_v = bonus_lvl_b

    # --- RÉSOLUTION DÉGÂTS (commun victoire attaquant ET défenseur) ---
    if vainqueur is not None:
        s_nom_safe = getattr(skill_vainqueur, 'stat_nom', "STAT")
        final_skill = Skill(skill_vainqueur.nom, skill_vainqueur.base, skill_vainqueur.bonus, pieces_restantes, skill_vainqueur.stat_bonus, stat_nom=s_nom_safe)

        damage_final, vis_fin, heads_final = final_skill.roll(bonus_niveau=bonus_v)



        ref_vainqueur = None
        for k, v in SKILLS_DB.items():
            if v['nom'] == skill_vainqueur.nom:
                ref_vainqueur = k
                break
        
        bonus_txt = "" 
        desc_sort = ""
        
        if ref_vainqueur:
            json_v = SKILLS_DB[ref_vainqueur].get('data_json', '{}')
            desc_sort = SKILLS_DB[ref_vainqueur].get('desc', '')
            # Appel avec heads=heads_final
            damage_final, msg_v = traiter_effets_json(json_v, vainqueur, perdant, damage_final, heads=heads_final)
            if msg_v: bonus_txt += f"\n{msg_v}"

            # --- SINGULARITÉ : consommation sur tout sort offensif (clash) ---
            _data_clash_sing = {}
            try: _data_clash_sing = json.loads(json_v)
            except (json.JSONDecodeError, TypeError): pass
            if not _data_clash_sing.get("check_singularite_all") and "singularite" in perdant.effets:
                ignore_sing_c, bonus_sing_c, msg_sing_c = consommer_singularite(perdant, vainqueur)
                if ignore_sing_c:
                    damage_final += bonus_sing_c
                    vainqueur._ignore_armor = True
                    vainqueur._ignore_rob = True
                    bonus_txt += f"\n{msg_sing_c}"

            # Masse Initiale (Magie Gravitationnelle P1) : sorts TC → +1 Lestage si cible ≥ 3 Lestages
            sort_data_v = SKILLS_DB[ref_vainqueur]
            if "passif_grav_masse" in vainqueur.competences and sort_data_v.get("cat") == "tronc":
                if get_lestage(perdant) >= 3:
                    ajouter_lestage(perdant, 1, vainqueur)
                    bonus_txt += "\n⚫ **Masse Initiale** : +1 Lestage bonus (cible portait ≥ 3 Lestages) !"

        # --- BONUS RACIAUX & EFFETS ---
        if vainqueur.race == "Drakéide":
            drake_bonus = vainqueur.niveau // 3
            if drake_bonus > 0:
                damage_final += drake_bonus
                bonus_txt += f" 🐲+{drake_bonus}(Drakéide)"

        # --- MOINE DU LOTUS : +4 Base si Perturbé | +2 Base si Éveil P5 ---
        if "moine_lotus" in vainqueur.sous_classes_unlocked:
            if "passif_lotus_eveil" in vainqueur.competences:
                damage_final += 2
                bonus_txt += " +2(Éveil)"
            elif not vainqueur.concentre:
                damage_final += 4
                bonus_txt += " 🔥+4(Perturbé)"

        # --- LÉGION DE FER : -3 Base en Posture (-1 si Implacable P4) ---
        if "legion_fer" in vainqueur.sous_classes_unlocked and vainqueur.posture_active:
            malus_p = 1 if "passif_legion_implacable" in vainqueur.competences else 3
            damage_final -= malus_p
            bonus_txt += f" 🛡️(-{malus_p} Posture)"
        
        if hasattr(vainqueur, "vampire_boost") and vainqueur.vampire_boost > 0:
            damage_final += vainqueur.vampire_boost
            bonus_txt += f" + {vainqueur.vampire_boost} (Sang)"
            vainqueur.vampire_boost = 0
        
        if "mutilation" in vainqueur.effets:
            damage_final = int(damage_final * 0.75)
            bonus_txt += " 🦴(-25% Mutilé)"
        
        if "gel" in perdant.effets:
            damage_final = int(damage_final * 1.5)
            bonus_txt += " x1.5 (❄️ Brise-Glace)"
            del perdant.effets["gel"]
            perdant.sauvegarder()

        # --- FESTIN : Bonus Tronc Commun (Clash) ---
        sort_data_vainqueur = None
        if vainqueur == p_attaquant and clash_data.get('ref_a') in SKILLS_DB:
            sort_data_vainqueur = SKILLS_DB[clash_data['ref_a']]
        elif vainqueur == p_defenseur and sort in SKILLS_DB:
            sort_data_vainqueur = SKILLS_DB[sort]
        if sort_data_vainqueur and "magie_sang" in vainqueur.sous_classes_unlocked and sort_data_vainqueur.get("cat") == "tronc" and vainqueur.classe == "mage":
            stade_v = get_festin_stade(vainqueur)
            if stade_v >= 2:
                damage_final += 6
                perdant.ajouter_effet("hemorragie", 1)
                bonus_txt += f" 🩸+6(Festin Stade2+)"
            elif stade_v == 1:
                damage_final += 3
                bonus_txt += f" 🩸+3(Festin Stade1)"
        # --- RÉSONANCE ÉLÉMENTAIRE : Bonus Feu (Clash) ---
        if "magie_elementaire" in vainqueur.sous_classes_unlocked and vainqueur.classe == "mage":
            bonus_res_v = get_bonus_resonance(vainqueur)
            if "feu" in bonus_res_v:
                damage_final += bonus_res_v["feu"]
                bonus_txt += f" 🔥+{bonus_res_v['feu']}(Rés)"

        msg_soin_vamp = ""
        if vainqueur.race == "Vampire" and damage_final > 0:
            vainqueur.pv_actuel = min(vainqueur.pv_max, vainqueur.pv_actuel + 1)
            msg_soin_vamp = "\n🩸 **Soif de sang :** +1 PV."

        # --- ÉCOLE DE L'ESTOC : status_si_clash_gagne (Sixte, Tierce, Riposte du Maître) ---
        msg_clash_statut = ""
        flag_sscg = vainqueur.effets.pop("_status_si_clash_gagne", None)
        if flag_sscg:
            try:
                statuts_g = json.loads(flag_sscg["valeur"])
                for eff_c, eff_v in statuts_g.items():
                    perdant.ajouter_effet(eff_c, eff_v)
                    msg_clash_statut += f"\n⚔️ **Clash Gagné** → {eff_c.capitalize()} ({eff_v}) sur {perdant.nom} !"
            except (json.JSONDecodeError, AttributeError): pass

        # --- ÉCOLE DE L'ESTOC : retour_degats_si_marge_3 (Passe Royale P5) ---
        msg_retour = ""
        if vainqueur.effets.pop("_retour_marge_3", None):
            marge = pieces_restantes  # pièces restantes du vainqueur = marge
            if marge >= 3:
                vainqueur.effets.pop("_retour_marge_3", None)
                perdant.pv_actuel = max(0, perdant.pv_actuel - damage_final)
                msg_retour = f"\n⚔️ **Passe Royale** : Marge de {marge} pièces — {perdant.nom} subit également {damage_final} dégâts en retour !"
                perdant.sauvegarder()

        if msg_clash_statut: bonus_txt += msg_clash_statut
        if msg_retour: bonus_txt += msg_retour

        if vainqueur and damage_final > 0:
            cs_add_infliges(vainqueur.user_id, vainqueur.nom, damage_final)
            cs_get(perdant.user_id, perdant.nom)
        ref_a_clash = clash_data.get('ref_a')
        if ref_a_clash: appliquer_cooldown(p_attaquant, ref_a_clash)
        appliquer_cooldown(p_defenseur, sort)
        # Moine du Lotus : mise à jour état concentré/perturbé pour les deux combattants
        sort_data_a = SKILLS_DB.get(ref_a_clash, {}) if ref_a_clash else {}
        maj_etat_moine(p_attaquant, sort_data_a, [])
        maj_etat_moine(p_defenseur, skill_data_b, [])
        p_attaquant.sauvegarder(); p_defenseur.sauvegarder()
        # Distorsion Permanente
        LAST_ATTACKER[perdant.user_id] = vainqueur.user_id
        cibles_sec_gagnant = None
        data_gagnant = {}
        if vainqueur == p_attaquant:
            cibles_sec_gagnant = clash_data.get('cibles_sec_a')
            if clash_data.get('ref_a') in SKILLS_DB:
                data_gagnant = json.loads(SKILLS_DB[clash_data['ref_a']].get('data_json', '{}'))
        elif vainqueur == p_defenseur:
            cibles_sec_gagnant = cibles_secondaires
            if sort in SKILLS_DB:
                data_gagnant = json.loads(SKILLS_DB[sort].get('data_json', '{}'))

        embed_fin = discord.Embed(title="FIN DU CLASH", color=0xF1C40F)
        embed_fin.description = f"🏆 **{vainqueur.nom}** l'emporte !"
        visuel_str = ' '.join(vis_fin) if vis_fin else "💨"
        
        embed_fin.add_field(
            name=f"Dégâts sur {perdant.nom}", 
            value=f"*{desc_sort}*\n🎲 **Jet ({pieces_restantes} pièces) :** {visuel_str}\n💥 **TOTAL : {damage_final} DÉGÂTS** {bonus_txt}{msg_soin_vamp}", 
            inline=False
        )
        
        if cibles_sec_gagnant and (data_gagnant.get("aoe") or data_gagnant.get("ricochet")):
            persos_sec = parse_cibles_sec(cibles_sec_gagnant)
            noms_sec = ", ".join(f"**{ps.nom}** (<@{ps.user_id}>)" for ps in persos_sec) if persos_sec else cibles_sec_gagnant
            embed_fin.add_field(
                name="💥 ATTAQUE AOE/RICOCHET",
                value=f"{noms_sec} :\n👉 **`/defense` contre {damage_final} dégâts !**\n*(Les effets de statut sont appliqués immédiatement)*",
                inline=False
            )
            lignes_aoe = appliquer_statuts_aoe(persos_sec, data_gagnant, heads=heads_final)
            if lignes_aoe:
                embed_fin.add_field(name="☠️ Effets Zone appliqués", value="\n".join(lignes_aoe), inline=False)

        embed_fin.add_field(name="Action", value=f"👉 **<@{perdant.user_id}>**, utilisez `/defense` !", inline=False)
        await log_combat(interaction, embed_fin)
        await interaction.followup.send(embed=embed_fin)

    # --- AoE ATTAQUANT même si perdant (effets de zone toujours appliqués) ---
    # Si l'attaquant avait une AoE et a perdu le clash, les cibles secondaires
    # reçoivent quand même les dégâts de base du sort (sans les pièces restantes)
    elif vainqueur is None or vainqueur == p_defenseur:
        cibles_sec_atq = clash_data.get('cibles_sec_a')
        if cibles_sec_atq:
            ref_a = clash_data.get('ref_a')
            if ref_a and ref_a in SKILLS_DB:
                data_a = {}
                try: data_a = json.loads(SKILLS_DB[ref_a].get('data_json', '{}'))
                except: data_a = {}
                if data_a.get("aoe") or data_a.get("ricochet"):
                    skill_a_base = clash_data.get('skill_a')
                    dmg_zone = getattr(skill_a_base, 'base', 0) if skill_a_base else 0
                    persos_sec_atq = parse_cibles_sec(cibles_sec_atq)
                    noms_sec_atq = ", ".join(f"**{ps.nom}** (<@{ps.user_id}>)" for ps in persos_sec_atq) if persos_sec_atq else cibles_sec_atq
                    embed_fin.add_field(
                        name="💥 ZONE ATTAQUANT (clash perdu — dégâts de base)",
                        value=f"{noms_sec_atq} :\n👉 **`/defense` contre {dmg_zone} dégâts** (dégâts de base, clash perdu)\n*(Les effets de statut sont appliqués immédiatement)*",
                        inline=False
                    )
                    lignes_aoe_atq = appliquer_statuts_aoe(persos_sec_atq, data_a, heads=heads_a)
                    if lignes_aoe_atq:
                        embed_fin.add_field(name="☠️ Effets Zone appliqués", value="\n".join(lignes_aoe_atq), inline=False)

        embed_fin.add_field(name="Action", value=f"👉 **<@{perdant.user_id}>**, utilisez `/defense` !", inline=False)
        
        await log_combat(interaction, embed_fin)
        await interaction.followup.send(embed=embed_fin)
    else:
        await interaction.followup.send("⚖️ **Égalité parfaite !** Aucun dégât.")

        
# 4. ATTAQUE 
@bot.tree.command(name="attaque", description="Attaque")
@app_commands.describe(
    sort="Votre technique", cible="L'adversaire (tapez pour chercher)",
    description="Action RP", personnage="[Optionnel] Votre personnage (si vous jouez plusieurs fiches)",
    cible_sec1="Cible de zone 1 (optionnel)", cible_sec2="Cible de zone 2 (optionnel)", cible_sec3="Cible de zone 3 (optionnel)",
    bonus_base="[Optionnel] Bonus fixe sur la Base (buff, circonstance MJ…)",
    bonus_pieces="[Optionnel] Pièces bonus supplémentaires"
)
@app_commands.autocomplete(sort=sort_offensif_autocomplete, personnage=joueur_perso_autocomplete, cible=cible_fiche_autocomplete,
    cible_sec1=cible_fiche_autocomplete, cible_sec2=cible_fiche_autocomplete, cible_sec3=cible_fiche_autocomplete)
async def attaque(interaction: discord.Interaction, sort: str, cible: str, description: str, personnage: str = None,
                  cible_sec1: str = None, cible_sec2: str = None, cible_sec3: str = None,
                  bonus_base: int = 0, bonus_pieces: int = 0):
    await interaction.response.defer()
    msg_designation_pre = ""
    cibles_secondaires = " ".join(s for s in [cible_sec1, cible_sec2, cible_sec3] if s) or None
    p: Personnage = Personnage.charger_par_nom(interaction.user.id, personnage) if personnage else Personnage.charger(interaction.user.id)
    p_cible = parse_cible_arg(cible)

    if not p: return await interaction.followup.send("❌ Pas de fiche.", ephemeral=True)
    if not p_cible: return await interaction.followup.send("❌ La cible n'a pas de fiche.", ephemeral=True)
    if p.pv_actuel <= 0: return await interaction.followup.send("💀 K.O.", ephemeral=True)

    if is_stun_actif(p): return await interaction.followup.send("💫 **Étourdi !**", ephemeral=True)
    if "gel" in p.effets: return await interaction.followup.send("❄️ **Gelé !**", ephemeral=True)

    sort = resolve_sort_ref(sort)
    if sort not in SKILLS_DB: return await interaction.followup.send("❌ Sort introuvable.", ephemeral=True)
    skill_data = SKILLS_DB[sort]

    dispo, msg_err = verifier_cooldown(p, sort)
    if not dispo: return await interaction.followup.send(msg_err, ephemeral=True)
    
    if skill_data.get('type') == 'soin': return await interaction.followup.send(f"🚫 C'est un soin.", ephemeral=True)
    if "(BONUS)" in skill_data['nom'].upper() or "(BONUS)" in sort.upper():
        return await interaction.followup.send("❌ Utilisez `/action_bonus`.", ephemeral=True)
    
    cout = skill_data.get("cout", 0); cout_type = skill_data.get("cout_type", "mana")
    reduc_humain = p.niveau // 3
    if p.race == "Humain" and p.classe == "mage" and reduc_humain > 0: 
        cout = max(int(skill_data.get("cout", 0) / 2), cout - reduc_humain)

    # Affinité Naturelle : -1 Mana sur sorts élémentaires
    if "passif_elem_affinite" in p.competences and cout_type == "mana":
        try:
            _d = json.loads(skill_data.get("data_json","{}"))
            if "generate_charge" in _d: cout = max(0, cout - 1)
        except (json.JSONDecodeError, TypeError): pass
    # Surcharge Élémentaire : -50% Mana si 3 charges du même élément
    if "passif_elem_surcharge" in p.competences and cout_type == "mana" and p.charges_elementaires:
        _cv, _cnt = Counter(p.charges_elementaires).most_common(1)[0]
        if _cnt >= 3 and all(e == _cv for e in p.charges_elementaires): cout = max(0, cout // 2)

    # Légion de Fer : cout_zero_si_posture — annule le coût AVANT débit
    try:
        _dj = json.loads(skill_data.get("data_json", "{}"))
        if _dj.get("cout_zero_si_posture") and p.posture_active:
            cout = 0
        if _dj.get("coins_bonus_si_posture") and p.posture_active:
            skill_data = dict(skill_data)
            skill_data["coins"] = skill_data.get("coins", 0) + _dj["coins_bonus_si_posture"]
    except (json.JSONDecodeError, TypeError): pass

    # Art de l'Estoc Maîtrisé (École de l'Estoc P5) : -1 Tension par Passe jouée (max -3)
    # Moine du Lotus : sorts de sous-classe coûtent -3 Ferveur si Concentré
    if ("moine_lotus" in p.sous_classes_unlocked and p.concentre
            and cout_type == "ferveur" and skill_data.get("cat") == "spe"):
        cout = max(0, cout - 3)

    msg_estoc_maitre = ""
    if "passif_estoc_maitre" in p.competences and cout_type == "tension":
        passe_count = getattr(p, "passe_count", 0)
        if passe_count > 0:
            reduction_estoc = min(passe_count, 3)
            cout = max(0, cout - reduction_estoc)
            msg_estoc_maitre = f"\n⚔️ **Art de l'Estoc Maîtrisé** : -{reduction_estoc} Tension (Passes jouées: {passe_count})."
            p.passe_count = 0  # Reset compteur après utilisation

    cout_paye_en_pv = False
    val_actuelle = getattr(p, cout_type, 0)

    if cout > 0:
        is_vampire_mage = (p.race == "Vampire" and p.classe == "mage")
        mode_sang = "mode_sang" in p.effets
        if is_vampire_mage and (mode_sang or p.pv_actuel > cout) and (mode_sang or val_actuelle < cout):
            p.pv_actuel -= cout; cout_paye_en_pv = True
        elif val_actuelle >= cout: setattr(p, cout_type, val_actuelle - cout)
        else: return await interaction.followup.send(f"❌ Pas assez de **{cout_type}**.", ephemeral=True)

    # --- Hémorragie Attaquant ---
    msg_hemo = ""
    if "hemorragie" in p.effets:
        val_hemo = p.effets["hemorragie"]["valeur"]
        p.pv_actuel -= val_hemo
        msg_hemo = f"\n🩸 **Hémorragie** : L'effort vous blesse (-{val_hemo} PV)."

    stat_nom = skill_data["stat_type"].upper()
    stat_valeur = getattr(p, skill_data["stat_type"], 0)
    if p.classe == "guerrier": stat_valeur = p.phy; stat_nom = "PHY"
    elif p.classe == "mage": stat_valeur = p.esp; stat_nom = "ESP"
    elif p.classe == "pretre": stat_valeur = p.foi; stat_nom = "FOI"

    skill_obj = Skill(skill_data["nom"], skill_data["base"], skill_data["bonus"], skill_data["coins"], stat_bonus=stat_valeur, stat_nom=stat_nom)

    if "hate" in p.effets:
        skill_obj.coins += 2
        del p.effets["hate"]
    if "titanenblut" in p.effets:
        skill_obj.coins += 1

    # --- TOXINE (Assassin Confrérie) : -1 Pièce par stack sur l'attaquant ---
    if "toxine" in p.effets:
        stacks_toxine = p.effets["toxine"].get("valeur", 1)
        skill_obj.coins = max(1, skill_obj.coins - stacks_toxine)
        visuel.append(f"🧪(-{stacks_toxine}🪙 Toxine)")

    # --- FURTIF ASSASSIN : +1 Pièce sur le prochain sort ---
    if "furtif_assassin" in p.effets:
        skill_obj.coins += 1
        del p.effets["furtif_assassin"]
        visuel.append("🌑(+1🪙 Furtif)")

    # --- LOGE DE L'OMBRE : bonus_si_deja_designee (Marquage Avancé P2) ---
    _flag_ma = p.effets.pop("_bonus_marquage_avance", None)
    if _flag_ma:
        skill_obj.coins += _flag_ma.get("valeur", 1)

    # --- ORACLE : malus_base (Touche du Destin) — réduit la Base de ce sort ---
    _malus_b = p.effets.pop("malus_base", None)
    if _malus_b:
        skill_obj.base = max(0, skill_obj.base - _malus_b["valeur"])
    _malus_bp = p.effets.pop("malus_bonus_pieces", None)
    if _malus_bp:
        skill_obj.bonus = max(0, skill_obj.bonus - _malus_bp["valeur"])

    # --- BONUS MANUELS (paramètres optionnels de la commande) ---
    msg_bonus_manuel = ""
    if bonus_base != 0:
        skill_obj.base = max(0, skill_obj.base + bonus_base)
        signe = "+" if bonus_base > 0 else ""
        msg_bonus_manuel += f"\n✨ **Bonus Base** : {signe}{bonus_base}"
    if bonus_pieces != 0:
        skill_obj.coins = max(1, skill_obj.coins + bonus_pieces)
        signe = "+" if bonus_pieces > 0 else ""
        msg_bonus_manuel += f"\n✨ **Bonus Pièces** : {signe}{bonus_pieces}"

    bonus_niv = p.get_bonus_niveau()
    # --- Force Pile (Oracle Inversion de Probabilité) ---
    fp = bool(p.effets.get("force_pile"))
    if fp:
        del p.effets["force_pile"]
    total, visuel, heads = skill_obj.roll(bonus_niveau=bonus_niv, force_pile=fp)
    if fp: visuel.append("🔮(Toutes Pile !)")

    if skill_obj.coins > skill_data["coins"]: visuel.append("⚡(+2 Pièces)")
    if "poison" in p.effets:
        malus = (5 + p.niveau) // 5
        total -= malus
        visuel.append(f"☠️(-{malus} Psn)")

    # --- Décharge : double les pièces AVANT le roll (appliqué si sort tronc) ---
    decharge_used = False
    if "decharge_active" in p.effets and skill_data.get("cat") == "tronc":
        skill_obj.coins *= 2
        del p.effets["decharge_active"]
        decharge_used = True
        # Recalcul du roll avec les pièces doublées
        total, visuel, heads = skill_obj.roll(bonus_niveau=bonus_niv)
        visuel.append("⚡🌪️(Décharge x2 Pièces)")

    json_data = skill_data.get('data_json', '{}')

    # --- DÉSIGNATION (Loge de l'Ombre) — appliquée AVANT le seuil/traiter ---
    msg_designation_pre = ""
    if "loge_ombre" in p.sous_classes_unlocked and p_cible and p.designation_target_id == p_cible.user_id:
        pieces_bonus_d_pre, msg_designation_pre = appliquer_designation(p, p_cible, skill_data)
        if pieces_bonus_d_pre > 0:
            skill_obj.coins += pieces_bonus_d_pre
            total, visuel, heads = skill_obj.roll(bonus_niveau=bonus_niv)
            visuel.append(f"🎯+{pieces_bonus_d_pre}(Désig)")

    total, msg_effets_spe = traiter_effets_json(json_data, p, p_cible, total, heads=heads)

    # Masse Initiale (Magie Gravitationnelle P1) : sorts TC → +1 Lestage si cible ≥ 3 Lestages
    if "passif_grav_masse" in p.competences and skill_data.get("cat") == "tronc":
        if get_lestage(p_cible) >= 3:
            ajouter_lestage(p_cible, 1, p)
            msg_effets_spe = (msg_effets_spe or "") + "\n⚫ **Masse Initiale** : +1 Lestage bonus (cible portait ≥ 3 Lestages) !"

    # --- SINGULARITÉ : consommation sur tout sort offensif (sauf sorts qui gèrent eux-mêmes via check_singularite_all) ---
    msg_singularite = ""
    _data_parse_sing = {}
    try: _data_parse_sing = json.loads(skill_data.get("data_json", "{}"))
    except (json.JSONDecodeError, TypeError): pass
    if not _data_parse_sing.get("check_singularite_all") and "singularite" in p_cible.effets:
        ignore_sing, bonus_sing_val, msg_sing_txt = consommer_singularite(p_cible, p)
        if ignore_sing:
            total += bonus_sing_val
            p._ignore_armor = True
            p._ignore_rob = True
            msg_singularite = f"\n{msg_sing_txt}"

    # --- Passifs & Mécaniques ---
    if "gel" in p_cible.effets:
        total = int(total * 1.5)
        visuel.append("❄️(Brise-Glace x1.5)")
        del p_cible.effets["gel"]

    # --- FESTIN : Bonus Tronc Commun ---
    msg_festin = ""
    if "magie_sang" in p.sous_classes_unlocked and skill_data.get("cat") == "tronc" and p.classe == "mage":
        stade = get_festin_stade(p)
        if stade >= 2:
            total += 6
            p_cible.ajouter_effet("hemorragie", 1)
            msg_festin = f"\n🩸 **Festin Stade {stade}** : +6 Dégâts + Hémorragie auto !"
            visuel.append(f"🩸+6(Stade2+)")
        elif stade == 1:
            total += 3
            msg_festin = f"\n🩸 **Festin Stade 1** : +3 Dégâts."
            visuel.append("🩸+3(Stade1)")

    # --- ASSASSIN DE LA CONFRÉRIE — Passifs sur sorts TC ---
    msg_sadisme = ""
    _is_tc = skill_data.get("cat") == "tronc"
    if "assassin_confrerie" in p.sous_classes_unlocked and p_cible:
        nb_alts = get_nb_alterations(p_cible)

        # SADISME (mécanique signature) — TC uniquement
        if _is_tc:
            if nb_alts >= 3:
                total += 12
                msg_sadisme += f"\n🗡️ **Sadisme** : +12 dégâts ({nb_alts} types d'altérations) ! *(Attaque Inesquivable)*"
                p._inesquivable = True
            elif nb_alts == 2:
                total += 8
                msg_sadisme += f"\n🗡️ **Sadisme** : +8 dégâts ({nb_alts} altérations)."
            elif nb_alts == 1:
                total += 4
                msg_sadisme += f"\n🗡️ **Sadisme** : +4 dégâts (1 altération)."

        # Lame Infectée (P1) — toujours, 25% chance Poison ou Hémo
        if "passif_assassin_lame" in p.competences and total > 0:
            import random as _r
            if _r.random() < 0.25:
                p_cible.ajouter_effet("poison", 1)
                msg_sadisme += "\n🗡️ **Lame Infectée** : Poison 1 déclenché (25%) !"

        # Bourreau des Ombres (P3) — TC avec 3+ altérations → coût Tension = 0
        if _is_tc and "passif_assassin_bourreau" in p.competences and nb_alts >= 3:
            remboursement = skill_data.get("cout", 0)
            if skill_data.get("cout_type") == "tension" and remboursement > 0:
                p.tension = min(p.tension + remboursement, 20)
                msg_sadisme += f"\n🗡️ **Bourreau des Ombres** : Coût en Tension remboursé (+{remboursement})."

        # L'Heure du Crime (P4) — TC sur cible empoisonnée → ignore Armure + Rob
        if _is_tc and "passif_assassin_heure" in p.competences and "poison" in p_cible.effets:
            p._ignore_armor = True
            p._ignore_rob   = True
            msg_sadisme += "\n🗡️ **L'Heure du Crime** : Armure + Robustesse ignorées (cible empoisonnée)."

        # ignore_armor_si_hemo (Coup Vicieux Novice)
        _data_spe = {}
        try:
            import json as _j
            _data_spe = _j.loads(skill_data.get("data_json", "{}"))
        except Exception: pass
        if _data_spe.get("ignore_armor_si_hemo") and "hemorragie" in p_cible.effets:
            p._ignore_armor = True
            msg_sadisme += "\n🗡️ **Coup Vicieux** : Armure ignorée (cible en Hémorragie)."

        # Silence (Dague Toxique P3) — magie impossible ce tour
        if _data_spe.get("silence_cible"):
            p_cible.ajouter_effet("silence", 1)
            msg_sadisme += "\n🤫 **Silence** : magie impossible pour la cible ce tour."

        # execute_sous_20pct (Coup Vicieux Avancé P5)
        if _data_spe.get("execute_sous_20pct"):
            seuil_20 = p_cible.pv_max * 0.20
            if p_cible.pv_actuel <= seuil_20:
                p_cible.pv_actuel = 0
                msg_sadisme += f"\n💀 **Exécution** : {p_cible.nom} est exécuté(e) (< 20% PV) !"

        # L'Ange Noir (P5) — kill avec 3+ altérations
        if "passif_assassin_ange" in p.competences and p_cible.pv_actuel <= 0 and nb_alts >= 3:
            p.tension = min(p.tension + 5, 20)
            p.pv_actuel = min(p.pv_max, p.pv_actuel + 15)
            msg_sadisme += "\n🖤 **L'Ange Noir** : Kill avec 3+ altérations ! +5 Tension, +15 PV."

    # --- RÉSONANCE ÉLÉMENTAIRE : Bonus Dégâts Feu ---
    msg_resonance = ""
    if "magie_elementaire" in p.sous_classes_unlocked and p.classe == "mage":
        bonus_res = get_bonus_resonance(p)
        if "feu" in bonus_res:
            total += bonus_res["feu"]
            msg_resonance = f"\n🔥 **Résonance Feu** : +{bonus_res['feu']} Dégâts."
            visuel.append(f"🔥+{bonus_res['feu']}(Rés)")
        # Air boost esquive (juste narratif ici, affiché)
        if "air" in bonus_res:
            msg_resonance += f"\n💨 **Résonance Air** : +{bonus_res['air']} Esquive (passif)."

    # --- DÉSIGNATION — traitée avant le roll, msg récupéré ---
    msg_designation = msg_designation_pre

    # --- SENTENCE (Inquisiteur) ---
    msg_sentence = ""
    if "inquisiteur" in p.sous_classes_unlocked and p_cible.user_id in p.sentence_targets:
        base_bonus_s, ignore_armure_s, msg_sentence = appliquer_legere_inquisiteur(p, p_cible, skill_data)
        if base_bonus_s > 0:
            total += base_bonus_s
            visuel.append(f"📜+{base_bonus_s}(Sentence)")
        # Grand Inquisiteur P5 : si cible tombe à 0 PV après cette attaque (check post-dégâts)
        p._sentence_ignore_armure = ignore_armure_s

    # --- PASSE ESTOC (bonus si passe_active) ---
    # Mémoire du Corps (P4) : étend le bonus au tour précédent via last_action_type
    if "ecole_estoc" in p.sous_classes_unlocked:
        memoire_active = "passif_estoc_memoire" in p.competences and p.last_action_type == "passe"
        passe_check = p.passe_active or memoire_active
        if passe_check:
            try:
                data_j_estoc = json.loads(skill_data.get("data_json","{}"))
                bonus_p = data_j_estoc.get("bonus_si_passe", {})
                if bonus_p:
                    if bonus_p.get("cout_zero"):
                        pass  # géré au coût
                    coins_b = bonus_p.get("coins_bonus", 0)
                    if coins_b:
                        skill_obj.coins += coins_b
                        total, visuel, heads = skill_obj.roll(bonus_niveau=bonus_niv)
                        visuel.append(f"⚔️+{coins_b}🪙(Passe)")
                    if memoire_active and not p.passe_active:
                        visuel.append("🧠(Mémoire)")
            except (json.JSONDecodeError, KeyError): pass
            p.passe_active = 0

    # --- DISCIPLINE DU SALON (P3) : +1 Tension si dernière action = Passe et Estoc ce tour ---
    if "passif_estoc_discipline" in p.competences and p.last_action_type == "passe":
        try:
            data_j_disc = json.loads(skill_data.get("data_json", "{}"))
            if data_j_disc.get("bonus_si_passe"):  # identifie les Estocs
                p.tension += 1
                visuel.append("⚔️+1💢(Discipline)")
        except (json.JSONDecodeError, KeyError): pass

    # --- POSTURE LÉGION (malus Base à l'attaque) ---
    msg_posture_atk = ""
    if "legion_fer" in p.sous_classes_unlocked and p.posture_active:
        malus_base = 1 if "passif_legion_implacable" in p.competences else 3
        total -= malus_base
        visuel.append(f"🛡️(-{malus_base} Posture)")
        msg_posture_atk = f"\n🛡️ Posture active : -{malus_base} dégâts."

    # --- MOINE DU LOTUS (+4 Base si Perturbé) ---
    if "moine_lotus" in p.sous_classes_unlocked and not p.concentre:
        total += 4
        visuel.append("🔥+4(Perturbé)")
    # Passif Éveil P5 : +2 Base permanent
    if "passif_lotus_eveil" in p.competences:
        total += 2
        visuel.append("+2(Éveil)")

    # --- MISE À JOUR last_action_type + état Moine ---
    msg_moine_transition = maj_etat_moine(p, skill_data, visuel)

    if p.race == "Drakéide" and p.niveau >= 3:
        total += (p.niveau // 3)
        visuel.append(f"🐲(+{p.niveau//3} Drakéide)")

    msg_vamp = ""
    if p.race == "Vampire" and total > 0:
        p.pv_actuel = min(p.pv_max, p.pv_actuel + 1)
        msg_vamp = "\n🩸 **Soif de sang :** +1 PV."

    if msg_effets_spe: visuel.append(f"\n{msg_effets_spe}")


    if "mutilation" in p.effets:
        total = int(total * 0.75)
        visuel.append("🦴(-25% Mutilé)")

    # --- LOGE DE L'OMBRE : Grand Régulateur P5 ---
    # Kill sur cible Désignée → +15 Mana + nouvelle Désignation gratuite
    msg_regulateur = ""
    if (p_cible.pv_actuel <= 0
            and "loge_ombre" in p.sous_classes_unlocked
            and "passif_ombre_regulateur" in p.competences
            and p.designation_target_id == p_cible.user_id):
        p.mana = min(p.mana_max, p.mana + 15)
        p.designation_target_id = 0
        p.designation_stacks = 1  # nouvelle Désignation gratuite prête
        msg_regulateur = "\n🎯⭐ **Grand Régulateur** : Kill sur cible Désignée ! +15 Mana + Désignation rechargée !"

    if total > 0: cs_add_infliges(p.user_id, p.nom, total)
    cs_get(p_cible.user_id, p_cible.nom)
    appliquer_cooldown(p, sort)
    p.sauvegarder()
    p_cible.sauvegarder()
    LAST_ATTACKER[p_cible.user_id] = p.user_id

    # Récupérer les flags ignore posés par traiter_effets_json
    ignore_armor_flag = getattr(p, "_ignore_armor", False)
    ignore_rob_flag   = getattr(p, "_ignore_rob",   False)
    # Sentence ignore (rétrocompat)
    if getattr(p, "_sentence_ignore_armure", False):
        ignore_armor_flag = True
    # Nettoyage des flags temporaires
    p._ignore_armor = False; p._ignore_rob = False; p._sentence_ignore_armure = False

    embed = discord.Embed(title="⚔️ ATTAQUE", color=0xFF0000)
    msg_v4 = ""
    if msg_designation: msg_v4 += f"\n{msg_designation}"
    if msg_sentence: msg_v4 += f"\n{msg_sentence}"
    if msg_posture_atk: msg_v4 += msg_posture_atk
    if msg_sadisme: msg_v4 += msg_sadisme
    if msg_estoc_maitre: msg_v4 += msg_estoc_maitre
    if msg_regulateur: msg_v4 += msg_regulateur
    if msg_moine_transition: msg_v4 += msg_moine_transition
    embed.description = f"**{p.nom}** attaque **{p_cible.nom}** !\n*« {description} »*{msg_hemo}{msg_festin}{msg_resonance}{msg_v4}{msg_bonus_manuel}{msg_singularite}"
    
    calcul_txt = f"Base {skill_obj.base} + ({heads}x{skill_obj.bonus}) + {stat_nom}"
    if cout_paye_en_pv: calcul_txt += " (PV🩸)"
    
    embed.add_field(name=f"Technique : {skill_obj.nom}", value=f"*{skill_data['desc']}*\n{' '.join(visuel)}\n`{calcul_txt}`\n💥 **Dégâts Totaux : {total}**{msg_vamp}", inline=False)

    # Instruction /defense pour la cible — indique si perce_armure
    if ignore_armor_flag:
        embed.add_field(name="🗡️ Attaque Perforante", value=f"👉 **{p_cible.nom}** : `/defense` avec **perce_armure: Vrai** ! (Armure + Rob ignorées)", inline=False)
    elif ignore_rob_flag:
        embed.add_field(name="🗡️ Rob Percée", value=f"👉 **{p_cible.nom}** : `/defense` avec **perce_armure: Vrai** ! (Robustesse ignorée)", inline=False)

    data_parse = json.loads(json_data)

    if cibles_secondaires and (data_parse.get("aoe") or data_parse.get("ricochet")):
        persos_sec = parse_cibles_sec(cibles_secondaires)
        noms_sec = ", ".join(f"**{ps.nom}** (<@{ps.user_id}>)" for ps in persos_sec) if persos_sec else cibles_secondaires
        embed.add_field(name="💥 Cibles Collatérales", value=f"{noms_sec} : dans la zone !\n👉 **`/defense` contre {total} dégâts !**", inline=False)
        lignes_effets = appliquer_statuts_aoe(persos_sec, data_parse, heads=heads)
        if lignes_effets:
            embed.add_field(name="☠️ Effets Zone appliqués", value="\n".join(lignes_effets), inline=False)

    if cibles_secondaires and data_parse.get("aoe_reduit"):
        total_reduit = max(1, total // 2)
        persos_sec = parse_cibles_sec(cibles_secondaires)
        noms_sec = ", ".join(f"**{ps.nom}** (<@{ps.user_id}>)" for ps in persos_sec) if persos_sec else cibles_secondaires
        embed.add_field(name="💥 Cible Secondaire (demi-dégâts)", value=f"{noms_sec} !\n👉 **`/defense` contre {total_reduit} dégâts** (frappe réduite de moitié) !", inline=False)
        lignes_effets = appliquer_statuts_aoe(persos_sec, data_parse, heads=heads)
        if lignes_effets:
            embed.add_field(name="☠️ Effets Zone appliqués", value="\n".join(lignes_effets), inline=False)

    await log_combat(interaction, embed)
    await interaction.followup.send(embed=embed)

# 5. DEFENSE (Modifiée - Réduction Passive)
@bot.tree.command(name="defense", description="Se défendre : Mitigation ou Esquive")
@app_commands.describe(type_def="Encaisser ou Esquiver", degats_subis="Dégâts à subir", ressource_spend="Mana/Tension/Ferveur à dépenser", perce_armure="Mettre sur Vrai si l'attaque adverse ignore l'armure", personnage="[Optionnel] Votre personnage (si vous jouez plusieurs fiches)")
@app_commands.autocomplete(personnage=joueur_perso_autocomplete)
@app_commands.choices(type_def=[
    app_commands.Choice(name="🛡️ Encaisser", value="tank"),
    app_commands.Choice(name="🏃 Esquive (Risque x1.5 dégâts)", value="esquive")
])
async def defense(interaction: discord.Interaction, type_def: app_commands.Choice[str], degats_subis: int, ressource_spend: int = 0, perce_armure: bool = False, personnage: str = None):
    p: Personnage = Personnage.charger_par_nom(interaction.user.id, personnage) if personnage else Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("Pas de fiche.", ephemeral=True)
    if p.pv_actuel <= 0: return await interaction.response.send_message("💀 K.O.", ephemeral=True)

    # --- A. ÉTOURDISSEMENT (Bloquant Total) ---
    if is_stun_actif(p):
        p.pv_actuel -= degats_subis
        if p.pv_actuel < 0: p.pv_actuel = 0
        p.sauvegarder()
        return await interaction.response.send_message(f"💫 **Vous êtes Étourdi !** Impossible de vous défendre.\n💥 Vous subissez **{degats_subis}** dégâts plein pot. (PV: {p.pv_actuel})", ephemeral=True)
    
    # --- NOUVEAU : INVULNÉRABILITÉ (Intervention Divine) ---
    if "invulnerable" in p.effets:
        embed = discord.Embed(title="Invulnérabilité", color=0xF1C40F)
        embed.description = f" Vous ignorez totalement les **{degats_subis}** dégâts."
        return await interaction.response.send_message(embed=embed)

    embed = discord.Embed(title="🛡️ Défense", color=0xF1C40F)
    degats_bruts = degats_subis
    
    ## Calcul Malus Poison
    malus_poison = 0
    if "poison" in p.effets:
        malus_poison = (5 + p.niveau) // 5 # <-- MODIFIÉ ICI

    # --- DÉVIATION TOTALE (Oracle P4) : annule complètement l'attaque ---
    if "deviation_totale" in p.effets:
        del p.effets["deviation_totale"]
        p.sauvegarder()
        embed_dev = discord.Embed(title="🔮 Déviation Totale", color=0x9b59b6)
        embed_dev.description = f"**{p.nom}** était protégé par une **Déviation Totale** !\n💫 L'attaque est annulée — **0 dégâts** !"
        return await interaction.response.send_message(embed=embed_dev)

    # --- REDIRECTION ACTIVE (Oracle P5) : annule et redirige (MJ gère la nouvelle cible) ---
    if "redirection_active" in p.effets:
        del p.effets["redirection_active"]
        p.sauvegarder()
        embed_red = discord.Embed(title="🔮 Déviation Absolue", color=0x9b59b6)
        embed_red.description = f"**{p.nom}** était protégé par une **Déviation Absolue** !\n↩️ L'attaque est redirigée vers un ennemi — le MJ désigne la nouvelle cible !"
        return await interaction.response.send_message(embed=embed_red)

    # --- B. ESQUIVE ---
    if type_def.value == "esquive":
        # Gestion Enracinement (Agilité = 0)
        coins_agi = max(1, p.agi)
        msg_root = ""
        if "root" in p.effets:
            coins_agi = 0
            msg_root = " 🌳(Enraciné: Agi 0)"

        base_esq = 2; bonus_esq = 5
        skill_esq = Skill("Esquive", base_esq, bonus_esq, coins_agi, stat_bonus=0)
        
        # Résonance Air (Magie Élémentaire) : bonus esquive
        bonus_air_esq = 0
        if "magie_elementaire" in p.sous_classes_unlocked and p.classe == "mage":
            bonus_res_esq = get_bonus_resonance(p)
            if "air" in bonus_res_esq:
                bonus_air_esq = bonus_res_esq["air"]
        
        nb_rolls = 2 if (p.race == "Féral" or "hate" in p.effets) else 1
        best_total = -999; best_visuel = []
        
        for _ in range(nb_rolls):
            tot, vis, _ = skill_esq.roll(bonus_niveau=p.get_bonus_niveau())
            tot -= malus_poison
            tot += bonus_air_esq
            if tot > best_total: best_total, best_visuel = tot, vis
        
        if "hate" in p.effets:
            best_visuel.append("⚡(Hâte)")
            del p.effets["hate"]

        if bonus_air_esq > 0: best_visuel.append(f"💨+{bonus_air_esq}(Rés Air)")
        if malus_poison > 0: best_visuel.append(f"☠️(-{malus_poison})")
        if msg_root: best_visuel.append(msg_root)

        embed.add_field(name="Tentative d'Esquive", value=f"Agilité ({coins_agi} dés): {' '.join(best_visuel)}\nScore: **{best_total}** vs Dégâts: **{degats_subis}**", inline=False)
        
        if best_total >= degats_subis:
            degats_bruts = 0
            embed.add_field(name="Résultat", value="💨 **ESQUIVE PARFAITE !**", inline=False)
        else:
            degats_bruts = int(degats_subis * 1.5)
            embed.add_field(name="Résultat", value=f"💥 **Échoué !** x1.5 dégâts : **{degats_bruts}**.", inline=False)

    # --- C. MITIGATION (TANK) ---
    else:
        reduction_extra = 0; msg_detail = []
        reduction_niveau = p.get_bonus_niveau()
        msg_detail.append(f"• Bonus Niveau : -{reduction_niveau}")

        if "bouclier" in p.effets:
            val_bouclier = p.effets["bouclier"]["valeur"]
            msg_detail.append(f" **Bouclier Actif : -{val_bouclier}**")
            reduction_extra += val_bouclier
            del p.effets["bouclier"]

        # --- MOINE : Posture du Lotus (armure_concentre / armure_perturbe) ---
        if "moine_lotus" in p.sous_classes_unlocked and "posture_lotus_active" in p.effets:
            lotus_data = p.effets["posture_lotus_active"]
            if p.concentre:
                val_l = lotus_data.get("armure_concentre", lotus_data.get("armure_base", 0))
                msg_detail.append(f"• 🌸 **Posture Lotus (Concentré)** : -{val_l}")
            else:
                val_l = lotus_data.get("armure_perturbe", lotus_data.get("armure_base", 0))
                msg_detail.append(f"• 🔥 **Posture Lotus (Perturbé)** : -{val_l}")
            reduction_extra += val_l
            del p.effets["posture_lotus_active"]

        nom_ressource = ""; stock_actuel = 0; multiplicateur = 0
        if p.classe == "guerrier": nom_ressource = "tension"; stock_actuel = p.tension; multiplicateur = 4
        elif p.classe == "mage": nom_ressource = "mana"; stock_actuel = p.mana; multiplicateur = 2
        elif p.classe == "pretre": nom_ressource = "ferveur"; stock_actuel = p.ferveur; multiplicateur = 0.5
        elif p.classe == "monstre": nom_ressource = "mana"; stock_actuel = p.mana; multiplicateur = 2

        if ressource_spend > 0:
            if stock_actuel >= ressource_spend:
                setattr(p, nom_ressource, stock_actuel - ressource_spend)
                reduction_extra += int(ressource_spend * multiplicateur)
                msg_detail.append(f"• Dépense {ressource_spend} {nom_ressource} : -{int(ressource_spend * multiplicateur)}")

        total_reduc = reduction_extra + reduction_niveau
        degats_bruts = max(0, degats_subis - total_reduc)

        embed.add_field(name="🛡️ Encaissement Actif", value="\n".join(msg_detail) + f"\n**Total bloqué : -{total_reduc}**", inline=False)
        
        # --- D. APPLICATION DE LA ROBUSTESSE UNIVERSELLE ---
    degats_finaux = degats_bruts
    
    if not perce_armure: # <--- NOUVEAU : On vérifie que l'attaque ne perce pas l'armure
        robustesse_val = p.get_robustesse()
        if degats_finaux > 0 and robustesse_val > 0:
            degats_bloques = min(degats_finaux, robustesse_val)
            degats_finaux -= degats_bloques
            embed.add_field(name="🧱 Robustesse", value=f"Votre corps/équipement absorbe **{degats_bloques}** dégâts (Total Rob: {robustesse_val}).", inline=False)
    else:
        embed.add_field(name="🛡️❌ Armure Percée", value="L'attaque ignore totalement votre Robustesse !", inline=False)

    # --- E. ARMURE MAGIQUE (L'état temporaire) ---
    msg_armure = ""
    if not perce_armure: # <--- NOUVEAU : On vérifie aussi pour l'armure magique
        if degats_finaux > 0 and "armure" in p.effets:
            val_armure = p.effets["armure"]["valeur"]
            degats_bloques = min(degats_finaux, val_armure)
            degats_finaux -= degats_bloques
            p.effets["armure"]["valeur"] -= 1
            if p.effets["armure"]["valeur"] <= 0:
                del p.effets["armure"]
                msg_armure = f"\n🛡️ L'état **Armure** a bloqué **{degats_bloques}** dégâts et se brise !"
            else:
                msg_armure = f"\n🛡️ L'état **Armure** a bloqué **{degats_bloques}** dégâts (-1 charge. Reste: {p.effets['armure']['valeur']})."
                
            embed.add_field(name="🛡️ Armure Magique", value=msg_armure.strip(), inline=False)

    # --- FINALISATION ---
    msg_ko = ""
    msg_gain = ""
    msg_v4_def = ""

    # --- PASSE ESTOC : +2 Tension si passe_active ---
    msg_passe_t = appliquer_passe_trigger(p)
    if msg_passe_t: msg_v4_def += f"\n{msg_passe_t}"

    # --- PARADE ABSORB (École de l'Estoc P3) : réduit dégâts ---
    degats_finaux, msg_parade = appliquer_parade_absorb(p, degats_finaux)
    if msg_parade: msg_v4_def += f"\n{msg_parade}"

    # --- LÉGION : reduction_fixe_posture (Bastion Novice/Avancé) ---
    if "reduction_fixe_posture" in p.effets and degats_finaux > 0:
        red_fixe = p.effets["reduction_fixe_posture"]["valeur"]
        bloques_fixe = min(degats_finaux, red_fixe)
        degats_finaux -= bloques_fixe
        del p.effets["reduction_fixe_posture"]
        msg_v4_def += f"\n🛡️ **Réduction Fixe (Bastion)** : -{bloques_fixe} dégâts supplémentaires."

    # --- LÉGION DE FER : Robustesse ×2 en Posture ---
    if "legion_fer" in p.sous_classes_unlocked and p.posture_active and not perce_armure:
        rob_bonus_posture = p.get_robustesse()  # Déjà appliqué ci-dessus, on ajoute une 2ème fois
        if degats_finaux > 0 and rob_bonus_posture > 0:
            degats_bloques_pos = min(degats_finaux, rob_bonus_posture)
            degats_finaux -= degats_bloques_pos
            msg_v4_def += f"\n🛡️ **Posture Légion** : -{degats_bloques_pos} dégâts supplémentaires (Rob×2)."
            embed.add_field(name="⚔️ Posture Défensive", value=f"Robustesse doublée : **-{degats_bloques_pos}** dégâts.", inline=False)

    if degats_finaux > 0:
        cs_add_recus(p.user_id, p.nom, degats_finaux)
        pv_avant_v4 = p.pv_actuel
        p.pv_actuel -= degats_finaux
        if p.classe == "guerrier":
            p.tension += 1
            msg_gain = "\n💢 **+1 Tension** (Douleur)"

        # --- SERMENT DU SANG (Clan du Nord) : calcul bonus ---
        if "clan_nord" in p.sous_classes_unlocked and p.serment_actif:
            calculer_serment(p, degats_finaux)

        # --- FUREUR TRIBALE (Clan du Nord P3) ---
        if "passif_nord_fureur" in p.competences:
            msg_fureur = appliquer_fureur_tribale(p, pv_avant, degats_finaux)
            if msg_fureur:
                embed.add_field(name="🔥 Fureur Tribale", value=msg_fureur, inline=False)

        # --- LE DERNIER REMPART (Légion P5) : <20% PV → Posture auto + Tension ---
        if "passif_legion_rempart_final" in p.competences and p.posture_active == 0:
            seuil_20 = p.pv_max * 0.2
            if p.pv_actuel <= seuil_20 and pv_avant_v4 > seuil_20:
                if not p.effets.get("_rempart_used"):
                    p.posture_active = 1
                    p.tension = min(p.tension + 3, 20)
                    p.effets["_rempart_used"] = {"duree": 999, "valeur": 1}
                    p.effets["posture_forcee"] = {"duree": 2, "valeur": 1}
                    msg_v4_def += "\n🛡️🔥 **Dernier Rempart** : Posture automatique (2 tours) + +3 Tension !"
                    embed.add_field(name="🔱 Dernier Rempart", value="PV critiques ! Posture Défensive activée automatiquement pour 2 tours.", inline=False)

        # --- LÉGION MURAILLE P3 : seuil KO à -10 en Posture ---
        if "passif_legion_muraille" in p.competences and p.posture_active:
            if p.pv_actuel < -10:
                p.pv_actuel = -10

        if p.pv_actuel <= 0:
            # Indestructible (Clan du Nord P5) : survie à 1 PV une fois
            if "passif_nord_indestructible" in p.competences and not p.effets.get("_indestructible_used"):
                p.pv_actuel = 1
                p.effets["_indestructible_used"] = {"duree": 999, "valeur": 1}
                msg_ko = "\n⚡ **L'Indestructible** : La mort vous refuse ! Vous survivez à 1 PV !"
            elif "unsterblich" in p.effets:
                p.pv_actuel = 1
                del p.effets["unsterblich"]
                msg_ko = "\nLa mort vous refuse. Vous survivez à 1 PV !"
            elif "passif_legion_muraille" in p.competences and p.posture_active and p.pv_actuel >= -10:
                msg_ko = f"\n💀 **K.O.** — Muraille de Chair : Vous tenez jusqu'à -10 PV ({p.pv_actuel} PV)."
            else:
                p.pv_actuel = 0
                msg_ko = "\n💀 **VOUS ÊTES K.O. !**"
                p.tension = 0
                p.ferveur = 0

    p.sauvegarder()
    
    # --- REBOND ACTIF (Rempart de Corps Avancé) : renvoie dégâts si des dégâts ont été bloqués ---
    msg_rebond = ""
    if "rebond_actif" in p.effets:
        dmg_bloques_total = max(0, degats_subis - degats_finaux)
        val_rebond = p.effets["rebond_actif"]["valeur"]
        del p.effets["rebond_actif"]
        if dmg_bloques_total > 0:
            msg_rebond = f"\n⚔️ **Rebond de Rempart** : {val_rebond} dégâts renvoyés à l'attaquant !"
            embed.add_field(name="↩️ Rebond", value=f"L'attaquant subit **{val_rebond}** dégâts en retour (annoncez-le).", inline=False)
        p.sauvegarder()
    
    # Aura de Sacrifice (Ordre Hospitalier P1) :
    # Cherche parmi toutes les sessions actives un Hospitalier avec aura_active.
    msg_aura = ""
    if degats_finaux > 0 and p.user_id != 0:
        try:
            conn_aura = get_db_connection()
            sessions_rows = conn_aura.execute(
                "SELECT j.user_id FROM sessions s JOIN joueurs j ON j.user_id=s.user_id AND j.nom=s.nom_perso_actif WHERE j.user_id != ?",
                (p.user_id,)
            ).fetchall()
            conn_aura.close()
            for row in sessions_rows:
                p_hosp = Personnage.charger(row['user_id'])
                if (p_hosp and p_hosp.pv_actuel > 0
                        and "ordre_hospitalier" in p_hosp.sous_classes_unlocked
                        and "aura_active" in p_hosp.effets):
                    transfert = 6 if ("passif_hosp_martyr" in p_hosp.competences and p_hosp.pv_actuel <= p_hosp.pv_max * 0.25) else 3
                    transfert = min(transfert, degats_finaux)
                    degats_finaux -= transfert
                    # Rembourser les PV déjà prélevés sur le défenseur
                    p.pv_actuel += transfert
                    p_hosp.pv_actuel -= transfert
                    # Passif Vigilance du Martyr (P1) : +1 Verset par transfert si >20% PV
                    if "passif_hosp_aura" in p_hosp.competences and p_hosp.pv_actuel > p_hosp.pv_max * 0.20:
                        p_hosp.versets = getattr(p_hosp, "versets", 0) + 1
                    # Foi Inébranlable (P2) : coupe l'Aura si l'Hospitalier tombe à 1 PV
                    if "passif_hosp_resilience" in p_hosp.competences and p_hosp.pv_actuel <= 1:
                        del p_hosp.effets["aura_active"]
                    p_hosp.sauvegarder()
                    p.sauvegarder()
                    msg_aura = f"\n✨ **Aura de Sacrifice** : {p_hosp.nom} absorbe {transfert} dégâts pour vous !"
                    break  # Un seul Hospitalier actif à la fois
        except Exception as e:
            print(f"[Aura Hospitalier] Erreur: {e}")

    # Distorsion Permanente (Magie Gravitationnelle P4) : l'attaquant reçoit 1 Lestage
    msg_distorsion = ""
    if not perce_armure:
        attaquant_id = LAST_ATTACKER.get(p.user_id)
        if attaquant_id:
            p_atq = Personnage.charger(attaquant_id)
            if p_atq and "passif_grav_distorsion" in p.competences:
                ajouter_lestage(p_atq, 1, p)
                p_atq.sauvegarder()
                msg_distorsion = f"\n⚫ **Distorsion Permanente** : {p_atq.nom} reçoit 1 Lestage en vous attaquant !"

    pv_pct = p.pv_actuel / p.pv_max if p.pv_max > 0 else 0
    if pv_pct > 0.75:    pv_etat = "🟩 En forme"
    elif pv_pct > 0.50:  pv_etat = "🟨 Légèrement blessé"
    elif pv_pct > 0.25:  pv_etat = "🟧 Sérieusement blessé"
    elif pv_pct > 0:     pv_etat = "🟥 État critique"
    else:                pv_etat = "💀 K.O."
    txt_bilan = f"Dégâts reçus: **{degats_finaux}**\nÉtat: {pv_etat}{msg_gain}"
    embed.add_field(name="Bilan", value=txt_bilan + msg_ko + msg_v4_def + msg_rebond + msg_distorsion + msg_aura, inline=False)
    if msg_ko: embed.color = 0x000000
        
    await log_combat(interaction, embed)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="recitation", description="🙏 (Prêtre) Générer de la Ferveur par la prière")
@app_commands.describe(type_r="Intensité de la prière")
@app_commands.choices(type_r=[
    app_commands.Choice(name="🕯️ Simple (+15 Ferveur)", value="simple"),
    app_commands.Choice(name="📜 Complexe (+30 Ferveur)", value="complexe")
])
async def recitation(interaction: discord.Interaction, type_r: app_commands.Choice[str]):
    p: Personnage = Personnage.charger(interaction.user.id)
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




@bot.tree.command(name="sacrifice", description="🩸 (Vampire Guerrier) Sacrifier des PV pour augmenter les dégâts")
@app_commands.describe(pv_a_sacrifier="PV à convertir en dégâts")
async def sacrifice(interaction: discord.Interaction, pv_a_sacrifier: int):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    
    if p.race != "Vampire" or p.classe != "guerrier":
        return await interaction.response.send_message("🚫 Réservé aux Vampires Guerriers.", ephemeral=True)

    # Limite calculée : 5 de base + 1 tous les 2 niveaux
    limit_max = 5 + (p.niveau // 2)
    
    if pv_a_sacrifier > limit_max:
        return await interaction.response.send_message(f"⚠️ Vous ne pouvez pas sacrifier plus de **{limit_max} PV** à votre niveau.", ephemeral=True)

    if p.pv_actuel <= pv_a_sacrifier:
        return await interaction.response.send_message("💀 Vous ne pouvez pas vous tuer avec ce pouvoir.", ephemeral=True)

    # Application
    p.pv_actuel -= pv_a_sacrifier
    # On stocke le boost dans une variable temporaire sur l'objet (non sauvegardée en DB, tant pis si reboot)
    # Ou mieux : ajoutez une colonne 'temp_boost' en DB si vous voulez de la persistance.
    # Pour l'instant, faisons simple en mémoire :
    p.vampire_boost = pv_a_sacrifier 
    
    p.sauvegarder()
    
    embed = discord.Embed(title="🩸 Sacrifice de Sang", color=0x880000)
    embed.description = f"**{p.nom}** s'entaille la chair !\nChecking : **-{pv_a_sacrifier} PV**\nProchaine attaque : **+{pv_a_sacrifier} Dégâts**"
    await interaction.response.send_message(embed=embed)





#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
# --- COMMANDES UTILITAIRES ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------

@bot.tree.command(name="mode_sang", description="🩸 (Vampire Mage) Activer/Désactiver la priorité aux PV pour les sorts")
async def mode_sang(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    if p.race != "Vampire" or p.classe != "mage":
        return await interaction.response.send_message("🚫 Réservé aux Vampires Mages.", ephemeral=True)

    if "mode_sang" in p.effets:
        del p.effets["mode_sang"]
        etat = "🔵 **DÉSACTIVÉ** (Priorité Mana)"
    else:
        # On met une durée infinie (9999) pour que ça reste tant qu'on ne l'enlève pas
        p.ajouter_effet("mode_sang", 9999, 0)
        etat = "🩸 **ACTIVÉ** (Priorité PV)"

    p.sauvegarder()
    
    embed = discord.Embed(title="🩸 Magie du Sang", description=f"Mode : {etat}\n\n*Si activé, vos sorts consommeront vos PV en priorité, gardant votre Mana pour le bouclier.*", color=0x880000)
    await interaction.response.send_message(embed=embed)


# ========================================================================================
# --- COMMANDES V4 — SOUS-CLASSES ---
# ========================================================================================

@bot.tree.command(name="serment", description="🩸 (Clan du Nord) Activer le Serment du Sang")
async def serment(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    if "clan_nord" not in p.sous_classes_unlocked:
        return await interaction.response.send_message("🚫 Réservé au **Clan du Nord**.", ephemeral=True)
    if p.serment_actif:
        return await interaction.response.send_message("⚠️ Le Serment du Sang est **déjà actif**.", ephemeral=True)

    # --- CONDITION : avoir perdu au moins 40% de ses PV max ---
    seuil_serment = int(p.pv_max * 0.6)
    if p.pv_actuel > seuil_serment:
        pv_manquants = p.pv_actuel - seuil_serment
        return await interaction.response.send_message(
            f"🩸 **Serment refusé.** La Tribu ne jure que dans la douleur.\n"
            f"Vous devez avoir perdu au moins **40% de vos PV** ({int(p.pv_max * 0.4)} PV).\n"
            f"Il vous faut encore perdre **{pv_manquants} PV** avant de pouvoir prononcer le Serment.",
            ephemeral=True
        )

    p.serment_actif = 1
    p.serment_bonus = 0
    msg_bonus = ""
    # Passif Indestructible P5 : +5 PV temporaires à l'activation
    if "passif_nord_indestructible" in p.competences:
        p.pv_actuel = min(p.pv_max, p.pv_actuel + 5)
        msg_bonus = "\n⚡ **L'Indestructible** : +5 PV au Serment !"
    p.sauvegarder()
    embed = discord.Embed(title="🩸 Serment du Sang", color=0x8B0000)
    embed.description = f"**{p.nom}** prononce le Serment du Sang !\nChaque dégât subi renforce vos attaques.{msg_bonus}"
    embed.add_field(name="Règle", value="• Chaque 5 PV perdus → +1 Dégâts permanent (jusqu'à fin combat)\n• Bonus actuel : **{0}**".format(p.serment_bonus), inline=False)
    await log_combat(interaction, embed)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="posture", description="🛡️ (Légion de Fer) Toggle Posture Défensive")
async def posture(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    if "legion_fer" not in p.sous_classes_unlocked:
        return await interaction.response.send_message("🚫 Réservé à la **Légion de Fer**.", ephemeral=True)

    p.posture_active = 1 - p.posture_active
    p.sauvegarder()
    if p.posture_active:
        embed = discord.Embed(title="🛡️ Posture Défensive — ACTIVE", color=0x2980b9)
        embed.description = "Vous adoptez une posture défensive.\n• Robustesse ×2\n• -3 Dégâts en attaque (−1 si passif Implacable)\n• Seuil KO à -10 PV si Muraille de Chair"
    else:
        embed = discord.Embed(title="⚔️ Posture Défensive — Inactive", color=0x7f8c8d)
        embed.description = "Vous abandonnez la posture défensive.\n• Retour en mode offensif."
    await log_combat(interaction, embed)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="sentence", description="📜 (Inquisiteur) Prononcer une Sentence contre une cible")
@app_commands.describe(cible="La cible à Condamner (tapez pour chercher)", crime="Le crime ou transgression (narration)")
@app_commands.autocomplete(cible=perso_cible_autocomplete)
async def sentence(interaction: discord.Interaction, cible: str, crime: str):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    if "inquisiteur" not in p.sous_classes_unlocked:
        return await interaction.response.send_message("🚫 Réservé à l'**Inquisiteur de la Confrérie**.", ephemeral=True)

    # Résolution de la cible depuis l'user_id (string → int)
    try:
        cible_id = int(cible)
    except ValueError:
        return await interaction.response.send_message("❌ Cible invalide. Utilisez l'autocomplétion.", ephemeral=True)
    if cible_id == interaction.user.id:
        return await interaction.response.send_message("❌ Impossible de se Condamner soi-même.", ephemeral=True)

    p_cible = Personnage.charger(cible_id)
    if not p_cible:
        return await interaction.response.send_message("❌ Cette cible n'a pas de fiche.", ephemeral=True)

    # Résolution du membre Discord pour le ping (optionnel)
    membre_cible = interaction.guild.get_member(cible_id) if interaction.guild else None
    cible_mention = membre_cible.mention if membre_cible else f"**{p_cible.nom}**"

    # Plafond sentences simultanées : P3 = 2, P5 = 3, sinon 1
    if "passif_inq_grand" in p.competences: max_sentences = 3
    elif "passif_inq_permanente" in p.competences: max_sentences = 2
    else: max_sentences = 1
    if cible_id not in p.sentence_targets:
        if len(p.sentence_targets) >= max_sentences:
            p.sentence_targets.pop(0)  # Retire la plus ancienne
        p.sentence_targets.append(cible_id)
    p.sentence_target_id = cible_id  # Rétrocompat
    msg_bonus = ""
    # Passif Balance du Confesseur P4 : +15 Ferveur à chaque Sentence
    if "passif_inq_balance" in p.competences:
        p.ferveur += 15
        msg_bonus = "\n⚖️ **Balance du Confesseur** : +15 Ferveur !"
    p.sauvegarder()
    embed = discord.Embed(title="📜 SENTENCE PRONONCÉE", color=0x8e44ad)
    embed.description = f"L'Inquisiteur **{p.nom}** condamne {cible_mention} !"
    embed.add_field(name="🎭 Cible", value=f"**{p_cible.nom}** (Niv {p_cible.niveau} {p_cible.classe.capitalize()})", inline=True)
    embed.add_field(name="⚖️ Crime", value=f"*{crime}*", inline=False)
    embed.add_field(name="Effets", value="• Tous les sorts contre le Condamné : +3 Base\n• Légère Inquisiteur : +5 Base supplémentaires\n• Execute si ≤ 30% PV", inline=False)
    if msg_bonus: embed.set_footer(text=msg_bonus.strip())
    await log_combat(interaction, embed)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="designation", description="🎯 (Loge de l'Ombre) Poser une Désignation sur une cible")
@app_commands.describe(cible="La cible à Désigner (tapez pour chercher)")
@app_commands.autocomplete(cible=perso_cible_autocomplete)
async def designation(interaction: discord.Interaction, cible: str):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    if "loge_ombre" not in p.sous_classes_unlocked:
        return await interaction.response.send_message("🚫 Réservé à la **Loge de l'Ombre**.", ephemeral=True)

    try:
        cible_id = int(cible)
    except ValueError:
        return await interaction.response.send_message("❌ Cible invalide. Utilisez l'autocomplétion.", ephemeral=True)
    if cible_id == interaction.user.id:
        return await interaction.response.send_message("❌ Impossible de se Désigner soi-même.", ephemeral=True)

    p_cible = Personnage.charger(cible_id)
    if not p_cible:
        return await interaction.response.send_message("❌ Cette cible n'a pas de fiche.", ephemeral=True)

    membre_cible = interaction.guild.get_member(cible_id) if interaction.guild else None
    cible_mention = membre_cible.mention if membre_cible else f"**{p_cible.nom}**"

    p.designation_target_id = cible_id
    p.designation_stacks = 1
    p.sauvegarder()
    embed = discord.Embed(title="🎯 Désignation Posée", color=0x1abc9c)
    embed.description = f"**{p.nom}** a marqué {cible_mention} !"
    embed.add_field(name="🎭 Cible", value=f"**{p_cible.nom}** (Niv {p_cible.niveau} {p_cible.classe.capitalize()})", inline=True)
    embed.add_field(name="Effets", value="• +3 Pièces (bonus) sur toutes les attaques via TC\n• Stacks de Désignation : **1**", inline=False)
    await log_combat(interaction, embed)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="mj_presage", description="🔮 [MJ] Valider le résultat d'un Présage Oracle")
@app_commands.describe(joueur="Le joueur Oracle", verdict="Résultat du présage")
@app_commands.choices(verdict=[
    app_commands.Choice(name="✅ Exact (max Ferveur)", value="exact"),
    app_commands.Choice(name="〰️ Partiel (moitié Ferveur)", value="partiel"),
    app_commands.Choice(name="❌ Faux (0 Ferveur)", value="faux"),
])
async def mj_presage(interaction: discord.Interaction, joueur: discord.Member, verdict: app_commands.Choice[str]):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("🚫 Réservé au MJ.", ephemeral=True)

    p: Personnage = Personnage.charger(joueur.id)
    if not p: return await interaction.response.send_message("❌ Joueur sans fiche.", ephemeral=True)
    if "oracle" not in p.sous_classes_unlocked:
        return await interaction.response.send_message("❌ Ce joueur n'est pas un **Oracle**.", ephemeral=True)

    # Calcul du gain selon palier
    if verdict.value == "exact":
        if "passif_oracle_inevitable" in p.competences: gain = 30
        elif "passif_oracle_tisserand" in p.competences: gain = 25
        elif "passif_oracle_futur" in p.competences: gain = 20
        else: gain = 15
    elif verdict.value == "partiel":
        gain = 12 if "passif_oracle_tisserand" in p.competences else 7
    else:
        gain = 0

    p.ferveur += gain
    # Poser le flag _presage_exact pour activer les bonus conditionnels des sorts Oracle
    if verdict.value == "exact":
        # duree:2 pour survivre au /tour du round courant et être actif au tour suivant
        p.effets["_presage_exact"] = {"duree": 999, "valeur": 1}
    else:
        p.effets.pop("_presage_exact", None)
    p.sauvegarder()

    couleur = 0x2ecc71 if verdict.value == "exact" else (0xf39c12 if verdict.value == "partiel" else 0xe74c3c)
    embed = discord.Embed(title="🔮 Validation de Présage", color=couleur)
    embed.description = f"Présage de {joueur.mention} : **{verdict.name}**"
    embed.add_field(name="Récompense", value=f"+**{gain}** Ferveur" if gain > 0 else "Aucune Ferveur gagnée.", inline=False)
    embed.add_field(name="Ferveur Totale", value=f"🙏 **{p.ferveur}**", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="retire_effet", description="Retirer un état (Correction ou Dissipation)")
@app_commands.describe(effet="L'effet à retirer", cible="Joueur cible (Laisser vide pour soi-même)")
@app_commands.choices(effet=[
    app_commands.Choice(name="🧹 TOUT NETTOYER (Reset)", value="all"),
    app_commands.Choice(name="🔥 Brûlure", value="brulure"),
    app_commands.Choice(name="☠️ Poison", value="poison"),
    app_commands.Choice(name="🩸 Hémorragie", value="hemorragie"),
    app_commands.Choice(name="❄️ Gel", value="gel"),
    app_commands.Choice(name="💫 Étourdissement", value="stun"),
    app_commands.Choice(name="🌳 Enracinement", value="root"),
    app_commands.Choice(name="⚡ Hâte", value="hate"),
    app_commands.Choice(name="🌑 Corruption", value="corruption")
])
@app_commands.describe(cible="[Optionnel] Cible via @", cible_fiche="[Optionnel] Cible via nom de fiche (prioritaire)")
@app_commands.autocomplete(cible_fiche=cible_fiche_autocomplete)
async def retire_effet(interaction: discord.Interaction, effet: app_commands.Choice[str], cible: discord.Member = None, cible_fiche: str = None):
    if cible_fiche:
        p = parse_cible_arg(cible_fiche)
        if not p: return await interaction.response.send_message("❌ Fiche introuvable.", ephemeral=True)
    elif cible:
        p = Personnage.charger(cible.id)
        if not p: return await interaction.response.send_message(f"❌ **{cible.display_name}** n'a pas de fiche.", ephemeral=True)
    else:
        p = Personnage.charger(interaction.user.id)
        if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    code = effet.value
    msg = ""

    # 3. Logique de suppression
    if code == "all":
        if not p.effets:
            msg = f"✨ **{p.nom}** n'avait aucun effet actif."
        else:
            p.effets = {} # On vide tout
            msg = f"🛁 **{p.nom}** a été nettoyé de **tous** ses effets."
    
    else:
        if code in p.effets:
            del p.effets[code] # On retire l'effet spécifique
            msg = f"✅ L'effet **{effet.name}** a été retiré de **{p.nom}**."
        else:
            # Petit message discret si l'effet n'était pas là
            msg = f"❌ **{p.nom}** n'avait pas l'effet **{effet.name}** actif."

    # 4. Sauvegarde
    p.sauvegarder()
    
    # On affiche le résultat (visible par tous pour éviter la triche en
    await interaction.response.send_message(msg)



@bot.tree.command(name="meditation", description="🙏 (Prêtre/Mage) Régénération lente (Max 75 Ferveur / Max Mana). CD: 1h.")
@app_commands.checks.cooldown(1, 3600) 
async def meditation(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    msg = ""
    if p.classe == "pretre":
        if p.ferveur >= 75:
            return await interaction.response.send_message("🙏 Votre foi est déjà suffisamment haute (75+). Gardez votre énergie pour le combat.", ephemeral=True)
            
        gain = 30 + (p.sag * 2)
        nouvelle_valeur = min(75, p.ferveur + gain)
        gain_reel = nouvelle_valeur - p.ferveur
        
        p.ferveur = nouvelle_valeur
        msg = f"🙏 **Prière silencieuse...**\n**+{gain_reel} Ferveur** (Total: {p.ferveur})"
    
    elif p.classe == "mage":
        # Le mage remplit son mana (Max Mana natif)
        if p.mana >= p.mana_max:
             return await interaction.response.send_message("🔵 Votre réserve de mana est déjà pleine.", ephemeral=True)

        gain = p.esp + p.int_stat
        p.mana = min(p.mana_max, p.mana + gain)
        msg = f"✨ **Méditation...** .\n**+{gain} Mana**."
    
    else:
        return await interaction.response.send_message("❌ Seuls les classes magiques peuvent méditer.", ephemeral=True)

    p.sauvegarder()
    
    embed = discord.Embed(title="Méditation (1h CD)", description=msg, color=0x3498db)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="echauffement", description="⚔️ (Guerrier) Monter la Tension hors-combat (Max 2). CD: 1h.")
@app_commands.checks.cooldown(1, 3600) # 1 heure
async def echauffement(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    if p.classe != "guerrier":
        return await interaction.response.send_message("❌ Réservé aux Guerriers.", ephemeral=True)

    # LIMITE DE STACK : Max 2 Tension
    if p.tension >= 2:
        return await interaction.response.send_message("⚠️ Vous êtes déjà prêt (Tension 2+). Pas besoin de plus d'échauffement.", ephemeral=True)

    p.tension += 1
    p.sauvegarder()
    
    embed = discord.Embed(title="Échauffement (1h CD)", color=0xe74c3c)
    embed.description = f"**{p.nom}**  !\n**+1 Tension** (Total: {p.tension})"
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="pigeon", description="🐦 Envoyer un message RP à un joueur (Délai 30min).")
@app_commands.describe(joueur="Le destinataire", message="Le contenu de la lettre")
@app_commands.checks.cooldown(1, 1800) # 30 minutes de cooldown entre deux envois
async def pigeon(interaction: discord.Interaction, joueur: discord.Member, message: str):
    p_expediteur: Personnage = Personnage.charger(interaction.user.id)
    nom_expediteur = p_expediteur.nom if p_expediteur else interaction.user.display_name

    embed_depart = discord.Embed(title="🐦 Pigeon envoyé", color=0x2ecc71)
    embed_depart.description = f"Votre message pour **{joueur.display_name}** a été confié à un pigeon voyageur.\n*Durée estimée : 30 minutes.*"
    await interaction.response.send_message(embed=embed_depart, ephemeral=True)

    async def voyage_du_pigeon():
        await asyncio.sleep(1800)

        # Embed destinataire
        embed_recu = discord.Embed(title="📩 Courrier Reçu", color=0xf1c40f)
        embed_recu.set_author(name=f"De : {nom_expediteur}", icon_url=interaction.user.display_avatar.url)
        embed_recu.description = f"📜 *Une lettre arrive pour vous...*\n\n**« {message} »**"
        embed_recu.set_footer(text="Ce message a voyagé 30 minutes.")

        # --- Envoi au destinataire dans son salon privé ---
        salon_id = PIGEON_CHANNELS.get(joueur.id)
        envoye = False
        if salon_id:
            salon = interaction.client.get_channel(salon_id)
            if salon:
                await salon.send(content=joueur.mention, embed=embed_recu)
                envoye = True
        # Fallback MP si pas de salon configuré
        if not envoye:
            try:
                await joueur.send(embed=embed_recu)
            except discord.Forbidden:
                try:
                    await interaction.channel.send(content=joueur.mention, embed=embed_recu)
                except Exception:
                    pass

        # --- Copie aux MJs ---
        embed_mj = discord.Embed(title="📬 Copie MJ — Pigeon Voyageur", color=0x95a5a6)
        embed_mj.description = (
            f"**De :** {nom_expediteur} ({interaction.user.mention})\n"
            f"**À :** {joueur.display_name} ({joueur.mention})\n\n"
            f"**« {message} »**"
        )
        embed_mj.set_footer(text="Copie automatique pour les MJs")

        for gm_id in GM_IDS:
            gm_salon_id = PIGEON_CHANNELS.get(gm_id)
            if gm_salon_id:
                gm_salon = interaction.client.get_channel(gm_salon_id)
                if gm_salon:
                    await gm_salon.send(embed=embed_mj)
                    continue
            try:
                gm_member = interaction.guild.get_member(gm_id)
                if gm_member:
                    await gm_member.send(embed=embed_mj)
            except discord.Forbidden:
                pass

    asyncio.create_task(voyage_du_pigeon())






@bot.tree.command(name="set_stat", description="Modifier manuellement vos stats (Pour appliquer vos Passifs/Bonus)")
@app_commands.describe(stat="La statistique à modifier", valeur="La nouvelle valeur EXACTE")
@app_commands.choices(stat=[
    app_commands.Choice(name="💚 PV Maximum", value="pv_max"),
    app_commands.Choice(name="💚 PV Actuels", value="pv_actuel"),
    app_commands.Choice(name="🔵 Mana Maximum", value="mana_max"),
    app_commands.Choice(name="🔵 Mana Actuel", value="mana"),
    app_commands.Choice(name="🟨 Ferveur", value="ferveur"),
    app_commands.Choice(name="📖 Versets", value="versets"),
    app_commands.Choice(name="🔴 Tension", value="tension"),
    app_commands.Choice(name="💪 Physique (Force)", value="phy"),
    app_commands.Choice(name="🛡️ Constitution", value="const"),
    app_commands.Choice(name="💨 Agilité", value="agi"),
    app_commands.Choice(name="✨ Esprit (Magie)", value="esp"),
    app_commands.Choice(name="🧠 Intelligence", value="int_stat"),
    app_commands.Choice(name="🙏 Foi", value="foi"),
    app_commands.Choice(name="🦉 Sagesse", value="sag"),
    app_commands.Choice(name="🧱 Robustesse (Armure/Items)", value="robustesse"),
    app_commands.Choice(name="🗣️ Oral", value="oral"),
    app_commands.Choice(name="👻 Discrétion", value="discretion"),
    app_commands.Choice(name="🤸 Acrobatie", value="acrobatie"),
    app_commands.Choice(name="💪 Force RP", value="force_rp"),
    app_commands.Choice(name="🏕️ Survie", value="survie"),
    app_commands.Choice(name="⚔️ Bonus Base (items)", value="bonus_base_item"),
    app_commands.Choice(name="🎲 Bonus Pièces (items)", value="bonus_pieces_item"),
    app_commands.Choice(name="💚 Bonus PV Max (items)", value="pv_max_bonus_item"),
    app_commands.Choice(name="🔵 Bonus Mana Max (items)", value="mana_max_bonus_item"),
])
async def set_stat(interaction: discord.Interaction, stat: app_commands.Choice[str], valeur: int):
    # 1. Chargement
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    # 2. Récupération de l'ancienne valeur (pour l'affichage)
    code_stat = stat.value
    ancienne_valeur = getattr(p, code_stat, 0)
    
    # 3. Modification
    # Petite sécurité pour ne pas mettre des PV négatifs par erreur
    if valeur < 0 and "pv" in code_stat:
        valeur = 0

    # Si on modifie mana_max ou pv_max directement, stocker le delta dans bonus_item
    # pour que recalculer_derives le prenne en compte et ne l'écrase pas
    if code_stat == "mana_max":
        p.recalculer_derives()  # calcule la base actuelle
        base_actuelle = p.mana_max
        delta = valeur - base_actuelle
        p.mana_max_bonus_item = getattr(p, 'mana_max_bonus_item', 0) + delta
        p.recalculer_derives()
        code_stat = "mana_max_bonus_item"
        ancienne_valeur = p.mana_max
    elif code_stat == "pv_max":
        p.recalculer_derives()
        base_actuelle = p.pv_max
        delta = valeur - base_actuelle
        p.pv_max_bonus_item = getattr(p, 'pv_max_bonus_item', 0) + delta
        p.recalculer_derives()
        code_stat = "pv_max_bonus_item"
        ancienne_valeur = p.pv_max
    else:
        setattr(p, code_stat, valeur)

    # Si on modifie les PV Max, on ne touche pas aux PV actuels (sauf si actuels > max)
    if p.pv_actuel > p.pv_max:
        p.pv_actuel = p.pv_max
    if p.mana > p.mana_max:
        p.mana = p.mana_max

    # Si on modifie une stat qui affecte les dérivés, recalculer
    if code_stat in ['int_stat', 'sag', 'mana_max_bonus_item', 'pv_max_bonus_item', 'mana_bonus_racial']:
        p.recalculer_derives()
    p.sauvegarder()

    # 4. Confirmation
    embed = discord.Embed(title="✍️ Modification Manuelle", color=0x3498db)
    embed.description = f"**{stat.name}** modifiée."
    embed.add_field(name="Avant", value=str(ancienne_valeur), inline=True)
    embed.add_field(name="Après", value=f"**{valeur}**", inline=True)
    embed.set_footer(text="C'est à vous de tenir vos comptes à jour selon vos passifs !")
    
    await interaction.response.send_message(embed=embed)

    
@bot.tree.command(name="personnalisation", description="Modifier l'apparence de votre fiche de personnage")
@app_commands.describe(alias="Surnom ou Titre (ex: Le Ténébreux)", description="Histoire ou physique (Max 1000 car.)", image_url="Lien direct vers une image (http...)")
async def personnalisation(interaction: discord.Interaction, alias: str = None, description: str = None, image_url: str = None):
    p: Personnage = Personnage.charger(interaction.user.id)
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





# ═══════════════════════════════════════════════════════════════════════════════
# VIEW — Menu déroulant des techniques (affiché depuis /fiche)
# ═══════════════════════════════════════════════════════════════════════════════

class TechniquesSelect(discord.ui.Select):
    def __init__(self, p):
        self.p_data = p

        dons_raciaux = {
            "Elfe": "Sagesse Ancestrale", "Humain": "Adaptabilité", "Nain": "Peau de Pierre",
            "Drakéide": "Sang de Dragon", "Féral": "Instinct Animal", "Céleste": "Grâce Divine",
            "Vampire": "Soif de Sang"
        }

        # Catégories disponibles selon ce que le perso possède
        categories = {}
        if p.race in dons_raciaux:
            categories["🧬 Don Racial"] = [f"🧬 {dons_raciaux[p.race]}"]

        passifs, actifs, bonus_list, soins = [], [], [], []
        for skill_key in p.competences:
            if skill_key not in SKILLS_DB:
                continue
            d = SKILLS_DB[skill_key]
            nom = d["nom"]
            cout = f" ({d['cout']} {d['cout_type']})" if d.get("cout", 0) > 0 else ""
            if d.get("type") == "passif":
                passifs.append(f"🛡️ {nom}")
            elif d.get("type") == "soin":
                soins.append(f"💚 {nom}{cout}")
            elif "(BONUS)" in nom.upper():
                bonus_list.append(f"⚡ {nom}{cout}")
            else:
                actifs.append(f"🔹 {nom}{cout}")

        if passifs:   categories["✨ Passifs"] = passifs
        if actifs:    categories["⚔️ Techniques actives"] = actifs
        if bonus_list:categories["⚡ Actions Bonus"] = bonus_list
        if soins:     categories["💚 Soins"] = soins

        self.categories = categories

        options = [
            discord.SelectOption(label=cat, value=cat, description=f"{len(lst)} élément(s)")
            for cat, lst in categories.items()
        ]
        if not options:
            options = [discord.SelectOption(label="Aucune technique", value="none")]

        super().__init__(
            placeholder="📖 Choisir une catégorie de techniques...",
            min_values=1,
            max_values=1,
            options=options[:25],
        )

    async def callback(self, interaction: discord.Interaction):
        choix = self.values[0]
        if choix == "none":
            return await interaction.response.send_message("Aucune technique enregistrée.", ephemeral=True)
        liste = self.categories.get(choix, [])
        # Découpe en blocs de 1024 chars max (limite Discord field)
        blocs = []
        current = ""
        for ligne in liste:
            if len(current) + len(ligne) + 1 > 1020:
                blocs.append(current)
                current = ligne
            else:
                current += ("\n" if current else "") + ligne
        if current:
            blocs.append(current)

        embed = discord.Embed(title=choix, color=0x9b59b6)
        for i, bloc in enumerate(blocs):
            embed.add_field(name="​" if i > 0 else choix, value=bloc, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class FicheTechniquesView(discord.ui.View):
    def __init__(self, p):
        super().__init__(timeout=120)
        self.add_item(TechniquesSelect(p))


@bot.tree.command(name="fiche", description="Voir votre fiche complète (Design Remasterisé)")
async def fiche(interaction: discord.Interaction):
    # 1. Chargement
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: 
        return await interaction.response.send_message("❌ Pas de fiche. Utilisez **/creation**.", ephemeral=True)
    
    # --- A. COULEURS & AMBIANCE SELON LA CLASSE ---
    # Guerrier = Rouge sang, Mage = Violet mystique, Prêtre = Or divin
    couleurs_classe = {
        "guerrier": 0xe74c3c, 
        "mage": 0x9b59b6,     
        "pretre": 0xf1c40f,
        "monstre": 0x2c3e50
    }
    couleur_embed = couleurs_classe.get(p.classe, 0x95a5a6) # Gris par défaut

   # --- B. TITRE & HEADER ---
    titre_perso = f"📜 {p.nom}"
    if p.alias: titre_perso += f" « {p.alias} »"
    
    # On prépare l'affichage des sous-classes
    txt_sous_classes = ""
    if p.sous_classes_unlocked:
        sc_liste = ", ".join([sc.capitalize() for sc in p.sous_classes_unlocked])
        txt_sous_classes = f"\n**Spécialisations :** {sc_liste}"

    embed = discord.Embed(
        title=titre_perso, 
        description=f"*{p.description}*{txt_sous_classes}", 
        color=couleur_embed
    )
    
    if p.image_url:
        embed.set_thumbnail(url=p.image_url)

    # --- C. FONCTION BARRE DE VIE (Interne) ---
    def draw_bar(actuel, max_val, length=8, c_full="█", c_empty="░"):
        if max_val == 0: return c_empty * length
        pct = max(0, min(1, actuel / max_val))
        fill = int(pct * length)
        return f"{c_full * fill}{c_empty * (length - fill)}"

    # --- D. BLOC ÉTAT VITAL (BARRES) ---
    # On construit l'affichage PV + Ressource
    barre_pv = draw_bar(p.pv_actuel, p.pv_max, 10, "🟩", "⬛")
    txt_vital = f"**PV** {p.pv_actuel}/{p.pv_max}\n`{barre_pv}`"

    txt_ressource = ""
    if p.classe == "guerrier":
        barre_tens = "🔴" * p.tension + "⚫" * (5 - p.tension) # 5 points max visuel
        txt_ressource = f"\n**Tension**\n`{barre_tens}` ({p.tension})"
    elif p.classe == "mage":
        barre_mana = draw_bar(p.mana, p.mana_max, 10, "🟦", "⬛")
        txt_ressource = f"\n**Mana** {p.mana}/{p.mana_max}\n`{barre_mana}`"
    elif p.classe == "pretre":
        # Barre ferveur + Compteur versets
        barre_ferv = draw_bar(p.ferveur, 100, 10, "🟨", "⬛") # Disons 100 max pour l'affichage
        txt_ressource = f"\n**Ferveur** : {p.ferveur} | **Versets** : {p.versets}\n`{barre_ferv}`"

    embed.add_field(name="❤️ État Vital", value=txt_vital + txt_ressource, inline=True)

    # --- E. BLOC STATISTIQUES (FILTRÉ & PROPRE) ---
    stats_box = ""
    if p.classe == "guerrier":
        stats_box = (
            f"```ansi\n"
            f"💪 PHY : {p.phy}\n"
            f"🛡️ CON : {p.const}\n"
            f"💨 AGI : {p.agi}\n"
            f"🧱 ROB : {p.get_robustesse()}\n"
            f"```"
        )
    elif p.classe == "mage":
        stats_box = (
            f"```ansi\n"
            f"✨ ESP : {p.esp}\n"
            f"🧠 INT : {p.int_stat}\n"
            f"💨 AGI : {p.agi}\n"
            f"🧱 ROB : {p.get_robustesse()}\n"
            f"```"
        )
    elif p.classe == "pretre":
        stats_box = (
            f"```ansi\n"
            f"🙏 FOI : {p.foi}\n"
            f"🦉 SAG : {p.sag}\n"
            f"💨 AGI : {p.agi}\n"
            f"🧱 ROB : {p.get_robustesse()}\n"
            f"```"
        )
    
    embed.add_field(name="📊Statistiques", value=stats_box, inline=True)
    
    # --- F. BLOC RP (Mise à jour complète) ---
    rp_txt = (
        f"🗣️ Oral: **{p.oral}** 👻 Discr.: **{p.discretion}**\n"
        f"🤸 Acro: **{p.acrobatie}** 💪 Force: **{p.force_rp}**\n"
        f"🏕️ Surv: **{p.survie}** 💉 Méd.: **{p.medecine}**\n"
        f"⚗️ Sci.: **{p.sciences}** 📜 Hist: **{p.histoire}**\n"
        f"🙏 Rel.: **{p.religion}**"
    )
    embed.add_field(name="🎭Talents ", value=rp_txt, inline=False)

    # --- G. ÉQUIPEMENT ---
    if p.equipement:
        items_txt = []
        icones = {"arme": "⚔️", "collier": "📿", "anneau": "💍", "armure": "🛡️", "cape": "🧥", "ceinture": "🧵"}
        for item in p.equipement:
            ico = icones.get(item['slot'], "🔸")
            items_txt.append(f"{ico} **{item['nom']}**")
        # Bonus items actifs
        bonus_txt = []
        if getattr(p, 'bonus_base_item', 0) > 0:
            bonus_txt.append(f"⚔️ +{p.bonus_base_item} Base (item)")
        if getattr(p, 'bonus_pieces_item', 0) > 0:
            bonus_txt.append(f"🎲 +{p.bonus_pieces_item} Pièces (item)")
        equip_display = " | ".join(items_txt)
        if bonus_txt:
            equip_display += "\n" + " | ".join(bonus_txt)
        embed.add_field(name="Équipements", value=equip_display, inline=False)

    or_p = p.monnaie // 100
    argent_p = (p.monnaie % 100) // 10
    bronze_p = p.monnaie % 10
    embed.add_field(name="💰 Bourse", value=f"**{or_p}** 🥇 | **{argent_p}** 🥈 | **{bronze_p}** 🥉", inline=False)

    # --- H. GRIMOIRE (SORTS) — affiché via menu déroulant ---
    # (Les techniques sont accessibles via le bouton ci-dessous)

    # --- I. TEMPS DE RECHARGE (COOLDOWNS) ---
    if p.cooldowns:
        cds_txt = []
        for ref, tr in p.cooldowns.items():
            sk_cd = SKILLS_DB.get(ref)
            if sk_cd:
                nom_sort = sk_cd['nom']
            else:
                try:
                    conn_cd = get_db_connection()
                    row_cd = conn_cd.execute("SELECT nom FROM config_sorts WHERE ref = ?", (ref,)).fetchone()
                    conn_cd.close()
                    nom_sort = row_cd['nom'] if row_cd else ref
                except Exception:
                    nom_sort = ref
            cds_txt.append(f"⏳ **{nom_sort}** : {tr} tr")
        if cds_txt:
            embed.add_field(name="⏳ Sorts en Recharge", value="\n".join(cds_txt), inline=False)

    # --- J. BADGES RP ---
    if p.badges:
        badges_txt = " • ".join([f"🏅 {b}" for b in p.badges])
        embed.add_field(name="🏅 Titres & Distinctions", value=badges_txt, inline=False)

    # --- FOOTER ---
    total_pts = p.points_stat + p.points_attribut + p.points_comp
    txt_footer = f"Niveau {p.niveau} • {total_pts} points à dépenser"
    # --- J. ÉTATS ACTIFS (Ajout) ---
    if p.effets:
        txt_effets = []
        # On reprend les mêmes icônes que le /tour pour la cohérence
        icones_effets = {
            "brulure": "🔥", "poison": "☠️", "hemorragie": "🩸",
            "gel": "❄️", "stun": "💫", "root": "🌳",
            "hate": "⚡", "corruption": "🌑", "mode_sang": "🩸", "armure": "🛡️"
        }
        
        for code, data in p.effets.items():
            ico = icones_effets.get(code, "❓")
            # On affiche la durée restante
            duree = data['duree']
            # Pour le mode sang ou les effets infinis (9999), on met "Actif"
            duree_txt = f"{duree} tours" if duree < 9000 else "Actif"
            txt_effets.append(f"{ico} **{code.capitalize()}** ({duree_txt})")
            
        embed.add_field(name="🧬 États Actuels", value="\n".join(txt_effets), inline=False)
    embed.set_footer(text=txt_footer, icon_url=interaction.user.display_avatar.url)

    # --- VIEW avec bouton "Voir les techniques" ---
    view = FicheTechniquesView(p)
    await interaction.response.send_message(embed=embed, view=view)




@bot.tree.command(name="creation", description="Créer un personnage")
@app_commands.describe(race="Votre origine détermine vos dons innés")
@app_commands.choices(classe=[
    app_commands.Choice(name="Guerrier", value="Guerrier"),
    app_commands.Choice(name="Mage", value="Mage"),
    app_commands.Choice(name="Prêtre", value="Pretre")
], race=[
    app_commands.Choice(name="Humain (Polyvalent)", value="Humain"),
    app_commands.Choice(name="Elfe (Histoire/Magie)", value="Elfe"),
    app_commands.Choice(name="Nain (Résistance/Artisanat)", value="Nain"),
    app_commands.Choice(name="Drakéide (Dégâts/Intimidation)", value="Drakéide"),
    app_commands.Choice(name="Féral (Instinct/Pistage)", value="Féral"),
    app_commands.Choice(name="Céleste (Soins/Lumière)", value="Céleste"),
    app_commands.Choice(name="Vampire (Vol de vie/Sang)", value="Vampire")
])
async def creation(interaction: discord.Interaction, nom: str, classe: app_commands.Choice[str], race: app_commands.Choice[str]):
    user_id = interaction.user.id
    conn = get_db_connection()
    if conn.execute("SELECT 1 FROM joueurs WHERE user_id = ? AND nom = ?", (user_id, nom)).fetchone():
        conn.close(); return await interaction.response.send_message(f"❌ Nom pris.", ephemeral=True)
    conn.close()

    if race.value == "Vampire" and classe.value == "Pretre":
        return await interaction.response.send_message("🧛🚫 Les **Vampires** ne peuvent pas être Prêtres (Incompatible avec la Foi sacrée).", ephemeral=True)

    try:
        p = Personnage(interaction.user.id, nom, classe.value, race=race.value)
        
        # Dans la commande creation :
        # Sort de base
        skill_base = ""
        if  p.classe == "guerrier": skill_base = "frappe_lourde_novice"
        elif p.classe == "mage": skill_base = "zooltrak_novice"  # 
        else: skill_base = "lumiere_divine"
        # Fallback si la ref exacte n'existe pas en DB
        if skill_base not in SKILLS_DB:
            skill_base = resolve_sort_ref(skill_base)
        if skill_base in SKILLS_DB: p.competences.append(skill_base); p.sauvegarder()
        
        embed = discord.Embed(title="✨ Personnage Créé !", color=0x2ecc71)
        embed.add_field(name="Identité", value=f"**{p.nom}**\n{p.race} {p.classe.capitalize()}", inline=True)
        
        # Affichage du Don unique
        don = RACES_DB[race.value]['don']
        embed.add_field(name="Don Racial", value=don, inline=False)
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"Erreur: {e}", ephemeral=True)




@bot.tree.command(name="fin_combat", description="Reset Tension, Ferveur")
async def fin_combat(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("Pas de fiche.", ephemeral=True)
    msg = ""
    if p.classe == "guerrier":
        tension_base = 1 + (p.niveau // 3) if p.race == "Céleste" else 0
        p.tension = tension_base
        p.fureur_tribale_used = 0  # Reset pour TOUS les guerriers, pas seulement Clan du Nord
        msg += f"💢 Tension réinitialisée à {tension_base}."
    elif p.classe == "pretre":
        p.ferveur = 0
        msg += "🙏 Ferveur à 0."
    
    # Reset mécaniques de sous-classes V1/V2
    if "magie_sang" in p.sous_classes_unlocked and p.festin > 0:
        p.festin = 0
        msg += "\n🩸 **Jauge de Festin** réinitialisée à 0."
    if "magie_elementaire" in p.sous_classes_unlocked and p.charges_elementaires:
        p.charges_elementaires = []
        msg += "\n✨ **Charges Élémentaires** dissipées."
    # Nettoyage flag Décharge active
    p.effets.pop("decharge_active", None)

    # Reset mécaniques V4
    if "ecole_estoc" in p.sous_classes_unlocked:
        p.passe_active = 0; p.parade_absorb = 0; p.passe_count = 0
        msg += "\n⚔️ **École de l'Estoc** : Passe & Parade réinitialisées."
    # Nettoyage flags temporaires inter-combats
    p.effets.pop("_kill_relancer_dispo", None)
    p.effets.pop("_status_si_clash_gagne", None)
    p.effets.pop("_retour_marge_3", None)
    p.effets.pop("_bonus_marquage_avance", None)
    if "clan_nord" in p.sous_classes_unlocked:
        p.serment_bonus = 0; p.serment_actif = 0
        p.effets.pop("_indestructible_used", None)
        msg += "\n🩸 **Clan du Nord** : Serment & Fureur réinitialisés."
    if "moine_lotus" in p.sous_classes_unlocked:
        p.concentre = 1
        msg += "\n🌸 **Moine du Lotus** : Concentration restaurée."
    if "legion_fer" in p.sous_classes_unlocked:
        p.posture_active = 0
        p.effets.pop("_rempart_used", None); p.effets.pop("posture_forcee", None)
        msg += "\n🛡️ **Légion de Fer** : Posture désactivée."
    if "loge_ombre" in p.sous_classes_unlocked:
        # Œil de la Confrérie (P4) : la Désignation persiste entre combats d'une même session
        if "passif_ombre_oeil" not in p.competences:
            p.designation_target_id = 0; p.designation_stacks = 0
            msg += "\n🎯 **Loge de l'Ombre** : Désignation levée."
        else:
            msg += "\n🎯 **Loge de l'Ombre** : Désignation maintenue (Œil de la Confrérie)."
    if "inquisiteur" in p.sous_classes_unlocked:
        p.sentence_target_id = 0; p.sentence_targets = []
        p.effets.pop("_indestructible_used", None)
        msg += "\n📜 **Inquisiteur** : Sentence(s) levée(s)."
    
    
    # Reset cooldowns (en tours de combat — remis à zéro en fin de combat)
    if p.cooldowns:
        p.cooldowns = {}
        msg += "\n⏳ **Cooldowns** remis à zéro."

    # --- LIQUIDATION DES EFFETS DoT RÉSIDUELS ---
    dot_msg = ""
    dot_total = 0
    effets_dot = ["brulure", "hemorragie", "poison"]
    effets_a_suppr = []
    for code in list(p.effets.keys()):
        data = p.effets[code]
        if code == "brulure":
            degats = data.get("valeur", data.get("duree", 0))
            dot_total += degats
            dot_msg += f"\n🔥 **Brûlure** résiduelle : -{degats} PV"
            effets_a_suppr.append(code)
        elif code == "hemorragie":
            valeur = data.get("valeur", 0)
            degats = max(1, valeur // 2)
            dot_total += degats
            dot_msg += f"\n🩸 **Hémorragie** résiduelle : -{degats} PV"
            effets_a_suppr.append(code)
        elif code == "poison":
            malus = (5 + p.niveau) // 5
            dot_msg += f"\n☠️ **Poison** résiduel dissipé (malus {malus} retiré)"
            effets_a_suppr.append(code)
        elif code not in ["_indestructible_used", "_rempart_used", "_kill_relancer_dispo",
                          "_status_si_clash_gagne", "_retour_marge_3", "_bonus_marquage_avance"]:
            effets_a_suppr.append(code)

    for code in effets_a_suppr:
        p.effets.pop(code, None)

    if dot_total > 0:
        p.pv_actuel = max(0, p.pv_actuel - dot_total)
        dot_msg += f"\n💥 **Total dégâts de fin** : -{dot_total} PV"

    if dot_msg:
        msg += f"\n\n**☠️ Effets résiduels liquidés :**{dot_msg}"

    p.sauvegarder()
    embed = discord.Embed(title="Fin de Combat", description=msg, color=0x95a5a6)
    if COMBAT_STATS:
        lignes_stats = []
        for uid, st in sorted(COMBAT_STATS.items(), key=lambda x: -x[1]["degats_infliges"]):
            nm = st["nom"] or f"#{uid}"
            lignes_stats.append(
                f"**{nm}** — ⚔️ {st['degats_infliges']} infligés | 🛡️ {st['degats_recus']} reçus | 💚 {st['soins']} soins"
            )
        embed.add_field(name="📊 Stats du Combat", value="\n".join(lignes_stats), inline=False)
        COMBAT_STATS.clear()
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="repos", description="Récupération totale (PV, Mana, Versets)")
async def repos(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("Pas de fiche.", ephemeral=True)
    
    p.recalculer_derives()  # Recalcule versets_max, mana_max, pv_max avant de les utiliser
    p.pv_actuel = p.pv_max
    
    if p.mode_entrainement:
        p.mode_entrainement = 0
        p.snapshot_entrainement = None
    
    if p.classe == "mage": p.mana = p.mana_max
    elif p.classe == "pretre": p.ferveur = 0; p.versets = p.versets_max
    elif p.classe == "guerrier":
        p.tension = 1 + (p.niveau // 3) if p.race == "Céleste" else 0

    # Reset des effets de statut (un repos long soigne tout)
    effets_a_effacer = ["brulure", "poison", "hemorragie", "gel", "stun", "root",
                        "corruption", "mutilation", "no_regen"]
    for e in effets_a_effacer:
        p.effets.pop(e, None)

    # Reset des flags de combat (fureur, serment, etc.)
    p.fureur_tribale_used = 0
    if "clan_nord" in p.sous_classes_unlocked:
        p.serment_actif = 0; p.serment_bonus = 0
    if "moine_lotus" in p.sous_classes_unlocked:
        p.concentre = 1
    if "legion_fer" in p.sous_classes_unlocked:
        p.posture_active = 0
        p.effets.pop("_rempart_used", None); p.effets.pop("posture_forcee", None)
    if "loge_ombre" in p.sous_classes_unlocked:
        p.designation_target_id = 0; p.designation_stacks = 0
    if "inquisiteur" in p.sous_classes_unlocked:
        p.sentence_target_id = 0; p.sentence_targets = []
    if "ecole_estoc" in p.sous_classes_unlocked:
        p.passe_active = 0; p.parade_absorb = 0; p.passe_count = 0
    if "magie_sang" in p.sous_classes_unlocked:
        p.festin = 0
    if "magie_elementaire" in p.sous_classes_unlocked:
        p.charges_elementaires = []
    
    p.sauvegarder()
    await interaction.response.send_message("💤 **Repos Long** : PV, Ressources, Effets et États de combat restaurés.")


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
    stats_txt = f"Base: {s['base']} | Bonus: +{s['bonus']}/coin | coins: {s['coins']} , stats : ({s['stat_type'].upper()})"
    embed.add_field(name="⚙️ Infos Techniques", value=f"**Type:** {s.get('type', 'Actif').capitalize()}\n**Pallier:** {s['pallier']}\n**Coût:** {cout_txt}", inline=True)
    embed.add_field(name="🎲 Dégâts / Effet", value=stats_txt, inline=False)
    req_txt = f"Classe: {', '.join(s['classes']).capitalize()}"
    if s.get('cat') == 'spe': req_txt += "\nSPÉCIALISATION (Sous-classe)"
    embed.add_field(name="🔒 Pré-requis", value=req_txt, inline=True)
    await interaction.response.send_message(embed=embed)

@grimoire.autocomplete('nom')
async def grimoire_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    # Le MJ voit tout, le joueur ne voit que ses sorts appris
    is_mj = is_gm(user_id)
    p = Personnage.charger(user_id)
    
    choix = []
    for k, v in SKILLS_DB.items():
        if not is_mj:
            if not p or k not in p.competences:
                continue # Cache le sort s'il n'est pas appris
            
        if current.lower() in v['nom'].lower():
            choix.append(app_commands.Choice(name=v['nom'], value=k))
            
    return choix[:25]

async def apprendre_autocomplete(interaction: discord.Interaction, current: str):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return []
    
    choix = []
    for k, v in SKILLS_DB.items():
        if k in p.competences: continue  # déjà connu

        cat = v.get('cat', 'tronc')
        classes_brutes = v.get('classes', [])
        if isinstance(classes_brutes, str):
            try: classes_list = json.loads(classes_brutes)
            except: classes_list = []
        else:
            classes_list = classes_brutes
        if isinstance(classes_list, str):
            try: classes_list = json.loads(classes_list)
            except: classes_list = []

        if cat == 'spe':
            # Visible seulement si la sous-classe est débloquée
            if not any(sc in p.sous_classes_unlocked for sc in classes_list):
                continue
        elif cat == 'tronc':
            # Visible seulement si la classe correspond
            if p.classe not in classes_list:
                continue
        elif cat == 'monstre':
            # Sorts freestyle : jamais achetables via /apprendre (donnés par GM)
            continue
        # autres cats (ex: spe custom) : affichés si sous-classe débloquée
        else:
            if classes_list and not any(sc in p.sous_classes_unlocked for sc in classes_list):
                continue

        if current.lower() in v['nom'].lower():
            choix.append(app_commands.Choice(name=f"[P{v['pallier']}] {v['nom']}", value=k))

    return choix[:25]





@bot.tree.command(name="jet_attributs", description="🎲 Faire un test de compétence RP (Oral, Sciences, etc.)")
@app_commands.describe(attribut="L'attribut à tester", difficulte="Difficulté à battre (Défaut 50)")
@app_commands.choices(attribut=[
    app_commands.Choice(name="🤸 Acrobatie (Saut/Équilibre)", value="acrobatie"),
    app_commands.Choice(name="🗣️ Oral (Convaincre/Mentir)", value="oral"),
    app_commands.Choice(name="💪 Force RP (Soulever,...)", value="force_rp"),
    app_commands.Choice(name="👻 Discrétion (Se cacher/Voler)", value="discretion"),
    app_commands.Choice(name="🏕️ Survie (Pistage/Nature/analyse de l'environnement)", value="survie"),
    app_commands.Choice(name="📜 Histoire (Savoir/Légendes)", value="histoire"),
    app_commands.Choice(name="⚗️ Sciences (Magie théorique/Ingénierie)", value="sciences"),
    app_commands.Choice(name="💉 Médecine (Soins/Anatomie)", value="medecine"),
    app_commands.Choice(name="🙏 Religion (Dieux/Démons)", value="religion")
])
async def jet_attributs(interaction: discord.Interaction, attribut: app_commands.Choice[str], difficulte: int = 50):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    # Récupération de la valeur (ex: 3)
    valeur_attr = getattr(p, attribut.value, 0)
    bonus = valeur_attr * 7
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


@bot.tree.command(name="help", description="📚 Afficher la liste complète et à jour des commandes")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="📚 Grimoire du Voyageur", description="Guide des commandes et règles v3.", color=0x3498db)
    
    # 1. BASES & EQUIPEMENT
    txt_bases = (
        "`/creation` : Créer votre personnage (7 Races dispos)\n"
        "`/fiche` : Voir votre fiche complète (Stats & RP)\n"
        "`/inventaire` : Voir votre sac et équipement\n"
        "`/equiper [ID]` / `/desequiper [ID]` : Gérer vos objets\n"
        "`/repos` : Récupération totale (PV, Mana)\n"
        "`/personnalisation` : Modifier image/description/alias\n"
        "`/mes_persos` : Changer de personnage actif\n"
        "`/set_stat` : Modifier manuellement vos stats (Passifs)"
    )
    embed.add_field(name="🎒 Bases & Gestion", value=txt_bases, inline=False)

    # 2. COMBAT & ACTIONS
    txt_combat = (
        "`/tour` : **Début de tour** (HUD, Initiative, Effets)\n"
        "`/attaque` : Attaque simple sur une cible\n"
        "`/clash` : Provoquer un duel (L'adversaire doit Riposter)\n"
        "`/riposte` : Répondre à un Clash\n"
        "`/defense` : Réagir à une attaque (Tank ou Esquive)\n"
        "`/action_bonus` : Action rapide (Buff/Soin personnel)\n"
        "`/soigner` : Lancer un sort de soin sur autrui\n"
        "`/appliquer` : Infliger un effet (Brûlure, Poison...)\n"
        "`/recitation` : (Prêtre) Générer de la Ferveur\n"
        "`/sacrifice` : (Vampire) Convertir PV en Dégâts\n"
        "`/fin_combat` : Reset immédiat (Tension/Ferveur)"
    )
    embed.add_field(name="⚔️ Système de Combat", value=txt_combat, inline=False)

    # 3. GLOSSAIRE DES EFFETS (Mis à jour)
    txt_effets = (
        "🔥 **Brûlure** : Dégâts fixes début de tour.\n"
        "☠️ **Poison** : Malus aux jets `-(5 + Niv/5)`.\n"
        "🩸 **Hémorragie** : Dégâts début tour + Dégâts si vous attaquez.\n"
        "🌑 **Corruption** : Draine ressources. Contagieux au soin.\n"
        "❄️ **Gel** : Passe tour (Défense OK). Prochain coup **x1.5**.\n"
        "💫 **Étourdi** : Passe tour. **Aucune défense**.\n"
        "🌳 **Enraciné** : Agilité réduite à 0.\n"
        "⚡ **Hâte** : Avantage sur le prochain jet."
    )
    embed.add_field(name="🧬 États & Altérations", value=txt_effets, inline=False)

    # 4. PROGRESSION
    txt_prog = (
        "`/ameliorer` : Monter une stat (Physique, Esprit...)\n"
        "`/ameliorer_attribut` : Monter une stat RP (Oral, Survie...)\n"
        "`/apprendre` : Acheter une compétence (Règle Pyramide)\n"
        "`/debloquer_specialisation` : Ouvrir une sous-classe\n"
        "`/voir_voie` : Voir l'arbre de talents d'une classe\n"
        "`/grimoire` : Lire les détails techniques d'un sort\n"
        "`/jet_attributs` : Faire un test de dés (RP hors combat)"
    )
    embed.add_field(name="📈 Évolution", value=txt_prog, inline=False)

    # 5. UTILITAIRES
    txt_util = (
        "`/entrainement` : Mode sans risque (Sauvegarde stats)\n"
        "`/fin_entrainement` : Récupérer ses stats d'avant"
    )
    embed.add_field(name="Divers", value=txt_util, inline=False)

    # 6. GM (Admin)
    txt_gm = (
        "`/gm_incarner` / `/gm_creer` : Gestion PNJ\n"
        "`/gm_levelup` : Faire monter un niveau\n"
        "`/gm_effet` : Appliquer un état (Admin)\n"
        "`/gm_set_stat` : Forcer une stat (Boss)\n"
        "`/gm_give_item` / `_spell` / `_points` : Dons\n"
        "`/gm_creer_item` / `_sort` / `_spe` : Configuration\n"
        "`/gm_reset_combats` : Débloquer les clashs qui bugent"
    )
    embed.add_field(name="🔧 Commandes MJ", value=txt_gm, inline=False)

    embed.set_footer(text="Frieren RPG Bot • v3.2 (Final Update)")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)





@bot.tree.command(name="inventaire", description="Voir votre sac et équipement")
async def inventaire(interaction: discord.Interaction):
    user_id = interaction.user.id
    p = Personnage.charger(user_id)
    conn = get_db_connection()

    items = conn.execute('''
        SELECT i.id, i.equipe, i.identifie,
               c.nom, c.slot, c.description, c.rarete, c.points_limite, c.necessite_etude
        FROM inventaire i
        JOIN config_items c ON i.item_ref = c.ref
        WHERE i.user_id = ?
        ORDER BY i.equipe DESC, c.slot
    ''', (user_id,)).fetchall()
    conn.close()

    if not items:
        return await interaction.response.send_message("🎒 Votre sac est vide.", ephemeral=True)

    RARETE_EMOJI = {"commun":"⚪","peu_commun":"🟢","rare":"🔵","epique":"🟣","legendaire":"🟠"}
    RARETE_POINTS = {"commun":5,"peu_commun":10,"rare":15,"epique":25,"legendaire":40}
    SLOT_ICONES = {"arme":"⚔️","collier":"📿","anneau":"💍","armure":"🛡️","cape":"🧥","ceinture":"🧵",
                   "chapeau":"🎩","gants":"🧤","bottes":"👢"}

    pts_max = (p.niveau * 5) if p else 0
    pts_util = 0
    txt_equip = ""
    txt_sac = ""

    for item in items:
        pts = item['points_limite'] or RARETE_POINTS.get(item['rarete'], 5)
        em_rare = RARETE_EMOJI.get(item['rarete'], "⚪")
        em_slot = SLOT_ICONES.get(item['slot'], "🔸")
        id_str = f"ID:{item['id']}"

        if not item['identifie'] and item['necessite_etude']:
            ligne = f"• **???** {em_slot} *(Non identifié — `/etudier {item['id']}`)* [{id_str}]\n  *Description cachée jusqu'à identification complète.*\n"
        else:
            ligne = f"• **{item['nom']}** {em_rare}{em_slot} — {pts}pts [{id_str}]\n  *{item['description']}*\n"

        if item['equipe']:
            pts_util += pts
            txt_equip += ligne
        else:
            txt_sac += ligne

    embed = discord.Embed(title="🎒 Inventaire", color=0xe67e22)
    embed.add_field(name="⚔️ Équipement Porté", value=txt_equip or "Rien.", inline=False)
    embed.add_field(name="🎒 Dans le sac", value=txt_sac or "Vide.", inline=False)
    if p:
        barre = "█" * int((pts_util/pts_max)*10) + "░" * (10-int((pts_util/pts_max)*10)) if pts_max else "░"*10
        embed.add_field(name="⚖️ Jauge de Limite", value=f"`{barre}` **{pts_util}/{pts_max}** pts (Niv.{p.niveau}×5)", inline=False)
    embed.set_footer(text="/equiper [ID] • /desequiper [ID] • /etudier [ID]")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="equiper", description="Équiper un objet (Gère automatiquement les slots)")
@app_commands.describe(item_id="Le numéro ID visible dans /inventaire")
async def equiper(interaction: discord.Interaction, item_id: int):
    user_id = interaction.user.id
    p = Personnage.charger(user_id)
    if not p:
        return await interaction.response.send_message("❌ Pas de fiche active.", ephemeral=True)

    conn = get_db_connection()
    target = conn.execute('''
        SELECT i.id, i.item_ref, i.equipe, i.identifie,
               c.nom, c.slot, c.description, c.rarete, c.bonus_json, c.points_limite, c.necessite_etude
        FROM inventaire i
        JOIN config_items c ON i.item_ref = c.ref
        WHERE i.id = ? AND i.user_id = ?
    ''', (item_id, user_id)).fetchone()

    if not target:
        conn.close()
        return await interaction.response.send_message("❌ Objet introuvable dans votre inventaire.", ephemeral=True)

    if target['equipe'] == 1:
        conn.close()
        return await interaction.response.send_message("⚠️ Cet objet est déjà équipé.", ephemeral=True)

    # Vérif étude
    if target['necessite_etude'] and not target['identifie']:
        conn.close()
        return await interaction.response.send_message(
            "🔍 Cet objet n'a pas encore été identifié. Utilisez `/etudier` pour le déchiffrer.", ephemeral=True)

    # Vérif limite de points
    RARETE_POINTS = {"commun": 5, "peu_commun": 10, "rare": 15, "epique": 25, "legendaire": 40}
    pts_item = target['points_limite'] or RARETE_POINTS.get(target['rarete'], 5)
    pts_max = p.niveau * 5

    # Calculer les points déjà utilisés
    equipes = conn.execute('''
        SELECT c.points_limite, c.rarete
        FROM inventaire i JOIN config_items c ON i.item_ref = c.ref
        WHERE i.user_id = ? AND i.equipe = 1
    ''', (user_id,)).fetchall()
    pts_utilises = sum(row['points_limite'] or RARETE_POINTS.get(row['rarete'], 5) for row in equipes)

    if pts_utilises + pts_item > pts_max:
        conn.close()
        RARETE_EMOJI = {"commun":"⚪","peu_commun":"🟢","rare":"🔵","epique":"🟣","legendaire":"🟠"}
        return await interaction.response.send_message(
            f"⚠️ **Limite d'équipement atteinte !**\n"
            f"Jauge : **{pts_utilises}/{pts_max}** pts (niveau {p.niveau} × 5)\n"
            f"Cet item coûte **{pts_item} pts** {RARETE_EMOJI.get(target['rarete'],'⚪')} — il vous manque {pts_item-(pts_max-pts_utilises)} pts.",
            ephemeral=True)

    slot_vise = target['slot']
    SLOT_LIMITS = {"arme":1,"collier":1,"anneau":2,"armure":1,"cape":1,"ceinture":1,"chapeau":1,"gants":1,"bottes":1}
    limit = SLOT_LIMITS.get(slot_vise, 1)

    items_equipes_slot = conn.execute('''
        SELECT i.id FROM inventaire i JOIN config_items c ON i.item_ref = c.ref
        WHERE i.user_id = ? AND i.equipe = 1 AND c.slot = ?
    ''', (user_id, slot_vise)).fetchall()

    msg_retrait = ""
    if len(items_equipes_slot) >= limit:
        if slot_vise == "anneau" and len(items_equipes_slot) >= 2:
            conn.close()
            return await interaction.response.send_message("✋ Déjà 2 anneaux équipés. Déséquipez-en un d'abord.", ephemeral=True)
        else:
            conn.execute('''
                UPDATE inventaire SET equipe = 0
                WHERE user_id = ? AND equipe = 1 AND item_ref IN (SELECT ref FROM config_items WHERE slot = ?)
            ''', (user_id, slot_vise))
            msg_retrait = "\n*(Ancien objet déséquipé automatiquement)*"

    conn.execute("UPDATE inventaire SET equipe = 1 WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

    RARETE_EMOJI = {"commun":"⚪","peu_commun":"🟢","rare":"🔵","epique":"🟣","legendaire":"🟠"}
    embed = discord.Embed(title="⚔️ Équipement mis à jour", color=0x2ecc71)
    embed.description = f"Vous avez équipé **{target['nom']}** {RARETE_EMOJI.get(target['rarete'],'⚪')}.{msg_retrait}"
    embed.add_field(name="Effet", value=target['description'], inline=False)
    embed.add_field(name="Jauge de limite", value=f"**{pts_utilises+pts_item}/{pts_max}** pts utilisés", inline=True)
    embed.set_footer(text="Les bonus sont appliqués automatiquement au recalcul de vos stats.")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="desequiper", description="Retirer un objet")
@app_commands.describe(item_id="Le numéro ID visible dans /inventaire")
async def desequiper(interaction: discord.Interaction, item_id: int):
    user_id = interaction.user.id
    conn = get_db_connection()
    
    check = conn.execute("SELECT equipe, item_ref FROM inventaire WHERE id = ? AND user_id = ?", (item_id, user_id)).fetchone()
    
    if not check:
        conn.close()
        return await interaction.response.send_message("❌ Objet introuvable.", ephemeral=True)
    
    if check['equipe'] == 0:
        conn.close()
        return await interaction.response.send_message("⚠️ Cet objet est déjà dans votre sac.", ephemeral=True)

    conn.execute("UPDATE inventaire SET equipe = 0 WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    
    await interaction.response.send_message("🎒 Objet déséquipé.")



@bot.tree.command(name="equipement", description="🎒 Voir et gérer votre équipement par slots")
async def equipement(interaction: discord.Interaction):
    user_id = interaction.user.id
    p = Personnage.charger(user_id)
    if not p:
        return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    conn = get_db_connection()
    items = conn.execute("""
        SELECT i.id, c.ref, c.nom, c.slot, c.description, i.equipe, i.identifie, c.necessite_etude
        FROM inventaire i
        JOIN config_items c ON i.item_ref = c.ref
        WHERE i.user_id = ?
        ORDER BY c.slot, i.equipe DESC
    """, (user_id,)).fetchall()
    conn.close()

    SLOTS = [
        ("arme",     "⚔️",  "Arme",             1),
        ("chapeau",  "🎩",  "Chapeau",           1),
        ("armure",   "🛡️",  "Armure",            1),
        ("gants",    "🧤",  "Gants",             1),
        ("bottes",   "👢",  "Bottes",            1),
        ("collier",  "📿",  "Collier/Amulette",  1),
        ("anneau",   "💍",  "Bague/Anneau",      2),
        ("cape",     "🧥",  "Cape",              1),
        ("ceinture", "🧵",  "Ceinture",          1),
    ]

    # Indexer les items par slot
    items_par_slot = {}
    items_sac = []
    for item in items:
        slot = item['slot']
        if slot not in items_par_slot:
            items_par_slot[slot] = {"equipes": [], "sac": []}
        if item['equipe'] == 1:
            items_par_slot[slot]["equipes"].append(item)
        else:
            items_sac.append(item)

    # --- EMBED PRINCIPAL ---
    embed = discord.Embed(title=f"🧳 Équipement de {p.nom}", color=0xe67e22)

    # Slots équipés
    slots_txt = ""
    for slot_key, ico, slot_nom, max_slots in SLOTS:
        data = items_par_slot.get(slot_key, {"equipes": [], "sac": []})
        equipes = data["equipes"]
        if equipes:
            for it in equipes:
                nom_aff = "???" if (it['necessite_etude'] and not it['identifie']) else it['nom']
                slots_txt += f"{ico} **{slot_nom}** : {nom_aff} *(ID {it['id']})*\n"
        else:
            slots_txt += f"{ico} **{slot_nom}** : *— vide —*\n"

    embed.add_field(name="⚔️ Objets Équipés", value=slots_txt, inline=False)

    # Sac
    if items_sac:
        sac_txt = ""
        for it in items_sac:
            ico_sac = {"arme":"⚔️","collier":"📿","anneau":"💍","armure":"🛡️","cape":"🧥","ceinture":"🧵",
                       "chapeau":"🎩","gants":"🧤","bottes":"👢"}.get(it['slot'], "🔸")
            if it['necessite_etude'] and not it['identifie']:
                sac_txt += f"{ico_sac} **???** *(ID {it['id']})* — *Description cachée — `/etudier {it['id']}`*\n"
            else:
                sac_txt += f"{ico_sac} **{it['nom']}** *(ID {it['id']})* — {it['description']}\n"
        embed.add_field(name="🎒 Dans le sac", value=sac_txt, inline=False)
    else:
        embed.add_field(name="🎒 Dans le sac", value="*Vide.*", inline=False)

    # --- MENUS DÉROULANTS ---
    class EquipView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            # Menu Équiper — items dans le sac
            if items_sac:
                options_equip = [
                    discord.SelectOption(
                        label=f"{'???' if (it['necessite_etude'] and not it['identifie']) else it['nom']} ({it['slot']})",
                        value=str(it['id']),
                        description="Non identifié — /etudier requis" if (it['necessite_etude'] and not it['identifie']) else (it['description'][:100] if it['description'] else ""),
                        emoji={"arme":"⚔️","collier":"📿","anneau":"💍","armure":"🛡️","cape":"🧥","ceinture":"🧵",
                               "chapeau":"🎩","gants":"🧤","bottes":"👢"}.get(it['slot'], "🔸")
                    )
                    for it in items_sac[:25]
                ]
                self.add_item(EquipSelect(options_equip))

            # Menu Déséquiper — items équipés
            items_equipes = [it for it in items if it['equipe'] == 1]
            if items_equipes:
                options_desequip = [
                    discord.SelectOption(
                        label=f"Retirer : {it['nom']} ({it['slot']})",
                        value=str(it['id']),
                        emoji={"arme":"⚔️","collier":"📿","anneau":"💍","armure":"🛡️","cape":"🧥","ceinture":"🧵"}.get(it['slot'], "🔸")
                    )
                    for it in items_equipes[:25]
                ]
                self.add_item(DesequipSelect(options_desequip))

    class EquipSelect(discord.ui.Select):
        def __init__(self, options):
            super().__init__(placeholder="✅ Équiper un objet...", options=options, row=0)

        async def callback(self, interaction: discord.Interaction):
            item_id = int(self.values[0])
            conn2 = get_db_connection()
            target = conn2.execute("""
                SELECT i.item_ref, c.slot, c.nom, c.description, i.equipe
                FROM inventaire i JOIN config_items c ON i.item_ref = c.ref
                WHERE i.id = ? AND i.user_id = ?
            """, (item_id, interaction.user.id)).fetchone()

            if not target:
                conn2.close()
                return await interaction.response.send_message("❌ Objet introuvable.", ephemeral=True)

            slot_vise = target['slot']
            limit = 2 if slot_vise == "anneau" else 1
            count = conn2.execute("""
                SELECT COUNT(*) FROM inventaire i
                JOIN config_items c ON i.item_ref = c.ref
                WHERE i.user_id = ? AND i.equipe = 1 AND c.slot = ?
            """, (interaction.user.id, slot_vise)).fetchone()[0]

            if count >= limit:
                if slot_vise == "anneau":
                    conn2.close()
                    return await interaction.response.send_message("✋ 2 anneaux déjà équipés. Retirez-en un d'abord.", ephemeral=True)
                else:
                    conn2.execute("""
                        UPDATE inventaire SET equipe = 0
                        WHERE user_id = ? AND equipe = 1
                        AND item_ref IN (SELECT ref FROM config_items WHERE slot = ?)
                    """, (interaction.user.id, slot_vise))

            conn2.execute("UPDATE inventaire SET equipe = 1 WHERE id = ?", (item_id,))
            conn2.commit()
            conn2.close()
            await interaction.response.send_message(f"✅ **{target['nom']}** équipé !\n⚠️ Ajustez vos stats avec `/set_stat` si besoin.", ephemeral=True)

    class DesequipSelect(discord.ui.Select):
        def __init__(self, options):
            super().__init__(placeholder="❌ Retirer un objet équipé...", options=options, row=1)

        async def callback(self, interaction: discord.Interaction):
            item_id = int(self.values[0])
            conn2 = get_db_connection()
            target = conn2.execute("""
                SELECT c.nom FROM inventaire i JOIN config_items c ON i.item_ref = c.ref
                WHERE i.id = ? AND i.user_id = ?
            """, (item_id, interaction.user.id)).fetchone()
            if not target:
                conn2.close()
                return await interaction.response.send_message("❌ Objet introuvable.", ephemeral=True)
            conn2.execute("UPDATE inventaire SET equipe = 0 WHERE id = ?", (item_id,))
            conn2.commit()
            conn2.close()
            await interaction.response.send_message(f"🎒 **{target['nom']}** retiré.", ephemeral=True)

    has_items = len(items) > 0
    view = EquipView() if has_items else None
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)




#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
# --- COMMANDES D'AMÉLIORATION ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------

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
    p: Personnage = Personnage.charger(interaction.user.id)
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
    app_commands.Choice(name="🤸 Acrobatie (Saut/Équilibre)", value="acrobatie"),
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
    p: Personnage = Personnage.charger(interaction.user.id)
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





@bot.tree.command(name="apprendre", description="Acheter une compétence")
@app_commands.describe(competence="Nom de la compétence")
@app_commands.autocomplete(competence=apprendre_autocomplete)
async def apprendre(interaction: discord.Interaction, competence: str):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    if competence not in SKILLS_DB: return await interaction.response.send_message("❌ Sort introuvable.", ephemeral=True)
    
    skill = SKILLS_DB[competence]
    pallier_vise = skill['pallier']
    cat = skill.get('cat', 'tronc')
    
    # 1. GESTION DU COÛT
    cout_reclamé = pallier_vise
    if p.points_comp < cout_reclamé:
        return await interaction.response.send_message(f"❌ **Pas assez de points**. Coût : **{cout_reclamé}** (Dispo: {p.points_comp}).", ephemeral=True)

    if competence in p.competences:
        return await interaction.response.send_message("⚠️ Vous connaissez déjà ce sort.", ephemeral=True)

    # 2. VÉRIFICATION DES CONDITIONS (Progression Unifiée)
    
    # A. Vérification de l'accès à la classe / sous-classe
    if cat == "spe":
        classes_spe = skill.get('classes', [])
        if not classes_spe:
            return await interaction.response.send_message("❌ Sort sans classe définie.", ephemeral=True)
        nom_arbre = classes_spe[0]
        if nom_arbre not in p.sous_classes_unlocked:
            return await interaction.response.send_message(f"🔒 Arbre **{nom_arbre.capitalize()}** verrouillé. Utilisez `/debloquer_specialisation`.", ephemeral=True)
    elif cat == "tronc":
        if p.classe not in skill.get('classes', []):
             return await interaction.response.send_message(f"🚫 Réservé aux {skill.get('classes', ['?'])[0]}.", ephemeral=True)

    # B. Règle de la Pyramide Unifiée (Mélange Tronc + Spé)
    if pallier_vise > 1:
        nb_requis = 3
        compteur_prev = 0
        
        for s_key in p.competences:
            if s_key in SKILLS_DB:
                s_data = SKILLS_DB[s_key]
                # On cherche les sorts du pallier exactement en-dessous
                if s_data['pallier'] == (pallier_vise - 1):
                    # On vérifie que c'est bien un sort valide (Tronc de sa classe OU Spé débloquée)
                    if s_data.get('cat') == 'tronc' and p.classe in s_data.get('classes', []):
                        compteur_prev += 1
                    elif s_data.get('cat') == 'spe' and any(sc in p.sous_classes_unlocked for sc in s_data.get('classes', [])):
                        compteur_prev += 1

        if compteur_prev < nb_requis:
            return await interaction.response.send_message(
                f"🔒 **Bases insuffisantes !**\nIl vous faut **{nb_requis}** sorts du Pallier {pallier_vise-1} (mix Tronc Commun et/ou Spécialisation) pour débloquer le Pallier {pallier_vise}. Vous en avez actuellement {compteur_prev}.", 
                ephemeral=True
            )

    # 3. ACHAT ET SAUVEGARDE
    p.points_comp -= cout_reclamé
    p.competences.append(competence)
    
    # Bonus Passif Auto (inchangé)
    msg_bonus = ""
    if cat == "spe":
        nom_arbre = skill['classes'][0]
        passif_a_donner = None
        for ref, data in SKILLS_DB.items():
            if (data.get('cat') == 'spe' and data['classes'][0] == nom_arbre and data['pallier'] == pallier_vise and data['type'] == 'passif'):
                passif_a_donner = ref
                break 
        if passif_a_donner and passif_a_donner not in p.competences:
            p.competences.append(passif_a_donner)
            msg_bonus = f"\n🎁 **Passif offert :** {SKILLS_DB[passif_a_donner]['nom']}."

    p.sauvegarder()
    await interaction.response.send_message(f"✅ **{skill['nom']}** (P{pallier_vise}) appris !{msg_bonus}")


#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
# --- COMMANDES GM ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------


@bot.tree.command(name="gm_hud", description="(GM) Tableau de bord combat — PV/ressources/effets de tous les combattants")
async def gm_hud(interaction: discord.Interaction):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    await interaction.response.defer()
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT j.user_id, j.nom, j.classe, j.niveau,
               j.pv_actuel, j.pv_max, j.mana, j.mana_max,
               j.tension, j.ferveur, j.effets, j.cooldowns, j.const, j.robustesse
        FROM sessions s
        JOIN joueurs j ON j.user_id = s.user_id AND j.nom = s.nom_perso_actif
        ORDER BY j.nom
    """).fetchall()
    conn.close()
    if not rows:
        return await interaction.followup.send("❌ Aucun personnage en session.", ephemeral=True)

    def bar(cur, mx, n=8):
        if mx <= 0: return "░" * n
        f = round(max(0, cur) / mx * n)
        pct = max(0, cur) / mx
        ico = "🟩" if pct > 0.5 else ("🟨" if pct > 0.25 else "🟥")
        return ico * f + "⬛" * (n - f)

    ICONES = {"brulure":"🔥","poison":"☠️","hemorragie":"🩸","gel":"❄️","stun":"💫","root":"🌳","hate":"⚡","corruption":"🌑","armure":"🛡️"}
    CLASSE_ICO = {"guerrier":"⚔️","mage":"🔮","pretre":"🙏","monstre":"👹"}

    embed = discord.Embed(title="📊 HUD Combat", color=0x2C3E50)
    embed.set_footer(text=f"{len(rows)} combattant(s) en session • /gm_hud pour rafraîchir")

    for r in rows:
        try: effets = json.loads(r['effets']) if r['effets'] else {}
        except: effets = {}
        try: cooldowns = json.loads(r['cooldowns']) if r['cooldowns'] else {}
        except: cooldowns = {}

        pv_cur = r['pv_actuel']; pv_max = r['pv_max']
        barre = bar(pv_cur, pv_max)
        pct = round(max(0, pv_cur) / pv_max * 100) if pv_max > 0 else 0
        classe = r['classe']

        if classe == "guerrier":
            rob = (r['robustesse'] or 0) + (r['const'] or 0)
            res = f"💢 Tension: **{r['tension']}** | 🧱 Rob: {rob}"
        elif classe == "mage":
            res = f"🔵 Mana: **{r['mana']}/{r['mana_max']}**"
        elif classe == "pretre":
            res = f"🟨 Ferveur: **{r['ferveur']}**"
        else:
            res = f"🔵 Mana: **{r['mana']}/{r['mana_max']}**"

        effets_txt = " ".join(
            f"{ICONES.get(c,'❓')}{('∞' if d.get('duree',0)>=9000 else str(d.get('duree',0))+'t')}"
            for c, d in effets.items() if not c.startswith("_")
        )
        cds_txt_parts = []
        for ref, tr in cooldowns.items():
            sk = SKILLS_DB.get(ref)
            if sk:
                nm_cd = sk['nom'][:12]
            else:
                try:
                    conn_c = get_db_connection()
                    row_c = conn_c.execute("SELECT nom FROM config_sorts WHERE ref=?", (ref,)).fetchone()
                    conn_c.close()
                    nm_cd = (row_c['nom'][:12] if row_c else ref[:10])
                except: nm_cd = ref[:10]
            cds_txt_parts.append(f"⏳{nm_cd}({tr}t)")

        cs = COMBAT_STATS.get(r['user_id'], {})
        stats_txt = f" | ⚔️{cs.get('degats_infliges',0)} 🛡️{cs.get('degats_recus',0)} 💚{cs.get('soins',0)}" if cs else ""

        ko = "💀 " if pv_cur <= 0 else ""
        lines = [f"`{barre}` **{pv_cur}/{pv_max}** ({pct}%){stats_txt}", res]
        if effets_txt: lines.append("États: " + effets_txt)
        if cds_txt_parts: lines.append("CD: " + " ".join(cds_txt_parts))

        embed.add_field(
            name=f"{ko}{CLASSE_ICO.get(classe,'👤')} {r['nom']} (Niv {r['niveau']})",
            value="\n".join(lines),
            inline=False
        )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="gm_reset_combats", description="(GM) Vide la mémoire des clashs en attente en cas de bug/AFK.")
async def gm_reset_combats(interaction: discord.Interaction):
    if not is_gm(interaction.user.id): 
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    
    nb = len(PENDING_CLASHES)
    PENDING_CLASHES.clear()
    await interaction.response.send_message(f"✅ **{nb} clash(s)** en attente effacé(s). File de combat vidée.", ephemeral=True)


@bot.tree.command(name="gm_respec", description="(GM) Remplace une spécialisation, oublie ses sorts et rembourse les Points de Compétence.")
@app_commands.describe(
    joueur="Le joueur à modifier", 
    ancienne_spe="La spé à oublier (ex: ordre hospitalier)",
    nouvelle_spe="La nouvelle spé (ex: magie gravitationnelle)"
)
async def gm_respec(interaction: discord.Interaction, joueur: discord.Member, ancienne_spe: str, nouvelle_spe: str):
    # 1. Sécurité GM
    if not is_gm(interaction.user.id): 
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    p = Personnage.charger(joueur.id)
    if not p:
        return await interaction.response.send_message("❌ Ce joueur n'a pas de fiche.", ephemeral=True)

    ancienne_spe = ancienne_spe.lower()
    nouvelle_spe = nouvelle_spe.lower()

    if ancienne_spe not in p.sous_classes_unlocked:
        return await interaction.response.send_message(f"❌ **{p.nom}** ne possède pas la spécialisation **{ancienne_spe}**.", ephemeral=True)

    points_rembourses = 0
    sorts_a_oublier = []

    for sort_id in list(p.competences):
        if sort_id in SKILLS_DB:
            info_sort = SKILLS_DB[sort_id]
            classes_autorisees = [c.lower() for c in info_sort.get("classes", [])]
            
            if info_sort.get("cat") == "spe" and ancienne_spe in classes_autorisees:
                sorts_a_oublier.append(sort_id)
                # Les passifs sont offerts gratuitement à l'achat → pas de remboursement
                if info_sort.get("type") != "passif":
                    points_rembourses += info_sort.get("pallier", 1)


    for sort_id in sorts_a_oublier:
        p.competences.remove(sort_id)


    p.sous_classes_unlocked.remove(ancienne_spe)
    if nouvelle_spe not in p.sous_classes_unlocked:
        p.sous_classes_unlocked.append(nouvelle_spe)
    p.points_comp += points_rembourses 
    p.sauvegarder()
    embed = discord.Embed(title="Respécialisation Réussie", color=0x3498DB)
    embed.description = f"Le MJ a fait oublier la voie **{ancienne_spe.capitalize()}** à {joueur.mention} pour lui accorder **{nouvelle_spe.capitalize()}** !"

    if sorts_a_oublier:
        noms_sorts = [SKILLS_DB[s]["nom"] for s in sorts_a_oublier]
        embed.add_field(name="Sorts oubliés", value=", ".join(noms_sorts), inline=False)
        
    embed.add_field(name="Points Remboursés", value=f"**+{points_rembourses}** Points de Compétence\n(Total actuel: {p.points_comp})", inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="gm_spawn", description="(GM) Générer un Monstre ou PNJ prêt au combat")
@app_commands.describe(nom="Nom du PNJ", niveau="Niveau de puissance", classe="Classe et style de défense")
@app_commands.choices(classe=[
    app_commands.Choice(name="👹 Monstre-Guerrier (Utilise sa Constitution pour Tanker)", value="Monstre-Guerrier"),
    app_commands.Choice(name="👹 Monstre-Mage (Utilise son Mana pour Tanker)", value="Monstre-Mage"),
    app_commands.Choice(name="👹 Monstre-Prêtre (Ferveur)", value="Monstre-Pretre"),
    app_commands.Choice(name="👤 Humain-Guerrier", value="Humain-Guerrier"),
    app_commands.Choice(name="👤 Humain-Mage", value="Humain-Mage")
])
async def gm_spawn(interaction: discord.Interaction, nom: str, niveau: int, classe: app_commands.Choice[str]):
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    await interaction.response.defer()

    # --- 1. CONFIGURATION AUTOMATIQUE ---
    val_classe = classe.value
    race_defaut = "Monstre" if "Monstre" in val_classe else "Humain"
    classe_mecanique = val_classe.split("-")[1].lower() # Récupère "guerrier", "mage" ou "pretre"
    
    conn = get_db_connection()
    conn.execute("DELETE FROM joueurs WHERE user_id = ? AND nom = ?", (interaction.user.id, nom))
    conn.commit()

    # --- 2. CRÉATION ---
    p = Personnage(interaction.user.id, nom, classe_mecanique, race=race_defaut)
    p.niveau = niveau

    # --- 3. POINTS DE STATS MANUELS ---
    # Au lieu de répartir aléatoirement, on stocke les points pour le MJ.
    # (Ex: Niveau 10 = 30 points à distribuer)
    points_a_distribuer = niveau * 3
    p.points_stat += points_a_distribuer

    # --- 4. APPRENTISSAGE DES SORTS ---
    learned_log = []
    pallier_max = (niveau // 3) + 1 
    
    for ref, data in SKILLS_DB.items():
        classes_sort = data.get('classes', [])
        cat_sort = data.get('cat', 'tronc')
        
        eligible = False
        if race_defaut == "Monstre" and ("monstre" in classes_sort or cat_sort == "monstre"):
            eligible = True
        if classe_mecanique in classes_sort and cat_sort == "tronc":
            eligible = True
            
        if eligible and data['pallier'] <= pallier_max:
            if ref not in p.competences:
                p.competences.append(ref)
                learned_log.append(data['nom'])

    # --- 5. FINALISATION ---
    p.recalculer_derives()
    if race_defaut == "Monstre":
        p.pv_max += (niveau * 5)
        p.mana_max += (niveau * 2)

    p.pv_actuel = p.pv_max
    if p.classe == "mage": p.mana = p.mana_max
    if p.classe == "pretre": p.versets = p.versets_max
    
    session_mj = conn.execute('SELECT nom_perso_actif FROM sessions WHERE user_id = ?', (interaction.user.id,)).fetchone()
    conn.commit()
    conn.close()
    p.sauvegarder()
    if session_mj:
        conn_r = get_db_connection()
        conn_r.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (interaction.user.id, session_mj['nom_perso_actif']))
        conn_r.commit(); conn_r.close()

    # --- 6. AFFICHAGE ---
    embed = discord.Embed(title=f"👹 {nom} Généré !", color=0x800000 if race_defaut == "Monstre" else 0x3498db)
    embed.description = f"**Niveau {niveau} | {classe.name}**\n*Utilise les règles défensives du {classe_mecanique.capitalize()}.*\n\n⚠️ **Vous avez {p.points_stat} points de stats à répartir !**"
    
    stats_resume = f"💪 PHY: **{p.phy}** 🛡️ CON: **{p.const}** 💨 AGI: **{p.agi}**\n✨ ESP: **{p.esp}** 🧠 INT: **{p.int_stat}** 🦉 SAG: **{p.sag}**"
    embed.add_field(name="📊 Statistiques de base", value=stats_resume, inline=False)
    
    status_resume = f"💚 **{p.pv_max} PV**"
    if p.mana_max > 0: status_resume += f" | 🔵 **{p.mana_max} Mana**"
    embed.add_field(name="État Vital Actuel", value=status_resume, inline=True)
    
    embed.add_field(name="📚 Grimoire", value=f"**{len(learned_log)}** techniques apprises automatiquement.", inline=False)
    embed.set_footer(text="Utilisez /ameliorer pour dépenser ses points de stats manuellement !")
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="gm_add_boss_skill", description="(GM) Créer une compétence de Boss avec stats précises")
@app_commands.describe(
    nom="Nom de l'attaque", 
    description="Description de l'effet", 
    base="Dégâts garantis (Base)", 
    pieces="Nombre de pièces à lancer",
    bonus="Dégâts par pièce réussie",
    stat="Statistique utilisée"
)
@app_commands.choices(stat=[
    app_commands.Choice(name="Physique (Force)", value="phy"),
    app_commands.Choice(name="Esprit (Magie)", value="esp"),
    app_commands.Choice(name="Agilité", value="agi"),
    app_commands.Choice(name="Brut (Aucune stat)", value="aucune")
])
async def gm_add_boss_skill(interaction: discord.Interaction, nom: str, description: str, base: int, pieces: int, bonus: int, stat: app_commands.Choice[str]):
    # Sécurité
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Incarnez d'abord le Boss.", ephemeral=True)

    # CORRECTION ICI : On utilise l'ID de l'interaction Discord pour l'unicité (plus besoin d'import time)
    unique_id = f"boss_{interaction.id}"
    
    stat_code = stat.value if stat else "phy"
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO config_sorts 
        (ref, nom, classes, pallier, cout_achat, base, coins, bonus, stat_type, cout, cout_type, desc, type, cat)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        unique_id, nom, '["monstre"]', 1, 0, 
        base, pieces, bonus, stat_code, 0, "mana", 
        description, "actif", "monstre"
    ))
    conn.commit()
    conn.close()
    
    reload_data()
    
    if unique_id not in p.competences:
        p.competences.append(unique_id)
        p.sauvegarder()

    embed = discord.Embed(title="👹 Technique de Boss Acquise", color=0x2c3e50)
    embed.description = f"**{p.nom}** a appris **{nom}** !"
    # Affichage de la formule mathématique pour vérification
    formule = f"{base} + ({pieces} x {bonus}) + {stat.name}"
    embed.add_field(name="Détails", value=f"📜 *{description}*\n🎲 **Formule :** `{formule}`", inline=False)
    
    await interaction.response.send_message(embed=embed)



@bot.tree.command(name="gm_freestyle", description="(GM) Créer une attaque sur mesure et l'ajouter à un personnage")
@app_commands.describe(
    nom="Nom de l'attaque (ex: Souffle Ardent)", 
    description="Narration", 
    base="Dégâts de base", pieces="Nombre de dés", bonus="Dégâts par dé", 
    stat="Stat utilisée",
    effet_type="Ajouter un statut spécial à l'attaque ?",
    effet_val="Puissance de l'effet (ex: 2 pour Brûlure 2)",
    zone="L'attaque touche-t-elle plusieurs personnes (AoE) ?",
    cooldown_tours="Cooldown en tours de combat (0 = aucun)",
    cible_fiche="[Optionnel] Donner le sort à une fiche spécifique (sinon : votre personnage actif)",
    type_sort="Type du sort : Actif (attaque) ou Bonus (action bonus, utilitaire)"
)
@app_commands.choices(stat=[
    app_commands.Choice(name="Physique", value="phy"),
    app_commands.Choice(name="Esprit", value="esp"),
    app_commands.Choice(name="Agilité", value="agi"),
    app_commands.Choice(name="Foi", value="foi"),
    app_commands.Choice(name="Brut (Aucune stat)", value="aucune")
], effet_type=[
    app_commands.Choice(name="🔥 Brûlure", value="brulure"),
    app_commands.Choice(name="☠️ Poison", value="poison"),
    app_commands.Choice(name="🩸 Hémorragie", value="hemorragie"),
    app_commands.Choice(name="💫 Étourdissement", value="stun"),
    app_commands.Choice(name="🌳 Enracinement", value="root"),
    app_commands.Choice(name="🦴 Mutilation", value="mutilation")
], type_sort=[
    app_commands.Choice(name="⚔️ Actif (apparaît dans /attaque et /clash)", value="actif"),
    app_commands.Choice(name="⚡ Bonus (apparaît dans /action_bonus)", value="bonus"),
])
@app_commands.autocomplete(cible_fiche=cible_fiche_autocomplete)
async def gm_freestyle(
    interaction: discord.Interaction, 
    nom: str, description: str, base: int, pieces: int, bonus: int, 
    stat: app_commands.Choice[str], 
    effet_type: app_commands.Choice[str] = None, effet_val: int = 1, zone: bool = False, cooldown_tours: int = 0,
    cible_fiche: str = None, type_sort: app_commands.Choice[str] = None
):
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    # Déterminer le personnage cible
    if cible_fiche:
        p_cible = parse_cible_arg(cible_fiche)
        if not p_cible:
            return await interaction.response.send_message("❌ Fiche introuvable.", ephemeral=True)
    else:
        p_cible = Personnage.charger(interaction.user.id)
        if not p_cible:
            return await interaction.response.send_message("❌ Incarnez d'abord un personnage avec /gm_spawn, ou précisez une cible_fiche.", ephemeral=True)

    # Déterminer le type et le nom affiché
    is_bonus = type_sort and type_sort.value == "bonus"
    sort_type = "utilitaire" if is_bonus else "actif"
    # Les sorts bonus doivent avoir "(Bonus)" dans le nom pour apparaître dans /action_bonus
    nom_final = nom if not is_bonus else (nom if "(Bonus)" in nom or "(BONUS)" in nom else f"{nom} (Bonus)")

    # 1. Générer une ID unique
    unique_id = f"free_{int(time.time())}"
    stat_code = stat.value if stat else "aucune"

    # 2. Construction du JSON des effets (automatique)
    data_effets = {}
    if effet_type:
        seuil_moyen = max(1, pieces // 2)
        data_effets["seuil"] = seuil_moyen
        data_effets["status"] = {effet_type.value: effet_val}
    if zone:
        data_effets["aoe"] = True
        
    json_str = json.dumps(data_effets)

    # 3. Sauvegarde dans le Grimoire global
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO config_sorts 
        (ref, nom, classes, pallier, cout_achat, base, coins, bonus, stat_type, cout, cout_type, cooldown, desc, type, cat, data_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        unique_id, nom_final, '["monstre"]', 1, 0, 
        base, pieces, bonus, stat_code, 0, "mana",
        cooldown_tours,
        description, sort_type, "monstre", json_str
    ))
    conn.commit()
    conn.close()
    
    reload_data()
    
    # 4. Ajout à la fiche cible
    p_cible = parse_cible_arg(cible_fiche) if cible_fiche else Personnage.charger(interaction.user.id)
    if p_cible:
        p_cible.competences.append(unique_id)
        p_cible.sauvegarder()

    # 5. Affichage
    if is_bonus:
        embed = discord.Embed(title="⚡ Sort Bonus Créé & Équipé !", color=0x00FFFF)
        embed.description = f"**{p_cible.nom}** a appris **{nom_final}**.\n*Disponible dans `/action_bonus`.*"
    else:
        embed = discord.Embed(title="⚡ Compétence Créée & Équipée !", color=0xE67E22)
        embed.description = f"**{p_cible.nom}** a appris l'attaque **{nom_final}**.\n*Elle est désormais dans l'autocomplétion de `/clash` et `/attaque`.*"
    
    details = f"🎲 **Formule :** Base {base} + ({pieces}x{bonus}) + {stat.name}\n"
    if effet_type: 
        details += f"✨ **Effet :** {effet_type.name} ({effet_val})\n"
    if zone:
        details += "💥 **Zone :** Touche plusieurs cibles\n"
    if cooldown_tours > 0:
        details += f"⏳ **Cooldown :** {cooldown_tours} tours\n"
    details += f"📋 **Type :** {'⚡ Bonus (action_bonus)' if is_bonus else '⚔️ Actif (attaque/clash)'}"
    embed.add_field(name="Paramètres", value=details, inline=False)
    embed.add_field(name="Narration", value=f"*{description}*", inline=False)
    
    await interaction.response.send_message(embed=embed)



        
@bot.tree.command(name="gm_effet", description="(GM) Appliquer un état (Puissance optionnelle, défaut +1)")
@app_commands.describe(joueur="[Optionnel] Cible via @", cible_fiche="[Optionnel] Cible via nom de fiche (prioritaire)", effet="Type", duree="Tours", puissance="Puissance (Défaut: 1)")
@app_commands.autocomplete(cible_fiche=cible_fiche_autocomplete)
@app_commands.choices(effet=[
    app_commands.Choice(name="🔥 Brûlure", value="brulure"),
    app_commands.Choice(name="☠️ Poison", value="poison"),
    app_commands.Choice(name="🩸 Hémorragie", value="hemorragie"),
    app_commands.Choice(name="❄️ Gel", value="gel"),
    app_commands.Choice(name="💫 Étourdissement", value="stun"),
    app_commands.Choice(name="🌳 Enracinement", value="root"),
    app_commands.Choice(name="🌑 Corruption", value="corruption"),
    app_commands.Choice(name="⚡ Hâte", value="hate"),
])
async def gm_effet(interaction: discord.Interaction, effet: app_commands.Choice[str], duree: int, joueur: discord.Member = None, cible_fiche: str = None, puissance: int = 1):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    if cible_fiche:
        p = parse_cible_arg(cible_fiche)
    elif joueur:
        p = Personnage.charger(joueur.id)
    else:
        return await interaction.response.send_message("❌ Précisez une cible (@ ou nom de fiche).", ephemeral=True)
    if not p:
        return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    p.ajouter_effet(effet.value, duree, puissance) 
    p.sauvegarder()

    n_duree = p.effets[effet.value]["duree"]
    n_valeur = p.effets[effet.value]["valeur"]

    await interaction.response.send_message(f"✅ **{effet.name}** sur **{p.nom}** → Durée: {n_duree} | X: {n_valeur}")

@bot.tree.command(name="gm_incarner", description="(GM) Prendre le contrôle d'un PNJ existant")
@app_commands.describe(nom="Nom exact du PNJ")
@app_commands.autocomplete(nom=my_perso_autocomplete)
async def gm_incarner(interaction: discord.Interaction, nom: str):
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

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
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

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
        session_mj2 = conn.execute('SELECT nom_perso_actif FROM sessions WHERE user_id = ?', (user_id,)).fetchone()
        conn.commit(); conn.close()
        p.sauvegarder()
        if session_mj2:
            conn_r2 = get_db_connection()
            conn_r2.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)', (user_id, session_mj2['nom_perso_actif']))
            conn_r2.commit(); conn_r2.close()
        await interaction.response.send_message(f"👹 PNJ **{p.nom}** créé ! Utilisez `/gm_incarner` pour l'incarner.")
    except Exception as e:
        await interaction.response.send_message(f"Erreur: {e}", ephemeral=True)


@bot.tree.command(name="gm_levelup", description="(GM) Faire monter un joueur de niveau")
@app_commands.describe(joueur="Le joueur à level up", niveaux="Nombre de niveaux (défaut 1)")
async def gm_levelup(interaction: discord.Interaction, joueur: discord.Member, niveaux: int = 1):
    if not is_gm(interaction.user.id): 
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    p = Personnage.charger(joueur.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    ancien_niv = p.niveau
    anciens_pv = p.pv_max
    anciens_mana = p.mana_max
    
    p.niveau += niveaux
    # On récupère les messages d'évolution avant de sauvegarder
    msg_race = p.verifier_evolution_race(niveaux)
    
    p.points_stat += (1 * niveaux)
    p.points_attribut += (1 * niveaux)
    p.points_comp += (1 * niveaux)
    
    p.recalculer_derives()
    p.pv_actuel = p.pv_max
    p.sauvegarder()

    embed = discord.Embed(title="🎉 LEVEL UP !", description=f"Félicitations {joueur.mention} !", color=0xF1C40F)
    embed.add_field(name="Niveau", value=f"{ancien_niv} ➔ **{p.niveau}**", inline=False)
    
    if msg_race:
        embed.add_field(name="🧬 Évolution", value=msg_race, inline=False)
    
    embed.add_field(name="Points Gagnés", value=f"💪 Stats: +{niveaux}\n🧠 Attr: +{niveaux}\n✨ Comp: +{niveaux}", inline=True)
    await interaction.response.send_message(content=f"{joueur.mention}", embed=embed)



@bot.tree.command(name="gm_set_stat", description="(GM) Forcer une statistique à une valeur précise (Pour Monstres/Boss)")
@app_commands.describe(stat="La stat à modifier", valeur="La valeur exacte", cible_fiche="[Optionnel] Fiche cible (MJ actif si vide)")
@app_commands.autocomplete(cible_fiche=cible_fiche_autocomplete)
@app_commands.choices(stat=[
    app_commands.Choice(name="💚 PV Max", value="pv_max"),
    app_commands.Choice(name="💚 PV Actuels", value="pv_actuel"),
    app_commands.Choice(name="🔵 Mana Max", value="mana_max"),
    app_commands.Choice(name="💪 Physique (Force)", value="phy"),
    app_commands.Choice(name="🛡️ Constitution", value="const"),
    app_commands.Choice(name="💨 Agilité", value="agi"),
    app_commands.Choice(name="✨ Esprit", value="esp"),
    app_commands.Choice(name="🧠 Intelligence", value="int_stat"),
    app_commands.Choice(name="🧱 Robustesse (Armure/Items)", value="robustesse"),
    app_commands.Choice(name="⚔️ Bonus Base (items)", value="bonus_base_item"),
    app_commands.Choice(name="🎲 Bonus Pièces (items)", value="bonus_pieces_item"),
    app_commands.Choice(name="💚 Bonus PV Max (items)", value="pv_max_bonus_item"),
    app_commands.Choice(name="🔵 Bonus Mana Max (items)", value="mana_max_bonus_item"),
])
async def gm_set_stat(interaction: discord.Interaction, stat: app_commands.Choice[str], valeur: int, cible_fiche: str = None):
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    if cible_fiche:
        p = parse_cible_arg(cible_fiche)
        if not p: return await interaction.response.send_message("❌ Fiche introuvable.", ephemeral=True)
    else:
        p: Personnage = Personnage.charger(interaction.user.id)
        if not p: return await interaction.response.send_message("❌ Incarnez un personnage ou précisez une cible_fiche.", ephemeral=True)

    code_stat = stat.value
    
    # Modification directe
    setattr(p, code_stat, valeur)
    
    # Si on change les PV Max, on remet les PV actuels au max aussi pour être sympa
    if code_stat == "pv_max":
        p.pv_actuel = valeur

    p.sauvegarder()

    embed = discord.Embed(title="🔧 Modification GM", color=0x95a5a6)
    embed.description = f"La stat **{stat.name}** de **{p.nom}** est maintenant fixée à **{valeur}**."
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="gm_creer_sort", description="(GM) Créer sort/passif (Options spécifiques Prêtre incluses)")
@app_commands.describe(
    ref="Code unique (ex: soin_majeur)", 
    nom="Nom affiché", 
    classe="Classe principale",
    type_sort="Type de capacité",
    pallier="Niveau (1, 2...)",
    description="Description",
    # Optionnels
    cout="Coût (Mana pour Mage / Tension pour Guerrier / Ferveur pour Prêtre)",
    versets="(Prêtre) Nombre de versets requis/consommés",
    specialisation="Sous-classe (si nécessaire)",
    base="Dégâts/Soin de base", 
    coins="Nb pièces", 
    bonus="Bonus par pièce", 
    stat="Statistique utilisée"
)
@app_commands.autocomplete(classe=classe_autocomplete, stat=stat_autocomplete, specialisation=spe_autocomplete)
@app_commands.choices(visibilite=[
    app_commands.Choice(name="Tronc Commun", value="tronc"),
    app_commands.Choice(name="Spécialisation", value="spe"),
    app_commands.Choice(name="Monstre", value="monstre")
], type_sort=[
    app_commands.Choice(name="⚔️ Attaque / Actif", value="actif"),
    app_commands.Choice(name="🛡️ Passif", value="passif"),
    app_commands.Choice(name="💚 Soin", value="soin")
])
async def gm_creer_sort(
    interaction: discord.Interaction, 
    visibilite: app_commands.Choice[str],
    type_sort: app_commands.Choice[str],
    ref: str, 
    nom: str, 
    classe: str, 
    pallier: int, 
    description: str,
    # Arguments Optionnels
    cout: int = 0,
    versets: int = 0, # <--- NOUVEAU CHAMP
    cooldown: int = 0,
    specialisation: str = None,
    base: int = 0, 
    coins: int = 0, 
    bonus: int = 0, 
    stat: str = None
):
    # Sécurité GM
    if not is_gm(interaction.user.id): 
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    cat = visibilite.value
    classes_list = []
    
    # 1. Gestion Classes
    if cat == "monstre": classes_list = ["monstre"]
    elif cat == "spe":
        if not specialisation: return await interaction.response.send_message("❌ Spécialisation requise.", ephemeral=True)
        classes_list = [specialisation.lower()]
    else: classes_list = [classe.lower()]

    # 2. Gestion Prêtre & Coûts
    cout_type = "mana" # Défaut
    classe_lower = classe.lower()

    if "guerrier" in classe_lower: 
        cout_type = "tension"
    elif "pretre" in classe_lower: 
        cout_type = "ferveur" 
        # Si c'est un prêtre, 'cout' devient automatiquement de la Ferveur.
    
    # Si c'est un passif, on nettoie les stats de combat
    stat_db = stat if stat else "phy"
    if type_sort.value == "passif":
        base = 0; coins = 0; bonus = 0; stat_db = "aucune"
        # On garde cout et versets car certains passifs puissants pourraient avoir un pré-requis
    else:
        if not stat: return await interaction.response.send_message("❌ Précisez la statistique pour un Actif/Soin.", ephemeral=True)

    # 3. Sauvegarde
    conn = get_db_connection()
    try:
        # Notez l'ajout de la colonne 'versets' dans la requête
        conn.execute('''
            INSERT OR REPLACE INTO config_sorts 
            (ref, nom, classes, pallier, cout_achat, base, coins, bonus, stat_type, cout, cout_type, versets, cooldown, desc, type, cat)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ref.lower(), nom, json.dumps(classes_list), pallier, 1, 
            base, coins, bonus, stat_db, cout, cout_type, versets, cooldown, description, 
            type_sort.value, cat
        ))
        conn.commit()
        reload_data()
        
        # Confirmation visuelle
        embed = discord.Embed(title="✅ Compétence Enregistrée", color=0x2ecc71)
        embed.add_field(name="Nom", value=f"{nom} ({type_sort.name})", inline=True)
        
        cout_txt = f"{cout} {cout_type.capitalize()}"
        if versets > 0: cout_txt += f" + {versets} Versets"
        if cooldown > 0: cout_txt += f" + {cooldown} tours de recharge"
        embed.add_field(name="Coût / Requis", value=cout_txt, inline=True)
        embed.description = f"**{classe}** (P{pallier})\n{description}"
            
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur SQL : {e}", ephemeral=True)
    finally:
        conn.close()



@bot.tree.command(name="voir_voie", description="Voir tous les sorts d'une classe (Tronc + Spécialisations)")
@app_commands.describe(classe="La classe à inspecter")
@app_commands.autocomplete(classe=classe_autocomplete)
async def voir_voie(interaction: discord.Interaction, classe: str):
    classe_input = classe.lower()
    p: Personnage = Personnage.charger(interaction.user.id)
    unlocked_list = p.sous_classes_unlocked if p else []

    conn = get_db_connection()
    # On récupère les descriptions des spés existantes
    sous_classes_db = conn.execute("SELECT nom, description FROM config_sous_classes").fetchall()
    info_sous_classes = {row['nom']: row['description'] for row in sous_classes_db}
    
    # On récupère TOUS les sorts
    tous_sorts = conn.execute("SELECT * FROM config_sorts ORDER BY pallier ASC").fetchall()
    conn.close()

    # --- Tri des données ---
    sorts_tronc = []
    sorts_par_spe = {}

    for row in tous_sorts:
        sort = dict(row)
        try: sort_classes = json.loads(sort['classes'])
        except (json.JSONDecodeError, TypeError): continue

        # Formatage de la ligne de sort
        txt_cout = f"[{sort['cout']} {sort['cout_type']}]" if sort['cout'] > 0 else ""
        if sort['type'] == 'passif':
            ligne = f"🛡️ **[{sort['pallier']}] {sort['nom']}**\n*{sort['desc']}*"
        else:
            stats = f"({sort['base']} + {sort['coins']}x{sort['bonus']} {sort['stat_type'].upper()})"
            ligne = f"🔹 **[{sort['pallier']}] {sort['nom']}** {txt_cout}\n{stats} *{sort['desc']}*"

        if sort['cat'] == 'tronc' and classe_input in sort_classes:
            sorts_tronc.append(ligne)
        elif sort['cat'] == 'spe':
            for sc in sort_classes:
                if sc not in sorts_par_spe: sorts_par_spe[sc] = []
                sorts_par_spe[sc].append(ligne)

    # --- Création des Embeds (Découpage pour éviter la limite de 6000) ---
    embeds_a_envoyer = []

    # 1. Embed Tronc Commun
    if sorts_tronc:
        embed_tronc = discord.Embed(title=f"🌳 TRONC COMMUN : {classe.upper()}", color=0x3498db)
        contenu_tronc = "\n\n".join(sorts_tronc)
        
        # Découpage par champs de 1024 car.
        for i in range(0, len(contenu_tronc), 1000):
            embed_tronc.add_field(name="Techniques", value=contenu_tronc[i:i+1000], inline=False)
        embeds_a_envoyer.append(embed_tronc)

    # 2. Embeds par Spécialisation
    for sc, liste_sorts in sorts_par_spe.items():
        # Sécurité : Le joueur ne voit que ses spés débloquées ou si c'est le MJ
        is_mj = is_gm(interaction.user.id)
        if sc not in unlocked_list and not is_mj:
            continue

        embed_spe = discord.Embed(title=f"✨ VOIE : {sc.upper()}", color=0x9b59b6)
        embed_spe.description = f"*{info_sous_classes.get(sc, 'Spécialisation avancée.')}*"
        
        contenu_spe = "\n\n".join(liste_sorts)
        for i in range(0, len(contenu_spe), 1000):
            embed_spe.add_field(name="Capacités", value=contenu_spe[i:i+1000], inline=False)
        
        if sc not in unlocked_list:
            embed_spe.set_footer(text="🔒 Verrouillé (Affichage MJ)")
        
        embeds_a_envoyer.append(embed_spe)

    # --- Envoi final ---
    if not embeds_a_envoyer:
        return await interaction.response.send_message(f"❌ Aucun sort trouvé pour la classe {classe}.", ephemeral=True)

    # Discord autorise jusqu'à 10 embeds par message
    await interaction.response.send_message(embeds=embeds_a_envoyer[:10])


@bot.tree.command(name="gm_delete_sort", description="(GM) Supprimer définitivement un sort de la base")
@app_commands.describe(ref="Le sort à supprimer")
@app_commands.autocomplete(ref=grimoire_autocomplete) # On réutilise l'autocomplétion existante
async def gm_delete_sort(interaction: discord.Interaction, ref: str):
    # 1. Sécurité GM
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    # 2. Vérification existence
    if ref not in SKILLS_DB:
        return await interaction.response.send_message(f"❌ Le sort avec la ref **{ref}** n'existe pas.", ephemeral=True)

    nom_sort = SKILLS_DB[ref]['nom']

    # 3. Suppression SQL
    conn = get_db_connection()
    conn.execute("DELETE FROM config_sorts WHERE ref = ?", (ref,))
    conn.commit()
    conn.close()

    # 4. Mise à jour de la mémoire du bot
    reload_data() 

    await interaction.response.send_message(f"🗑️ Le sort **{nom_sort}** (Ref: `{ref}`) a été supprimé de la configuration.")



@bot.tree.command(name="gm_clean_skills", description="(GM) Retirer les sorts inexistants des fiches joueurs")
async def gm_clean_skills(interaction: discord.Interaction):
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    
    conn = get_db_connection()
    joueurs = conn.execute("SELECT user_id, nom, competences FROM joueurs").fetchall()
    
    rapport = []
    count_retires = 0

    for j in joueurs:
        try:
            skills_list = json.loads(j['competences'])
            new_list = []
            dirty = False
            
            for s in skills_list:
                if s in SKILLS_DB:
                    new_list.append(s)
                else:
                    dirty = True
                    count_retires += 1
            
            if dirty:
                conn.execute("UPDATE joueurs SET competences = ? WHERE user_id = ? AND nom = ?", (json.dumps(new_list), j['user_id'], j['nom']))
                rapport.append(f"👤 **{j['nom']}** : Nettoyé.")
                
        except Exception:
            continue

    conn.commit()
    conn.close()
    
    msg = f"🧹 **Nettoyage terminé !**\nTotal sorts supprimés : {count_retires}"
    if rapport:
        msg += "\n" + "\n".join(rapport)
        
    await interaction.response.send_message(msg)


@bot.tree.command(name="gm_creer_spe", description="(GM) Créer une nouvelle spécialisation")
@app_commands.describe(nom="Nom de la spé (ex: Necromancien)", classe_mere="Classe requise", description="Description RP")
@app_commands.choices(classe_mere=[
    app_commands.Choice(name="Guerrier", value="guerrier"),
    app_commands.Choice(name="Mage", value="mage"),
    app_commands.Choice(name="Prêtre", value="pretre")
])
async def gm_creer_spe(interaction: discord.Interaction, nom: str, classe_mere: app_commands.Choice[str], description: str):
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO config_sous_classes VALUES (?, ?, ?)", (nom.lower(), classe_mere.value, description))
        conn.commit()
        await interaction.response.send_message(f"✅ Spécialisation **{nom}** créée pour les **{classe_mere.name}s**.")
    except sqlite3.IntegrityError:
        await interaction.response.send_message(f"⚠️ La spé **{nom}** existe déjà.", ephemeral=True)
    finally:
        conn.close()


@bot.tree.command(name="debloquer_specialisation", description="Débloquer l'accès à une sous-classe")
@app_commands.describe(nom_spe="Nom de la spécialisation")
async def debloquer_specialisation(interaction: discord.Interaction, nom_spe: str):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    nom_spe = nom_spe.lower()
    
    # 1. On cherche si des sorts existent pour cette spé dans la configuration
    conn = get_db_connection()
    check_sort = conn.execute("SELECT classes FROM config_sorts WHERE cat = 'spe' AND classes LIKE ?", (f'%"{nom_spe}"%',)).fetchone()
    conn.close()
    
    if not check_sort:
        return await interaction.response.send_message(f"❌ La spécialisation **{nom_spe}** n'existe pas ou n'a aucun sort enregistré dans le grimoire.", ephemeral=True)

    # 2. Vérification si déjà débloqué
    if nom_spe in p.sous_classes_unlocked:
        return await interaction.response.send_message(f"⚠️ Vous avez déjà débloqué l'arbre **{nom_spe.capitalize()}**.", ephemeral=True)

    # 3. Application du déblocage (Sans coût en PC)
    p.sous_classes_unlocked.append(nom_spe)
    p.sauvegarder()
    
    await interaction.response.send_message(f"🔓 **Arbre débloqué !**\nVous avez désormais accès à la voie : **{nom_spe.capitalize()}**.\nUtilisez `/apprendre` pour acquérir les techniques de cet arbre.")



@bot.tree.command(name="gm_delete_spe", description="(GM) Supprimer une spécialisation et tous ses sorts")
@app_commands.describe(nom="Nom de la spécialisation à supprimer")
@app_commands.autocomplete(nom=spe_autocomplete)
async def gm_delete_spe(interaction: discord.Interaction, nom: str):
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    nom_spe = nom.lower()
    conn = get_db_connection()
    exists = conn.execute("SELECT 1 FROM config_sous_classes WHERE nom = ?", (nom_spe,)).fetchone()
    if not exists:
        conn.close()
        return await interaction.response.send_message(f"❌ La spécialisation **{nom_spe}** n'existe pas.", ephemeral=True)
    cursor = conn.execute("DELETE FROM config_sorts WHERE cat = 'spe' AND classes LIKE ?", (f'%"{nom_spe}"%',))
    deleted_spells_count = cursor.rowcount
    conn.execute("DELETE FROM config_sous_classes WHERE nom = ?", (nom_spe,))
    conn.commit()
    conn.close()
    reload_data()
    await interaction.response.send_message(f"🗑️ Spécialisation **{nom_spe.capitalize()}** supprimée.\n🔥 **{deleted_spells_count}** sorts associés ont été effacés du grimoire.")


# --- COMMANDES ITEMS (GM) ---

@bot.tree.command(name="gm_creer_item", description="(GM) Créer un objet")
@app_commands.describe(
    ref="Code unique (ex: epee_fer)", nom="Nom affiché",
    description="Description des effets",
    rarete="Rareté de l'objet",
    bonus_json='Bonus JSON (ex: {"pv_max":5,"mana_max":10,"phy":1})',
    necessite_etude="L'objet doit-il être étudié avant de fonctionner ?"
)
@app_commands.choices(slot=[
    app_commands.Choice(name="⚔️ Arme",             value="arme"),
    app_commands.Choice(name="📿 Collier/Amulette",  value="collier"),
    app_commands.Choice(name="💍 Bague/Anneau",      value="anneau"),
    app_commands.Choice(name="🛡️ Armure",            value="armure"),
    app_commands.Choice(name="🧥 Cape",              value="cape"),
    app_commands.Choice(name="🧵 Ceinture",          value="ceinture"),
    app_commands.Choice(name="🎩 Chapeau",           value="chapeau"),
    app_commands.Choice(name="🧤 Gants",             value="gants"),
    app_commands.Choice(name="👢 Bottes",            value="bottes"),
], rarete=[
    app_commands.Choice(name="⚪ Commun (5 pts)",       value="commun"),
    app_commands.Choice(name="🟢 Peu commun (10 pts)",  value="peu_commun"),
    app_commands.Choice(name="🔵 Rare (15 pts)",        value="rare"),
    app_commands.Choice(name="🟣 Épique (25 pts)",      value="epique"),
    app_commands.Choice(name="🟠 Légendaire (40 pts)",  value="legendaire"),
])
async def gm_creer_item(interaction: discord.Interaction, ref: str, nom: str, slot: app_commands.Choice[str], description: str,
                        rarete: app_commands.Choice[str] = None, bonus_json: str = '{}', necessite_etude: bool = False):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    rarete_val = rarete.value if rarete else "commun"
    RARETE_POINTS = {"commun": 5, "peu_commun": 10, "rare": 15, "epique": 25, "legendaire": 40}
    pts = RARETE_POINTS.get(rarete_val, 5)

    # Valider bonus_json
    try:
        json.loads(bonus_json)
    except Exception:
        return await interaction.response.send_message("❌ `bonus_json` invalide. Ex: `{\"pv_max\":5,\"mana_max\":10}`", ephemeral=True)

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO config_items (ref, nom, slot, description, rarete, bonus_json, points_limite, necessite_etude) VALUES (?,?,?,?,?,?,?,?)",
            (ref.lower(), nom, slot.value, description, rarete_val, bonus_json, pts, 1 if necessite_etude else 0)
        )
        conn.commit()
        RARETE_EMOJI = {"commun":"⚪","peu_commun":"🟢","rare":"🔵","epique":"🟣","legendaire":"🟠"}
        emoji = RARETE_EMOJI.get(rarete_val, "⚪")
        etude_str = " *(Requiert étude)*" if necessite_etude else ""
        await interaction.response.send_message(
            f"✅ **{nom}** créé ! {emoji} {rarete_val.replace('_',' ').capitalize()} — {pts} pts de limite{etude_str}\n"
            f"*Slot : {slot.name} | Bonus : `{bonus_json}`*"
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : {e}", ephemeral=True)
    finally:
        conn.close()

# Autocomplétion pour faciliter le don d'item
async def item_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db_connection()
    rows = conn.execute("SELECT nom, ref FROM config_items WHERE nom LIKE ?", (f"%{current}%",)).fetchall()
    conn.close()
    return [app_commands.Choice(name=r['nom'], value=r['ref']) for r in rows][:25]

async def set_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db_connection()
    rows = conn.execute("SELECT nom, set_ref FROM config_sets WHERE nom LIKE ?", (f"%{current}%",)).fetchall()
    conn.close()
    return [app_commands.Choice(name=r['nom'], value=r['set_ref']) for r in rows][:25]

@bot.tree.command(name="gm_creer_set", description="(GM) Créer un set d'items avec bonus par pièces équipées")
@app_commands.describe(
    set_ref="Code unique du set (ex: set_ombre)",
    nom="Nom affiché du set",
    description="Description narrative",
    bonus_2='Bonus à 2 pièces JSON (ex: {"mana_max":10,"phy":1})',
    bonus_4='Bonus à 4 pièces JSON (ex: {"pv_max":20,"bonus_base_item":2})'
)
async def gm_creer_set(interaction: discord.Interaction, set_ref: str, nom: str, description: str,
                       bonus_2: str = '{}', bonus_4: str = '{}'):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    try:
        json.loads(bonus_2); json.loads(bonus_4)
    except:
        return await interaction.response.send_message("❌ JSON invalide dans les bonus.", ephemeral=True)

    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO config_sets VALUES (?,?,?,?,?)",
                 (set_ref.lower(), nom, description, bonus_2, bonus_4))
    conn.commit(); conn.close()
    await interaction.response.send_message(
        f"✅ Set **{nom}** créé !\n"
        f"• 2 pièces : `{bonus_2}`\n"
        f"• 4 pièces : `{bonus_4}`"
    )

@bot.tree.command(name="gm_ajouter_set_item", description="(GM) Associer un item à un set")
@app_commands.describe(set_ref="Ref du set", item_ref="Ref de l'item")
@app_commands.autocomplete(set_ref=set_autocomplete, item_ref=item_autocomplete)
async def gm_ajouter_set_item(interaction: discord.Interaction, set_ref: str, item_ref: str):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    conn = get_db_connection()
    s = conn.execute("SELECT nom FROM config_sets WHERE set_ref=?", (set_ref,)).fetchone()
    it = conn.execute("SELECT nom FROM config_items WHERE ref=?", (item_ref,)).fetchone()
    if not s or not it:
        conn.close()
        return await interaction.response.send_message("❌ Set ou item introuvable.", ephemeral=True)
    conn.execute("INSERT OR IGNORE INTO config_set_items VALUES (?,?)", (set_ref, item_ref))
    conn.commit(); conn.close()
    await interaction.response.send_message(f"✅ **{it['nom']}** ajouté au set **{s['nom']}**.")

@bot.tree.command(name="sets", description="Voir les sets actifs sur votre personnage")
async def sets(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = get_db_connection()
    # Récupérer les items équipés et identifiés
    equipes = conn.execute('''
        SELECT i.item_ref FROM inventaire i WHERE i.user_id=? AND i.equipe=1 AND i.identifie=1
    ''', (user_id,)).fetchall()
    refs_equipes = {r['item_ref'] for r in equipes}

    tous_sets = conn.execute("SELECT * FROM config_sets").fetchall()
    embed = discord.Embed(title="🔮 Sets d'Équipement", color=0x9b59b6)
    found = False
    for s in tous_sets:
        items_set = conn.execute("SELECT item_ref FROM config_set_items WHERE set_ref=?", (s['set_ref'],)).fetchall()
        refs_set = [r['item_ref'] for r in items_set]
        count = sum(1 for r in refs_set if r in refs_equipes)
        if count == 0: continue
        found = True
        actif_2 = count >= 2
        actif_4 = count >= 4
        b2 = json.loads(s['bonus_2']) if s['bonus_2'] else {}
        b4 = json.loads(s['bonus_4']) if s['bonus_4'] else {}
        txt = f"*{s['description']}*\n**Pièces équipées : {count}/{len(refs_set)}**\n"
        if b2: txt += f"{'✅' if actif_2 else '⬜'} 2 pièces : {', '.join(f'+{v} {k}' for k,v in b2.items())}\n"
        if b4: txt += f"{'✅' if actif_4 else '⬜'} 4 pièces : {', '.join(f'+{v} {k}' for k,v in b4.items())}\n"
        embed.add_field(name=f"{'🟣' if actif_2 else '⬜'} {s['nom']}", value=txt, inline=False)
    conn.close()
    if not found:
        embed.description = "Aucun set actif sur votre personnage."
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="gm_give_item", description="(GM) Donner un objet à un joueur")
@app_commands.autocomplete(item_ref=item_autocomplete)
async def gm_give_item(interaction: discord.Interaction, joueur: discord.Member, item_ref: str):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    conn = get_db_connection()
    item = conn.execute("SELECT nom, necessite_etude FROM config_items WHERE ref=?", (item_ref,)).fetchone()
    if not item:
        conn.close()
        return await interaction.response.send_message("❌ Objet inconnu.", ephemeral=True)

    # Si étude requise : identifie=0, sinon 1
    identifie = 0 if item['necessite_etude'] else 1
    conn.execute("INSERT INTO inventaire (user_id, item_ref, identifie) VALUES (?,?,?)",
                 (joueur.id, item_ref, identifie))
    conn.commit(); conn.close()

    suffix = "\n⚠️ *Cet objet doit être **étudié** (`/etudier`) avant de fonctionner.*" if not identifie else ""
    await interaction.response.send_message(
        f"🎁 **{item['nom']}** ajouté à l'inventaire de {joueur.display_name}.{suffix}"
    )


@bot.tree.command(name="etudier", description="Étudier un objet non identifié (1 tentative / 24h)")
@app_commands.describe(item_id="L'ID de l'objet dans /inventaire")
async def etudier(interaction: discord.Interaction, item_id: int):
    import datetime as _dt
    import random as _rnd
    import asyncio as _asyncio
    user_id = interaction.user.id
    conn = get_db_connection()

    inv = conn.execute('''
        SELECT i.id, i.identifie, i.item_ref, c.nom, c.description, c.rarete, c.necessite_etude
        FROM inventaire i JOIN config_items c ON i.item_ref = c.ref
        WHERE i.id=? AND i.user_id=?
    ''', (item_id, user_id)).fetchone()

    if not inv:
        conn.close()
        return await interaction.response.send_message("❌ Objet introuvable dans votre inventaire.", ephemeral=True)
    if inv['identifie']:
        conn.close()
        return await interaction.response.send_message("✅ Cet objet est déjà identifié !", ephemeral=True)
    if not inv['necessite_etude']:
        conn.close()
        return await interaction.response.send_message("ℹ️ Cet objet ne nécessite pas d'étude.", ephemeral=True)

    prog = conn.execute("SELECT * FROM etude_progress WHERE user_id=? AND inv_id=?",
                        (user_id, item_id)).fetchone()
    now = _dt.datetime.utcnow()

    if prog and prog['derniere_tentative']:
        last = _dt.datetime.fromisoformat(prog['derniere_tentative'])
        if (now - last).total_seconds() < 86400:
            reste = 86400 - (now - last).total_seconds()
            h = int(reste // 3600); m = int((reste % 3600) // 60)
            conn.close()
            return await interaction.response.send_message(
                f"⏳ **Prochaine étude dans {h}h{m:02d}.**\nProgression : **{prog['reussites']}/3** réussites.",
                ephemeral=True)

    reussites = prog['reussites'] if prog else 0

    RARETE_N     = {"commun": 5, "peu_commun": 6, "rare": 7, "epique": 8, "legendaire": 9}
    RARETE_EMOJI = {"commun": "⚪", "peu_commun": "🟢", "rare": "🔵", "epique": "🟣", "legendaire": "🟠"}
    N         = RARETE_N.get(inv['rarete'], 5)
    rarete_em = RARETE_EMOJI.get(inv['rarete'], "⚪")
    T_MEMO    = 15  # secondes pour mémoriser (toutes raretés)

    ALL = ["⭐", "🌟", "✨", "💫", "🌠", "🔮", "🌌", "⚡", "🔥"]
    pool = ALL[:]
    _rnd.shuffle(pool)
    seq_correcte = pool[:N]
    seq_melangee = seq_correcte[:]
    while seq_melangee == seq_correcte and N > 1:
        _rnd.shuffle(seq_melangee)
    _rnd.shuffle(seq_melangee)

    seq_str = ",".join(seq_correcte)
    if not prog:
        conn.execute("INSERT INTO etude_progress (user_id, inv_id, reussites, sequence_en_cours) VALUES (?,?,?,?)",
                     (user_id, item_id, reussites, seq_str))
    else:
        conn.execute("UPDATE etude_progress SET sequence_en_cours=? WHERE user_id=? AND inv_id=?",
                     (seq_str, user_id, item_id))
    conn.commit()
    conn.close()

    seq_display = " ".join(seq_correcte)

    def make_memo_embed(remaining):
        e = discord.Embed(title="🔮 Étude de l'Artefact — Mémorisation", color=0x9b59b6)
        e.description = (
            f"{rarete_em} **Objet inconnu** — {inv['rarete'].replace('_', ' ').capitalize()}\n"
            f"Progression : **{reussites}/3** réussite(s)\n\n"
            f"**Mémorisez cette séquence !**\n"
            f"┃ {seq_display} ┃\n\n"
            f"⏱️ *Masquage dans **{remaining}s**...*"
        )
        return e

    await interaction.response.send_message(embed=make_memo_embed(T_MEMO), ephemeral=True)

    for remaining in range(T_MEMO - 1, 0, -1):
        await _asyncio.sleep(1)
        await interaction.edit_original_response(embed=make_memo_embed(remaining))

    await _asyncio.sleep(1)

    embed_jeu = discord.Embed(title="🔮 Étude de l'Artefact — Reproduction", color=0x9b59b6)
    embed_jeu.description = (
        f"{rarete_em} **Objet inconnu** — {inv['rarete'].replace('_', ' ').capitalize()}\n"
        f"Progression : **{reussites}/3** réussite(s)\n\n"
        f"**Reproduisez la séquence dans l'ordre !**\n"
        f"┃ {'❓ ' * N}┃"
    )
    embed_jeu.set_footer(text="Vous avez 90 secondes.")

    class EtudeView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=90)
            self.clicks = []
            self.seq_melangee = seq_melangee
            self.N = N
            self.item_id = item_id
            self.user_id = user_id
            self.reussites = reussites
            self.done = False

            for idx, emoji in enumerate(seq_melangee):
                row_n = 0 if idx < 5 else 1
                btn = discord.ui.Button(emoji=emoji, custom_id=f"star_{idx}",
                                        style=discord.ButtonStyle.secondary, row=row_n)
                btn.callback = self.make_callback(idx, emoji)
                self.add_item(btn)

            reset_btn = discord.ui.Button(label="↺ Reset", style=discord.ButtonStyle.danger,
                                          custom_id="reset", row=2)
            reset_btn.callback = self.reset_callback
            self.add_item(reset_btn)

        def make_callback(self, idx, emoji):
            async def callback(inter2: discord.Interaction):
                if inter2.user.id != self.user_id:
                    return await inter2.response.send_message("❌ Ce n'est pas votre étude.", ephemeral=True)
                if self.done or idx in self.clicks:
                    return await inter2.response.defer()

                self.clicks.append(idx)
                clicked = [self.seq_melangee[c] for c in self.clicks]
                status = " ".join(clicked) + " " + "◽" * (self.N - len(clicked))
                emb2 = inter2.message.embeds[0]
                emb2.description = (
                    f"{rarete_em} **Objet inconnu** — {inv['rarete'].replace('_', ' ').capitalize()}\n"
                    f"Progression : **{self.reussites}/3** réussite(s)\n\n"
                    f"**Reproduisez la séquence dans l'ordre !**\n"
                    f"┃ {status} ┃"
                )

                if len(self.clicks) == self.N:
                    self.done = True
                    await self.enregistrer(inter2, clicked, emb2)
                else:
                    await inter2.response.edit_message(embed=emb2, view=self)
            return callback

        async def reset_callback(self, inter2: discord.Interaction):
            if inter2.user.id != self.user_id: return
            self.clicks = []
            emb2 = inter2.message.embeds[0]
            emb2.description = (
                f"{rarete_em} **Objet inconnu** — {inv['rarete'].replace('_', ' ').capitalize()}\n"
                f"Progression : **{self.reussites}/3** réussite(s)\n\n"
                f"**Reproduisez la séquence dans l'ordre !**\n"
                f"┃ {'❓ ' * self.N}┃"
            )
            await inter2.response.edit_message(embed=emb2, view=self)

        async def enregistrer(self, inter2, clicked, emb2):
            import datetime as _dt2
            conn2 = get_db_connection()
            row = conn2.execute("SELECT sequence_en_cours FROM etude_progress WHERE user_id=? AND inv_id=?",
                                (self.user_id, self.item_id)).fetchone()
            seq_db = row['sequence_en_cours'].split(",") if row and row['sequence_en_cours'] else []
            ok = (clicked == seq_db)
            new_reussites = self.reussites + (1 if ok else 0)
            conn2.execute(
                "UPDATE etude_progress SET reussites=?, derniere_tentative=?, sequence_en_cours=NULL WHERE user_id=? AND inv_id=?",
                (new_reussites, _dt2.datetime.utcnow().isoformat(), self.user_id, self.item_id))

            for child in self.children:
                child.disabled = True

            if new_reussites >= 3:
                conn2.execute("UPDATE inventaire SET identifie=1 WHERE id=?", (self.item_id,))
                conn2.commit()
                it = conn2.execute("SELECT nom, description, rarete FROM config_items WHERE ref=?",
                                   (inv['item_ref'],)).fetchone()
                conn2.close()
                RE = {"commun":"⚪","peu_commun":"🟢","rare":"🔵","epique":"🟣","legendaire":"🟠"}
                emb3 = discord.Embed(title="✨ Artefact Identifié !", color=0xf1c40f)
                emb3.description = (
                    f"**{it['nom']}** {RE.get(it['rarete'],'⚪')}\n"
                    f"*{it['description']}*\n\n"
                    f"Utilisez `/equiper {self.item_id}` pour l'équiper !"
                )
                await inter2.response.edit_message(embed=emb3, view=self)
            else:
                conn2.commit(); conn2.close()
                emb3 = discord.Embed(
                    title="✅ Étude réussie !" if ok else "❌ Étude échouée",
                    color=0x2ecc71 if ok else 0xe74c3c)
                emb3.description = f"Progression : **{new_reussites}/3**\nRevenez dans 24h."
                if not ok:
                    emb3.add_field(name="Séquence correcte", value=" ".join(seq_db), inline=False)
                    emb3.add_field(name="Votre séquence",    value=" ".join(clicked),  inline=False)
                await inter2.response.edit_message(embed=emb3, view=self)

    await interaction.edit_original_response(embed=embed_jeu, view=EtudeView())

#-------------------------------------------------------------------------------------------------------------------------------------------
# --- COMMANDES DE DON ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------

@bot.tree.command(name="gm_give_points", description="(GM) Donner des points de compétence/stat/attribut")
@app_commands.describe(joueur="Le joueur cible", type_point="Type de points", montant="Quantité")
@app_commands.choices(type_point=[
    app_commands.Choice(name="💪 Points de Caractéristiques (Stats)", value="points_stat"),
    app_commands.Choice(name="✨ Points de Compétences (Sorts)", value="points_comp"),
    app_commands.Choice(name="🎭 Points d'Attributs (RP)", value="points_attribut")
])
async def gm_give_points(interaction: discord.Interaction, joueur: discord.Member, type_point: app_commands.Choice[str], montant: int):
    # Sécurité GM
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

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
    if not is_gm(interaction.user.id): return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

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

@bot.tree.command(name="gm_retirer_item", description="(GM) Retirer définitivement un objet de l'inventaire d'un joueur")
@app_commands.describe(joueur="Le joueur ciblé", item_ref="Le nom/code de l'objet")
@app_commands.autocomplete(item_ref=item_autocomplete)
async def gm_retirer_item(interaction: discord.Interaction, joueur: discord.Member, item_ref: str):
    # Sécurité GM
    if not is_gm(interaction.user.id): 
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
        
    conn = get_db_connection()
    
    # 1. Vérifier si le joueur possède bien l'objet
    # On prend l'ID (LIMIT 1) pour n'en supprimer qu'un seul s'il en a plusieurs
    check = conn.execute("SELECT id FROM inventaire WHERE user_id = ? AND item_ref = ? LIMIT 1", (joueur.id, item_ref)).fetchone()
    
    if not check:
        conn.close()
        return await interaction.response.send_message(f"❌ {joueur.display_name} ne possède pas cet objet.", ephemeral=True)
        
    # 2. Supprimer l'objet de la base de données
    conn.execute("DELETE FROM inventaire WHERE id = ?", (check['id'],))
    conn.commit()
    
    # 3. Récupérer le nom propre pour l'affichage
    item = conn.execute("SELECT nom FROM config_items WHERE ref = ?", (item_ref,)).fetchone()
    nom_item = item['nom'] if item else item_ref
    conn.close()
    
    # 4. Mettre à jour le personnage s'il le portait sur lui
    p = Personnage.charger(joueur.id)
    if p:
        p.charger_equipement() # Recharge l'équipement sans l'objet supprimé
        p.sauvegarder()
        
    embed = discord.Embed(title="objet retiré", color=0xe74c3c)
    embed.description = f"Le MJ a retiré **{nom_item}** de l'inventaire de {joueur.mention}."
    
    await interaction.response.send_message(embed=embed)



#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
# --- SYSTÈME ENTRAINEMENT ---
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------------------------------------



@bot.tree.command(name="entrainement", description="🛡️ Activer le mode Entraînement (Sauvegarde l'état actuel)")
async def entrainement(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    
    if p.mode_entrainement:
        return await interaction.response.send_message("⚠️ Vous êtes déjà en mode entraînement.", ephemeral=True)
    
    # On fait une "photo" (Snapshot) des stats actuelles pour les rendre plus tard
    snapshot = {
        "pv": p.pv_actuel,
        "mana": p.mana,
        "tension": p.tension,
        "ferveur": p.ferveur,
    }
    
    p.mode_entrainement = 1
    p.snapshot_entrainement = json.dumps(snapshot)
    p.sauvegarder()
    
    embed = discord.Embed(title="🥋 Mode Entraînement ACTIVÉ", color=0xFFFFFF)
    embed.description = "Vos stats actuelles sont sauvegardées.\nVos PV ne descendront pas en dessous de **1**.\n\nUtilisez `/fin_entrainement` pour terminer et récupérer vos ressources."
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="fin_entrainement", description="🛑 Quitter l'entraînement et récupérer vos stats")
async def fin_entrainement(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    
    if not p.mode_entrainement:
        return await interaction.response.send_message("❌ Vous n'êtes pas en entraînement.", ephemeral=True)
    
    msg = "🛑 **Entraînement Terminé.**\n"
    
    # Restauration depuis la sauvegarde (Snapshot)
    if p.snapshot_entrainement:
        try:
            data = json.loads(p.snapshot_entrainement)
            p.pv_actuel = data.get("pv", p.pv_actuel)
            p.mana = data.get("mana", p.mana)
            p.tension = data.get("tension", p.tension)
            p.ferveur = data.get("ferveur", p.ferveur)
            msg += "✨ Vos PV et ressources ont été restaurés à leur état d'origine."
        except (json.JSONDecodeError, KeyError):
            msg += "⚠️ Erreur lors de la restauration des données."
    
    # Désactivation
    p.mode_entrainement = 0
    p.snapshot_entrainement = None
    p.sauvegarder()
    
    await interaction.response.send_message(msg)


#-------------------------------------------------------------------------------------------------------------------------------------------
# --- COMMANDES MONNAIE ---
#-------------------------------------------------------------------------------------------------------------------------------------------

@bot.tree.command(name="bourse", description="Consulter l'état de votre bourse")
async def bourse(interaction: discord.Interaction):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)

    or_p = p.monnaie // 100
    argent_p = (p.monnaie % 100) // 10
    bronze_p = p.monnaie % 10

    embed = discord.Embed(title="💰 Bourse", color=0xF1C40F)
    embed.description = f"Contenu de la bourse de **{p.nom}** :"
    embed.add_field(name="Solde", value=f"**{or_p}** 🥇 | **{argent_p}** 🥈 | **{bronze_p}** 🥉", inline=False)
    embed.set_footer(text=f"Total en bronze : {p.monnaie}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="depenser", description="Dépenser de l'argent de votre bourse")
@app_commands.describe(or_p="Pièces d'Or", argent_p="Pièces d'Argent", bronze_p="Pièces de Bronze", raison="Raison de la dépense")
async def depenser(interaction: discord.Interaction, or_p: int = 0, argent_p: int = 0, bronze_p: int = 0, raison: str = "Achat de biens/services"):
    p: Personnage = Personnage.charger(interaction.user.id)
    if not p: return await interaction.response.send_message("❌ Pas de fiche.", ephemeral=True)
    
    # Conversion totale en bronze
    cout_total = (or_p * 100) + (argent_p * 10) + bronze_p
    
    if cout_total <= 0:
        return await interaction.response.send_message("❌ Montant invalide.", ephemeral=True)
        
    if p.monnaie < cout_total:
        manque = cout_total - p.monnaie
        m_or = manque // 100
        m_arg = (manque % 100) // 10
        m_br = manque % 10
        return await interaction.response.send_message(f"❌ Fonds insuffisants ! Il vous manque **{m_or}🥇 {m_arg}🥈 {m_br}🥉**.", ephemeral=True)
        
    p.monnaie -= cout_total
    p.sauvegarder()
    
    # Re-conversion pour l'affichage du reste
    rest_or = p.monnaie // 100
    rest_arg = (p.monnaie % 100) // 10
    rest_br = p.monnaie % 10
    
    embed = discord.Embed(title="Dépense", color=0xe67e22)
    embed.description = f"**{p.nom}** a ouvert sa bourse.\n*« {raison} »*"
    embed.add_field(name="Montant payé", value=f"**{or_p}** 🥇 | **{argent_p}** 🥈 | **{bronze_p}** 🥉", inline=False)
    embed.add_field(name="Reste en bourse", value=f"**{rest_or}** 🥇 | **{rest_arg}** 🥈 | **{rest_br}** 🥉", inline=False)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="gm_monnaie", description="(GM) Donner ou retirer de la monnaie à un joueur")
@app_commands.describe(joueur="Le joueur", action="Donner ou Retirer", or_p="Or", argent_p="Argent", bronze_p="Bronze")
@app_commands.choices(action=[
    app_commands.Choice(name="➕ Donner", value="add"),
    app_commands.Choice(name="➖ Retirer", value="sub")
])
@app_commands.describe(joueur="[Optionnel] Cible via @", cible_fiche="[Optionnel] Cible via nom de fiche (prioritaire)")
@app_commands.autocomplete(cible_fiche=cible_fiche_autocomplete)
async def gm_monnaie(interaction: discord.Interaction, action: app_commands.Choice[str], joueur: discord.Member = None, cible_fiche: str = None, or_p: int = 0, argent_p: int = 0, bronze_p: int = 0):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
    if cible_fiche:
        p = parse_cible_arg(cible_fiche)
    elif joueur:
        p = Personnage.charger(joueur.id)
    else:
        return await interaction.response.send_message("❌ Précisez une cible (@ ou nom de fiche).", ephemeral=True)
    if not p: return await interaction.response.send_message("❌ Joueur introuvable.", ephemeral=True)
    
    montant = (or_p * 100) + (argent_p * 10) + bronze_p
    
    if action.value == "add":
        p.monnaie += montant
        titre = "💰 Ajout de monnaie"
        c = 0xF1C40F
    else:
        p.monnaie = max(0, p.monnaie - montant)
        titre = "💰 Retrait de monnaie"
        c = 0xe74c3c
        
    p.sauvegarder()
    
    rest_or = p.monnaie // 100
    rest_arg = (p.monnaie % 100) // 10
    rest_br = p.monnaie % 10
    
    embed = discord.Embed(title=titre, color=c)
    embed.description = f"La bourse de **{p.nom}** a été modifiée par le MJ."
    
    signe = "+" if action.value == "add" else "-"
    embed.add_field(name="Modification", value=f"{signe} **{or_p}** 🥇 | **{argent_p}** 🥈 | **{bronze_p}** 🥉", inline=False)
    embed.add_field(name="Nouveau Solde", value=f"**{rest_or}** 🥇 | **{rest_arg}** 🥈 | **{rest_br}** 🥉", inline=False)
    
    await interaction.response.send_message(content=f"{joueur.mention}", embed=embed)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        minutes_restantes = int(error.retry_after // 60)
        secondes_restantes = int(error.retry_after % 60)
        await interaction.response.send_message(
            f"⏳ **Doucement !** Vous devez attendre encore {minutes_restantes}m {secondes_restantes}s.", 
            ephemeral=True
        )
    else:
        print(f"Erreur : {error}")
        try:
            await interaction.response.send_message("❌ Une erreur est survenue.", ephemeral=True)
        except discord.InteractionResponded:
            pass






#-------------------------------------------------------------------------------------------------------------------------------------------
# --- COMMANDES BADGES ---
#-------------------------------------------------------------------------------------------------------------------------------------------

@bot.tree.command(name="gm_badge_ajouter", description="(GM) Donner un badge / titre à un joueur")
@app_commands.describe(joueur="Le joueur à récompenser", badge="Le titre à lui attribuer (ex: Sauveur de Einsber)")
async def gm_badge_ajouter(interaction: discord.Interaction, joueur: discord.Member, badge: str):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    p = Personnage.charger(joueur.id)
    if not p:
        return await interaction.response.send_message("❌ Ce joueur n'a pas de fiche.", ephemeral=True)

    if badge in p.badges:
        return await interaction.response.send_message(f"⚠️ **{p.nom}** possède déjà le titre **{badge}**.", ephemeral=True)

    p.badges.append(badge)
    p.sauvegarder()

    embed = discord.Embed(title="🏅 Nouveau Titre !", color=0xF1C40F)
    embed.description = f"**{p.nom}** reçoit le titre :\n## 🏅 {badge}"
    embed.set_footer(text=f"Attribué par le MJ • Total : {len(p.badges)} titre(s)")
    await interaction.response.send_message(content=joueur.mention, embed=embed)


@bot.tree.command(name="gm_badge_retirer", description="(GM) Retirer un badge / titre d'un joueur")
@app_commands.describe(joueur="Le joueur ciblé", badge="Le titre à retirer (doit être exact)")
async def gm_badge_retirer(interaction: discord.Interaction, joueur: discord.Member, badge: str):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    p = Personnage.charger(joueur.id)
    if not p:
        return await interaction.response.send_message("❌ Ce joueur n'a pas de fiche.", ephemeral=True)

    if badge not in p.badges:
        titres = "\n".join(p.badges) if p.badges else "*Aucun*"
        return await interaction.response.send_message(
            f"❌ Titre **{badge}** introuvable sur **{p.nom}**.\nTitres actuels :\n{titres}",
            ephemeral=True
        )

    p.badges.remove(badge)
    p.sauvegarder()

    embed = discord.Embed(title="🗑️ Titre Retiré", color=0x95a5a6)
    embed.description = f"Le titre **{badge}** a été retiré de **{p.nom}**."
    await interaction.response.send_message(embed=embed, ephemeral=True)

#-------------------------------------------------------------------------------------------------------------------------------------------
# --- COMMANDE BACKUP ---
#-------------------------------------------------------------------------------------------------------------------------------------------

@bot.tree.command(name="gm_backup", description="(GM) Exporter toutes les données joueurs en JSON")
async def gm_backup(interaction: discord.Interaction):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    conn = get_db_connection()
    joueurs = conn.execute("SELECT * FROM joueurs").fetchall()
    inventaire = conn.execute("SELECT * FROM inventaire").fetchall()
    sessions = conn.execute("SELECT * FROM sessions").fetchall()
    config_items = conn.execute("SELECT * FROM config_items").fetchall()
    config_sets = conn.execute("SELECT * FROM config_sets").fetchall()
    config_set_items = conn.execute("SELECT * FROM config_set_items").fetchall()
    conn.close()

    data = {
        "date": discord.utils.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "joueurs": [dict(j) for j in joueurs],
        "inventaire": [dict(i) for i in inventaire],
        "sessions": [dict(s) for s in sessions],
        "config_items": [dict(i) for i in config_items],
        "config_sets": [dict(s) for s in config_sets],
        "config_set_items": [dict(si) for si in config_set_items],
    }

    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    file = discord.File(fp=__import__("io").BytesIO(json_bytes), filename=f"backup_{discord.utils.utcnow().strftime('%Y%m%d_%H%M')}.json")

    await interaction.followup.send(
        f"✅ Backup exporté — **{len(data['joueurs'])}** personnages, **{len(data['inventaire'])}** items inventaire, **{len(data['config_items'])}** items config.",
        file=file,
        ephemeral=True
    )

#-------------------------------------------------------------------------------------------------------------------------------------------
# --- COMMANDE RESTORE ---
#-------------------------------------------------------------------------------------------------------------------------------------------

@bot.tree.command(name="gm_restore", description="(GM) Restaurer les données depuis un fichier backup JSON")
async def gm_restore(interaction: discord.Interaction):
    if not is_gm(interaction.user.id):
        return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

    await interaction.response.send_message(
        "📂 **Envoyez le fichier backup `.json`** en réponse à ce message dans les 60 secondes.",
        ephemeral=True
    )

    def check(m):
        return (
            m.author.id == interaction.user.id
            and m.channel.id == interaction.channel_id
            and m.attachments
            and m.attachments[0].filename.endswith(".json")
        )

    try:
        msg = await interaction.client.wait_for("message", check=check, timeout=60.0)
    except asyncio.TimeoutError:
        return await interaction.followup.send("⏰ Temps écoulé. Restore annulé.", ephemeral=True)

    # Télécharger le fichier
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(msg.attachments[0].url) as resp:
                raw = await resp.read()
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return await interaction.followup.send(f"❌ Impossible de lire le fichier : {e}", ephemeral=True)

    joueurs_data = data.get("joueurs", [])
    inventaire_data = data.get("inventaire", [])
    sessions_data = data.get("sessions", [])
    config_items_data = data.get("config_items", [])
    config_sets_data = data.get("config_sets", [])
    config_set_items_data = data.get("config_set_items", [])

    if not joueurs_data:
        return await interaction.followup.send("❌ Aucune donnée joueur trouvée dans le fichier.", ephemeral=True)

    conn = get_db_connection()
    nb_joueurs = 0
    nb_inventaire = 0
    nb_sessions = 0
    nb_items = 0
    nb_sets = 0
    erreurs = []

    try:
        # Colonnes connues de la table joueurs
        colonnes_joueurs = [
            "user_id", "nom", "classe", "race", "niveau", "pv_actuel", "pv_max",
            "mana", "mana_max", "tension", "ferveur", "versets",
            "phy", "const", "agi", "esp", "int_stat", "foi", "sag",
            "points_stat", "points_comp", "points_attribut", "competences",
            "oral", "force_rp", "survie", "histoire", "sciences", "medecine",
            "religion", "discretion", "acrobatie",
            "alias", "description", "image_url",
            "mode_entrainement", "snapshot_entrainement", "sous_classes_unlocked",
            "effets", "cooldowns", "monnaie", "robustesse", "festin",
            "charges_elementaires", "passe_active", "parade_absorb",
            "last_action_type", "fureur_tribale_used", "concentre",
            "serment_actif", "serment_bonus", "posture_active",
            "designation_target_id", "designation_stacks",
            "sentence_target_id", "sentence_targets", "passe_count", "badges"
        ]

        for j in joueurs_data:
            try:
                row = {k: j[k] for k in colonnes_joueurs if k in j}
                row.setdefault("badges", "[]")
                row.setdefault("passe_count", 0)
                row.setdefault("sentence_targets", "[]")
                cols = ", ".join(row.keys())
                placeholders = ", ".join(["?"] * len(row))
                conn.execute(
                    f"INSERT OR REPLACE INTO joueurs ({cols}) VALUES ({placeholders})",
                    list(row.values())
                )
                nb_joueurs += 1
            except Exception as e:
                erreurs.append(f"Joueur {j.get('nom', '?')} : {e}")

        # Restaurer config_items — DELETE + INSERT pour forcer remplacement complet (noms, descriptions, raretés)
        for item in config_items_data:
            try:
                conn.execute("DELETE FROM config_items WHERE ref=?", (item["ref"],))
                conn.execute(
                    "INSERT INTO config_items (ref, nom, slot, description, rarete, bonus_json, points_limite, necessite_etude) VALUES (?,?,?,?,?,?,?,?)",
                    (item["ref"], item["nom"], item["slot"], item.get("description", ""),
                     item.get("rarete", "commun"), item.get("bonus_json", "{}"),
                     item.get("points_limite", 5), item.get("necessite_etude", 0))
                )
                nb_items += 1
            except Exception as e:
                erreurs.append(f"Item {item.get('ref', '?')} : {e}")

        # Restaurer config_sets
        for s in config_sets_data:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO config_sets VALUES (?,?,?,?,?)",
                    (s["set_ref"], s["nom"], s.get("description",""), s.get("bonus_2","{}"), s.get("bonus_4","{}"))
                )
                nb_sets += 1
            except Exception as e:
                erreurs.append(f"Set {s.get('set_ref','?')} : {e}")

        # Restaurer config_set_items
        for si in config_set_items_data:
            try:
                conn.execute("INSERT OR IGNORE INTO config_set_items VALUES (?,?)",
                             (si["set_ref"], si["item_ref"]))
            except Exception as e:
                erreurs.append(f"SetItem : {e}")

        # Restaurer inventaire avec colonne identifie (INSERT OR REPLACE pour forcer la mise à jour)
        for inv in inventaire_data:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO inventaire (id, user_id, item_ref, equipe, identifie) VALUES (?,?,?,?,?)",
                    (inv.get("id"), inv["user_id"], inv["item_ref"], inv.get("equipe", 0), inv.get("identifie", 1))
                )
                nb_inventaire += 1
            except Exception as e:
                erreurs.append(f"Inventaire : {e}")

        for s in sessions_data:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO sessions (user_id, nom_perso_actif) VALUES (?, ?)",
                    (s["user_id"], s["nom_perso_actif"])
                )
                nb_sessions += 1
            except Exception as e:
                erreurs.append(f"Session : {e}")

        conn.commit()
    except Exception as e:
        conn.close()
        return await interaction.followup.send(f"❌ Erreur critique : {e}", ephemeral=True)
    finally:
        conn.close()

    msg_erreurs = f"\n⚠️ {len(erreurs)} erreur(s) :\n" + "\n".join(erreurs[:5]) if erreurs else ""
    embed = discord.Embed(title="✅ Restore Terminé", color=0x2ecc71)
    embed.description = (
        f"**{nb_joueurs}** personnages restaurés\n"
        f"**{nb_inventaire}** items d'inventaire restaurés\n"
        f"**{nb_items}** config_items restaurés\n"
        f"**{nb_sets}** sets restaurés\n"
        f"**{nb_sessions}** sessions restaurées"
        f"{msg_erreurs}"
    )
    embed.set_footer(text=f"Depuis : {data.get('date', 'inconnu')}")
    await interaction.followup.send(embed=embed, ephemeral=True)

#-------------------------------------------------------------------------------------------------------------------------------------------

if __name__ == "__main__":
    # webserver.keep_alive()  # Décommenter si hébergé sur Replit
    if token:
        bot.run(token, log_handler=handler, log_level=logging.DEBUG)
    else:
        print("ERREUR : Le token est vide ou le fichier .env est mal placé.")