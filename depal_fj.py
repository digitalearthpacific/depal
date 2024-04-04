import glob
import itertools
import warnings
from pathlib import Path

import dask.array as da
import geopandas as gpd
import joblib
import pandas as pd
import rasterio.features
import rioxarray
import xarray as xr
from dask_ml.wrappers import ParallelPostFit
from datacube.utils.geometry import assign_crs
from geopandas import GeoDataFrame
from odc.stac import load
from pandas import Series
from pystac_client import Client
from xarray import Dataset

warnings.filterwarnings("ignore")

country = "Fiji"
DEP_CATALOG = "https://stac.staging.digitalearthpacific.org"
MSPC_CATALOG = "https://planetarycomputer.microsoft.com/api/stac/v1/"

chunks: dict = dict(x=2048, y=2048)
# chunks: dict = dict(x=100, y=100)

pd.set_option("display.max_rows", 200)
gdf_islands = gpd.read_file(Path(__file__).parent / "Fiji/fj_islands.geojson")
gdf_fj_adm = gpd.read_file(Path(__file__).parent / "Fiji/fj_adm.gpkg")


def list_islands():
    gdf_islands.sort_values(by=["area"], inplace=True)
    return pd.DataFrame(gdf_islands["area"].tolist())


# AOI from Island
def get_island(name):
    aoi = gdf_islands[gdf_islands["area"] == name]
    return aoi.geometry
    # return aoi.dissolve().geometry


def list_divisions():
    admin_type = "Division"
    return list_country_boundary(admin_type)


def list_provinces():
    admin_type = "Province"
    return list_country_boundary(admin_type)


# AOI from Province
def get_province(admin_name):
    return get_country_admin_boundary("Province", admin_name)


# AOI from Division
def get_division(admin_name):
    return get_country_admin_boundary("Division", admin_name)


def list_country_boundary(admin_type):
    cadm = gdf_fj_adm[gdf_fj_adm["country"] == country]
    admin_types = (
        cadm["type_1"].unique().tolist()
        + cadm["type_2"].unique().tolist()
        + cadm["type_3"].unique().tolist()
    )
    admin_types = list(itertools.filterfalse(lambda x: x == "", admin_types))
    idx = admin_types.index(admin_type) + 1
    data = cadm["name_" + str(idx)].unique().tolist()
    return pd.DataFrame(data)


# AOI from Country Administrative Boundary
def get_country_admin_boundary(admin_type, admin_name):
    cadm = gdf_fj_adm[gdf_fj_adm["country"] == country]
    admin_types = (
        cadm["type_1"].unique().tolist()
        + cadm["type_2"].unique().tolist()
        + cadm["type_3"].unique().tolist()
    )
    admin_types = list(itertools.filterfalse(lambda x: x == "", admin_types))
    idx = admin_types.index(admin_type) + 1
    aadm = cadm[cadm["name_" + str(idx)] == admin_name]
    return aadm.dissolve().geometry


def list_boundary_types():
    cadm = gdf_fj_adm[gdf_fj_adm["country"] == country]
    data = (
        cadm["type_1"].unique().tolist()
        + cadm["type_2"].unique().tolist()
        + cadm["type_3"].unique().tolist()
    )
    data = list(itertools.filterfalse(lambda x: x == "", data))
    return pd.DataFrame(data)


# AOI from GeoJson File (use geojson.io)
def get_area_from_geojson(geojson_file):
    local = gpd.read_file(geojson_file)
    area_of_interest = local
    return area_of_interest


# AOI from a Country Nation Boundary
def get_national_boundary():
    cadm = gdf_fj_adm[gdf_fj_adm["country"] == country]
    return cadm.dissolve().geometry


# BBOX from Area Of Interest (AOI)
def get_bbox(aoi):
    bbox = rasterio.features.bounds(aoi)
    return bbox


def get_annual_rgb(aoi: gpd.GeoSeries, year: str) -> xr.Dataset:
    # Use the geometry in the search and load functions
    geometry = aoi.geometry[0]
    bands = ["B04", "B03", "B02"]
    client = Client.open(DEP_CATALOG)

    # Search for items
    items = list(
        client.search(
            collections=["dep_s2_geomad"], intersects=geometry, datetime=str(year)
        ).items()
    )

    # Load those items
    data = load(
        items, bands=bands, chunks=chunks, geopolygon=geometry, resolution=100
    ).squeeze("time")

    return data


def plot_rgb(data):
    bands = ["B04", "B03", "B02"]
    da = data[bands].to_array().compute()
    plot = da.plot.imshow(x="x", y="y", robust=True, size=10)
    return plot


# NDVI (Normalised Difference Vegetation Index) = (NIR-red)/(NIR+red)
def get_ndvi(aoi, year="2017-01-01/2024-12-31"):  # 2017-2024
    bands = ["B04", "B08"]
    bbox = rasterio.features.bounds(aoi)
    client = Client.open(DEP_CATALOG)
    items = client.search(
        collections=["dep_s2_geomad"], bbox=bbox, datetime=year
    ).items()
    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=100)
    data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
    data = (data["B08"] - data["B04"]) / (data["B08"] + data["B04"])
    return data


# EVI Enhanced Vegetation Index
def get_evi(aoi, year="2017-01-01/2024-12-31"):  # 2017-2024
    bands = ["B04", "B08", "B02"]
    bbox = rasterio.features.bounds(aoi)
    client = Client.open(DEP_CATALOG)
    items = client.search(
        collections=["dep_s2_geomad"], bbox=bbox, datetime=year
    ).items()
    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=100)
    data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
    data = (2.5 * (data["B08"] - data["B04"])) * (
        data["B08"] + (6 * (data["B04"]) - (7.5 * (data["B02"])))
    ) + 1
    return data


# MNDWI (Mean Normalised Difference Water Index) = (Green – SWIR) / (Green + SWIR)
def get_mndwi(aoi, year="2017-01-01/2024-12-31"):  # 2017-2024
    bands = ["B03", "B12"]
    bbox = rasterio.features.bounds(aoi)
    client = Client.open(DEP_CATALOG)
    items = client.search(
        collections=["dep_s2_geomad"], bbox=bbox, datetime=year
    ).items()
    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=100)
    data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
    data = (data["B03"] - data["B12"]) / (data["B03"] + data["B12"])
    return data


# NDMI (Normalised Difference Moisture Index)
def get_ndmi(aoi, year="2017-01-01/2024-12-31"):  # 2017-2024
    bands = ["B08", "B11"]
    bbox = rasterio.features.bounds(aoi)
    client = Client.open(DEP_CATALOG)
    items = client.search(
        collections=["dep_s2_geomad"], bbox=bbox, datetime=year
    ).items()
    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=100)
    data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
    data = ((data["B08"]) - (data["B11"])) / ((data["B08"]) + (data["B11"]))
    return data


# BSI - Bare Soil Index
def get_bsi(aoi, year="2017-01-01/2024-12-31"):  # 2017-2024
    bands = ["B08", "B11"]
    bbox = rasterio.features.bounds(aoi)
    client = Client.open(DEP_CATALOG)
    items = client.search(
        collections=["dep_s2_geomad"], bbox=bbox, datetime=year
    ).items()
    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=100)
    data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
    data = ((data["B08"]) - (data["B11"])) / ((data["B08"]) + (data["B11"]))
    return data


# NDBI (Normalised Difference Built-up Index) (B06 - B05) / (B06 + B05); # - built up ratio of vegetation to paved surface
def get_ndbi(aoi, year="2017-01-01/2024-12-31"):  # 2017-2024
    bands = ["B05", "B06"]
    bbox = rasterio.features.bounds(aoi)
    client = Client.open(DEP_CATALOG)
    items = client.search(
        collections=["dep_s2_geomad"], bbox=bbox, datetime=year
    ).items()
    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=100)
    data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
    data = ((data["B06"]) - (data["B05"])) / ((data["B06"]) + (data["B05"]))
    return data


# SAVI (Standard Vegetation Index) = (800nm−670nm) / (800nm+670nm+L(1+L)) # where L = 0.5
def get_savi(aoi, year="2017-01-01/2024-12-31"):  # 2017-2024
    bands = ["B04", "B07"]
    bbox = rasterio.features.bounds(aoi)
    client = Client.open(DEP_CATALOG)
    items = client.search(
        collections=["dep_s2_geomad"], bbox=bbox, datetime=year
    ).items()
    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=100)
    data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
    data = (data["B07"] - data["B04"]) / (data["B07"] + data["B04"] + 0.5 * (1 + 0.5))
    return data
    # let index = (B08 - B01) / (B08 - B04);


# SIPI (Structure Insensitive Pigment Index) = (800nm−670nm) / (800nm+670nm+L(1+L)) # where L = 0.5
# def get_sipi(aoi, year="2017-01-01/2024-12-31"): #2017-2024
#    bands = ["B08", "B01", "B04"]
#    bbox = rasterio.features.bounds(aoi)
#    client = Client.open(DEP_CATALOG)
#    items = client.search(
#        collections=["dep_s2_geomad"],
#        bbox=bbox,
#        datetime=year
#    ).items()
#    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=100)
#    data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
#    data = (data["B08"] - data["B01"]) / (data["B08"] - data["B04"])
#    return data


# timeseries plotting of indicies
def plot(data, cmap="viridis"):  # RdYlGn #
    data.plot.imshow(x="x", y="y", col="time", col_wrap=3, cmap=cmap, robust=True)


def save_single(data, file_name):
    # data = data.transpose("time", "band", "y", "x").squeeze()
    data.rio.to_raster(file_name + ".tif", driver="COG")


# Save Multiple Outputs as GeoTIFF/COG Series
def save_multiple(data, file_name):
    # data = data.transpose("time", "band", "y", "x").squeeze()
    for idx, x in enumerate(data):
        x.rio.to_raster(file_name + "_" + str(idx) + ".tif", driver="COG")


# ML Utils
def get_image_values(points: GeoDataFrame, data: Dataset) -> GeoDataFrame:
    """Get values for each of the image bands at each of the points."""
    # Reproject points to the same CRS as the data
    points_projected = points.to_crs(data.odc.crs)

    # Convert points geodataframe to a DataArray with x & y coords
    points_da = points_projected.assign(
        x=points_projected.geometry.x, y=points_projected.geometry.y
    ).to_xarray()

    # a dataframe or series (for a single point)
    variables = (
        data.sel(points_da[["x", "y"]], method="nearest")
        .squeeze()
        .compute()
        .to_pandas()
    )

    if isinstance(variables, Series):
        variables = variables.to_frame().transpose()
        variables.index = points.index

    return variables


def predict_xr(
    model, input_xr, chunk_size=None, persist=False, proba=False, clean=False
):
    """
    Predict using a scikit-learn model on an xarray dataset.

    Shamelessly ripped from dea_tools
    """
    # if input_xr isn't dask, coerce it
    dask = True
    if not bool(input_xr.chunks):
        dask = False
        input_xr = input_xr.chunk({"x": len(input_xr.x), "y": len(input_xr.y)})

    # set chunk size if not supplied
    if chunk_size is None:
        chunk_size = int(input_xr.chunks["x"][0]) * int(input_xr.chunks["y"][0])

    def _predict_func(model, input_xr, persist, proba, clean):
        x, y, crs = input_xr.x, input_xr.y, input_xr.geobox.crs

        input_data = []

        variables = list(input_xr.data_vars)
        variables.sort()

        for var_name in variables:
            input_data.append(input_xr[var_name])

        input_data_flattened = []

        for arr in input_data:
            data = arr.data.flatten().rechunk(chunk_size)
            input_data_flattened.append(data)

        # reshape for prediction
        input_data_flattened = da.array(input_data_flattened).transpose()

        if clean is True:
            input_data_flattened = da.where(
                da.isfinite(input_data_flattened), input_data_flattened, 0
            )

        if (proba is True) & (persist is True):
            # persisting data so we don't require loading all the data twice
            input_data_flattened = input_data_flattened.persist()

        # apply the classification
        print("predicting...")
        out_class = model.predict(input_data_flattened)

        # Mask out NaN or Inf values in results
        if clean is True:
            out_class = da.where(da.isfinite(out_class), out_class, 0)

        # Reshape when writing out
        out_class = out_class.reshape(len(y), len(x))

        # stack back into xarray
        output_xr = xr.DataArray(out_class, coords={"x": x, "y": y}, dims=["y", "x"])

        output_xr = output_xr.to_dataset(name="predictions")

        if proba is True:
            print("   probabilities...")
            out_proba = model.predict_proba(input_data_flattened)

            # convert to %
            out_proba = da.max(out_proba, axis=1) * 100.0

            if clean is True:
                out_proba = da.where(da.isfinite(out_proba), out_proba, 0)

            out_proba = out_proba.reshape(len(y), len(x))

            out_proba = xr.DataArray(
                out_proba, coords={"x": x, "y": y}, dims=["y", "x"]
            )
            output_xr["probabilities"] = out_proba

        return assign_crs(output_xr, str(crs))

    if dask is True:
        # convert model to dask predict
        model = ParallelPostFit(model)
        with joblib.parallel_backend("dask"):
            output_xr = _predict_func(model, input_xr, persist, proba, clean)

    else:
        output_xr = _predict_func(model, input_xr, persist, proba, clean).compute()

    return output_xr


def do_coastal_clip(aoi, data, buffer=0):
    buffer = 0.001 * buffer  # 100 metres
    aoi = aoi.buffer(buffer)
    clipped = data.rio.clip(aoi.to_crs(data.rio.crs), all_touched=True)
    return clipped


def list_data_points():
    return pd.DataFrame(glob.glob("Fiji/fj_lulc_data*"))


def get_stats(tif_file, aoi):
    da = rioxarray.open_rasterio(tif_file)
    ds = da.to_dataset("band")
    ds = ds.rename({1: "class_id"})
    ds = do_coastal_clip(aoi, ds, buffer=0)
    da = ds.to_array().compute()
    summary = da.groupby(da).count().compute()
    summary = summary.to_pandas()
    summary = summary.drop(0)
    summary = summary.to_frame()
    df = summary
    df.rename(columns={0: "class_count"}, inplace=True)
    total = df.sum().to_numpy()[0]
    df["percent"] = (df["class_count"] / total) * 100
    df["class"] = ""
    df.loc[df.index == 1, "class"] = "Cropland"
    df.loc[df.index == 2, "class"] = "Forest"
    df.loc[df.index == 3, "class"] = "Grassland"
    df.loc[df.index == 4, "class"] = "Settlement"
    df.loc[df.index == 5, "class"] = "Mangroves/Wetland"
    df.loc[df.index == 6, "class"] = "Water"
    df.loc[df.index == 7, "class"] = "Bareland/Other"
    df = df[["class", "class_count", "percent"]]
    return df
