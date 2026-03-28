# Bot Discord — JDR Frieren

## Description
Bot Discord pour un JDR (jeu de rôle) basé sur l'univers de Frieren.
Gère les personnages, combats, sorts, inventaire et sessions de jeu.

## Stack technique
- **Python** avec `discord.py` (slash commands via `app_commands`)
- **SQLite** — base de données `frieren_jdr.db` (en production : `/data/frieren_jdr.db`)
- **dotenv** — token Discord dans `.env` (`DISCORD_TOKEN`)
- **Flask** — webserver optionnel (pour Replit)

## Structure
- `main.py` — fichier principal, contient tout le bot
- `webserver.py` — serveur Flask (désactivé par défaut)
- `frieren_jdr.db` — base de données SQLite locale
- `.env` — variables d'environnement (non versionné)

## Infos importantes
- **Guild ID** : `1446818667655594006`
- **Game Masters (GM_IDS)** : `[264667357631348749, 461067793677287434]`
- Les commandes sont des slash commands Discord (`/commande`)
- Le préfixe texte `!` est aussi configuré mais peu utilisé

## Tables SQLite principales
- `joueurs` — stats, compétences, sorts, effets des personnages
- `sessions` — personnage actif par joueur
- `config_sorts` — sorts disponibles
- `config_items` — items disponibles
- `inventaire` — inventaire des joueurs
- `config_sous_classes` — sous-classes disponibles

## Instructions pour les modifications
- Toujours lire le code concerné avant de le modifier
- Respecter le style Python existant (pas de type hints, commentaires en français)
- Les commandes sont des `@bot.tree.command()` avec `interaction: discord.Interaction`
- La DB se connecte via `get_db_connection()` — toujours fermer la connexion après usage
