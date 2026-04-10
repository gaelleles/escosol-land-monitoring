import os

import marimo as mo
import duckdb
import polars as pl

from sklearn.cluster import DBSCAN
from geopy.distance import distance
import shapely


def get_centroid_coords(p) -> tuple[float, float]:
    p_centroid = shapely.from_wkb(p).centroid

    return (p_centroid.y, p_centroid.x)


def distance_func(row_1, row_2) -> float:
    d = distance((row_1[1], row_1[2]), (row_2[1], row_2[2])).km

    return d


def main():
    DATABASE_URL = os.environ["DATABASE_PATH"]
    engine = duckdb.connect(DATABASE_URL, read_only=False)

    df_photo = engine.sql(
        """
        SELECT * from ign_photo
        """,
    ).pl()

    df_photo_with_centroid = df_photo.with_columns(
        pl.col("geom")
        .map_elements(get_centroid_coords, return_dtype=pl.Array(pl.Float64, 2))
        .alias("centroid")
    )

    estimator = DBSCAN(eps=1, metric=distance_func, min_samples=2, n_jobs=-1)

    X = df_photo_with_centroid.select(
        "id",
        pl.col("centroid").arr.get(0).alias("latitude"),
        pl.col("centroid").arr.get(1).alias("longitude"),
    ).to_pandas()
    labels = estimator.fit_predict(X)

    df_photo_with_centroid = df_photo_with_centroid.with_columns(
        pl.lit(labels).alias("labels")
    )

    engine.sql(
        "CREATE OR REPLACE TABLE ign_photo_cluster as (select * from df_photo_with_centroid)"
    )


if __name__ == "__main__":
    main()
