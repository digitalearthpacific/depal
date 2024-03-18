import os
from pathlib import Path
import geopandas as gpd
import pandas as pd
import pystac_client as pystac
import planetary_computer as pc
from pystac.extensions.projection import ProjectionExtension as proj
from pystac.extensions.item_assets import ItemAssetsExtension
import numpy as np
import xarray as xr
import xrspatial.multispectral as ms
from xrspatial.focal import mean, focal_stats, hotspots
import stackstac
from dask_gateway import GatewayCluster
from dask.distributed import Client
from dask.distributed import LocalCluster
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from collections import OrderedDict
from shapely.geometry import shape
import rioxarray
from rasterio.crs import CRS
from rasterio.plot import show
import rasterio.features
import itertools
import cartopy.crs as ccrs

import dask.array as da
import joblib
import xarray as xr
from dask_ml.wrappers import ParallelPostFit
from datacube.utils.geometry import assign_crs
from geopandas import GeoDataFrame
from odc.stac import load
from pandas import Series
from planetary_computer import sign_url
from pystac_client import Client
from xarray import Dataset
import glob

country = "Fiji"
DEP_CATALOG = "https://stac.staging.digitalearthpacific.org"
MSPC_CATALOG = "https://planetarycomputer.microsoft.com/api/stac/v1/"

chunks: dict = dict(x=2048, y=2048)
#chunks: dict = dict(x=100, y=100)

pd.set_option("display.max_rows", 200)
gdf_islands = gpd.read_file(Path(__file__).parent / "Fiji/fj_islands.geojson")
gdf_fj_adm = gpd.read_file(Path(__file__).parent / "Fiji/fj_adm.gpkg")

def list_islands():
    gdf_islands.sort_values(by=['area'], inplace=True)
    return pd.DataFrame(gdf_islands["area"].tolist())

# AOI from Island
def get_island(name):
    aoi = gdf_islands[gdf_islands["area"] == name]
    return aoi.geometry
    #return aoi.dissolve().geometry
    
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

#BBOX from Area Of Interest (AOI)
def get_bbox(aoi):
    bbox = rasterio.features.bounds(aoi)
    return bbox

#indicies
def get_annual_rgb(aoi, year):
    bands=["B04", "B03", "B02"]
    bbox = rasterio.features.bounds(aoi)
    client = Client.open(DEP_CATALOG)
    items = client.search(
        collections=["dep_s2_geomad"],
        bbox=bbox,
        datetime=str(year)
    ).items()
    data = load(items, bands=bands, chunks=chunks, bbox=bbox, resolution=10).squeeze("time")
    return data

def plot_rgb(data):
    bands=["B04", "B03", "B02"]
    da = data[bands].to_array().compute()
    plot = da.plot.imshow(x="x", y="y", robust=True, size=10)
    return plot

def get_ndvi(aoi): #2017-2024
    pass




#ML Utils
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
    return  pd.DataFrame(glob.glob("Fiji/fj_lulc_data*"))