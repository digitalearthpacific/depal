"""depal.py: Digital Earth Pacific (Abstration Library)"""
__author__ = "Sachindra Singh"
__copyright__ = "Pacific Community (SPC)"
__license__ = "GPL"
__version__ = "0.0.1"
__email__ = "sachindras@spc.int"
__status__ = "Development"

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

# Global
padm = gpd.read_file(Path(__file__).parent / "padm.gpkg", layer="padm")
catalog = pystac.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace
)
pd.set_option("display.max_rows", None)
pd.set_option("display.max_colwidth", None)
default_resolution = 100
chunk_size = 4096
cluster = None
client = None


# Initialise and Configure Dask and Resolution Defaults
def init(type="local", maxWorkers=4, resolution=100):
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
    area_of_interest = local.geometry[0]
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


# AOI from Country Administrative Boundary
def get_country_admin_boundary(country, admin_type, admin):
    cadm = padm[padm["country"] == country]
    admin_types = (
        cadm["type_1"].unique().tolist()
        + cadm["type_2"].unique().tolist()
        + cadm["type_3"].unique().tolist()
    )
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


# Xarray Dataset from STAC
def get_data(
    aoi,
    bands=[],
    collection_name="sentinel-2-l2a",
    timeframe="2023-01-01/2023-12-31",
    cloudcover=10,
    resolution=default_resolution,
    max=30,
    period="monthly",
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
            #band=lambda x: x.common_name.rename("band"),  # use common names
            time=lambda x: x.time.dt.round("D"),
            # time=pd.to_datetime([item.properties["datetime"] for item in items])
            #  .tz_convert(None)
            #  .to_numpy()
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
    if period == "daily":
        data = data.resample(time="1D").median("time", keep_attrs=True).compute()

    return data


# Latest RGB Images
def get_latest_images(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2023-01-01/2023-12-31",
    cloudcover=10,
    resolution=default_resolution,
    max=30,
    period="daily",
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
    )
    true_color_aggs = [
        ms.true_color(x.sel(band="red"), x.sel(band="green"), x.sel(band="blue"))
        for x in data
    ]
    true_color = xr.concat(true_color_aggs, dim="time")
    return true_color


# median composite - Cloudless Mosaic achieved y combining images across time
def get_cloudless_mosaic(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=100,
    period="yearly",
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
    )
    median_aggs = [
        ms.true_color(x.sel(band="red"), x.sel(band="green"), x.sel(band="blue"))
        for x in data
    ]
    median_composite = xr.concat(median_aggs, dim="time")
    return median_composite


# ndvi - Normalised Difference Vegetation Index
def get_ndvi(
    aoi,
    collection_name="sentinel-2-l2a",
    timeframe="2019-11-01/2022-11-31",
    cloudcover=10,
    resolution=default_resolution,
    max=100,
    period="monthly",
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
    max=100,
    period="monthly",
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
    )
    median_aggs = [
        ms.evi(x.sel(band="nir"), x.sel(band="blue"), x.sel(band="red")) for x in data
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
    max=100,
    period="monthly",
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
    max=100,
    period="monthly",
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
    max=100,
    period="monthly",
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
    max=100,
    period="monthly",
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


# Focal Mean Smooting
def smooth(data):
    return data


# Clip Coastal Buffer by Metres
def coastal_clip(aoi, data, buffer=100):
    return data


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
def chart_land_cover(data):
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
    data.plot.imshow(x="x", y="y", col="time", cmap=cmap, col_wrap=5)


# Save Data as GeoTIFF/COG Series
def save(data, file_name):
    for idx, x in enumerate(data):
        x.rio.to_raster(
            file_name + "_" + str(idx) + ".tif", driver="COG", dtype="int16"
        )
