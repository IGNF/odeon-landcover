import gdal
import numpy as np
import rasterio
import math
from rasterio.enums import Resampling
from rasterio.windows import from_bounds, transform
from rasterio.plot import reshape_as_image
from skimage.transform import resize
from skimage import img_as_float
from odeon.commons.rasterio import get_scale_factor_and_img_size_from_dataset, get_center_from_bound
from odeon import LOGGER


def image_to_ndarray(image_file, width=None, height=None, band_indices=None):
    """Load and transform an image into a ndarray according to parameters:
    - center-cropping to fit width, height
    - loading of specific bands to fit image_bands array

    Parameters
    ----------
    image_file : str
        full image file path
    width : int, optional
        output image width, by default None (native image width is used)
    height : int, optional
        output image height, by default None (native image height is used)
    band_indices : obj:`list` of :obj: `int`, optional
        list of band indices to be loaded in output image, by default None (native image bands are used)

    Returns
    -------
    out: ndarray
        a numpy array representing the image
    """

    # load full image at a specific resolution
    ds = gdal.Open(image_file, gdal.GA_ReadOnly)

    if ds is None:

        LOGGER.error(f"File {image_file} not valid.")

    # center crop with width and height
    img = ds.ReadAsArray()
    dims = len(img.shape)  # one channel or many

    if dims == 3:

        img = img.swapaxes(0, 2).swapaxes(0, 1)

    else:

        img = img[..., np.newaxis]
    # image shape is now W x H x B

    if width is None:

        width = img.shape[0]

    if height is None:

        height = width

    # cropping
    crop_size_x = img.shape[0] - width
    crop_size_y = img.shape[1] - height
    dx_left = int(crop_size_x / 2)
    dx_right = crop_size_x - dx_left
    dy_top = int(crop_size_y / 2)
    dy_bottom = crop_size_y - dy_top

    if not (dx_left == 0 or dx_right == 0):

        img = img[dx_left:-dx_right, :, :]

    if not (dy_top == 0 or dy_bottom == 0):

        img = img[:, dy_top:-dy_bottom, :]

    # bands selection
    if dims == 3 and not(band_indices is None):

        img = img[:, :, band_indices]

    return img


def raster_to_ndarray_from_dataset(src,
                                   width,
                                   height,
                                   resolution,
                                   band_indices=None,
                                   resampling=Resampling.bilinear,
                                   window=None,
                                   boundless=True):
    LOGGER.debug(window)

    " get the width and height at the target resolution "
    _, _, scaled_width, scaled_height = get_scale_factor_and_img_size_from_dataset(src,
                                                                                   resolution=(resolution,
                                                                                               resolution),
                                                                                   width=width,
                                                                                   height=height)

    scaled_height, scaled_width = math.ceil(scaled_height), math.ceil(scaled_width)

    if band_indices is None:
        band_indices = range(1, src.count + 1)

    if window is None:

        img = src.read(indexes=band_indices,
                       out_shape=(len(band_indices), scaled_height, scaled_width),
                       resampling=resampling)
    else:

        img = src.read(indexes=band_indices,
                       window=window,
                       out_shape=(len(band_indices), scaled_height, scaled_width),
                       resampling=resampling,
                       boundless=boundless)

    " reshape img from gdal band format to numpy ndarray format "
    img = reshape_as_image(img)

    if img.ndim == 2:
        img = img[..., np.newaxis]

    if scaled_width >= width and scaled_height >= height:

        if scaled_width > width or scaled_height > height:
            " handling case of dest_res > src_res, example from 0.5 to 0.2 "
            img = crop_center(img, width, height)

    if scaled_width < width or scaled_height > height:
        " handling case of dest_res < src_res, example from 0.2 to 0.5 "
        img = resize(img, (width, height))

    meta = src.meta.copy()
    LOGGER.debug(meta)

    " compute the new affine transform "
    if scaled_width != width or scaled_height != height:

        side_x = (img.shape[0] * resolution) / 2
        side_y = (img.shape[1] * resolution) / 2
        bounds = src.bounds
        center_x, center_y = get_center_from_bound(bounds.left, bounds.bottom, bounds.right, bounds.top)
        left, bottom, right, top = center_x - side_x, center_y - side_y, center_x + side_x, center_y + side_y
        window = from_bounds(left, bottom, right, top, src.transform)
        affine = transform(window, src.transform)
        meta["transform"] = affine

    return img, meta


def raster_to_ndarray(image_file,
                      width,
                      height,
                      resolution,
                      band_indices=None,
                      resampling=Resampling.bilinear,
                      window=None):

    LOGGER.debug(image_file)

    with rasterio.open(image_file) as src:

        return raster_to_ndarray_from_dataset(src, width, height, resolution, band_indices, resampling, window)


def crop_center(img, cropx, cropy):

    if img.ndim == 2:

        y, x = img.shape

    else:

        y, x, _ = img.shape

    startx = x // 2 - (cropx // 2)
    starty = y // 2 - (cropy // 2)
    return img[starty:starty + cropy, startx:startx + cropx]


def substract_margin(img, margin_x, margin_y):

    if img.ndim == 2:

        y, x = img.shape

    else:

        y, x, _ = img.shape

    return img[0 + margin_y: y - margin_y, 0 + margin_x:x - margin_x]


class TypeConverter:

    def __init__(self):

        self._from = "float32"
        self._to = "uint8"

    def from_type(self, img_type):

        self._from = img_type
        return self

    def to_type(self, img_type):

        self._to = img_type
        return self

    def convert(self, img, threshold=0.5):

        if self._from == "float32":

            if self._to == "float32":

                return img

            elif self._to == "uint8":

                if img.max() > 1:

                    info = np.idebug(img.dtype)  # Get the information of the incoming image type
                    img = img.astype(np.float32) / info.max  # normalize the data to 0 - 1

                img = 255 * img  # scale by 255
                return img.astype(np.uint8)

            elif self._to == "bit":

                img = img > threshold
                return img.astype(np.uint8)

            else:

                LOGGER.warning("the output type has not been interpreted")
                return img


def ndarray_to_affine(affine):
    """

    Parameters
    ----------
    affine : numpy Array

    Returns
    -------
    rasterio.Affine
    """
    return rasterio.Affine(affine[0], affine[1], affine[2], affine[3], affine[4], affine[5])


class CollectionDatasetReader:

    @staticmethod
    def get_stacked_window_collection(dict_of_raster, meta, bounds, width, height, resolution, dem=False):

        handle_dem = False
        stacked_bands = None

        if ("DSM" in dict_of_raster.keys()) and ("DTM" in dict_of_raster) and dem is True:

            handle_dem = True

        for key, value in dict_of_raster.items():

            if (key not in ["DSM", "DTM"]) or handle_dem is False:

                src = value["connection"]
                window = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], src.meta["transform"])
                band_indices = value["bands"]

                img, _ = raster_to_ndarray_from_dataset(src,
                                                        width,
                                                        height,
                                                        resolution,
                                                        band_indices=band_indices,
                                                        resampling=Resampling.bilinear,
                                                        window=window)

                # pixels are normalized to [0, 1]
                img = img_as_float(img)

                LOGGER.debug(f"type of img: {type(img)}, shape {img.shape}")

                stacked_bands = img if stacked_bands is None else np.dstack([stacked_bands, img])
                LOGGER.debug(f"type of stacked bands: {type(stacked_bands)}, shape {stacked_bands.shape}")

        if handle_dem:

            dsm_ds = dict_of_raster["DSM"]["connection"]
            dtm_ds = dict_of_raster["DTM"]["connection"]
            dsm_window = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], dsm_ds.meta["transform"])
            dtm_window = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], dtm_ds.meta["transform"])

            dsm_img, _ = raster_to_ndarray_from_dataset(src,
                                                        width,
                                                        height,
                                                        resolution,
                                                        band_indices=band_indices,
                                                        resampling=Resampling.bilinear,
                                                        window=dsm_window)

            dtm_img, _ = raster_to_ndarray_from_dataset(src,
                                                        width,
                                                        height,
                                                        resolution,
                                                        band_indices=band_indices,
                                                        resampling=Resampling.bilinear,
                                                        window=dtm_window)

            dsm_img = img_as_float(dsm_img)
            dtm_img = img_as_float(dtm_img)
            img = dsm_img - dtm_img
            img = img_as_float(img)

            LOGGER.debug(f"img min: {img.min()}, img shape: {img.shape}")

            stacked_bands = img if stacked_bands is None else np.dstack([stacked_bands, img])
            LOGGER.debug(f"type of stacked bands: {type(stacked_bands)}, shape {stacked_bands.shape}")

        return stacked_bands
