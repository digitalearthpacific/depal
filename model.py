import geopandas as gpd
import pandas as pd
import xarray as xr

def add_image_values(pts: gpd.GeoDataFrame, image: xr.DataArray) -> gpd.GeoDataFrame:
    """Add the values of the image at each point location to the input GeoDataFrame"""
    # Get values for each of the image bands at each of the points.
    pts = pts.to_crs(image.rio.crs)
    x = xr.DataArray(pts.geometry.x, dims="points")
    y = xr.DataArray(pts.geometry.y, dims="points")
    pt_values_i = image.sel(x=x, y=y, method="nearest")
    return pd.concat([pts, pt_values_i.squeeze().to_pandas().transpose()], axis=1)


def get_model_prediction(model, training_image: xr.DataArray) -> xr.DataArray:
    # Prediction needs to be done on a 2-d ndarray (that is, rows are raster cells and columns are values for each band),
    # so "stack" the geographic x & y values into a single dimension.
    training_image_2d = training_image.stack(z=('y','x'))
    X_pred = training_image_2d.values.transpose()

    # Run the prediction. This will take a minute or two.
    y_pred = model.predict(X_pred)

    # If you load a whole image, you may get memory errors, a simple way to fix that would be to do a quick batching like this
    # y_pred_s2 = np.concatenate([s2_model.predict(batch) for batch in np.array_split(X_pred_s2,100)])

    # The best other alternative (specifically if you can't load X_pred_s2 into memory) would probably be to use
    # xarray.map_blocks and predict over each block.

    # Now we need to assign the predicted values to a new raster object. We do this by
    # 1. Creating an xarray object with the same dimensions as the prediction image, and 1 band
    prediction_1d = training_image_2d.isel(band=1)

    # 2. Assigning the predictions above to its values
    prediction_1d.values = y_pred.astype('int16')

    # "unstack" the z-dimension into x & y, and save as a raster.
    # This creates an xarray image with the same dimensions as the input
    # image, and one band of integer values.
    return prediction_1d.unstack()


from base64 import b64encode
from io import BytesIO

from PIL import Image
from ipyleaflet import ImageOverlay


def get_overlay(array: xr.DataArray, cmap) -> ImageOverlay:
    """Create an rgb image overlay for the given DataArray and colormap.
    `array` should be a 2-d array."""
    rgb = (cmap(array.rio.reproject(3857))[:, :, :4] * 255).astype(np.uint8)
    
    # Make the first band transparent if the first three are 255. 
    # I'm assuming that's the "default" value for cmap(value)
    # I could be wrong and there could be an obvious way to do this.
    mask = np.all(rgb[:,:,:3] == 255, axis=2)
    rgb[mask, 3] = 0

    image_pil = Image.fromarray(rgb)

    # Create a BytesIO object to hold the PNG image in memory
    image_bytes = BytesIO()

    # Save the image as PNG to the BytesIO object
    image_pil.save(image_bytes, format='PNG')

    # Get the PNG data from the BytesIO object
    image_data = b64encode(image_bytes.getvalue()).decode("ascii")
    imgurl = "data:image/png;base64," + image_data

    bounds = array.rio.reproject(4326).rio.bounds()
    lf_bounds = [(bounds[1], bounds[0]), (bounds[3], bounds[2])]
    return ImageOverlay(url=imgurl, bounds=lf_bounds)
