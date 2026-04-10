import marimo

__generated_with = "0.19.4"
app = marimo.App(width="medium")


@app.cell
def _(mo):
    mo.md(r"""
    # Analyse des jeux de données Photovoltaiques et OCS-GE
    """)
    return


@app.cell
def _():
    import re
    import duckdb
    import numpy as np
    import marimo as mo
    import polars as pl
    import plotly.express as px
    import folium
    import shapely
    from shapely import wkb
    from pyproj import Transformer
    from spatial_polars import SpatialFrame
    import json
    return Transformer, duckdb, folium, json, mo, pl, px, shapely, wkb


@app.cell
def _(duckdb):
    con = duckdb.connect("escosol.duckdb")
    return (con,)


@app.cell
def _(con, mo):
    _ = mo.sql(
        f"""
        LOAD SPATIAL
        """,
        output=False,
        engine=con
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## IGN Photovoltaïque sol
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Description du jeu de données
    """)
    return


@app.cell
def _(con, ign_photovoltaique_sol, mo):
    _df = mo.sql(
        f"""
        SUMMARIZE ign_photovoltaique_sol
        """,
        engine=con
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    Le jeu de données IGN photovoltaïque comporte 2217 linges pour 2110 installations uniques. Les différents parcs ont été identifiés grâce à des images prises entre 2019 et 2023 (variable `millesime`). Pour chaque parc on a l'occupation géospatiale exacte et sa surface observée.
    Cependant le jeu de données comporte très peu d'informations sur les caractéristiques de chaque parc, notamment **98% des parcs n'ont pas leur puissance de renseignée**.
    """)
    return


@app.cell
def _(con, ign_photovoltaique_sol, mo):
    df_photo = mo.sql(
        f"""
        SELECT
            *,
            ST_AsWkb (geom) as geom_wkb
        FROM
            ign_photovoltaique_sol
        """,
        engine=con
    )
    return (df_photo,)


@app.cell
def _(df_photo, folium, shapely, wkb):
    m = folium.Map(location=[46.227638, 2.213749], zoom_start=6, tiles="OpenStreetMap")

    for row in df_photo.iter_rows(named=True):
        geom_shapely = wkb.loads(row["geom_wkb"])
        folium.GeoJson(shapely.to_geojson(geom_shapely)).add_to(m)

    m
    return


@app.cell
def _(con, ign_photovoltaique_sol, mo):
    _df = mo.sql(
        f"""
        SELECT
        	b."COM",
            count(distinct id) as num_installations
        FROM ign_photovoltaique_sol a
        left join 'https://www.insee.fr/fr/statistiques/fichier/8377162/v_commune_2025.csv' b on a."insee_com"[1]=b."COM"
        group by 1
        order by 2 desc
        """,
        engine=con
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Surface
    """)
    return


@app.cell
def _(con, ign_photovoltaique_sol, mo):
    _ = mo.sql(
        f"""
        SELECT
            sum(surf_parc) as surface_parc_totale_declaree
        from
            ign_photovoltaique_sol
        """,
        engine=con
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Croisement avec le jeu de données OCS
    """)
    return


@app.cell
def _(con, ign_photovoltaique_sol, mo, ocs):
    df_link = mo.sql(
        f"""
        with
            escosol_projected as (
                SELECT
                    ips.*,
                    -- Projette dans le bon referentiel
                    CASE
                        WHEN LIST_BOOL_OR(
                            LIST_APPLY(ips.insee_com, lambda s: s::text ~ '^971.*|972.*')
                        ) THEN ST_Transform (ips.geom, 'EPSG:4326','EPSG:5490' , true)
                        WHEN LIST_BOOL_OR(
                            LIST_APPLY(ips.insee_com, lambda s: s::text ~ '^973.*')
                        ) THEN ST_Transform (ips.geom, 'EPSG:4326','EPSG:2972' , true)
            			WHEN LIST_BOOL_OR(
                            LIST_APPLY(ips.insee_com, lambda s: s::text ~ '^974.*')
                        ) THEN ST_Transform (ips.geom, 'EPSG:4326','EPSG:2975' , true)
                        WHEN LIST_BOOL_OR(
                            LIST_APPLY(ips.insee_com, lambda s: s::text ~ '^976.*')
                        ) THEN ST_Transform (ips.geom, 'EPSG:4326','EPSG:4471' , true)
                        ELSE ST_Transform (ips.geom, 'EPSG:4326','EPSG:2154' , true)
                    END as geom_proj,
            		CASE
                        WHEN LIST_BOOL_OR(
                            LIST_APPLY(ips.insee_com, lambda s: s::text ~ '^971.*|972.*')
                        ) THEN 5490
                        WHEN LIST_BOOL_OR(
                            LIST_APPLY(ips.insee_com, lambda s: s::text ~ '^973.*')
                        ) THEN 2972
            			WHEN LIST_BOOL_OR(
                            LIST_APPLY(ips.insee_com, lambda s: s::text ~ '^974.*')
                        ) THEN 2975
                        WHEN LIST_BOOL_OR(
                            LIST_APPLY(ips.insee_com, lambda s: s::text ~ '^976.*')
                        ) THEN 4471
                        ELSE 2154
                    END as geom_original_referential
                FROM
                    ign_photovoltaique_sol ips
            ),
        escosol_joined as (
        SELECT
            ep.*,
            ST_AsWKB(ep.geom_proj) as geom_proj_wkb,
            o.id,
            o.millesime as millesime_ocs,
            o.code_us,
            o.the_geom as ocs_geom,
            ST_AsWKB(o.the_geom) as ocs_geom_wkb,
            ST_Intersection(ep.geom_proj,o.the_geom) as geom_intersection,
            ST_AsWKB(ST_Intersection(ep.geom_proj,o.the_geom)) as geom_intersection_wkb
        from
            escosol_projected ep
        left join ocs o on ST_INTERSECTS(ep.geom_proj,o.the_geom))
        SELECT
        	ej.*,
            st_area(ej.geom_proj) as project_geom_area,
            st_area(ej.ocs_geom) as ocs_geom_area,
            ST_area(ej.geom_intersection) as geom_intersection_area
        from escosol_joined ej
        """,
        engine=con
    )
    return (df_link,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Analyse des liens entres parcs et OCS :
    """)
    return


@app.cell
def _(df_link, pl):
    df_link_filtered = df_link.filter(
        (pl.col("millesime") > pl.col("millesime_ocs")) | pl.col("id_1").is_null()
    ).filter(
        (
            (
                pl.col("millesime_ocs")
                .rank(descending=True)
                .over(partition_by=["id", "id_1"], order_by="millesime_ocs")
                == 1
            ) # Uniquement les données OCS les plus récentes mais jamais plus que le millésime des données photovolat_iques
        )
        | pl.col("id_1").is_null()
    )
    return (df_link_filtered,)


@app.cell
def _(mo):
    mo.md(r"""
    Est-ce que tous les parcs ont des correspondances dans le jeu de données OCS ?
    """)
    return


@app.cell
def _(df_link_filtered, pl):
    df_link_filtered.group_by("id").agg(
        (pl.col("id_1").count() > 0).alias("has_ocs")
    ).select(pl.col("has_ocs").value_counts().struct.unnest())
    return


@app.cell
def _(mo):
    mo.md(r"""
    3 parcs n'en ont pas :
    """)
    return


@app.cell
def _(df_link_filtered, pl):
    df_link_filtered.filter(pl.col("id_1").is_null())
    return


@app.cell
def _(Transformer, folium, pl, shapely, wkb):
    def create_map(
        df: pl.DataFrame, geom_colname: str, project: bool = False
    ) -> folium.Map:
        m = folium.Map(zoom_start=6, tiles="OpenStreetMap")
        for row in df.iter_rows(
            named=True
        ):
            geom_shapely = wkb.loads(row[geom_colname])
            if project:
                transformer = Transformer.from_crs(
                    row["geom_original_referential"], 4326
                )
                geom_shapely = shapely.transform(
                    geom_shapely, transformer.transform, interleaved=False
                )
            folium.Polygon(shapely.get_coordinates(geom_shapely),popup=row["id"]).add_to(m)
        return m
    return


@app.cell
def _(mo):
    mo.md(r"""
    #### Vérification des surfaces :
    """)
    return


@app.cell
def _(df_link_filtered, pl):
    # Verification des surfaces

    df_link_filtered.group_by("id").agg(
        pl.col("insee_com"),
        pl.col("surf_parc").max(),
        pl.col("project_geom_area").max(),
        pl.col("ocs_geom_area"),
        pl.len().alias("num_lines"),
        pl.col("id_1").n_unique().alias("num_unique_ocs_tiles"),
        pl.col("geom_intersection_area").sum(),
    ).with_columns(
        (
            (pl.col("surf_parc") - pl.col("geom_intersection_area"))
            / pl.col("surf_parc")
        ).alias("area_error"),
        (
            (pl.col("project_geom_area") - pl.col("geom_intersection_area"))
            / pl.col("project_geom_area")
        ).alias("area_geom_error"),
    ).sort(pl.col("area_geom_error").abs(), descending=True)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Statistiques sur les usages
    """)
    return


@app.cell
def _():
    CODES_US_MAPPING = {
        "US1.1": "Agriculture",
        "US1.2": "Sylviculture",
        "US1.3": "Activités d’extraction",
        "US1.4": "Pêche et aquaculture",
        "US1.5": "Autres productions primaires",
        "US2": "Production secondaire",
        "US235": "Usage mixte ",
        "US3": "Production tertiaire",
        "US4.1.1": "Réseaux routiers",
        "US4.1.2": "Réseaux ferrés ",
        "US4.1.3": "Réseaux aériens ",
        "US4.1.4": "Réseaux de transport fluvial et maritime",
        "US4.1.5": "Autres réseaux de transport",
        "US4.2": "Services de logistique et de stockage",
        "US4.3": "Réseaux d'utilité publique",
        "US5": "Usage résidentiel ",
        "US6.1": "Zones en transition",
        "US6.2": "Zones abandonnées",
        "US6.3": "Sans usage",
        "US6.6": "Usage inconnu ",
    }

    CODES_US_COLOR_MAPPING = {
        "US1.1": "#ffffa8",
        "US1.2": "#008000",
        "US1.3": "#a700cc",
        "US1.4": "#000099",
        "US1.5": "#996633",
        "US2": "#e5e5e5",
        "US235": "#e6004d",
        "US3": "#ff8c00",
        "US4.1.1": "#cc0000",
        "US4.1.2": "#5a5a5a",
        "US4.1.3": "#e6cce6",
        "US4.1.4": "#0066ff",
        "US4.1.5": "#660033",
        "US4.2": "#ff0000",
        "US4.3": "#ff4d00",
        "US5": "#be0960",
        "US6.1": "#ff4dff",
        "US6.2": "#404040",
        "US6.3": "#f0f028",
        "US6.6": "#ffcc00",
    }
    return CODES_US_COLOR_MAPPING, CODES_US_MAPPING


@app.cell
def _(CODES_US_MAPPING, df_link_filtered, pl):
    df_code_us_by_surface = pl.concat(
        [
            df_link_filtered.with_columns(
                pl.col("code_us").fill_null(pl.lit("Code US inconnu"))
            )
            .group_by(["id", "code_us"])
            .agg(
                pl.col("geom_intersection_area").sum().alias("surface"),
            ),
            # Reste de surface sans correspondance avec une géométrie OCS :
            df_link_filtered.with_columns(
                pl.col("code_us").fill_null(pl.lit("Code US inconnu"))
            )
            .group_by(["id"])
            .agg(
                (
                    pl.col("project_geom_area").max()
                    - pl.col("geom_intersection_area").sum()
                )
                .sum()
                .alias("surface"),
            )
            .with_columns(pl.lit("Sans correspondance").alias("code_us"))
            .select(["id", "code_us", "surface"]),
        ],
        how="vertical_relaxed",
    ).group_by("code_us").agg(pl.col("surface").sum()).with_columns(
        pl.col("code_us").replace(CODES_US_MAPPING),
        (100*pl.col("surface")/pl.col("surface").sum()).alias("% de la surface")
    ).sort("surface",descending=True)
    df_code_us_by_surface
    return (df_code_us_by_surface,)


@app.cell
def _(df_code_us_by_surface, px):
    px.bar(
        df_code_us_by_surface,
        x="code_us",
        y="% de la surface",
        template="simple_white",
        text="% de la surface",
        text_auto=".2f",
        labels={
            "code_us": "Usage du sol occupé"
        },
        title = "Sur quels types d'occupation des sols les parcs phtovoltaïques sont-ils installés ?"
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Carte
    """)
    return


@app.cell
def _(
    CODES_US_COLOR_MAPPING,
    CODES_US_MAPPING,
    Transformer,
    df_link_filtered,
    folium,
    json,
    shapely,
):
    polygons = []
    ids_already_added = []
    for data in df_link_filtered.iter_rows(named=True):
        codes_insee = data["insee_com"]
    
        ocs_geom_wkb = data["geom_intersection_wkb"]
        transformer = Transformer.from_crs(
            data["geom_original_referential"], 4326, always_xy=True
        )

        if ocs_geom_wkb is not None:
            geom_ocs = shapely.from_wkb(ocs_geom_wkb)
            geom_ocs_4326 = shapely.transform(
                geom_ocs, transformer.transform, interleaved=False
            )
            color = CODES_US_COLOR_MAPPING.get(data["code_us"], "#b15928")
            description_us = CODES_US_MAPPING.get(data["code_us"], "Inconnu")
            geom_ocs_4326_geojson = json.loads(shapely.to_geojson(geom_ocs_4326))
            geom_ocs_4326_geojson_clean = {
                "type": "Feature",
                "geometry": geom_ocs_4326_geojson,
                "properties": {
                    "popup": f"{data['id_1']} | {description_us} - Surface partagée : {data['geom_intersection_area']}m^2"
                },
            }
            polygon_ocs = folium.GeoJson(
                geom_ocs_4326_geojson_clean,
                style_function=lambda feature: {
                    "fillColor": color,
                    "color": color,
                    "fill_opacity": 0.3,
                    "stroke":False,
                },
                popup=folium.GeoJsonPopup(fields=["popup"], labels=False),
                highlight_function=lambda feature: {
                    "color": "grey",
                    "stroke": True,
                },
                popup_keep_highlighted=True,
            )
            polygons.append(polygon_ocs)

        if not data["id"] in ids_already_added:
            geom_photo = shapely.from_wkb(data["geom_proj_wkb"])

            geom_photo_4326 = shapely.transform(
                geom_photo, transformer.transform, interleaved=False
            )
            geom_photo_4326_geojson = json.loads(shapely.to_geojson(geom_photo_4326))
            geom_photo_4326_geojson_clean = {
                "type": "Feature",
                "geometry": geom_photo_4326_geojson,
                "properties": {
                    "popup": f"{data['id']} | Surface totale : {data['surf_parc']} - Surace partagée : {data['geom_intersection_area']}m^2"
                },
            }

            polygon_photo = folium.GeoJson(
                geom_photo_4326_geojson_clean,
                fill_opacity=0.3,
                style_function=lambda feature: {
                    "color": "#f39c12",
                    "weight":4,
                    "fill":False
                },
                popup=folium.GeoJsonPopup(fields=["popup"], labels=False),
                highlight_function=lambda feature: {
                    "color": "red",
                    "stroke": True,
                    "fill":False
                },
            )
            polygons.append(polygon_photo)
            ids_already_added.append(data["id"])

    map_link = folium.Map(
        location=[46.2, 2.21],
        zoom_start=6,
        tiles="GeoportailFrance.orthos",
    )

    for polygon in polygons:
        polygon.add_to(map_link)

    map_link.save("map.html")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Données ODRE
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    #### Création de la table
    """)
    return


@app.cell
def _(con, mo):
    _df = mo.sql(
        f"""
        CREATE table if not exists registre_installations as
        from
            'https://object.files.data.gouv.fr/hydra-parquet/hydra-parquet/c14e5a7d-2ca6-4ad8-bc61-93889d13fc25.parquet'
        """,
        engine=con
    )
    return


@app.cell
def _(con, mo, registre_installations):
    _df = mo.sql(
        f"""
        SUMMARIZE registre_installations
        """,
        engine=con
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    #### Filtre sur les installations solaires
    """)
    return


@app.cell
def _(con, mo, registre_installations):
    df_registre_installations = mo.sql(
        f"""
        SELECT
            *
        from
            registre_installations
        where
            filiere = 'Solaire';
        """,
        engine=con
    )
    return (df_registre_installations,)


@app.cell
def _(df_registre_installations, pl):
    df_registre_installations.group_by("technologie").agg(pl.len())
    return


if __name__ == "__main__":
    app.run()
