"""depal.py: Digital Earth Pacific (Abstration Library)"""

__author__ = "Sachindra Singh"
__copyright__ = "Pacific Community (SPC)"
__license__ = "GPL"
__version__ = "0.0.1"
__email__ = "sachindras@spc.int"
__status__ = "Development"

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
import rioxarray
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
from odc.stac import load
from flox.xarray import xarray_reduce
import warnings

warnings.filterwarnings("ignore")


# Global
padm = gpd.read_file(Path(__file__).parent / "padm.gpkg", layer="padm")
catalog = pystac.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace
)
pd.set_option("display.max_rows", None)
pd.set_option("display.max_colwidth", None)
default_resolution = 10
default_max = 500
chunk_size = 4096
cluster = None
client = None


# Initialise and Configure Dask and Resolution Defaults
def init(maxWorkers=8):
    from dask_gateway import Gateway

    global cluster
    global client
    gateway = Gateway(auth="jupyterhub")
    options = gateway.cluster_options()
    options.image = "ghcr.io/digitalearthpacific/dep-analytics-lab-image:latest"
    options.worker_cores = maxWorkers
    options.worker_memory = 12
    cluster = gateway.new_cluster()
    client = cluster.get_client()
    cluster.adapt(minimum=1, maximum=maxWorkers)
    print(client)
    print(cluster.dashboard_link)


def init_old(type="remote", maxWorkers=4, resolution=10):
    print("Initiating DEPAL...")
    default_resolution = resolution
    global cluster
    global client
    if type == "local":
        cluster = LocalCluster()
        client = Client(cluster)
    if type == "remote":
        cluster = GatewayCluster()
        client = cluster.get_client()
        cluster.adapt(minimum=1, maximum=maxWorkers)
    print(client)
    print(cluster.dashboard_link)


# Cleanup Dask Resources
def cleanup():
    cluster.close()


# AOI from GeoJson File (use geojson.io)
def get_area_from_geojson(geojson_file):
    local = gpd.read_file(geojson_file)
    area_of_interest = local
    return area_of_interest


# List Pacific Island Countries and Territories
def list_countries():
    return pd.DataFrame(padm["country"].unique().tolist())


# List Administrative Boundaries In a Country
def list_boundary_types(country):
    cadm = padm[padm["country"] == country]
    data = (
        cadm["type_1"].unique().tolist()
        + cadm["type_2"].unique().tolist()
        + cadm["type_3"].unique().tolist()
    )
    data = list(itertools.filterfalse(lambda x: x == "", data))
    return pd.DataFrame(data)


# List Areas/Locations of a Administration Type Within A Country
def list_country_boundary(country, admin_type):
    cadm = padm[padm["country"] == country]
    admin_types = (
        cadm["type_1"].unique().tolist()
        + cadm["type_2"].unique().tolist()
        + cadm["type_3"].unique().tolist()
    )
    admin_types = list(itertools.filterfalse(lambda x: x == "", admin_types))
    idx = admin_types.index(admin_type) + 1
    data = cadm["name_" + str(idx)].unique().tolist()
    return pd.DataFrame(data)


# AOI from a Country Nation Boundary
def get_country_boundary(country):
    cadm = padm[padm["country"] == country]
    return cadm.dissolve().geometry


# BBOX from Area Of Interest (AOI)
def get_bbox(aoi):
    bbox = rasterio.features.bounds(aoi)
    return bbox


# AOI from Country Administrative Boundary
def get_country_admin_boundary(country, admin_type, admin):
    cadm = padm[padm["country"] == country]
    admin_types = (
        cadm["type_1"].unique().tolist()
        + cadm["type_2"].unique().tolist()
        + cadm["type_3"].unique().tolist()
    )
    admin_types = list(itertools.filterfalse(lambda x: x == "", admin_types))
    idx = admin_types.index(admin_type) + 1
    aadm = cadm[cadm["name_" + str(idx)] == admin]
    return aadm.dissolve().geometry


# List Data Sources, Pipelines and Models
def list_data_sources():
    collections = catalog.get_children()
    data = {}
    for c in collections:
        data[c.id] = c.title
    data = dict(OrderedDict(sorted(data.items())))
    return pd.DataFrame(data.items())


# List Data Bands and Common Names within a Data Source, Pipeline or Sensor
def list_data_bands(collection_name="sentinel-2-l2a"):
    collection = catalog.get_child(collection_name)
    return pd.DataFrame.from_dict(
        collection.summaries.lists["eo:bands"]
    )  # (collection.extra_fields["summaries"]["eo:bands"])


# List Data Assets (non-spectral) and Common Names within a Data Source, Pipeline or Sensor
def list_data_assets(collection_name):
    collection = catalog.get_child(collection_name)
    data = pd.DataFrame.from_dict(
        collection.extra_fields["item_assets"], orient="index"
    )[["title", "description"]]
    return data


# Xarray Dataset from STAC by Period Yearly, Quarterly, Monthly, Weekly, Daily
def get_data(
    aoi,
    bands=[],
    collection_name="sentinel-2-l2a",
    timeframe="2023-01-01/2023-12-31",
    cloudcover=10,
    resolution=default_resolution,
    max=max,
    period="monthly",
    coastal_clip=False,
):
    bbox = rasterio.features.bounds(aoi)
    search = catalog.search(
        bbox=bbox,
        datetime=timeframe,
        collections=[collection_name],
        max_items=max,
        query={"eo:cloud_cover": {"lt": cloudcover}},
    )
    items = search.item_collection()
    listing = []
    for i in items:
        listing.append(i.datetime.strftime("%m/%d/%Y %H:%M:%S"))
    print(listing)
    print("Images Found    : " + str(len(items)))

    # epsg
    item = next(search.get_items())
    epsg = proj.ext(item).epsg
    data = (
        stackstac.stack(
            items,
            assets=bands,
            epsg=epsg,
            bounds_latlon=bbox,
            chunksize=chunk_size,
            resolution=resolution,
            sortby_date=True,
        )
        .where(lambda x: x > 0, other=np.nan)  # sentinel-2 uses 0 as nodata
        .assign_coords(
            band=lambda x: x.common_name.rename("band"),  # use common names
            time=lambda x: x.time.dt.round("D"),
        )
    )

    # resampling and grouping
    # data = data.groupby("time." + period).median(keep_attrs=True).compute()
    print("Analysis Period : " + period)
    if period == "yearly":
        data = data.resample(time="1AS").median("time", keep_attrs=True).compute()
    if period == "quarterly":
        data = data.resample(time="1QS").median("time", keep_attrs=True).compute()
    if period == "monthly":
        data = data.resample(time="1MS").median("time", keep_attrs=True).compute()
    if period == "weekly":
        data = data.resample(time="1W").median("time", keep_attrs=True).compute()
    # if period == "daily":
    #    data = data.resample(time="1D").median("time", keep_attrs=True).compute()

    if coastal_clip == True:
        data = do_coastal_clip(aoi, data)

    return data


# Latest RGB Images
def get_latest_images(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2024-01-01/2024-12-31",
    cloudcover=10,
    resolution=default_resolution,
    max=default_max,
    period="daily",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        bands=["B04", "B03", "B02"],
        collection_name=collection_name,
        timeframe=timeframe,
        cloudcover=cloudcover,
        resolution=resolution,
        max=max,
        period=period,
        coastal_clip=coastal_clip,
    )
    true_color_aggs = [
        ms.true_color(x.sel(band="red"), x.sel(band="green"), x.sel(band="blue"))
        for x in data
    ]
    true_color = xr.concat(true_color_aggs, dim=data.coords["time"])
    true_color = true_color.drop_duplicates(dim="time")
    true_color = true_color.squeeze()
    return true_color


# median composite - Cloudless Mosaic achieved combining images across time
def get_cloudless_mosaic(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=default_max,
    period="yearly",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        bands=["B04", "B03", "B02"],
        collection_name=collection_name,
        timeframe=timeframe,
        cloudcover=cloudcover,
        resolution=resolution,
        max=max,
        period=period,
        coastal_clip=coastal_clip,
    )
    median_aggs = [
        ms.true_color(x.sel(band="red"), x.sel(band="green"), x.sel(band="blue"))
        for x in data
    ]
    median_composite = xr.concat(median_aggs, dim=data.coords["time"])  # dim="time")
    return median_composite


# ndvi - Normalised Difference Vegetation Index
def get_ndvi(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=default_max,
    period="monthly",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        bands=["B08", "B04"],
        collection_name=collection_name,
        timeframe=timeframe,
        cloudcover=cloudcover,
        resolution=resolution,
        max=max,
        period=period,
        coastal_clip=coastal_clip,
    )
    median_aggs = [ms.ndvi(x.sel(band="nir"), x.sel(band="red")) for x in data]
    ndvi = xr.concat(median_aggs, dim="time")
    return ndvi


# evi - Enhanced Vegetation
def get_evi(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=default_max,
    period="monthly",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        bands=["B08", "B02", "B04"],
        collection_name=collection_name,
        timeframe=timeframe,
        cloudcover=cloudcover,
        resolution=resolution,
        max=max,
        period=period,
        coastal_clip=coastal_clip,
    )
    median_aggs = [
        ms.evi(x.sel(band="nir"), x.sel(band="red"), x.sel(band="blue")) for x in data
    ]
    evi = xr.concat(median_aggs, dim="time")
    return evi


# gci - Green Chlorophyll Index
def get_gci(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=default_max,
    period="monthly",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        bands=["B08", "B03"],
        collection_name=collection_name,
        timeframe=timeframe,
        cloudcover=cloudcover,
        resolution=resolution,
        max=max,
        period=period,
        coastal_clip=coastal_clip,
    )
    median_aggs = [ms.gci(x.sel(band="nir"), x.sel(band="green")) for x in data]
    gci = xr.concat(median_aggs, dim="time")
    return gci


# sipi - Structure Insensitive Pigment Index: which is helpful in early disease detection in vegetation.
def get_sipi(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=default_max,
    period="monthly",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        bands=["B08", "B02", "B04"],
        collection_name=collection_name,
        timeframe=timeframe,
        cloudcover=cloudcover,
        resolution=resolution,
        max=max,
        period=period,
        coastal_clip=coastal_clip,
    )
    median_aggs = [
        ms.sipi(x.sel(band="nir"), x.sel(band="red"), x.sel(band="blue")) for x in data
    ]
    sipi = xr.concat(median_aggs, dim="time")
    return sipi


# ndmi - Normalised Difference Moisture Index
def get_ndmi(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=default_max,
    period="monthly",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        bands=["B08", "B11"],
        collection_name=collection_name,
        timeframe=timeframe,
        cloudcover=cloudcover,
        resolution=resolution,
        max=max,
        period=period,
        coastal_clip=coastal_clip,
    )
    median_aggs = [ms.ndmi(x.sel(band="nir"), x.sel(band="swir16")) for x in data]
    ndmi = xr.concat(median_aggs, dim="time")
    return ndmi


# ndmi - Normalised Difference Water Index
def get_ndwi(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=default_max,
    period="monthly",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        bands=["B08", "B12"],
        collection_name=collection_name,
        timeframe=timeframe,
        cloudcover=cloudcover,
        resolution=resolution,
        max=max,
        period=period,
        coastal_clip=coastal_clip,
    )
    ndwi_aggs = [
        (
            x.sel(band="nir")
            - x.sel(band="swir22") / x.sel(band="nir")
            + x.sel(band="swir22")
        )
        for x in data
    ]
    ndwi = xr.concat(ndwi_aggs, dim="time")
    return ndwi


# List Colour Maps
def colour_maps():
    for cmap in plt.colormaps():
        fig, ax = plt.subplots(figsize=(4, 0.4))
        ax.set_title(cmap)
        col_map = plt.get_cmap(cmap)
        mpl.colorbar.ColorbarBase(ax, cmap=col_map, orientation="horizontal")


# List Global LandCover DataSets
def list_global_land_cover():
    collections = catalog.get_children()
    data = {}
    for c in collections:
        if str.__contains__(c.title.lower(), "land cover") or str.__contains__(
            c.title.lower(), "worldcover"
        ):
            data[c.id] = c.title
    data = dict(OrderedDict(sorted(data.items())))
    print("only io-lulc-9-class and io-lulc are supported.")
    return pd.DataFrame(data.items())


# Get Global LandCover over AOI
def get_global_land_cover(aoi, name="io-lulc-9-class"):  # io-lulc-9-class, io-lulc
    bbox = rasterio.features.bounds(aoi)
    search = catalog.search(bbox=bbox, collections=[name])
    items = search.item_collection()
    listing = []
    for i in items:
        listing.append(i.id)
    print(listing)

    item = items[0]
    epsg = proj.ext(item).epsg
    nodata = item.assets["data"].extra_fields["raster:bands"][0]["nodata"]

    stack = stackstac.stack(
        items,
        epsg=epsg,
        dtype=np.ubyte,
        fill_value=nodata,
        bounds_latlon=bbox,
        sortby_date=False,
    )
    if name == "io-lulc-9-class":
        stack = stack.assign_coords(
            time=pd.to_datetime([item.properties["start_datetime"] for item in items])
            .tz_convert(None)
            .to_numpy()
        ).sortby("time")

    merged = None

    if name == "io-lulc-9-class":
        merged = stack.squeeze().compute()
        collection = catalog.get_collection(name)
        ia = ItemAssetsExtension.ext(collection)
        x = ia.item_assets["data"]
        class_names = {
            x["summary"]: x["values"][0] for x in x.properties["file:values"]
        }
        global values_to_classes
        values_to_classes = {v: k for k, v in class_names.items()}
        class_count = len(class_names)
        with rasterio.open(item.assets["data"].href) as src:
            colormap_def = src.colormap(1)  # get metadata colormap for band 1
            colormap = [
                np.array(colormap_def[i]) / 255
                for i in range(max(class_names.values()))
            ]
        global cmap
        cmap = ListedColormap(colormap)
        vmin = 0
        vmax = max(class_names.values())
        epsg = merged.epsg.item()
        p = merged.plot(
            subplot_kws=dict(projection=ccrs.epsg(epsg)),
            col="time",
            transform=ccrs.epsg(epsg),
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            figsize=(16, 6),
            col_wrap=3,
        )
        ticks = np.linspace(0.5, 10.5, 11)
        labels = [values_to_classes.get(i, "") for i in range(cmap.N)]
        p.cbar.set_ticks(ticks, labels=labels)
        p.cbar.set_label("Class")

    if name == "io-lulc":
        merged = (
            stackstac.mosaic(stack, dim="time", axis=None, nodata=0).squeeze().compute()
        )
        class_names = merged.coords["label:classes"].item()["classes"]
        class_count = len(class_names)
        with rasterio.open(item.assets["data"].href) as src:
            colormap_def = src.colormap(1)  # get metadata colormap for band 1
            colormap = [np.array(colormap_def[i]) / 255 for i in range(class_count)]
        cmap = ListedColormap(colormap)
        fig, ax = plt.subplots(
            figsize=(12, 6),
            dpi=125,
            subplot_kw=dict(projection=ccrs.epsg(epsg)),
            frameon=False,
        )
        p = merged.plot(
            ax=ax,
            transform=ccrs.epsg(epsg),
            cmap=cmap,
            add_colorbar=False,
            vmin=0,
            vmax=class_count,
        )
        ax.set_title("ESRI Land Cover 2023")
        cbar = plt.colorbar(p)
        cbar.set_ticks(range(class_count))
        cbar.set_ticklabels(class_names)

    return merged


# Annual Charting of Land Cover Classes
def chart_global_land_cover(data):
    df = data.stack(pixel=("y", "x")).T.to_pandas()
    counts = (
        df.stack()
        .rename("class")
        .reset_index()
        .groupby("time")["class"]
        .value_counts()
        .rename("count")
        .swaplevel()
        .sort_index(ascending=False)
        .rename(lambda x: x.year, level="time")
    )
    colors = cmap(counts.index.get_level_values("class") / cmap.N)
    fig = plt.figure(figsize=(12, 10))
    ax = counts.rename(values_to_classes, level="class").plot.barh(
        color=colors, width=0.9
    )
    ax.set(xlabel="Class count", title="Land Cover Distribution Per Year")
    plt.show()


# Visual Data by Colour Maps
def visualise(data, cmap=None):
    data.plot.imshow(x="x", y="y", col="time", cmap=cmap, col_wrap=4)


# Save Single Data as GeoTIFF/COG Series
# eg: d = data.sel(time="2023-01-23").expand_dims(dim="time"); dep.save_single(d, "tmp")
def save_single(data, file_name):
    data = data.transpose("time", "band", "y", "x").squeeze()
    data.rio.to_raster(file_name + ".tif", driver="COG")


# Save Multiple Outputs as GeoTIFF/COG Series
def save_multiple(data, file_name):
    data = data.transpose("time", "band", "y", "x").squeeze()
    for idx, x in enumerate(data):
        x.rio.to_raster(file_name + "_" + str(idx) + ".tif", driver="COG")


# Generate Annual Landcover Mosaic with Multiple Bands for ML Classification
def get_landcover_mosaic(
    aoi,
    year,
    bands=["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A"],
    resolution=10,
    max=10000,
    cloudcover=10,
    collection_name="sentinel-2-l2a",
    coastal_clip=False,
):
    data = get_data(
        aoi,
        timeframe=year,
        period="yearly",
        bands=bands,
        resolution=resolution,
        max=max,
        collection_name=collection_name,
        cloudcover=cloudcover,
        coastal_clip=coastal_clip,
    )
    data = data.squeeze()
    # if coastal_clip == True:
    #    data = data.dropna(dim="x")
    #    data = data.dropna(dim="y")
    return data


# Focal Mean Smoothing and Noise Removal
def smooth(data):
    mean_aggs = [mean(x) for x in data]
    data = xr.concat(mean_aggs, dim="time")
    return data


# Plot Mean TimeSeries for Indices
def plot(data):
    data.mean(dim=["x", "y"]).plot(size=8)
    plt.legend(loc="best")
    plt.title("Vegetation Index Trend")
    plt.ylabel("Mean Index")
    plt.grid()
    plt.show()


# Plot Cloudiness Percentage Over AOI over Timeframe eg: "2020/2022"
def plot_cloudiness(aoi, timeframe, collection_name="sentinel-2-l2a"):
    bbox = rasterio.features.bounds(aoi)
    search = catalog.search(
        collections=[collection_name],
        bbox=bbox,
        datetime=timeframe,
    )
    items = search.get_all_items()
    df = gpd.GeoDataFrame.from_features(items.to_dict())
    df["datetime"] = pd.to_datetime(df["datetime"])
    ts = df.set_index("datetime").sort_index()["eo:cloud_cover"].rolling(7).mean()
    ts.plot(title="Cloud Cover Percentage (7-Scene Rolling Average)")
    plt.grid()
    plt.figure(figsize=(14, 10))
    plt.show()


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


# Clip Coastal Buffer (by 100 Metres Intervals)
def do_coastal_clip(aoi, data, buffer=0):
    buffer = 0.001 * buffer  # 100 metres
    aoi = aoi.buffer(buffer)
    clipped = data.rio.clip(aoi.to_crs(data.rio.crs), all_touched=True)
    return clipped


# August 2024 Workshop
def get_annual_geomad(aoi, year="2023"):
    bbox = get_bbox(aoi)
    chunks = dict(x=100, y=100)
    catalog = "https://stac.staging.digitalearthpacific.org"
    client = pystac.Client.open(catalog)
    # Search for Sentinel-2 GeoMAD data
    items = client.search(
        collections=["dep_s2_geomad"], bbox=bbox, datetime=year
    ).items()
    print(f"Found {len(items)} items")
    # Load the data
    data = load(
        items, chunks=chunks, bbox=bbox, resolution=10, crs="EPSG:4326"
    ).squeeze("time")
    # coastal clip
    # data = dep.do_coastal_clip(aoi, data, buffer=0)
    return data


def list_data_points():
    return pd.DataFrame(glob.glob("Fiji/fj_lulc_data*"))


def get_stats(tif_file):
    da = rioxarray.open_rasterio(
        tif_file,
        # default_name is needed for flox
        default_name="class_1",
        chunks=True,
    ).squeeze()
    # classes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
    classes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
   
    summary = xarray_reduce(da, da, func="count", expected_groups=classes)
    summary = summary.to_pandas()
    # summary = summary.drop(0)
    summary = summary.to_frame()
    df = summary
    # remove water class
    df = df.drop(7)
    
    df.rename(columns={0: "class_count"}, inplace=True)
    total = df.sum().to_numpy()[0]
    df["percent"] = (df["class_count"] / total) * 100
    df["class"] = ""
    df.loc[df.index == 1, "class"] = "forest"
    df.loc[df.index == 2, "class"] = "cropland"
    df.loc[df.index == 3, "class"] = "grassland"
    df.loc[df.index == 4, "class"] = "shrubland"
    df.loc[df.index == 5, "class"] = "settlements"
    df.loc[df.index == 6, "class"] = "bareland"
    df.loc[df.index == 7, "class"] = "water"
    df.loc[df.index == 8, "class"] = "wetlands"
    df.loc[df.index == 9, "class"] = "sand"
    df.loc[df.index == 10, "class"] = "coral"
    df.loc[df.index == 11, "class"] = "seaweed"
    df.loc[df.index == 12, "class"] = "rock"
    df.loc[df.index == 13, "class"] = "mining"
    df.loc[df.index == 14, "class"] = "invasives"

    df = df[["class", "class_count", "percent"]]
    return df


def get_lulc_class_colours():
    classes = [
        [1, "forest", "#064a00"],
        [2, "cropland", "#ffce33"],
        [3, "grassland", "#d7ffa0"],
        [4, "shrubland", "#808000"],
        [5, "settlements", "#d10a1e"],
        [6, "bareland", "#968640"],
        [7, "water", "#71a8ff90"],
        [8, "wetlands", "#008080"],
        [9, "sand", "#F4A460"],
        [10, "coral", "#FF7F50"],
        [11, "seaweed", "#556B2F"],
        [12, "rock", "#808080"],
        [13, "mining", "#C3192b"],
        [14, "invasives", "#800080"],
        # [15, "rubble", "#A9A9A9"],
        # [17, "other", "#800080"],
        # [8, "mangroves", "#07b28d"],
        # [11, "seagrass", "#7FFFD4"],
    ]
    return classes
