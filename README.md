# 🤖 Transcription Bot

Un bot Telegram pour transcrire et traduire des fichiers audio/vidéo en utilisant Whisper et DeepL.

[![Docker Pulls](https://img.shields.io/docker/pulls/vincentkaleba/transcription-bot)](https://hub.docker.com/r/vincentkaleba/transcription-bot)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Fonctionnalités

- Transcription audio → texte (format SRT)
- Traduction des sous-titres (DeepL)
- Interface utilisateur avec barres de progression
- Choix du modèle Whisper (tiny, base, small, medium, large)
- Serveur de santé intégré
- Restriction d'accès par liste d'utilisateurs

## Déploiement rapide

### Prérequis
- Docker et Docker Compose
- Compte Telegram [@BotFather](https://t.me/BotFather)
- Clé API DeepL [gratuite](https://www.deepl.com/pro#developer)

### Étapes

1. Clonez le dépôt :
```bash
git clone https://github.com/vincentkaleba/transcription-bot.git
cd transcription-bot