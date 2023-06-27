
"""depal.py: Digital Earth Pacific (Abstration Library)"""
__author__ = "Sachindra Singh"
__copyright__ = "Pacific Community (SPC)"
__license__ = "GPL"
__version__ = "0.0.1"
__email__ = "sachindras@spc.int"
__status__ = "Development"

import geopandas as gpd
import pandas as pd
import pystac_client as pystac
import planetary_computer as pc
from pystac.extensions.projection import ProjectionExtension as proj
import numpy as np
import xarray as xr
import xrspatial.multispectral as ms
import stackstac
from dask_gateway import GatewayCluster
from dask.distributed import Client
from dask.distributed import LocalCluster
import matplotlib.pyplot as plt
from collections import OrderedDict
from shapely.geometry import shape
import rioxarray
from rasterio.crs import CRS
from rasterio.plot import show
import rasterio.features

#global
padm = gpd.read_file("padm.gpkg", layer='padm')
catalog = pystac.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",modifier=pc.sign_inplace)
pd.set_option('display.max_rows', None)
pd.set_option('display.max_colwidth', None)
default_resolution=100

print("Initiating DEPAL...")

#configure dask defaults
#Local Dask
cluster = LocalCluster()
client = Client(cluster)

#Remote Dask
def setup_dask(maxWorkers=2):
    cluster = GatewayCluster()
    client = cluster.get_client()
    cluster.adapt(minimum=1, maximum=maxWorkers)
    
def get_area__from_geojson(geojson_file):
    local =  gpd.read_file(geojson_file)
    area_of_interest = local.geometry[0]
    return area_of_interest

def list_countries():
    return pd.DataFrame(padm['country'].unique().tolist())

def list_boundary_types(country):
    cadm = padm[padm['country'] == country]
    data = cadm['type_1'].unique().tolist() + cadm['type_2'].unique().tolist() + cadm['type_3'].unique().tolist()
    return pd.DataFrame(data)

def list_country_boundary(country, admin_type):
    cadm = padm[padm['country'] == country]
    admin_types = cadm['type_1'].unique().tolist() + cadm['type_2'].unique().tolist() + cadm['type_3'].unique().tolist()
    idx = admin_types.index(admin_type) + 1
    data = cadm['name_' + str(idx)].unique().tolist()
    return pd.DataFrame(data)

def get_country_boundary(country, admin_type, admin):    
    cadm = padm[padm['country'] == country]
    admin_types = cadm['type_1'].unique().tolist() + cadm['type_2'].unique().tolist() + cadm['type_3'].unique().tolist()
    idx = admin_types.index(admin_type) + 1
    aadm = cadm[cadm['name_' + str(idx)] == admin]
    return aadm.dissolve().geometry

def list_data():    
    collections = catalog.get_children()
    data = {}
    for c in collections:
        data[c.id] = c.title
    data = dict(OrderedDict(sorted(data.items())))
    return pd.DataFrame(data.items())

def list_data_bands(collection_name = "sentinel-2-l2a"):    
    collection = catalog.get_child(collection_name)
    return pd.DataFrame(collection.extra_fields["summaries"]["eo:bands"])    

def list_data_assets(collection_name):
    collection = catalog.get_child(collection_name)
    data = pd.DataFrame.from_dict(collection.extra_fields["item_assets"], orient="index")[
        ["title", "description"]
    ]
    return data

#needs improvement, flexibility
def visualise(data):
    data.plot.imshow(x="x", y="y", col="time", col_wrap=5)    

def get_latest_images(aoi, collection_name="sentinel-2-l2a", timeframe="2023-01-01/2023-12-31", cloudcover=10, resolution=default_resolution, max=30, period="dayofyear"):    
    bbox = rasterio.features.bounds(aoi)
    search = catalog.search(
        bbox=bbox,
        datetime=timeframe,
        collections=[collection_name],
        query={"eo:cloud_cover": {"lt": cloudcover}},
    )
    items = search.item_collection()#[0:max]
    for i in items:
        print(i.datetime)
        
    print(len(items))
    #epsg
    item = next(search.get_items())
    epsg = proj.ext(item).epsg
    data = (
        stackstac.stack(
            items,
            assets=["B04", "B03", "B02"],  # red, green, blue
            epsg=epsg,
            bounds_latlon=bbox,
            chunksize=4096,
            resolution=resolution,
        )
        .where(lambda x: x > 0, other=np.nan)  # sentinel-2 uses 0 as nodata
        .assign_coords(
            band=lambda x: x.common_name.rename("band"),  # use common names
            time=lambda x: x.time.dt.round(
                "D"
            ),  # round time to daily for nicer plot labels
        )
    )
    data = data.groupby("time." + period).median(keep_attrs=True).compute()
    true_color_aggs = [
        ms.true_color(x.sel(band="red"), x.sel(band="green"), x.sel(band="blue"))
        for x in data
    ]
    true_color = xr.concat(true_color_aggs, dim="time")    
    return true_color
    
def get_cloudless_mosaic(aoi, collection_name="sentinel-2-l2a", timeframe="2019-11-01/2022-11-31", cloudcover=10, resolution=default_resolution, period="year"): #month
    bbox = rasterio.features.bounds(aoi)
    search = catalog.search(
        bbox=bbox,
        datetime=timeframe,
        collections=[collection_name],
        query={"eo:cloud_cover": {"lt": cloudcover}},
    )
    items = search.item_collection()#[0:max]
    for i in items:
        print(i.datetime)
        
    print(len(items))
    #epsg
    item = next(search.get_items())
    epsg = proj.ext(item).epsg
    data = (
        stackstac.stack(
            items,
            assets=["B04", "B03", "B02"],  # red, green, blue
            epsg=epsg,
            bounds_latlon=bbox,
            chunksize=4096,
            resolution=resolution,
        )
        .where(lambda x: x > 0, other=np.nan)  # sentinel-2 uses 0 as nodata
        .assign_coords(
            band=lambda x: x.common_name.rename("band"),  # use common names
            time=lambda x: x.time.dt.round(
                "D"
            ),  # round time to daily for nicer plot labels
        )
    )
    data = data.groupby("time." + period).median(keep_attrs=True).compute()
    median_aggs = [
        ms.true_color(x.sel(band="red"), x.sel(band="green"), x.sel(band="blue"))
        for x in data
    ]
    median_composite = xr.concat(median_aggs, dim="time")   
    return median_composite

def save(data, file_name):
    data.rio.to_raster(file_name + ".tif", driver="COG", dtype="int16")

def get_ndvi(aoi, collection_name="sentinel-2-l2a", timeframe="2019-11-01/2022-11-31", cloudcover=10, resolution=default_resolution, period="month"):
    pass

def get_evi(aoi, collection_name="sentinel-2-l2a", timeframe="2019-11-01/2022-11-31", cloudcover=10, resolution=default_resolution, period="month"):
    pass

def get_sipi(aoi, collection_name="sentinel-2-l2a", timeframe="2019-11-01/2022-11-31", cloudcover=10, resolution=default_resolution, period="month"):
    pass

def get_gci(aoi, collection_name="sentinel-2-l2a", timeframe="2019-11-01/2022-11-31", cloudcover=10, resolution=default_resolution, period="month"):
    pass



