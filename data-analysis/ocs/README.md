# Analyse de la base IGN photovoltaïque sol à partir de la bas eIGN de l'occupations des sols (OCS)

Deux jeux de données IGN de référence :

- [Installations de production photovoltaïque au sol](https://geoservices.ign.fr/photovoltaique-sol)
- [La base de données de référence pour la description de l’occupation du sol (OCS)](https://geoservices.ign.fr/ocsge)

## Prérequis:

Les scripts dans ce dossier nécessitent [uv](https://docs.astral.sh/uv/getting-started/installation/) d'installé.

## Téléchargement et constitution du jeu de données OCS

Le jeu de données OCS est composé de plusieurs centaines de fichiers archive contenant des fichiers gpkg.
Afin de les exploiter, un script permet de tous les télécharger, les extraire et les réunir en une seule table [duckdb](https://duckdb.org/).

> [!NOTE]
> L'ensemble des archives nécessitent ~30Go d'espace libre et ~100Go une fois décompressées. La table duckdb en elle-même pèse 100Go

Pour effectuer ces trois actions, un script est disponible `data_processing/ocs_dataset.py` :

```python
uv run data_processing/ocs_dataset.py --help
```

Exemple pour télécharger les scripts dans un sous répertoire `datasets` existant :

```python
uv run data_processing/ocs_dataset.py download --path ./datasets
```

Pour décompresser les fichiers :

```python
uv run data_processing/ocs_dataset.py extract --path ./datasets
```

Pour créer la table dans une base `escosol.duckdb` :

```python
uv run data_processing/ocs_dataset.py process_files --path ./datasets --duckdb_path ./escosol.duckdb
```

## Creation de la table pour le jeu de données IGN photovoltaïque

Un script `photovoltaique_sol_ddl.sql` permet de créer la table `ign_photovoltaique_sol` dans duckdb à partir du fichier gpkg téléchargé sur le site de l'IGN.

## Analyse

Un notebook [marimo](https://marimo.io/) se situe dans le dossier `data_analysis`.
